import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai import errors, types
from pydantic import ValidationError

from app.core.config import Settings
from app.models import EngineOil, Vehicle
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.research import ResearchService
from app.research.contracts import CatalogResearchProvider, ResearchProvider
from app.research.errors import (
    GeminiProviderError,
    ResearchProviderConfigurationError,
    ResearchProviderTimeoutError,
)
from app.research.factory import create_research_provider
from app.research.prompts import serialize_oil_catalog
from app.research.prompts.common import SYSTEM_PROMPT, build_vehicle_research_prompt
from app.research.providers.gemini.client import (
    GeminiClient,
    _gemini_response_json_schema,
)
from app.research.providers.gemini.provider import (
    GeminiResearchProvider as GeminiResearchAdapter,
)
from app.research.providers.opencode.provider import (
    OpenCodeResearchProvider as OpenCodeResearchAgent,
)
from app.research.providers.openrouter.provider import (
    OpenRouterResearchProvider as ResearchAgent,
)
from app.research.schemas import CatalogResearchResult, EngineOilResearchResult


def settings(**overrides):
    values = {
        "research_provider": "gemini",
        "gemini_api_key": "test-key",
        "gemini_model": "gemini-2.5-flash",
    }
    values.update(overrides)
    return Settings(**values)


def vehicle():
    return Vehicle(
        id=312,
        manufacturer="Peugeot",
        model="206",
        trim="Type 5",
        production_year_from=2003,
        production_year_to=2021,
        engine_code="TU5",
        engine_displacement="1587",
        fuel_type="gasoline",
    )


def research_payload(**overrides):
    payload = {
        "research_status": "FOUND",
        "vehicle_id": 312,
        "engine_code": "TU5",
        "recommended_sae": ["10W-40"],
        "alternative_sae": [],
        "minimum_api": "SL",
        "acea_specs": [],
        "oem_approvals": [],
        "confidence": 0.92,
        "sources": [
            {
                "title": "Manual",
                "url": "https://example.test/manual",
                "source_type": "OFFICIAL_MANUAL",
                "supported_claims": ["SAE 10W-40"],
            }
        ],
        "recommended_products": [],
        "notes": None,
    }
    payload.update(overrides)
    return payload


def response(payload, *, grounded=True):
    metadata = None
    if grounded:
        metadata = SimpleNamespace(
            web_search_queries=["Peugeot 206 TU5 oil specification"],
            grounding_chunks=[
                SimpleNamespace(
                    web=SimpleNamespace(
                        title="Manual", uri="https://example.test/manual"
                    )
                )
            ],
        )
    return SimpleNamespace(
        text=payload if isinstance(payload, str) else json.dumps(payload),
        candidates=[SimpleNamespace(grounding_metadata=metadata)],
    )


def sdk_client(*responses):
    generate = AsyncMock(side_effect=responses)
    return SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=generate),
            aclose=AsyncMock(),
        )
    )


@pytest.mark.asyncio
async def test_grounded_research_uses_google_search_and_parses_schema():
    raw_client = sdk_client(
        response("Grounded technical findings."),
        response(research_payload(), grounded=False),
    )
    adapter = GeminiResearchAdapter(GeminiClient(settings(), raw_client))
    result = await adapter.research_vehicle_oil_spec(vehicle())
    assert result.vehicle_id == 312
    assert raw_client.aio.models.generate_content.await_count == 2
    research_request = raw_client.aio.models.generate_content.await_args_list[0].kwargs
    extraction_request = raw_client.aio.models.generate_content.await_args_list[
        1
    ].kwargs
    assert research_request["model"] == "gemini-2.5-flash"
    assert research_request["config"].tools
    assert research_request["config"].response_schema is None
    assert research_request["config"].response_mime_type is None
    assert "strict JSON" in research_request["contents"]
    assert "Collect every documented" not in research_request["contents"]
    assert (
        "Do NOT search for every compatible commercial oil"
        in research_request["contents"]
    )
    assert extraction_request["config"].tools is None
    assert extraction_request["config"].temperature == 0
    assert extraction_request["config"].response_mime_type == "application/json"
    assert extraction_request["config"].response_schema is None
    assert (
        extraction_request["config"].response_json_schema
        == _gemini_response_json_schema()
    )
    assert "Grounded technical findings." in extraction_request["contents"]
    assert "https://example.test/manual" in extraction_request["contents"]
    assert "Do not search again" in extraction_request["contents"]
    assert adapter.client.last_grounding.queries
    assert adapter.client.last_grounding.sources
    assert adapter.client.last_research_text == "Grounded technical findings."
    assert adapter.client.last_structured_text is not None


def test_gemini_response_json_schema_normalizes_exclusive_minimums():
    schema = _gemini_response_json_schema()
    serialized_schema = json.dumps(schema)
    assert "exclusiveMinimum" not in serialized_schema

    product_ref = schema["properties"]["recommended_products"]["items"]["$ref"]
    product_schema = schema
    for path_part in product_ref.removeprefix("#/").split("/"):
        product_schema = product_schema[path_part]

    volume_alternatives = product_schema["properties"]["package_volume_liters"][
        "anyOf"
    ]
    interval_alternatives = product_schema["properties"][
        "claimed_service_interval_km"
    ]["anyOf"]
    assert next(item for item in volume_alternatives if item.get("type") == "number")[
        "minimum"
    ] == 0.0
    assert next(
        item for item in interval_alternatives if item.get("type") == "integer"
    )["minimum"] == 0


def test_google_sdk_accepts_normalized_response_json_schema_config():
    schema = _gemini_response_json_schema()

    config = types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=1024,
        response_mime_type="application/json",
        response_json_schema=schema,
    )

    assert config.response_json_schema == schema
    assert config.response_schema is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("package_volume_liters", 0), ("claimed_service_interval_km", 0)],
)
def test_gemini_schema_normalization_does_not_weaken_domain_validation(field, value):
    product = {
        "brand": "Iranol",
        "name": "Racing",
        "sae_viscosity": "10W-40",
        field: value,
    }

    with pytest.raises(ValidationError, match=field):
        EngineOilResearchResult.model_validate(
            research_payload(recommended_products=[product])
        )


@pytest.mark.asyncio
async def test_grounded_research_extracts_only_sourced_products():
    payload = research_payload(
        recommended_products=[
            {
                "brand": "Iranol",
                "name": "Racing",
                "sae_viscosity": "10W-40",
                "api_spec": "SL",
                "source_urls": ["https://example.test/product"],
            }
        ]
    )
    adapter = GeminiResearchAdapter(
        GeminiClient(
            settings(),
            sdk_client(
                response("Grounded product findings."),
                response(payload, grounded=False),
            ),
        )
    )
    result = await adapter.research_vehicle_oil_spec(vehicle())
    assert result.recommended_products[0].name == "Racing"
    assert result.recommended_products[0].source_urls == [
        "https://example.test/product"
    ]


@pytest.mark.asyncio
async def test_extra_valid_sources_and_recommended_products_are_accepted():
    first_product = {
        "brand": "Iranol",
        "name": "Racing",
        "sae_viscosity": "10W-40",
        "source_urls": ["https://example.test/product"],
    }
    second_product = {
        **first_product,
        "brand": "Behran",
        "name": "Super Pishtaz",
    }
    sources = [
        {
            "title": f"Source {index}",
            "url": f"https://source{index}.test/oil",
            "domain": f"source{index}.test",
            "source_type": "OTHER_TECHNICAL",
            "supported_claims": ["SAE 10W-40", "API SL"],
        }
        for index in range(4)
    ]
    adapter = GeminiResearchAdapter(
        GeminiClient(
            settings(),
            sdk_client(
                response("Grounded product findings."),
                response(
                    research_payload(
                        sources=sources,
                        recommended_products=[first_product, second_product],
                    ),
                    grounded=False,
                ),
            ),
        )
    )
    result = await adapter.research_vehicle_oil_spec(vehicle())
    assert [product.name for product in result.recommended_products] == [
        "Racing",
        "Super Pishtaz",
    ]
    assert len(result.sources) == 4


@pytest.mark.asyncio
async def test_invalid_structured_extraction_is_rejected_without_repair():
    raw_client = sdk_client(response("Grounded findings."), response("not json"))
    adapter = GeminiResearchAdapter(GeminiClient(settings(), raw_client))
    with pytest.raises(GeminiProviderError, match="structured extraction JSON"):
        await adapter.research_vehicle_oil_spec(vehicle())
    assert raw_client.aio.models.generate_content.await_count == 2


@pytest.mark.asyncio
async def test_found_without_grounding_is_rejected():
    raw_client = sdk_client(response(research_payload(), grounded=False))
    adapter = GeminiResearchAdapter(GeminiClient(settings(), raw_client))
    with pytest.raises(GeminiProviderError, match="no Google Search grounding"):
        await adapter.research_vehicle_oil_spec(vehicle())
    assert raw_client.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_unexpected_sdk_error_preserves_exception_details():
    raw_client = sdk_client(RuntimeError("transport exploded"))
    client = GeminiClient(settings(), raw_client)
    with pytest.raises(
        GeminiProviderError,
        match="Gemini request failed: RuntimeError: transport exploded",
    ):
        await client.generate_grounded("research")


@pytest.mark.asyncio
async def test_overloaded_request_retries_only_once():
    overloaded = errors.ServerError(
        503,
        {"error": {"status": "UNAVAILABLE", "message": "model overloaded"}},
    )
    raw_client = sdk_client(overloaded, response("Grounded findings."))
    client = GeminiClient(settings(), raw_client)
    result = await client.generate_grounded("research")
    assert result.text == "Grounded findings."
    assert raw_client.aio.models.generate_content.await_count == 2


@pytest.mark.asyncio
async def test_total_timeout_prevents_two_sequential_long_calls():
    call_number = 0

    async def slow_generate(**kwargs):
        nonlocal call_number
        call_number += 1
        await asyncio.sleep(0.06)
        if call_number == 1:
            return response("Grounded findings.")
        return response(research_payload(), grounded=False)

    generate = AsyncMock(side_effect=slow_generate)
    raw_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=generate),
            aclose=AsyncMock(),
        )
    )
    adapter = GeminiResearchAdapter(
        GeminiClient(
            settings(
                gemini_stage1_timeout_seconds=0.2,
                gemini_stage2_timeout_seconds=0.2,
                gemini_total_timeout_seconds=0.1,
            ),
            raw_client,
        )
    )
    with pytest.raises(ResearchProviderTimeoutError, match="total timeout"):
        await adapter.research_vehicle_oil_spec(vehicle())
    assert generate.await_count == 2


@pytest.mark.parametrize(
    ("field", "value"), [("vehicle_id", 123), ("engine_code", "TU5JP4")]
)
@pytest.mark.asyncio
async def test_exact_vehicle_identity_is_required(field, value):
    adapter = GeminiResearchAdapter(
        GeminiClient(
            settings(),
            sdk_client(
                response("Grounded findings."),
                response(research_payload(**{field: value}), grounded=False),
            ),
        )
    )
    with pytest.raises(GeminiProviderError, match=field):
        await adapter.research_vehicle_oil_spec(vehicle())


def test_catalog_serialization_has_only_contract_fields():
    oil = EngineOil(
        id=1,
        brand="Behran",
        name="Super Rana Plus",
        sae_viscosity="5W-30",
        api_spec="SN Plus",
        acea_specs=[],
        ilsac_spec="GF-6A",
        base_type="Full Synthetic",
        oem_approvals=["GM dexos1 Gen2"],
        package_volume_liters=Decimal("4.00"),
        package_volume_label="4 Liters",
        claimed_service_interval_km=5000,
    )
    assert serialize_oil_catalog([oil]) == [
        {
            "id": 1,
            "brand": "Behran",
            "name": "Super Rana Plus",
            "sae_viscosity": "5W-30",
            "api_spec": "SN Plus",
            "acea_specs": [],
            "ilsac_spec": "GF-6A",
            "base_type": "Full Synthetic",
            "oem_approvals": ["GM dexos1 Gen2"],
            "package_volume_liters": "4.00",
            "package_volume_label": "4 Liters",
            "claimed_service_interval_km": 5000,
        }
    ]
    json.dumps(serialize_oil_catalog([oil]))


def test_shared_prompt_has_rich_vehicle_and_complete_product_schema():
    hilux = Vehicle(
        id=1,
        manufacturer="Toyota",
        model="Hilux",
        trim="2.7 Double Cab 4x4",
        production_year_from=2024,
        production_year_to=2026,
        engine_displacement="2.7 L",
        engine_type="Inline-4",
        fuel_type="gasoline",
        power_hp=134,
        torque_nm=241,
        transmission="5M/6A",
        drivetrain="4WD",
        body_type="Pickup",
        body_style="Midsize Pickup",
    )
    prompt = build_vehicle_research_prompt(hilux)
    for expected in (
        "Engine type: Inline-4",
        "Power: 134 hp",
        "Torque: 241 Nm",
        "Transmission: 5M/6A",
        "Drivetrain: 4WD",
        "Body type: Pickup",
        "Body style: Midsize Pickup",
    ):
        assert expected in prompt
    for field in (
        "ilsac_spec",
        "package_volume_liters",
        "package_volume_label",
        "claimed_service_interval_km",
    ):
        assert field in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_deterministic_mode_does_not_send_catalog_to_gemini(db):
    stored_vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    EngineOilRepository(db).create(
        {
            "brand": "Catalog-only marker",
            "name": "Must not be sent",
            "sae_viscosity": "10W-40",
            "oem_approvals": [],
        }
    )
    result = EngineOilResearchResult.model_validate(
        research_payload(vehicle_id=stored_vehicle.id)
    )

    class RecordingGeminiProvider:
        provider_name = "gemini"
        research_vehicle_oil_spec = AsyncMock(return_value=result)
        research_vehicle_with_catalog = AsyncMock()

    provider = RecordingGeminiProvider()
    service = ResearchService(
        db,
        provider,
        settings(matching_strategy="deterministic"),
    )
    await service.research_vehicle(stored_vehicle.id)
    provider.research_vehicle_oil_spec.assert_awaited_once_with(stored_vehicle)
    provider.research_vehicle_with_catalog.assert_not_awaited()


@pytest.mark.parametrize(
    ("ids", "error"), [([2, 3], None), ([999], "unknown"), ([2, 2], "duplicate")]
)
@pytest.mark.asyncio
async def test_catalog_ids_are_validated(ids, error):
    oils = [
        EngineOil(
            id=item,
            brand="B",
            name=f"Oil {item}",
            sae_viscosity="10W-40",
            oem_approvals=[],
        )
        for item in (1, 2, 3)
    ]
    payload = {
        "research": research_payload(),
        "matches": [
            {
                "engine_oil_id": item,
                "compatibility_type": "COMPATIBLE",
                "match_score": 80,
                "confidence_score": 0.9,
                "reasons": ["meets specification"],
            }
            for item in ids
        ],
    }
    adapter = GeminiResearchAdapter(
        GeminiClient(
            settings(),
            sdk_client(
                response("Grounded technical findings."),
                response(payload, grounded=False),
            ),
        )
    )
    if error:
        with pytest.raises(GeminiProviderError, match=error):
            await adapter.research_vehicle_with_catalog(vehicle(), oils)
    else:
        result = await adapter.research_vehicle_with_catalog(vehicle(), oils)
        assert [match.engine_oil_id for match in result.matches] == ids
        calls = adapter.client.client.aio.models.generate_content.await_args_list
        assert "COMPLETE CATALOG" not in calls[0].kwargs["contents"]
        assert "COMPLETE CATALOG" in calls[1].kwargs["contents"]
        assert calls[1].kwargs["config"].response_schema is None
        assert (
            calls[1].kwargs["config"].response_json_schema
            == _gemini_response_json_schema(CatalogResearchResult)
        )


def test_all_adapters_satisfy_runtime_protocol_and_factory_selection():
    gemini = create_research_provider(settings())
    assert isinstance(gemini, ResearchProvider)
    assert isinstance(gemini, CatalogResearchProvider)
    openrouter = create_research_provider(
        settings(
            research_provider="openrouter",
            openrouter_api_key="test-key",
            openrouter_model="provider/model",
        )
    )
    assert isinstance(openrouter, ResearchAgent)
    assert isinstance(openrouter, ResearchProvider)
    opencode = create_research_provider(settings(research_provider="opencode"))
    assert isinstance(opencode, OpenCodeResearchAgent)
    assert isinstance(opencode, ResearchProvider)
    gemini.client.client.close()


def test_catalog_strategy_rejects_non_gemini_provider():
    with pytest.raises(ResearchProviderConfigurationError, match="only by Gemini"):
        Settings(research_provider="openrouter", matching_strategy="provider_catalog")
