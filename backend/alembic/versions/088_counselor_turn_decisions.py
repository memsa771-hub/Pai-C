"""Private durable Counselor move audit for focused next-turn extraction.

Revision ID: 088
Revises: 087
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_counselor_turn_decisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("source_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("move", sa.Text(), nullable=False),
        sa.Column("slot_key", sa.Text()),
        sa.Column("guard_violations", JSONB(), nullable=False,
                  server_default=sa.text("'[]'")),
        sa.UniqueConstraint("workspace_id", "source_event_id",
                            name="uq_counselor_turn_decision_source"),
    )
    op.create_index("idx_counselor_turn_decision_recent",
                    "pai_counselor_turn_decisions", ["workspace_id", "source_timestamp"])


def downgrade():
    op.drop_index("idx_counselor_turn_decision_recent",
                  table_name="pai_counselor_turn_decisions")
    op.drop_table("pai_counselor_turn_decisions")
