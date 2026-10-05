import pytest
from pydantic import ValidationError

from app.repositories.agent_job_repository import AgentJobRepository
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.agent_job import AgentJobCreate
from app.schemas.compatibility import CompatibilityCreate
from app.schemas.engine_oil import EngineOilCreate, EngineOilUpdate
from app.schemas.vehicle import VehicleCreate, VehicleUpdate


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
    repo.create_event(
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
    repo.create_event(
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


def test_vehicle_identity_includes_displacement_and_fuel_type(db):
    repo = VehicleRepository(db)
    gasoline = repo.create(
        {
            "manufacturer": "M",
            "model": "V",
            "engine_displacement": "1.6",
            "fuel_type": "gasoline",
        }
    )
    diesel = repo.create(
        {
            "manufacturer": "M",
            "model": "V",
            "engine_displacement": "1.5",
            "fuel_type": "diesel",
        }
    )
    assert gasoline.identity_key != diesel.identity_key


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (VehicleUpdate, {"manufacturer": None}),
        (VehicleUpdate, {"model": None}),
        (EngineOilUpdate, {"brand": None}),
        (EngineOilUpdate, {"name": None}),
        (EngineOilUpdate, {"sae_viscosity": None}),
    ],
)
def test_patch_rejects_explicit_null_for_non_nullable_fields(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_job_create_is_worker_owned_and_manual_audit_cannot_be_spoofed():
    assert AgentJobCreate(vehicle_id=1).model_dump() == {
        "vehicle_id": 1,
        "agent_version": None,
    }
    with pytest.raises(ValidationError):
        AgentJobCreate(vehicle_id=1, research_run_id=9)
    with pytest.raises(ValidationError):
        CompatibilityCreate(
            vehicle_id=1,
            engine_oil_id=2,
            compatibility_type="COMPATIBLE",
            match_score=80,
            confidence_score=0.8,
            created_by="AGENT",
        )


def test_compatibility_repository_has_no_mutation_api(db):
    repo = CompatibilityRepository(db)
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")
