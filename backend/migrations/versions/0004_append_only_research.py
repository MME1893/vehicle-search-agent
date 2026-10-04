"""append-only compatibility and research persistence architecture

Downgrade limitation: immutable compatibility events cannot be losslessly converted
back to one unique current row plus snapshots. Downgrade therefore refuses to run
when more than one event exists for a vehicle/oil pair instead of deleting history.
"""

import re
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_append_only_research"
down_revision = "0003_research_provenance"
branch_labels = None
depends_on = None

COMPAT = "vehicle_engine_oil_compatibilities"


def _part(value):
    if value is None:
        return ""
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", str(value)).casefold().strip())


def _sae(value):
    return re.sub(r"[^0-9W]", "", unicodedata.normalize("NFKC", value).upper())


def _oil_key(row):
    return "|".join((_part(row.brand), _part(row.name), _sae(row.sae_viscosity)))


def _vehicle_key(row):
    return "|".join(
        _part(value)
        for value in (
            row.manufacturer,
            row.model,
            row.trim,
            row.production_year_from,
            row.production_year_to,
            row.engine_code,
        )
    )


def _backfill_unique_key(table, key_function):
    bind = op.get_bind()
    rows = list(bind.execute(sa.text(f"SELECT * FROM {table} ORDER BY id")).mappings())
    seen = {}
    for row in rows:
        key = key_function(row)
        if key in seen:
            raise RuntimeError(
                f"cannot migrate {table}: ids {seen[key]} and {row.id} "
                f"have duplicate normalized identity {key!r}"
            )
        seen[key] = row.id
        bind.execute(
            sa.text(f"UPDATE {table} SET identity_key = :key WHERE id = :id"),
            {"key": key, "id": row.id},
        )


def upgrade():
    bind = op.get_bind()
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.add_column("vehicles", sa.Column("identity_key", sa.String(600)))
    _backfill_unique_key("vehicles", _vehicle_key)
    op.alter_column("vehicles", "identity_key", nullable=False)
    op.create_unique_constraint("uq_vehicles_identity_key", "vehicles", ["identity_key"])
    op.create_check_constraint(
        "ck_vehicles_production_year_range",
        "vehicles",
        "production_year_from IS NULL OR production_year_to IS NULL "
        "OR production_year_from <= production_year_to",
    )

    op.add_column("engine_oils", sa.Column("identity_key", sa.String(600)))
    _backfill_unique_key("engine_oils", _oil_key)
    op.alter_column("engine_oils", "identity_key", nullable=False)
    op.create_unique_constraint("uq_engine_oils_identity_key", "engine_oils", ["identity_key"])
    op.add_column("engine_oils", sa.Column("acea_specs", json_type, nullable=True))
    for row in bind.execute(sa.text("SELECT id, acea_spec FROM engine_oils")).mappings():
        value = [] if row.acea_spec is None else [row.acea_spec]
        bind.execute(
            sa.text("UPDATE engine_oils SET acea_specs = :value WHERE id = :id")
            .bindparams(sa.bindparam("value", type_=json_type)),
            {"value": value, "id": row.id},
        )
    op.alter_column("engine_oils", "acea_specs", nullable=False)
    op.drop_index("ix_engine_oils_acea_spec", table_name="engine_oils", if_exists=True)
    op.drop_column("engine_oils", "acea_spec")

    op.alter_column("research_runs", "status", new_column_name="research_status")
    op.add_column("research_runs", sa.Column("evaluation_status", sa.String(30)))
    op.add_column("research_runs", sa.Column("evaluation_reason", sa.String(2000)))
    bind.execute(
        sa.text(
            "UPDATE research_runs SET evaluation_status = CASE WHEN EXISTS "
            "(SELECT 1 FROM engine_specs s WHERE s.research_run_id = research_runs.id) "
            "THEN 'ACCEPTED' ELSE 'NEEDS_REVIEW' END, "
            "evaluation_reason = CASE WHEN EXISTS "
            "(SELECT 1 FROM engine_specs s WHERE s.research_run_id = research_runs.id) "
            "THEN 'migrated accepted research' ELSE 'migrated run requires review' END"
        )
    )
    op.alter_column("research_runs", "evaluation_status", nullable=False)
    op.alter_column("research_runs", "evaluation_reason", nullable=False)

    op.add_column("agent_jobs", sa.Column("research_run_id", sa.Integer()))
    op.create_foreign_key(
        "fk_agent_jobs_research_run", "agent_jobs", "research_runs",
        ["research_run_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_agent_jobs_research_run_id", "agent_jobs", ["research_run_id"])

    op.drop_constraint("uq_vehicle_oil", COMPAT, type_="unique")
    op.add_column(COMPAT, sa.Column("match_method", sa.String(50)))

    represented = [
        row.id
        for row in bind.execute(
            sa.text(
                f"SELECT DISTINCT c.id FROM {COMPAT} c JOIN compatibility_history h "
                "ON h.compatibility_id = c.id "
                "WHERE h.vehicle_id = c.vehicle_id AND h.engine_oil_id = c.engine_oil_id "
                "AND h.research_run_id = c.research_run_id "
                "AND h.engine_spec_id = c.engine_spec_id "
                "AND h.compatibility_type = c.compatibility_type "
                "AND h.match_score = c.match_score "
                "AND h.confidence_score = c.confidence_score "
                "AND ((h.reason = c.reason) OR (h.reason IS NULL AND c.reason IS NULL))"
            )
        ).mappings()
    ]
    bind.execute(
        sa.text(
            f"INSERT INTO {COMPAT} "
            "(vehicle_id, engine_oil_id, research_run_id, engine_spec_id, match_method, "
            "compatibility_type, match_score, confidence_score, reason, created_by, "
            "review_status, created_at, updated_at) "
            "SELECT h.vehicle_id, h.engine_oil_id, h.research_run_id, h.engine_spec_id, "
            "h.match_method, h.compatibility_type, h.match_score, h.confidence_score, "
            "h.reason, c.created_by, c.review_status, h.created_at, h.created_at "
            f"FROM compatibility_history h JOIN {COMPAT} c ON c.id = h.compatibility_id"
        )
    )
    op.drop_table("compatibility_history")
    if represented:
        bind.execute(
            sa.text(f"DELETE FROM {COMPAT} WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": represented},
        )
    bind.execute(sa.text(f"UPDATE {COMPAT} SET match_method = 'MANUAL' WHERE match_method IS NULL"))
    op.alter_column(COMPAT, "match_method", nullable=False)

    op.drop_constraint("fk_compatibility_engine_spec_id", COMPAT, type_="foreignkey")
    op.drop_index("ix_vehicle_engine_oil_compatibilities_engine_spec_id", table_name=COMPAT)
    op.drop_column(COMPAT, "engine_spec_id")
    op.drop_column(COMPAT, "review_status")
    for constraint in (
        "vehicle_engine_oil_compatibilities_vehicle_id_fkey",
        "vehicle_engine_oil_compatibilities_engine_oil_id_fkey",
    ):
        op.drop_constraint(constraint, COMPAT, type_="foreignkey")
    op.create_foreign_key(
        "fk_compatibility_vehicle", COMPAT, "vehicles", ["vehicle_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_compatibility_engine_oil", COMPAT, "engine_oils", ["engine_oil_id"], ["id"], ondelete="RESTRICT"
    )
    op.drop_constraint("agent_jobs_vehicle_id_fkey", "agent_jobs", type_="foreignkey")
    op.create_foreign_key(
        "fk_agent_jobs_vehicle", "agent_jobs", "vehicles", ["vehicle_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_compatibility_created_at", COMPAT, ["created_at"])
    op.create_index(
        "ix_compatibility_pair_latest", COMPAT,
        ["vehicle_id", "engine_oil_id", sa.text("created_at DESC"), sa.text("id DESC")]
    )
    op.create_check_constraint(
        "ck_compatibility_match_method", COMPAT,
        "match_method IN ('MANUAL','DIRECT_RESEARCH_PRODUCT','DETERMINISTIC_SPEC_MATCH')"
    )
    op.create_check_constraint(
        "ck_compatibility_type", COMPAT,
        "compatibility_type IN ('RECOMMENDED','COMPATIBLE','CONDITIONAL')"
    )
    op.create_check_constraint(
        "ck_compatibility_created_by", COMPAT,
        "created_by IN ('SYSTEM','AGENT','ADMIN')"
    )
    op.create_check_constraint(
        "ck_research_status", "research_runs",
        "research_status IN ('FOUND','INSUFFICIENT')"
    )
    op.create_check_constraint(
        "ck_research_evaluation_status", "research_runs",
        "evaluation_status IN ('ACCEPTED','NEEDS_REVIEW','REJECTED')"
    )
    op.create_check_constraint(
        "ck_agent_jobs_status", "agent_jobs",
        "status IN ('PENDING','RUNNING','COMPLETED','NEEDS_REVIEW','FAILED')"
    )
    op.drop_table("engine_specs")


def downgrade():
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            f"SELECT vehicle_id, engine_oil_id, COUNT(*) AS n FROM {COMPAT} "
            "GROUP BY vehicle_id, engine_oil_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).mappings().first()
    if duplicate:
        raise RuntimeError(
            "cannot downgrade append-only compatibility without data loss: "
            f"vehicle_id={duplicate.vehicle_id}, engine_oil_id={duplicate.engine_oil_id} "
            f"has {duplicate.n} events"
        )
    for name, table in (
        ("ck_agent_jobs_status", "agent_jobs"),
        ("ck_research_evaluation_status", "research_runs"),
        ("ck_research_status", "research_runs"),
        ("ck_compatibility_created_by", COMPAT),
        ("ck_compatibility_type", COMPAT),
        ("ck_compatibility_match_method", COMPAT),
    ):
        op.drop_constraint(name, table, type_="check")
    op.drop_index("ix_compatibility_pair_latest", table_name=COMPAT)
    op.drop_index("ix_compatibility_created_at", table_name=COMPAT)
    op.drop_constraint("fk_compatibility_vehicle", COMPAT, type_="foreignkey")
    op.drop_constraint("fk_compatibility_engine_oil", COMPAT, type_="foreignkey")
    op.create_foreign_key(
        "vehicle_engine_oil_compatibilities_vehicle_id_fkey", COMPAT,
        "vehicles", ["vehicle_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "vehicle_engine_oil_compatibilities_engine_oil_id_fkey", COMPAT,
        "engine_oils", ["engine_oil_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_constraint("fk_agent_jobs_vehicle", "agent_jobs", type_="foreignkey")
    op.create_foreign_key(
        "agent_jobs_vehicle_id_fkey", "agent_jobs", "vehicles",
        ["vehicle_id"], ["id"], ondelete="CASCADE"
    )
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "engine_specs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("research_run_id", sa.Integer(), sa.ForeignKey("research_runs.id", ondelete="RESTRICT")),
        sa.Column("engine_code", sa.String(80), nullable=False),
        sa.Column("recommended_sae", json_type, nullable=False),
        sa.Column("alternative_sae", json_type, nullable=False),
        sa.Column("minimum_api", sa.String(20)),
        sa.Column("acea_specs", json_type, nullable=False),
        sa.Column("oem_approvals", json_type, nullable=False),
        sa.Column("source", sa.String(180)), sa.Column("source_url", sa.String(1000)),
        sa.Column("evidence", json_type), sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_engine_specs_engine_code", "engine_specs", ["engine_code"])
    op.create_index("ix_engine_specs_research_run_id", "engine_specs", ["research_run_id"])
    op.add_column(COMPAT, sa.Column("engine_spec_id", sa.Integer()))
    op.create_foreign_key("fk_compatibility_engine_spec_id", COMPAT, "engine_specs", ["engine_spec_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_vehicle_engine_oil_compatibilities_engine_spec_id", COMPAT, ["engine_spec_id"])
    op.add_column(COMPAT, sa.Column("review_status", sa.String(30), server_default="PENDING", nullable=False))
    op.create_unique_constraint("uq_vehicle_oil", COMPAT, ["vehicle_id", "engine_oil_id"])
    op.create_table(
        "compatibility_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("compatibility_id", sa.Integer(), sa.ForeignKey(f"{COMPAT}.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("engine_oil_id", sa.Integer(), sa.ForeignKey("engine_oils.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("research_run_id", sa.Integer(), sa.ForeignKey("research_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("engine_spec_id", sa.Integer(), sa.ForeignKey("engine_specs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("match_method", sa.String(50), nullable=False),
        sa.Column("compatibility_type", sa.String(30), nullable=False),
        sa.Column("match_score", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in (
        "compatibility_id", "vehicle_id", "engine_oil_id", "research_run_id", "engine_spec_id"
    ):
        op.create_index(f"ix_compatibility_history_{column}", "compatibility_history", [column])
    op.drop_column(COMPAT, "match_method")
    op.add_column("engine_oils", sa.Column("acea_spec", sa.String(30)))
    for row in bind.execute(sa.text("SELECT id, acea_specs FROM engine_oils")).mappings():
        values = row.acea_specs or []
        bind.execute(sa.text("UPDATE engine_oils SET acea_spec=:value WHERE id=:id"), {"value": values[0] if values else None, "id": row.id})
    op.drop_column("engine_oils", "acea_specs")
    op.drop_constraint("uq_engine_oils_identity_key", "engine_oils", type_="unique")
    op.drop_column("engine_oils", "identity_key")
    op.drop_constraint("uq_vehicles_identity_key", "vehicles", type_="unique")
    op.drop_constraint("ck_vehicles_production_year_range", "vehicles", type_="check")
    op.drop_column("vehicles", "identity_key")
    op.drop_index("ix_agent_jobs_research_run_id", table_name="agent_jobs")
    op.drop_constraint("fk_agent_jobs_research_run", "agent_jobs", type_="foreignkey")
    op.drop_column("agent_jobs", "research_run_id")
    op.drop_column("research_runs", "evaluation_reason")
    op.drop_column("research_runs", "evaluation_status")
    op.alter_column("research_runs", "research_status", new_column_name="status")
