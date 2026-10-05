import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal
from app.repositories.engine_oil_repository import EngineOilRepository
from scripts.import_common import list_value, rows

REQUIRED = ("brand", "name", "sae_viscosity")
OIL_FIELDS = (
    "brand", "name", "sae_viscosity", "api_spec", "ilsac_spec", "base_type",
    "package_volume_label",
)


def _source_id(row: dict) -> str:
    return str(row.get("id", "unknown"))


def _oil_data(row: dict) -> dict:
    missing = [field for field in REQUIRED if row.get(field) in (None, "")]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    if row.get("created_from_research_run_id") is not None:
        raise ValueError("created_from_research_run_id must be null for catalog imports")
    approvals = list_value(row.get("oem_approvals"), "oem_approvals")
    acea = list_value(row.get("acea_specs", row.get("acea_spec")), "acea_specs")
    volume = _package_volume(row.get("package_volume_liters"))
    interval_value = (
        row.get("claimed_service_interval_km")
        if "claimed_service_interval_km" in row
        else row.get("service_interval_km")
    )
    interval = int(interval_value) if interval_value not in (None, "") else None
    if interval is not None and interval <= 0:
        raise ValueError("claimed_service_interval_km must be greater than 0")
    return {
        **{field: row.get(field) for field in OIL_FIELDS},
        "acea_specs": acea,
        "oem_approvals": approvals,
        "package_volume_liters": volume,
        "claimed_service_interval_km": interval,
        "created_from_research_run_id": None,
    }


def _package_volume(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        volume = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("package_volume_liters must be a valid decimal") from exc
    if not volume.is_finite() or volume <= 0:
        raise ValueError("package_volume_liters must be greater than 0")
    try:
        rounded = volume.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("package_volume_liters does not fit Numeric(6,2)") from exc
    if rounded != volume or rounded > Decimal("9999.99"):
        raise ValueError("package_volume_liters does not fit Numeric(6,2)")
    return rounded


def import_engine_oils(path: str, db: Session, dry_run: bool = False) -> tuple[int, int, int]:
    repo = EngineOilRepository(db)
    imported = skipped = invalid = 0
    for row in rows(path, collection_key="engine_oils"):
        if not isinstance(row, dict):
            print("Invalid oil source_id=unknown: row must be an object")
            invalid += 1
            continue
        try:
            data = _oil_data(row)
            if repo.find_by_identity(data):
                skipped += 1
                continue
            if not dry_run:
                with db.begin_nested():
                    repo.create(data)
            imported += 1
        except (TypeError, ValueError, SQLAlchemyError) as exc:
            print(f"Invalid oil source_id={_source_id(row)}: {exc}")
            invalid += 1
    if imported and not dry_run:
        db.commit()
    return imported, skipped, invalid


def main(path: str, dry_run: bool = False) -> None:
    with SessionLocal() as db:
        result = import_engine_oils(path, db, dry_run)
    print(f"Imported: {result[0]}\nSkipped: {result[1]}\nInvalid: {result[2]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import engine oils from JSON or CSV.")
    parser.add_argument("path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.path, args.dry_run)
