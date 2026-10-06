"""Durable roadmaps and independent student actions.

Revision ID: 084
Revises: 083
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_roadmaps",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("journey_id", sa.Text(), sa.ForeignKey("pai_student_journeys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_id", sa.Text()),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("route", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fit_level", sa.Text()),
        sa.Column("fit_dimensions", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("gaps", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("steps", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("total_cost", JSONB()),
        sa.Column("time_to_start", sa.Text()),
        sa.Column("risks", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sources", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("generation_status", sa.Text(), nullable=False, server_default=sa.text("'generating'")),
        sa.Column("stale_reason", sa.Text()),
        sa.Column("execution_run_id", sa.Text(), sa.ForeignKey("execution_runs.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("origin IN ('stated_goal', 'alternative', 'student_added', 'operator_suggested')", name="ck_roadmap_origin"),
        sa.CheckConstraint("fit_level IS NULL OR fit_level IN ('strong', 'partial', 'weak', 'not_possible_yet', 'unconfirmed')", name="ck_roadmap_fit"),
        sa.CheckConstraint("generation_status IN ('generating', 'ready', 'needs_info', 'failed', 'stale')", name="ck_roadmap_generation_status"),
        sa.CheckConstraint("version > 0", name="ck_roadmap_version"),
    )
    op.create_index("idx_roadmaps_workspace_journey", "pai_roadmaps", ["workspace_id", "journey_id", "updated_at"])
    op.create_index("idx_roadmaps_run", "pai_roadmaps", ["execution_run_id"])
    op.create_table(
        "pai_roadmap_student_state",
        sa.Column("roadmap_id", sa.Text(), sa.ForeignKey("pai_roadmaps.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("journey_id", sa.Text(), sa.ForeignKey("pai_student_journeys.id", ondelete="CASCADE"), nullable=False),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exploring", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("chosen_at", sa.DateTime(timezone=True)),
        sa.Column("focused_at", sa.DateTime(timezone=True)),
        sa.Column("presented_at", sa.DateTime(timezone=True)),
    )
    op.create_index("uq_roadmap_chosen_per_journey", "pai_roadmap_student_state", ["journey_id"], unique=True,
                    postgresql_where=sa.text("chosen_at IS NOT NULL"))
    op.create_index("idx_roadmap_student_state_journey", "pai_roadmap_student_state", ["journey_id"])


def downgrade():
    op.drop_index("idx_roadmap_student_state_journey", table_name="pai_roadmap_student_state")
    op.drop_index("uq_roadmap_chosen_per_journey", table_name="pai_roadmap_student_state")
    op.drop_table("pai_roadmap_student_state")
    op.drop_index("idx_roadmaps_run", table_name="pai_roadmaps")
    op.drop_index("idx_roadmaps_workspace_journey", table_name="pai_roadmaps")
    op.drop_table("pai_roadmaps")
