import argparse
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

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
    "engine_code", "engine_displacement", "engine_type", "fuel_type", "power_hp",
    "torque_nm", "transmission", "drivetrain", "body_type", "body_style",
)
POPULARITY_RANGE = re.compile(r"^(\d+)-(\d+)$")


def _source_id(row: dict) -> str:
    return str(row.get("id", "unknown"))


def _vehicle_data(row: dict) -> dict:
    missing = [field for field in REQUIRED if row.get(field) in (None, "")]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    data = {field: row.get(field) for field in VEHICLE_FIELDS}
    data["trim"] = row.get("trim") or row.get("trim_variant")
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
    for field in ("power_hp", "torque_nm"):
        data[field] = int(data[field]) if data[field] not in (None, "") else None
        if data[field] is not None and data[field] <= 0:
            raise ValueError(f"{field} must be greater than 0")
    return data


def popularity_range(value: str) -> tuple[int, int]:
    match = POPULARITY_RANGE.fullmatch(value)
    if not match:
        raise argparse.ArgumentTypeError(
            "popularity range must use FROM-TO, for example 90-100"
        )
    lower, upper = map(int, match.groups())
    if not 0 <= lower <= upper <= 100:
        raise argparse.ArgumentTypeError(
            "popularity range must satisfy 0 <= FROM <= TO <= 100"
        )
    return lower, upper


def _popularity(row: dict) -> Decimal | None:
    value = row.get("popularity")
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("popularity must be a number from 0 to 100") from exc
    if not result.is_finite() or not 0 <= result <= 100:
        raise ValueError("popularity must be a number from 0 to 100")
    return result


def import_vehicles(
    path: str,
    db: Session,
    dry_run: bool = False,
    popularity_ranges: list[tuple[int, int]] | None = None,
) -> tuple[int, int, int, int]:
    repo = VehicleRepository(db)
    imported = skipped_existing = filtered = invalid = 0
    popularity_ranges = popularity_ranges or []
    for row in rows(path, collection_key="vehicles"):
        if not isinstance(row, dict):
            print("Invalid vehicle source_id=unknown: row must be an object")
            invalid += 1
            continue
        try:
            popularity = _popularity(row)
            if popularity_ranges and (
                popularity is None
                or not any(lower <= popularity <= upper for lower, upper in popularity_ranges)
            ):
                filtered += 1
                continue
            data = _vehicle_data(row)
            if repo.find_by_identity(data):
                skipped_existing += 1
                continue
            if not dry_run:
                with db.begin_nested():
                    repo.create(data)
            imported += 1
        except (TypeError, ValueError, SQLAlchemyError) as exc:
            print(f"Invalid vehicle source_id={_source_id(row)}: {exc}")
            invalid += 1
    if imported and not dry_run:
        db.commit()
    return imported, skipped_existing, filtered, invalid


def main(
    path: str,
    dry_run: bool = False,
    popularity_ranges: list[tuple[int, int]] | None = None,
) -> None:
    with SessionLocal() as db:
        result = import_vehicles(path, db, dry_run, popularity_ranges)
    print(
        f"Imported: {result[0]}\nSkipped existing: {result[1]}\n"
        f"Filtered: {result[2]}\nInvalid: {result[3]}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import vehicles from JSON or CSV.")
    parser.add_argument("path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--popularity-range",
        action="append",
        type=popularity_range,
        default=[],
        dest="popularity_ranges",
        metavar="FROM-TO",
    )
    args = parser.parse_args()
    main(args.path, args.dry_run, args.popularity_ranges)
