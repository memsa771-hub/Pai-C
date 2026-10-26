"""The student's chosen route (the decision record PAI OS reads).

Revision ID: 118
Revises: 117

`pai_route_decisions` holds one row per choice from the roadmap engine: the
verdict and route snapshot at choose time, the route checklist and which steps
are ticked. A partial unique index keeps one active row per workspace; choosing
again withdraws the old row. Additive only: the old roadmap tables stay until
migration 119.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "118"
down_revision = "117"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "pai_route_decisions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("field_key", sa.Text(), nullable=False),
        sa.Column("possibility_id", UUID(as_uuid=False),
                  sa.ForeignKey("pai_possibilities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("verdict", JSONB(), nullable=False),
        sa.Column("route", JSONB(), nullable=False),
        sa.Column("steps", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("steps_done", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_route_decision_active", "pai_route_decisions", ["workspace_id"], unique=True,
                    postgresql_where=sa.text("withdrawn_at IS NULL"))
    op.create_index("idx_route_decisions_workspace", "pai_route_decisions", ["workspace_id", "chosen_at"])


def downgrade():
    op.drop_index("idx_route_decisions_workspace", table_name="pai_route_decisions")
    op.drop_index("uq_route_decision_active", table_name="pai_route_decisions")
    op.drop_table("pai_route_decisions")
