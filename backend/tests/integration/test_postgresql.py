import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import get_db
from app.main import app
from app.repositories.agent_job_repository import AgentJobRepository
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository


@pytest.fixture
def postgres_sessions():
    url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not configured")
    engine = create_engine(url, pool_pre_ping=True)
    assert engine.dialect.name == "postgresql"
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def test_restrict_delete_is_reported_as_conflict(postgres_sessions):
    suffix = uuid4().hex
    with postgres_sessions() as seed:
        vehicle = VehicleRepository(seed).create(
            {"manufacturer": "Postgres", "model": f"Restrict-{suffix}"}
        )
        oil = EngineOilRepository(seed).create(
            {
                "brand": "Postgres",
                "name": f"Restrict-{suffix}",
                "sae_viscosity": "5W-40",
                "oem_approvals": [],
            }
        )
        CompatibilityRepository(seed).create_event(
            {
                "vehicle_id": vehicle.id,
                "engine_oil_id": oil.id,
                "match_method": "MANUAL",
                "compatibility_type": "COMPATIBLE",
                "match_score": 80,
                "confidence_score": 0.8,
                "created_by": "ADMIN",
            }
        )
        vehicle_id, oil_id = vehicle.id, oil.id
        seed.commit()

    def override_db():
        with postgres_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        assert client.delete(f"/api/v1/vehicles/{vehicle_id}").status_code == 409
        assert client.delete(f"/api/v1/engine-oils/{oil_id}").status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_skip_locked_prevents_two_workers_claiming_one_job(postgres_sessions):
    suffix = uuid4().hex
    with postgres_sessions() as seed:
        vehicle = VehicleRepository(seed).create(
            {"manufacturer": "Postgres", "model": f"Locking-{suffix}"}
        )
        job = AgentJobRepository(seed).create({"vehicle_id": vehicle.id})
        job_id = job.id
        seed.commit()

    first = postgres_sessions()
    second = postgres_sessions()
    try:
        assert AgentJobRepository(first).get_pending_for_update(job_id).id == job_id
        assert AgentJobRepository(second).get_pending_for_update(job_id) is None
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
