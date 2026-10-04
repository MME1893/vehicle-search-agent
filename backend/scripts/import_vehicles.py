import argparse
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal
from app.repositories.vehicle_repository import VehicleRepository
from scripts.import_common import rows

REQUIRED = ("manufacturer", "model")
VEHICLE_FIELDS = (
    "manufacturer", "model", "trim", "production_year_from", "production_year_to",
    "engine_code", "engine_displacement", "fuel_type",
)


def _source_id(row: dict) -> str:
    return str(row.get("id", "unknown"))


def _vehicle_data(row: dict) -> dict:
    missing = [field for field in REQUIRED if row.get(field) in (None, "")]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    data = {field: row.get(field) for field in VEHICLE_FIELDS}
    data["trim"] = row.get("trim") if "trim" in row else row.get("trim_variant")
    for field in ("production_year_from", "production_year_to"):
        data[field] = int(data[field]) if data[field] not in (None, "") else None
    if (
        data["production_year_from"] is not None
        and data["production_year_to"] is not None
        and data["production_year_from"] > data["production_year_to"]
    ):
        raise ValueError("production_year_from > production_year_to")
    if data["engine_displacement"] is not None:
        data["engine_displacement"] = str(data["engine_displacement"])
    return data


def _sync_sequence(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT setval(pg_get_serial_sequence('vehicles', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM vehicles), 1), true)"))


def import_vehicles(path: str, db: Session, dry_run: bool = False) -> tuple[int, int, int]:
    repo = VehicleRepository(db)
    imported = skipped = invalid = 0
    for row in rows(path, collection_key="vehicles"):
        if not isinstance(row, dict):
            print("Invalid vehicle source_id=unknown: row must be an object")
            invalid += 1
            continue
        try:
            data = _vehicle_data(row)
            if row.get("id") is not None:
                source_id = int(row["id"])
                if repo.get_by_id(source_id):
                    skipped += 1
                    continue
                data["id"] = source_id
            if not dry_run:
                with db.begin_nested():
                    repo.create(data)
            imported += 1
        except (TypeError, ValueError, SQLAlchemyError) as exc:
            print(f"Invalid vehicle source_id={_source_id(row)}: {exc}")
            invalid += 1
    if imported and not dry_run:
        _sync_sequence(db)
        db.commit()
    return imported, skipped, invalid


def main(path: str, dry_run: bool = False) -> None:
    with SessionLocal() as db:
        result = import_vehicles(path, db, dry_run)
    print(f"Imported: {result[0]}\nSkipped: {result[1]}\nInvalid: {result[2]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import vehicles from JSON or CSV.")
    parser.add_argument("path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.path, args.dry_run)
