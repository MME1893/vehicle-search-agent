"""initial schema"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("manufacturer", sa.String(120), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("trim", sa.String(120)),
        sa.Column("production_year_from", sa.Integer),
        sa.Column("production_year_to", sa.Integer),
        sa.Column("engine_code", sa.String(80)),
        sa.Column("engine_displacement", sa.String(40)),
        sa.Column("fuel_type", sa.String(40)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_vehicles_engine_code", "vehicles", ["engine_code"])
    op.create_index(
        "ix_vehicles_manufacturer_model", "vehicles", ["manufacturer", "model"]
    )
    op.create_table(
        "engine_oils",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brand", sa.String(120), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("sae_viscosity", sa.String(20), nullable=False),
        sa.Column("api_spec", sa.String(20)),
        sa.Column("acea_spec", sa.String(30)),
        sa.Column("base_type", sa.String(40)),
        sa.Column("oem_approvals", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_engine_oils_sae_viscosity", "engine_oils", ["sae_viscosity"])
    op.create_index("ix_engine_oils_api_spec", "engine_oils", ["api_spec"])
    op.create_table(
        "engine_specs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("engine_code", sa.String(80), nullable=False),
        sa.Column("recommended_sae", postgresql.JSONB, nullable=False),
        sa.Column("alternative_sae", postgresql.JSONB, nullable=False),
        sa.Column("minimum_api", sa.String(20)),
        sa.Column("acea_specs", postgresql.JSONB, nullable=False),
        sa.Column("oem_approvals", postgresql.JSONB, nullable=False),
        sa.Column("source", sa.String(180)),
        sa.Column("source_url", sa.String(1000)),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_engine_specs_confidence"
        ),
    )
    op.create_index("ix_engine_specs_engine_code", "engine_specs", ["engine_code"])
    op.create_table(
        "vehicle_engine_oil_compatibilities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.Integer,
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "engine_oil_id",
            sa.Integer,
            sa.ForeignKey("engine_oils.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("compatibility_type", sa.String(30), nullable=False),
        sa.Column("match_score", sa.Integer, nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("reason", sa.String(2000)),
        sa.Column("created_by", sa.String(30), nullable=False),
        sa.Column("review_status", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("vehicle_id", "engine_oil_id", name="uq_vehicle_oil"),
        sa.CheckConstraint(
            "match_score >= 0 AND match_score <= 100", name="ck_compatibility_score"
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_compatibility_confidence",
        ),
    )
    op.create_index(
        "ix_compat_vehicle", "vehicle_engine_oil_compatibilities", ["vehicle_id"]
    )
    op.create_index(
        "ix_compat_oil", "vehicle_engine_oil_compatibilities", ["engine_oil_id"]
    )
    op.create_table(
        "agent_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.Integer,
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("current_step", sa.String(100)),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("error_message", sa.String(2000)),
        sa.Column("agent_version", sa.String(80)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_jobs_status", "agent_jobs", ["status"])


def downgrade():
    op.drop_table("agent_jobs")
    op.drop_table("vehicle_engine_oil_compatibilities")
    op.drop_table("engine_specs")
    op.drop_table("engine_oils")
    op.drop_table("vehicles")
