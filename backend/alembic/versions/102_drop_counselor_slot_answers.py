"""Drop the unused legacy Counselor slot-answer store.

Revision ID: 102
Revises: 101
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "102"
down_revision = "101"
branch_labels = depends_on = None


def upgrade():
    op.drop_table("pai_counselor_slot_answers")


def downgrade():
    # Restores the old schema only; deleted orphan data cannot be restored.
    op.create_table(
        "pai_counselor_slot_answers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("slot_key", sa.Text(), nullable=False),
        sa.Column("value", JSONB()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("confidence", sa.Float()),
        sa.Column("quote", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('pending', 'valid_unknown', 'declined')",
                           name="ck_counselor_slot_answer_status"),
        sa.UniqueConstraint("workspace_id", "source_event_id", "slot_key",
                            name="uq_counselor_slot_answer_event"),
    )
    op.create_index("idx_counselor_slot_answers_recent", "pai_counselor_slot_answers",
                    ["workspace_id", "created_at"])
