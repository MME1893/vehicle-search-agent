from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.schemas import CatalogResearchResult, EngineOilResearchResult
from app.core.config import Settings
from app.models import CompatibilityHistory, EngineOil, ResearchRun
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.research import ResearchService


@pytest.mark.asyncio
async def test_accepted_research_persists_spec_and_deterministic_matches(db):
    vehicle = VehicleRepository(db).create(
        {
            "manufacturer": "Iran Khodro",
            "model": "Peugeot 206",
            "engine_code": "TU5",
        }
    )
    oil = EngineOilRepository(db).create(
        {
            "brand": "Test",
            "name": "Oil",
            "sae_viscosity": "10W-40",
            "api_spec": "SN",
            "oem_approvals": [],
        }
    )
    result = EngineOilResearchResult.model_validate(
        {
            "research_status": "FOUND",
            "vehicle_id": vehicle.id,
            "engine_code": "TU5",
            "recommended_sae": ["10W-40"],
            "minimum_api": "SL",
            "confidence": 0.93,
            "sources": [
                {
                    "title": "Official manual",
                    "url": "https://manufacturer.example/manual.pdf",
                    "source_type": "OFFICIAL_MANUAL",
                    "supported_claims": ["SAE 10W-40", "API SL"],
                }
            ],
        }
    )
    agent = SimpleNamespace(research_vehicle_oil_spec=AsyncMock(return_value=result))
    service = ResearchService(db, agent, Settings(research_min_confidence=0.8))

    outcome = await service.research_vehicle(vehicle.id)
    assert outcome.evaluation.accepted
    assert service.find_candidates(outcome)[0].oil.id == oil.id

    spec = service.persist_engine_spec(outcome)
    assert spec.status == "VERIFIED"
    assert spec.evidence["sources"][0]["source_type"] == "OFFICIAL_MANUAL"
    assert service.persist_compatibilities(outcome) == 1

    saved = CompatibilityRepository(db).get_for_vehicle(vehicle.id)
    assert saved[0].engine_oil_id == oil.id
    assert saved[0].created_by == "AGENT"
    assert saved[0].research_run_id == outcome.research_run.id
    assert saved[0].engine_spec_id == spec.id
    history = db.query(CompatibilityHistory).all()
    assert len(history) == 1
    assert history[0].match_method == "DETERMINISTIC_SPEC_MATCH"


@pytest.mark.asyncio
async def test_sourced_recommended_product_is_created_before_matching_with_provenance(
    db,
):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    result = EngineOilResearchResult.model_validate(
        {
            "research_status": "FOUND",
            "vehicle_id": vehicle.id,
            "engine_code": "TU5",
            "recommended_sae": ["10W-40"],
            "minimum_api": "SL",
            "confidence": 0.94,
            "sources": [
                {
                    "title": "Official manual",
                    "url": "https://manufacturer.example/manual.pdf",
                    "source_type": "OFFICIAL_MANUAL",
                    "supported_claims": ["SAE 10W-40", "API SL"],
                }
            ],
            "recommended_products": [
                {
                    "brand": "  Test Brand ",
                    "name": "Documented Oil",
                    "sae_viscosity": "10w-40",
                    "api_spec": "SN",
                    "acea_spec": "A3/B4",
                    "base_type": "Synthetic",
                    "oem_approvals": ["PSA B71 2296"],
                    "recommendation_reason": "listed for TU5",
                    "source_urls": ["https://oil.example/product"],
                }
            ],
        }
    )
    provider = SimpleNamespace(
        provider_name="gemini",
        client=SimpleNamespace(
            model="gemini-test",
            last_research_text="raw grounded findings",
            last_grounding=SimpleNamespace(
                queries=["TU5 oil"],
                sources=[SimpleNamespace(title="Manual", uri="https://example/manual")],
            ),
            last_grounded_duration=0.125,
            last_extraction_duration=0.05,
        ),
        research_vehicle_oil_spec=AsyncMock(return_value=result),
    )
    service = ResearchService(db, provider, Settings(research_min_confidence=0.8))

    outcome = await service.research_vehicle(vehicle.id)
    spec = service.persist_engine_spec(outcome)
    matches = service.find_candidates(outcome)
    assert len(matches) == 1
    oil = db.query(EngineOil).one()
    assert oil.brand == "Test Brand"
    assert oil.acea_spec == "A3/B4"
    assert oil.oem_approvals == ["PSA B71 2296"]
    assert oil.created_from_research_run_id == outcome.research_run.id
    run = db.query(ResearchRun).one()
    assert run.raw_research_text == "raw grounded findings"
    assert run.search_queries == ["TU5 oil"]
    assert run.stage1_duration_ms == 125
    assert run.structured_result["recommended_products"][0]["name"] == "Documented Oil"

    assert service.persist_compatibilities(outcome) == 1
    compatibility = CompatibilityRepository(db).get_for_vehicle(vehicle.id)[0]
    history = db.query(CompatibilityHistory).one()
    assert compatibility.engine_oil_id == oil.id
    assert compatibility.engine_spec_id == spec.id
    assert history.match_method == "DIRECT_RESEARCH_PRODUCT"


@pytest.mark.asyncio
async def test_product_without_source_stays_in_research_but_is_not_created(db):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    result = EngineOilResearchResult.model_validate(
        {
            "research_status": "FOUND",
            "vehicle_id": vehicle.id,
            "engine_code": "TU5",
            "recommended_sae": ["10W-40"],
            "confidence": 0.9,
            "sources": [
                {
                    "title": "Manual",
                    "url": "https://example/manual",
                    "source_type": "OFFICIAL_MANUAL",
                    "supported_claims": ["SAE 10W-40"],
                }
            ],
            "recommended_products": [
                {
                    "brand": "Unknown",
                    "name": "Unsourced",
                    "sae_viscosity": "10W-40",
                }
            ],
        }
    )
    provider = SimpleNamespace(research_vehicle_oil_spec=AsyncMock(return_value=result))
    service = ResearchService(db, provider, Settings())
    outcome = await service.research_vehicle(vehicle.id)
    service.persist_engine_spec(outcome)
    assert outcome.result.recommended_products[0].name == "Unsourced"
    assert db.query(EngineOil).count() == 0


@pytest.mark.asyncio
async def test_provider_catalog_uses_one_call_and_skips_deterministic_matcher(db):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    oil = EngineOilRepository(db).create(
        {
            "brand": "Test",
            "name": "Oil",
            "sae_viscosity": "10W-40",
            "api_spec": "SN",
            "oem_approvals": [],
        }
    )
    research = EngineOilResearchResult.model_validate(
        {
            "research_status": "FOUND",
            "vehicle_id": vehicle.id,
            "engine_code": "TU5",
            "recommended_sae": ["10W-40"],
            "minimum_api": "SL",
            "confidence": 0.93,
            "sources": [
                {
                    "title": "Official manual",
                    "url": "https://manufacturer.example/manual.pdf",
                    "source_type": "OFFICIAL_MANUAL",
                    "supported_claims": ["SAE 10W-40", "API SL"],
                }
            ],
        }
    )
    catalog_result = CatalogResearchResult.model_validate(
        {
            "research": research,
            "matches": [
                {
                    "engine_oil_id": oil.id,
                    "compatibility_type": "RECOMMENDED",
                    "match_score": 95,
                    "confidence_score": 0.88,
                    "reasons": ["exact SAE", "API exceeds minimum"],
                }
            ],
        }
    )

    class CatalogProvider:
        provider_name = "gemini"

        async def research_vehicle_oil_spec(self, vehicle):
            raise AssertionError("normal research path must not be called")

        research_vehicle_with_catalog = AsyncMock(return_value=catalog_result)

    provider = CatalogProvider()
    service = ResearchService(
        db,
        provider,
        Settings(
            research_provider="gemini",
            matching_strategy="provider_catalog",
            gemini_api_key="test",
        ),
    )
    service.matcher = MagicMock()

    outcome = await service.research_vehicle(vehicle.id)
    sent_oils = provider.research_vehicle_with_catalog.await_args.args[1]
    assert [item.id for item in sent_oils] == [oil.id]
    assert outcome.evaluation.accepted
    assert service.find_candidates(outcome) == []
    service.matcher.find_candidates.assert_not_called()

    service.persist_engine_spec(outcome)
    assert service.persist_compatibilities(outcome) == 1
    saved = CompatibilityRepository(db).get_for_vehicle(vehicle.id)[0]
    assert saved.engine_oil_id == oil.id
    assert saved.confidence_score == 0.88
    assert saved.reason == "exact SAE; API exceeds minimum"
