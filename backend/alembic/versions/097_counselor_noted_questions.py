"""Questions deferred to post-mirror roadmap research.

Revision ID: 097
Revises: 096
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "counselor_noted_questions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_to_research", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "source_event_id", name="uq_counselor_noted_question_event"),
        sa.CheckConstraint("length(trim(question_to_research)) > 0", name="ck_counselor_noted_question_text"),
    )
    op.create_index("idx_counselor_noted_question_status", "counselor_noted_questions", ["workspace_id", "status"])


def downgrade():
    op.drop_table("counselor_noted_questions")
