"""current compatibility integrity and vehicle variant identity"""

import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0005_current_integrity"
down_revision = "0004_append_only_research"
branch_labels = None
depends_on = None

COMPAT = "vehicle_engine_oil_compatibilities"


def _part(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"[^\w]+", "", text)


def _vehicle_key(row, include_variant=True):
    values = [
        row.manufacturer,
        row.model,
        row.trim,
        row.production_year_from,
        row.production_year_to,
        row.engine_code,
    ]
    if include_variant:
        values.extend((row.engine_displacement, row.fuel_type))
    return "|".join(_part(value) for value in values)


def _rebuild_vehicle_identities(include_variant=True):
    bind = op.get_bind()
    rows = list(bind.execute(sa.text("SELECT * FROM vehicles ORDER BY id")).mappings())
    keyed = [(row.id, _vehicle_key(row, include_variant)) for row in rows]
    seen = {}
    for ident, key in keyed:
        if key in seen:
            raise RuntimeError(
                "cannot rebuild vehicle identities: "
                f"ids {seen[key]} and {ident} normalize to {key!r}"
            )
        seen[key] = ident
    op.drop_constraint("uq_vehicles_identity_key", "vehicles", type_="unique")
    for ident, key in keyed:
        bind.execute(
            sa.text("UPDATE vehicles SET identity_key=:key WHERE id=:id"),
            {"key": key, "id": ident},
        )
    op.create_unique_constraint("uq_vehicles_identity_key", "vehicles", ["identity_key"])


def upgrade():
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            f"SELECT vehicle_id, engine_oil_id, research_run_id, COUNT(*) AS n "
            f"FROM {COMPAT} WHERE research_run_id IS NOT NULL "
            "GROUP BY vehicle_id, engine_oil_id, research_run_id "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).mappings().first()
    if duplicate:
        raise RuntimeError(
            "cannot enforce one compatibility event per research snapshot: "
            f"vehicle_id={duplicate.vehicle_id}, engine_oil_id={duplicate.engine_oil_id}, "
            f"research_run_id={duplicate.research_run_id} has {duplicate.n} rows"
        )
    _rebuild_vehicle_identities(include_variant=True)
    op.create_unique_constraint(
        "uq_compatibility_research_run_oil",
        COMPAT,
        ["vehicle_id", "engine_oil_id", "research_run_id"],
    )
    op.drop_column(COMPAT, "updated_at")
    op.alter_column("agent_jobs", "error_message", new_column_name="status_reason")
    op.drop_constraint("ck_compatibility_match_method", COMPAT, type_="check")
    op.create_check_constraint(
        "ck_compatibility_match_method",
        COMPAT,
        "match_method IN ('MANUAL','DIRECT_RESEARCH_PRODUCT',"
        "'DETERMINISTIC_SPEC_MATCH','PROVIDER_CATALOG_MATCH')",
    )
    op.create_index("ix_agent_jobs_vehicle_id", "agent_jobs", ["vehicle_id"])
    op.create_index("ix_engine_oils_brand", "engine_oils", ["brand"])
    op.create_index("ix_vehicles_manufacturer", "vehicles", ["manufacturer"])
    op.create_index("ix_vehicles_model", "vehicles", ["model"])


def downgrade():
    provider_match = op.get_bind().execute(
        sa.text(
            f"SELECT id FROM {COMPAT} "
            "WHERE match_method='PROVIDER_CATALOG_MATCH' LIMIT 1"
        )
    ).scalar()
    if provider_match is not None:
        raise RuntimeError(
            "cannot downgrade while provider catalog compatibility events exist"
        )
    op.drop_index("ix_vehicles_model", table_name="vehicles", if_exists=True)
    op.drop_index("ix_vehicles_manufacturer", table_name="vehicles", if_exists=True)
    op.drop_index("ix_engine_oils_brand", table_name="engine_oils", if_exists=True)
    op.drop_index("ix_agent_jobs_vehicle_id", table_name="agent_jobs", if_exists=True)
    _rebuild_vehicle_identities(include_variant=False)
    op.alter_column("agent_jobs", "status_reason", new_column_name="error_message")
    op.drop_constraint("ck_compatibility_match_method", COMPAT, type_="check")
    op.create_check_constraint(
        "ck_compatibility_match_method",
        COMPAT,
        "match_method IN ('MANUAL','DIRECT_RESEARCH_PRODUCT',"
        "'DETERMINISTIC_SPEC_MATCH')",
    )
    op.add_column(
        COMPAT,
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.drop_constraint(
        "uq_compatibility_research_run_oil", COMPAT, type_="unique"
    )
