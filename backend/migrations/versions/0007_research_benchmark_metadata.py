"""add resumable research benchmark metadata"""

import sqlalchemy as sa
from alembic import op

revision = "0007_research_benchmark"
down_revision = "0006_vehicle_oil_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("research_runs", sa.Column("batch_id", sa.String(180)))
    op.add_column("research_runs", sa.Column("batch_lane", sa.String(60)))
    op.create_index(
        "ix_research_runs_batch_vehicle_lane",
        "research_runs",
        ["batch_id", "vehicle_id", "batch_lane"],
    )
    op.create_unique_constraint(
        "uq_research_runs_batch_vehicle_lane",
        "research_runs",
        ["batch_id", "vehicle_id", "batch_lane"],
    )


def downgrade():
    op.drop_constraint(
        "uq_research_runs_batch_vehicle_lane", "research_runs", type_="unique"
    )
    op.drop_index("ix_research_runs_batch_vehicle_lane", table_name="research_runs")
    op.drop_column("research_runs", "batch_lane")
    op.drop_column("research_runs", "batch_id")
