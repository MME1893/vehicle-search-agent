import argparse
import json
from decimal import Decimal

import pytest

from app.models import EngineOil, Vehicle
from scripts.import_engine_oils import import_engine_oils
from scripts.import_vehicles import import_vehicles, popularity_range


def _write(path, key, values):
    path.write_text(json.dumps({key: values}), encoding="utf-8")


def test_import_vehicle_new_shape_trim_alias_and_generated_ids(db, tmp_path):
    path = tmp_path / "vehicles.json"
    _write(path, "vehicles", [{
        "id": 312, "manufacturer": "Toyota", "model": "Hilux",
        "trim_variant": "2.7 Double Cab 4x4", "production_year_from": 2024,
        "production_year_to": 2026, "engine_displacement": "2.7 L",
        "engine_type": "Inline-4", "fuel_type": "gasoline", "power_hp": 134,
        "torque_nm": 241, "transmission": "5M/6A", "drivetrain": "4WD",
        "body_type": "Pickup", "body_style": "Midsize Pickup", "popularity": 100,
    }])

    assert import_vehicles(str(path), db) == (1, 0, 0, 0)
    vehicle = db.query(Vehicle).one()
    assert vehicle.id != 312
    assert vehicle.trim == "2.7 Double Cab 4x4"
    assert vehicle.engine_displacement == "2.7 L"
    assert vehicle.engine_type == "Inline-4"
    assert vehicle.power_hp == 134 and vehicle.torque_nm == 241
    assert not hasattr(vehicle, "popularity")
    assert import_vehicles(str(path), db) == (0, 1, 0, 0)


def test_import_vehicle_prefers_trim_and_filters_popularity(db, tmp_path):
    path = tmp_path / "vehicles.json"
    _write(path, "vehicles", [
        {"manufacturer": "A", "model": "low", "trim": "T", "trim_variant": "wrong", "popularity": 0},
        {"manufacturer": "A", "model": "edge", "popularity": 30},
        {"manufacturer": "A", "model": "middle", "popularity": 50},
        {"manufacturer": "A", "model": "high", "popularity": 90},
        {"manufacturer": "A", "model": "top", "popularity": 100},
        {"manufacturer": "A", "model": "missing"},
    ])
    assert import_vehicles(str(path), db, popularity_ranges=[(0, 30), (90, 100)]) == (
        4, 0, 2, 0
    )
    assert db.query(Vehicle).filter_by(model="low").one().trim == "T"


def test_import_vehicle_no_ranges_imports_missing_popularity_and_reports_invalid(db, tmp_path):
    path = tmp_path / "vehicles.json"
    _write(path, "vehicles", [
        {"manufacturer": "A", "model": "valid"},
        {"manufacturer": "A", "model": "bad-popularity", "popularity": 101},
        {"manufacturer": "A", "model": "bad-power", "power_hp": 0},
        {"manufacturer": "A", "model": "bad-years", "production_year_from": 2025, "production_year_to": 2024},
    ])
    assert import_vehicles(str(path), db) == (1, 0, 0, 3)


@pytest.mark.parametrize("value", ["90", "90-", "-100", "abc-def", "100-90", "0-101"])
def test_popularity_range_rejects_malformed_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        popularity_range(value)


def test_popularity_range_accepts_inclusive_and_overlapping_ranges():
    assert popularity_range("0-30") == (0, 30)
    assert popularity_range("100-100") == (100, 100)


def test_import_engine_oil_new_fields_identity_and_generated_ids(db, tmp_path):
    path = tmp_path / "engine_oils.json"
    _write(path, "engine_oils", [
        {
            "id": 19, "created_from_research_run_id": None, "brand": "Toyota",
            "name": "Toyota 20W50 SL", "sae_viscosity": "20W-50", "api_spec": "SL",
            "acea_specs": [" A3/B4 ", "", "A3/B4"], "ilsac_spec": "GF-5",
            "oem_approvals": [], "package_volume_liters": 4.0,
            "package_volume_label": "4 Liters", "claimed_service_interval_km": 5000,
        },
        {"brand": "Toyota", "name": "Toyota 20W50 SL", "sae_viscosity": "20W-50", "package_volume_liters": 4.00},
        {"brand": "Toyota", "name": "Toyota 20W50 SL", "sae_viscosity": "20W-50", "package_volume_liters": 1, "service_interval_km": 4000},
    ])

    assert import_engine_oils(str(path), db) == (2, 1, 0)
    oils = db.query(EngineOil).order_by(EngineOil.package_volume_liters).all()
    assert all(oil.id != 19 for oil in oils)
    assert oils[0].package_volume_liters == Decimal("1.00")
    assert oils[0].claimed_service_interval_km == 4000
    assert oils[1].ilsac_spec == "GF-5"
    assert oils[1].acea_specs == ["A3/B4"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("package_volume_liters", 0, "package_volume_liters must be greater than 0"),
        ("package_volume_liters", -1, "package_volume_liters must be greater than 0"),
        ("package_volume_liters", 1.234, "does not fit Numeric"),
        ("claimed_service_interval_km", 0, "claimed_service_interval_km must be greater than 0"),
        ("acea_specs", 42, "acea_specs must be a list"),
        ("oem_approvals", 42, "oem_approvals must be a list"),
        ("created_from_research_run_id", 7, "must be null"),
    ],
)
def test_import_engine_oil_invalid_rows_have_field_specific_errors(
    db, tmp_path, capsys, field, value, message
):
    path = tmp_path / "engine_oils.json"
    row = {"brand": "B", "name": "N", "sae_viscosity": "5W-40", field: value}
    _write(path, "engine_oils", [row])
    assert import_engine_oils(str(path), db) == (0, 0, 1)
    assert message in capsys.readouterr().out
