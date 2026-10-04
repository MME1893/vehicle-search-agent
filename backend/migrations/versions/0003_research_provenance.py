"""add research provenance and compatibility history"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_research_provenance"
down_revision = "0002_engine_spec_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(180)),
        sa.Column("matching_strategy", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("raw_research_text", sa.Text()),
        sa.Column("structured_result", postgresql.JSONB()),
        sa.Column("search_queries", postgresql.JSONB(), nullable=False),
        sa.Column("grounding_sources", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage1_duration_ms", sa.Integer()),
        sa.Column("stage2_duration_ms", sa.Integer()),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_research_runs_vehicle_id", "research_runs", ["vehicle_id"])

    op.add_column(
        "engine_specs", sa.Column("research_run_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_engine_specs_research_run",
        "engine_specs",
        "research_runs",
        ["research_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_engine_specs_research_run_id", "engine_specs", ["research_run_id"]
    )

    op.add_column(
        "engine_oils",
        sa.Column("created_from_research_run_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_engine_oils_created_from_research_run",
        "engine_oils",
        "research_runs",
        ["created_from_research_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_engine_oils_created_from_research_run_id",
        "engine_oils",
        ["created_from_research_run_id"],
    )

    for column, target in (
        ("research_run_id", "research_runs.id"),
        ("engine_spec_id", "engine_specs.id"),
    ):
        op.add_column(
            "vehicle_engine_oil_compatibilities",
            sa.Column(column, sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            f"fk_compatibility_{column}",
            "vehicle_engine_oil_compatibilities",
            target.split(".")[0],
            [column],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(
            f"ix_vehicle_engine_oil_compatibilities_{column}",
            "vehicle_engine_oil_compatibilities",
            [column],
        )

    op.create_table(
        "compatibility_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "compatibility_id",
            sa.Integer(),
            sa.ForeignKey("vehicle_engine_oil_compatibilities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "engine_oil_id",
            sa.Integer(),
            sa.ForeignKey("engine_oils.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "research_run_id",
            sa.Integer(),
            sa.ForeignKey("research_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "engine_spec_id",
            sa.Integer(),
            sa.ForeignKey("engine_specs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("match_method", sa.String(50), nullable=False),
        sa.Column("compatibility_type", sa.String(30), nullable=False),
        sa.Column("match_score", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(2000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    for column in (
        "compatibility_id",
        "vehicle_id",
        "engine_oil_id",
        "research_run_id",
        "engine_spec_id",
    ):
        op.create_index(
            f"ix_compatibility_history_{column}", "compatibility_history", [column]
        )


def downgrade():
    op.drop_table("compatibility_history")
    for column in ("engine_spec_id", "research_run_id"):
        op.drop_index(
            f"ix_vehicle_engine_oil_compatibilities_{column}",
            table_name="vehicle_engine_oil_compatibilities",
        )
        op.drop_constraint(
            f"fk_compatibility_{column}",
            "vehicle_engine_oil_compatibilities",
            type_="foreignkey",
        )
        op.drop_column("vehicle_engine_oil_compatibilities", column)
    op.drop_index(
        "ix_engine_oils_created_from_research_run_id", table_name="engine_oils"
    )
    op.drop_constraint(
        "fk_engine_oils_created_from_research_run", "engine_oils", type_="foreignkey"
    )
    op.drop_column("engine_oils", "created_from_research_run_id")
    op.drop_index("ix_engine_specs_research_run_id", table_name="engine_specs")
    op.drop_constraint(
        "fk_engine_specs_research_run", "engine_specs", type_="foreignkey"
    )
    op.drop_column("engine_specs", "research_run_id")
    op.drop_table("research_runs")
