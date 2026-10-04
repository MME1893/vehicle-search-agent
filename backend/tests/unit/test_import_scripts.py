import json

from app.models import EngineOil, Vehicle
from scripts.import_engine_oils import import_engine_oils
from scripts.import_vehicles import import_vehicles


def test_import_vehicle_actual_json_shape_and_idempotency(db, tmp_path):
    path = tmp_path / "vehicles.json"
    path.write_text(json.dumps({"vehicles": [
        {"id": 312, "manufacturer": "\u067e\u0698\u0648", "model": "206", "trim_variant": "\u062a\u06cc\u067e 5",
         "production_year_from": 2003, "production_year_to": 2021, "engine_code": "TU5",
         "engine_displacement": 1587, "fuel_type": "gasoline"},
        {"id": 313, "manufacturer": "M", "model": "Incomplete", "engine_code": None,
         "engine_displacement": None},
    ]}), encoding="utf-8")

    assert import_vehicles(str(path), db) == (2, 0, 0)
    vehicle = db.get(Vehicle, 312)
    assert vehicle.trim == "\u062a\u06cc\u067e 5"
    assert vehicle.engine_displacement == "1587"
    incomplete = db.get(Vehicle, 313)
    assert incomplete.engine_code is None
    assert incomplete.engine_displacement is None
    assert import_vehicles(str(path), db) == (0, 2, 0)


def test_import_engine_oil_actual_json_shape_preserves_api_spec(db, tmp_path):
    path = tmp_path / "engine_oils.json"
    path.write_text(json.dumps({"engine_oils": [{
        "id": 19, "brand": "TotalEnergies", "name": "Quartz 7000 10W-40",
        "sae_viscosity": "10W-40", "api_spec": "SN/CF", "acea_spec": "A3/B4",
        "base_type": "Semi Synthetic", "oem_approvals": ["PSA B71 2300", "Renault RN0700"],
    }]}), encoding="utf-8")

    assert import_engine_oils(str(path), db) == (1, 0, 0)
    oil = db.get(EngineOil, 19)
    assert oil.api_spec == "SN/CF"
    assert oil.oem_approvals == ["PSA B71 2300", "Renault RN0700"]
