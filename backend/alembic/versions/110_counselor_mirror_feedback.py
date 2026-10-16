"""Version-bound student Mirror feedback.

Revision ID: 110
Revises: 109
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "110"
down_revision = "109"
branch_labels = depends_on = None


def upgrade():
    op.create_table("pai_counselor_mirror_feedback",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mirror_version", sa.Integer(), nullable=False),
        sa.Column("understood", sa.Integer(), nullable=False),
        sa.Column("certainty_after", sa.Integer(), nullable=True),
        sa.Column("certainty_before", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("workspace_id", "mirror_version", name="uq_mirror_feedback_version"),
        sa.CheckConstraint("mirror_version >= 1", name="ck_mirror_feedback_version"),
        sa.CheckConstraint("understood BETWEEN 1 AND 5", name="ck_mirror_feedback_understood"),
        sa.CheckConstraint("certainty_after BETWEEN 0 AND 10", name="ck_mirror_feedback_after"),
        sa.CheckConstraint("certainty_before BETWEEN 0 AND 10", name="ck_mirror_feedback_before"))


def downgrade():
    op.drop_table("pai_counselor_mirror_feedback")
