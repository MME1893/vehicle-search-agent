"""add research evidence to engine specs"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_engine_spec_evidence"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "engine_specs", sa.Column("evidence", postgresql.JSONB(), nullable=True)
    )


def downgrade():
    op.drop_column("engine_specs", "evidence")
