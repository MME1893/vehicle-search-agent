import pytest
from pydantic import ValidationError

from app.repositories.agent_job_repository import AgentJobRepository
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.engine_oil import EngineOilCreate
from app.schemas.vehicle import VehicleCreate


def test_vehicle_create_validation_and_read(db):
    data = VehicleCreate(manufacturer="Iran Khodro", model="Samand", engine_code="TU5")
    vehicle = VehicleRepository(db).create(data.model_dump())
    assert VehicleRepository(db).get_by_id(vehicle.id).model == "Samand"
    with pytest.raises(ValidationError):
        VehicleCreate(manufacturer="", model="x")


def test_oil_approvals_and_filtering(db):
    EngineOilRepository(db).create(
        EngineOilCreate(
            brand="X",
            name="Y",
            sae_viscosity="5W-40",
            api_spec="SN",
            oem_approvals=["MB 229.5"],
        ).model_dump()
    )
    found, total = EngineOilRepository(db).list(sae_viscosity="5W-40")
    assert total == 1 and found[0].oem_approvals == ["MB 229.5"]


def test_compatibility_is_append_only(db):
    vehicle = VehicleRepository(db).create({"manufacturer": "M", "model": "V"})
    oil = EngineOilRepository(db).create(
        {"brand": "B", "name": "O", "sae_viscosity": "5W-40", "oem_approvals": []}
    )
    repo = CompatibilityRepository(db)
    repo.create(
        {
            "vehicle_id": vehicle.id,
            "engine_oil_id": oil.id,
            "compatibility_type": "COMPATIBLE",
            "match_score": 50,
            "confidence_score": 0.5,
            "created_by": "SYSTEM",
            "match_method": "MANUAL",
        }
    )
    repo.create(
        {
            "vehicle_id": vehicle.id,
            "engine_oil_id": oil.id,
            "compatibility_type": "COMPATIBLE",
            "match_score": 0,
            "confidence_score": 0.5,
            "created_by": "SYSTEM",
            "match_method": "MANUAL",
        }
    )
    assert len(repo.get_current_for_vehicle(vehicle.id)) == 1


def test_pending_job_retrieval(db):
    vehicle = VehicleRepository(db).create({"manufacturer": "M", "model": "V"})
    job = AgentJobRepository(db).create({"vehicle_id": vehicle.id})
    assert AgentJobRepository(db).get_next_pending().id == job.id
