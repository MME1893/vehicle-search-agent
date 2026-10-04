# import argparse
# import sys
# from pathlib import Path

# from sqlalchemy import text
# from sqlalchemy.exc import SQLAlchemyError
# from sqlalchemy.orm import Session

# BACKEND_ROOT = Path(__file__).resolve().parents[1]
# if str(BACKEND_ROOT) not in sys.path:
#     sys.path.insert(0, str(BACKEND_ROOT))

# from app.db.session import SessionLocal
# from app.repositories.engine_oil_repository import EngineOilRepository
# from scripts.import_common import list_value, rows

# REQUIRED = ("brand", "name", "sae_viscosity")
# OIL_FIELDS = ("brand", "name", "sae_viscosity", "api_spec", "acea_spec", "base_type")


# def _source_id(row: dict) -> str:
#     return str(row.get("id", "unknown"))


# def _oil_data(row: dict) -> dict:
#     missing = [field for field in REQUIRED if row.get(field) in (None, "")]
#     if missing:
#         raise ValueError(f"missing {', '.join(missing)}")
#     approvals = list_value(row.get("oem_approvals"))
#     if not all(isinstance(approval, str) for approval in approvals):
#         raise ValueError("oem_approvals must contain only strings")
#     return {**{field: row.get(field) for field in OIL_FIELDS}, "oem_approvals": approvals}


# def _sync_sequence(db: Session) -> None:
#     if db.bind is not None and db.bind.dialect.name == "postgresql":
#         db.execute(text("SELECT setval(pg_get_serial_sequence('engine_oils', 'id'), "
#                         "COALESCE((SELECT MAX(id) FROM engine_oils), 1), true)"))
#         db.commit()


# def import_engine_oils(path: str, db: Session, dry_run: bool = False) -> tuple[int, int, int]:
#     repo = EngineOilRepository(db)
#     imported = skipped = invalid = 0
#     for row in rows(path, collection_key="engine_oils"):
#         if not isinstance(row, dict):
#             print("Invalid oil source_id=unknown: row must be an object")
#             invalid += 1
#             continue
#         try:
#             data = _oil_data(row)
#             if row.get("id") is not None:
#                 source_id = int(row["id"])
#                 if repo.get_by_id(source_id):
#                     skipped += 1
#                     continue
#                 data["id"] = source_id
#             if not dry_run:
#                 repo.create(data)
#             imported += 1
#         except (TypeError, ValueError) as exc:
#             print(f"Invalid oil source_id={_source_id(row)}: {exc}")
#             invalid += 1
#         except SQLAlchemyError as exc:
#             db.rollback()
#             print(f"Invalid oil source_id={_source_id(row)}: {exc}")
#             invalid += 1
#     if imported and not dry_run:
#         _sync_sequence(db)
#     return imported, skipped, invalid


# def main(path: str, dry_run: bool = False) -> None:
#     db = SessionLocal()
#     try:
#         imported, skipped, invalid = import_engine_oils(path, db, dry_run)
#     finally:
#         db.close()
#     print(f"Imported: {imported}\nSkipped: {skipped}\nInvalid: {invalid}")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Import engine oils from JSON or CSV.")
#     parser.add_argument("path", help="Path to the engine-oil data file")
#     parser.add_argument("--dry-run", action="store_true", help="Validate without inserting")
#     args = parser.parse_args()
#     main(args.path, args.dry_run)

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repositories.engine_oil_repository import EngineOilRepository
from scripts.import_common import list_value, rows


# Hardcoded database URL for running this script from Windows host
DATABASE_URL = "postgresql+psycopg://oil:simpleoil1234@localhost:5432/engine_oil"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


REQUIRED = (
    "brand",
    "name",
    "sae_viscosity",
)

OIL_FIELDS = (
    "brand",
    "name",
    "sae_viscosity",
    "api_spec",
    "acea_spec",
    "base_type",
)


def _source_id(row: dict) -> str:
    return str(row.get("id", "unknown"))


def _oil_data(row: dict) -> dict:
    missing = [field for field in REQUIRED if row.get(field) in (None, "")]

    if missing:
        raise ValueError(f"missing {', '.join(missing)}")

    approvals = list_value(row.get("oem_approvals"))

    if not all(isinstance(approval, str) for approval in approvals):
        raise ValueError("oem_approvals must contain only strings")

    return {
        **{field: row.get(field) for field in OIL_FIELDS},
        "oem_approvals": approvals,
    }


def _sync_sequence(db: Session) -> None:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(
        text(
            """
            SELECT setval(
                pg_get_serial_sequence(
                    'engine_oils',
                    'id'
                ),
                COALESCE(
                    (SELECT MAX(id) FROM engine_oils),
                    1
                ),
                true
            )
            """
        )
    )
    db.commit()


def import_engine_oils(
    path: str,
    db: Session,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    repo = EngineOilRepository(db)

    imported = 0
    skipped = 0
    invalid = 0

    for row in rows(
        path,
        collection_key="engine_oils",
    ):
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
                repo.create(data)

            imported += 1

        except (TypeError, ValueError) as exc:
            print(f"Invalid oil source_id={_source_id(row)}: {exc}")
            invalid += 1

        except SQLAlchemyError as exc:
            db.rollback()

            print(f"Database error source_id={_source_id(row)}: {exc}")

            invalid += 1

    if imported and not dry_run:
        _sync_sequence(db)

    return imported, skipped, invalid


def main(
    path: str,
    dry_run: bool = False,
) -> None:
    print(f"Connecting to: {DATABASE_URL}")
    print(f"Importing from: {path}")

    db = SessionLocal()

    try:
        imported, skipped, invalid = import_engine_oils(
            path,
            db,
            dry_run,
        )
    finally:
        db.close()

    print()
    print(f"Imported: {imported}")
    print(f"Skipped: {skipped}")
    print(f"Invalid: {invalid}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import engine oils from JSON or CSV.")

    parser.add_argument(
        "path",
        help="Path to the engine-oil data file",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without inserting",
    )

    args = parser.parse_args()

    main(
        args.path,
        args.dry_run,
    )
