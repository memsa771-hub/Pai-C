"""Persist the reviewed Counselor route choice for future OS hand-off.

Revision ID: 091
Revises: 090
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_decision_records",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("journey_id", sa.Text(), sa.ForeignKey("pai_student_journeys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("roadmap_id", sa.Text(), sa.ForeignKey("pai_roadmaps.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("roadmap_version", sa.Integer(), nullable=False),
        sa.Column("confirmed_summary", JSONB(), nullable=False),
        sa.Column("real_objective", sa.Text(), nullable=True),
        sa.Column("accepted_gaps", JSONB(), nullable=False),
        sa.Column("accepted_risks", JSONB(), nullable=False),
        sa.Column("assumptions", JSONB(), nullable=False),
        sa.Column("choice_channel", sa.Text(), nullable=False),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("roadmap_version > 0", name="ck_decision_roadmap_version"),
        sa.CheckConstraint("choice_channel IN ('chat', 'voice', 'roadmaps')", name="ck_decision_choice_channel"),
        sa.UniqueConstraint("journey_id", "roadmap_id", "roadmap_version", name="uq_decision_route_version"),
    )
    op.create_index("idx_decision_workspace_current", "pai_decision_records", ["workspace_id", "chosen_at"])


def downgrade():
    op.drop_index("idx_decision_workspace_current", table_name="pai_decision_records")
    op.drop_table("pai_decision_records")
