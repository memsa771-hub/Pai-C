"""Validated next-turn Planner instructions.

Revision ID: 105
Revises: 104
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision = "105"
down_revision = "104"
branch_labels = depends_on = None


def upgrade():
    op.create_table("pai_turn_plans",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.Text(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notebook_version", sa.Integer(), nullable=False),
        sa.Column("plan", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "source_event_id", name="uq_turn_plan_workspace_event"))


def downgrade():
    op.drop_table("pai_turn_plans")
