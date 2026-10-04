from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.schemas import (
    EngineOilResearchResult,
    ProviderOilMatch,
    ResearchExecution,
)
from app.core.config import Settings
from app.models import Compatibility, EngineOil, ResearchRun
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.research import ResearchService


def result(vehicle_id, *, products=None, confidence=0.93):
    return EngineOilResearchResult.model_validate(
        {
            "research_status": "FOUND",
            "vehicle_id": vehicle_id,
            "engine_code": "TU5",
            "recommended_sae": ["10W-40"],
            "minimum_api": "SL",
            "confidence": confidence,
            "sources": [{
                "title": "Official manual",
                "url": "https://manufacturer.example/manual.pdf",
                "source_type": "OFFICIAL_MANUAL",
                "supported_claims": ["SAE 10W-40", "API SL"],
            }],
            "recommended_products": products or [],
        }
    )


@pytest.mark.asyncio
async def test_accepted_research_persists_append_only_match(db):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Iran Khodro", "model": "206", "engine_code": "TU5"}
    )
    oil = EngineOilRepository(db).create(
        {"brand": "Test", "name": "Oil", "sae_viscosity": "10W-40",
         "api_spec": "SN", "acea_specs": [], "oem_approvals": []}
    )
    provider = SimpleNamespace(
        provider_name="test",
        research_vehicle_oil_spec=AsyncMock(return_value=ResearchExecution(
            research=result(vehicle.id), provider="test", model="model"
        )),
    )
    outcome = await ResearchService(db, provider, Settings()).execute_vehicle_research(vehicle.id)
    events = db.query(Compatibility).all()
    assert outcome.evaluation.accepted
    assert events[0].engine_oil_id == oil.id
    assert events[0].match_method == "DETERMINISTIC_SPEC_MATCH"
    assert events[0].research_run_id == outcome.research_run.id
    assert db.query(ResearchRun).one().evaluation_status == "ACCEPTED"


@pytest.mark.asyncio
async def test_sourced_product_is_created_with_explicit_execution_metadata(db):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    product = {
        "brand": " Test Brand ", "name": "Documented Oil", "sae_viscosity": "10w-40",
        "api_spec": "SN", "acea_specs": ["A3/B4"], "oem_approvals": ["PSA B71 2296"],
        "source_urls": ["https://oil.example/product"],
    }
    execution = ResearchExecution(
        research=result(vehicle.id, products=[product]), provider="gemini", model="gemini-test",
        raw_research_text="raw", search_queries=["TU5 oil"],
        grounding_sources=[{"title": "Manual", "url": "https://example/manual"}],
        stage1_duration_ms=125, stage2_duration_ms=50,
    )
    provider = SimpleNamespace(research_vehicle_oil_spec=AsyncMock(return_value=execution))
    outcome = await ResearchService(db, provider, Settings()).execute_vehicle_research(vehicle.id)
    oil = db.query(EngineOil).one()
    run = db.query(ResearchRun).one()
    assert oil.acea_specs == ["A3/B4"]
    assert oil.created_from_research_run_id == run.id
    assert run.raw_research_text == "raw" and run.search_queries == ["TU5 oil"]
    assert db.query(Compatibility).one().match_method == "DIRECT_RESEARCH_PRODUCT"
    assert outcome.compatibility_ids


@pytest.mark.asyncio
async def test_unsourced_product_is_not_created(db):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    product = {"brand": "Unknown", "name": "Unsourced", "sae_viscosity": "10W-40"}
    provider = SimpleNamespace(research_vehicle_oil_spec=AsyncMock(return_value=result(vehicle.id, products=[product])))
    await ResearchService(db, provider, Settings()).execute_vehicle_research(vehicle.id)
    assert db.query(EngineOil).count() == 0


@pytest.mark.asyncio
async def test_provider_catalog_skips_deterministic_matcher(db):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    oil = EngineOilRepository(db).create(
        {"brand": "Test", "name": "Oil", "sae_viscosity": "10W-40",
         "api_spec": "SN", "acea_specs": [], "oem_approvals": []}
    )

    class Provider:
        provider_name = "gemini"
        async def research_vehicle_oil_spec(self, vehicle):
            raise AssertionError
        research_vehicle_with_catalog = AsyncMock(return_value=ResearchExecution(
            research=result(vehicle.id), provider="gemini",
            matches=[ProviderOilMatch(engine_oil_id=oil.id, compatibility_type="RECOMMENDED",
                                      match_score=95, confidence_score=0.88, reasons=["exact SAE"])],
        ))

    service = ResearchService(db, Provider(), Settings(matching_strategy="provider_catalog"))
    service.matcher = MagicMock()
    outcome = await service.execute_vehicle_research(vehicle.id)
    service.matcher.find_candidates.assert_not_called()
    assert outcome.provider_matches[0].engine_oil_id == oil.id
    assert db.query(Compatibility).one().confidence_score == 0.88
