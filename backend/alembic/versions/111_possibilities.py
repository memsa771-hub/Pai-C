"""Evidence-backed possibilities.

Revision ID: 111
Revises: 110
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "111"
down_revision = "110"
branch_labels = depends_on = None


def upgrade():
    op.create_table("pai_possibilities",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("journey_id", sa.Text(), sa.ForeignKey("pai_student_journeys.id", ondelete="CASCADE"), nullable=False),
        *[sa.Column(name, sa.Text(), nullable=False) for name in ("title", "normalized_title", "kind", "why", "status", "source")],
        *[sa.Column(name, JSONB(), nullable=False) for name in ("evidence", "unknowns", "mirror_versions")],
        sa.Column("roadmap_id", sa.Text(), sa.ForeignKey("pai_roadmaps.id", ondelete="SET NULL")),
        sa.Column("mentioned_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "normalized_title", name="uq_possibility_title"),
        sa.CheckConstraint("status IN ('suggested','exploring','saved','dismissed','chosen')", name="ck_possibility_status"),
        sa.CheckConstraint("source IN ('mirror','planner','student')", name="ck_possibility_source"),
        sa.CheckConstraint("kind IN ('stated_goal','family_wish','strength_based','safe_or_local','test_the_dream','discovered','student_added')", name="ck_possibility_kind"))


def downgrade():
    op.drop_table("pai_possibilities")
