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
from app.repositories.engine_oil_repository import EngineOilRepository
from scripts.import_common import list_value, rows

REQUIRED = ("brand", "name", "sae_viscosity")
OIL_FIELDS = ("brand", "name", "sae_viscosity", "api_spec", "base_type")


def _source_id(row: dict) -> str:
    return str(row.get("id", "unknown"))


def _oil_data(row: dict) -> dict:
    missing = [field for field in REQUIRED if row.get(field) in (None, "")]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    approvals = list_value(row.get("oem_approvals"))
    acea = list_value(row.get("acea_specs", row.get("acea_spec")))
    if not all(isinstance(item, str) for item in [*approvals, *acea]):
        raise ValueError("specification lists must contain only strings")
    return {
        **{field: row.get(field) for field in OIL_FIELDS},
        "acea_specs": acea,
        "oem_approvals": approvals,
    }


def _sync_sequence(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT setval(pg_get_serial_sequence('engine_oils', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM engine_oils), 1), true)"))


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
            print(f"Invalid oil source_id={_source_id(row)}: {exc}")
            invalid += 1
    if imported and not dry_run:
        _sync_sequence(db)
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
