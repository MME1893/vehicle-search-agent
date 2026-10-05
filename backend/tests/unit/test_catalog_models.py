from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.domain.identity import engine_oil_identity_key, vehicle_identity_key
from app.models import EngineOil, Vehicle
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.engine_oil import EngineOilCreate, EngineOilRead
from app.schemas.vehicle import VehicleCreate, VehicleRead

VEHICLE_IDENTITY = {
    "manufacturer": "Toyota",
    "model": "Hilux",
    "trim": "Double Cab",
    "production_year_from": 2024,
    "production_year_to": 2026,
    "engine_code": "2TR-FE",
    "engine_displacement": "2.7 L",
    "engine_type": "Inline-4",
    "fuel_type": "gasoline",
    "transmission": "6A",
    "drivetrain": "4WD",
    "body_type": "Pickup",
    "body_style": "Midsize Pickup",
}


def _vehicle_key(**changes):
    values = VEHICLE_IDENTITY | changes
    return vehicle_identity_key(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("engine_type", "V6"),
        ("engine_displacement", "4.0 L"),
        ("fuel_type", "diesel"),
        ("transmission", "5M"),
        ("drivetrain", "2WD"),
        ("body_type", "SUV"),
        ("body_style", "Full-size Pickup"),
    ],
)
def test_vehicle_identity_includes_frozen_variant_fields(field, value):
    assert _vehicle_key() != _vehicle_key(**{field: value})


def test_vehicle_identity_ignores_power_and_torque_through_orm_hook(db):
    vehicle = VehicleRepository(db).create(
        VEHICLE_IDENTITY | {"power_hp": 134, "torque_nm": 241}
    )
    original = vehicle.identity_key
    VehicleRepository(db).update(vehicle, {"power_hp": 140, "torque_nm": 250})
    assert vehicle.identity_key == original
    VehicleRepository(db).update(vehicle, {"transmission": "5M"})
    assert vehicle.identity_key != original


def test_vehicle_new_fields_round_trip_schema_and_positive_constraints(db):
    payload = VehicleCreate(**VEHICLE_IDENTITY, power_hp=134, torque_nm=241)
    vehicle = VehicleRepository(db).create(payload.model_dump())
    read = VehicleRead.model_validate(vehicle)
    assert read.engine_type == "Inline-4" and read.body_style == "Midsize Pickup"
    with pytest.raises(ValidationError):
        VehicleCreate(manufacturer="M", model="V", power_hp=0)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(Vehicle(manufacturer="M", model="V", torque_nm=-1))
        db.flush()


def test_engine_oil_package_identity_is_decimal_stable_and_metadata_free():
    base = engine_oil_identity_key("Shell", "X", "5W-40", 4)
    assert base == engine_oil_identity_key("Shell", "X", "5W-40", 4.0)
    assert base == engine_oil_identity_key("Shell", "X", "5W-40", Decimal("4.00"))
    assert base != engine_oil_identity_key("Shell", "X", "5W-40", 1)
    assert engine_oil_identity_key("Shell", "X", "5W-40", None).endswith("|")


def test_engine_oil_new_fields_round_trip_and_positive_constraints(db):
    payload = EngineOilCreate(
        brand="Shell",
        name="Helix",
        sae_viscosity="5W-40",
        api_spec="SP",
        acea_specs=["A3/B4"],
        ilsac_spec="GF-6",
        package_volume_liters=Decimal("4.00"),
        package_volume_label="4 Liters",
        claimed_service_interval_km=10000,
    )
    oil = EngineOilRepository(db).create(payload.model_dump())
    read = EngineOilRead.model_validate(oil)
    assert read.package_volume_liters == Decimal("4.00")
    assert read.claimed_service_interval_km == 10000
    with pytest.raises(ValidationError):
        EngineOilCreate(brand="B", name="N", sae_viscosity="5W-40", package_volume_liters=0)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            EngineOil(
                brand="B",
                name="N",
                sae_viscosity="5W-40",
                claimed_service_interval_km=-1,
            )
        )
        db.flush()


def test_engine_oil_identity_ignores_specification_metadata(db):
    oil = EngineOilRepository(db).create(
        {
            "brand": "Shell",
            "name": "X",
            "sae_viscosity": "5W-40",
            "package_volume_liters": Decimal("4.00"),
        }
    )
    original = oil.identity_key
    EngineOilRepository(db).update(
        oil,
        {
            "api_spec": "SP",
            "acea_specs": ["A3/B4"],
            "ilsac_spec": "GF-6",
            "base_type": "synthetic",
            "oem_approvals": ["MB 229.5"],
            "package_volume_label": "4 L",
            "claimed_service_interval_km": 10000,
        },
    )
    assert oil.identity_key == original
