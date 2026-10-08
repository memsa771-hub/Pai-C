"""One current roadmap per confirmed-Mirror lane; fit metadata uses route JSONB.

Revision ID: 100
Revises: 099
"""
from alembic import op
import sqlalchemy as sa

revision = "100"
down_revision = "099"
branch_labels = depends_on = None


def upgrade():
    op.add_column("pai_roadmaps", sa.Column("lane", sa.Text(), nullable=True))
    op.create_index("uq_roadmaps_journey_lane", "pai_roadmaps", ["workspace_id", "journey_id", "lane"], unique=True)


def downgrade():
    op.drop_index("uq_roadmaps_journey_lane", table_name="pai_roadmaps")
    op.drop_column("pai_roadmaps", "lane")
