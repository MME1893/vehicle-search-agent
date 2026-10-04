from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.schemas import EngineOilResearchResult
from app.core.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.research import ResearchService


@pytest.fixture
def api_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def research_result(vehicle_id: int, confidence: float = 0.93):
    return EngineOilResearchResult.model_validate(
        {
            "research_status": "FOUND",
            "vehicle_id": vehicle_id,
            "engine_code": "TU5",
            "recommended_sae": ["10W-40"],
            "minimum_api": "SL",
            "confidence": confidence,
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


async def persist_research(db, vehicle_id: int, confidence: float = 0.93):
    provider = SimpleNamespace(
        provider_name="test-provider",
        research_vehicle_oil_spec=AsyncMock(
            return_value=research_result(vehicle_id, confidence)
        ),
    )
    service = ResearchService(db, provider, Settings())
    return await service.execute_vehicle_research(vehicle_id)


@pytest.mark.asyncio
async def test_history_api_returns_complete_timeline(api_db):
    vehicle = VehicleRepository(api_db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    oil = EngineOilRepository(api_db).create(
        {
            "brand": "Test",
            "name": "Oil",
            "sae_viscosity": "10W-40",
            "api_spec": "SN",
            "oem_approvals": [],
        }
    )
    outcome = await persist_research(api_db, vehicle.id)

    def override_db():
        yield api_db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(f"/api/research/vehicles/{vehicle.id}/history")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["vehicle"]["id"] == vehicle.id
    assert len(payload["timeline"]) == 1
    entry = payload["timeline"][0]
    assert entry["research_run"]["id"] == outcome.research_run.id
    assert entry["sources"][0]["source_type"] == "OFFICIAL_MANUAL"
    assert entry["matched_oils"][0]["id"] == oil.id
    assert entry["compatibilities"][0]["match_method"] == (
        "DETERMINISTIC_SPEC_MATCH"
    )


def test_history_api_returns_404_for_unknown_vehicle(api_db):
    def override_db():
        yield api_db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/research/vehicles/999/history")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json() == {"detail": "vehicle not found"}


@pytest.mark.asyncio
async def test_persistence_flow_keeps_each_run_and_compatibility_snapshot(db):
    vehicle = VehicleRepository(db).create(
        {"manufacturer": "Peugeot", "model": "206", "engine_code": "TU5"}
    )
    EngineOilRepository(db).create(
        {
            "brand": "Test",
            "name": "Oil",
            "sae_viscosity": "10W-40",
            "api_spec": "SN",
            "oem_approvals": [],
        }
    )

    first = await persist_research(db, vehicle.id, 0.91)
    second = await persist_research(db, vehicle.id, 0.97)

    from app.services.research.history_service import ResearchHistoryService

    history = ResearchHistoryService(db).get_vehicle_history(vehicle.id)
    assert [entry.research_run.id for entry in history.timeline] == [
        first.research_run.id,
        second.research_run.id,
    ]
    assert [len(entry.compatibilities) for entry in history.timeline] == [1, 1]
    assert history.timeline[0].compatibilities[0].confidence_score == 0.91
    assert history.timeline[1].compatibilities[0].confidence_score == 0.97
