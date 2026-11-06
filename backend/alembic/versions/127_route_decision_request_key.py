"""The request key of a decision version written for a choice request (P1-T6, R-07).

Revision ID: 127
Revises: 126

`pai_route_decisions.request_key` (nullable text) names the OS choice request that made the version
(`choice_request:{proposal_id}`), so a repeated delivery finds its version instead of writing n+2. The partial unique
index `uq_route_decision_request_key` (workspace_id, request_key) covers the rows that have a key. Downgrade drops
both.
"""
from alembic import op
import sqlalchemy as sa

revision = "127"
down_revision = "126"
branch_labels = depends_on = None

INDEX = "uq_route_decision_request_key"


def upgrade():
    op.add_column("pai_route_decisions", sa.Column("request_key", sa.Text(), nullable=True))
    op.create_index(INDEX, "pai_route_decisions", ["workspace_id", "request_key"], unique=True,
                    postgresql_where=sa.text("request_key IS NOT NULL"),
                    sqlite_where=sa.text("request_key IS NOT NULL"))


def downgrade():
    op.drop_index(INDEX, table_name="pai_route_decisions")
    op.drop_column("pai_route_decisions", "request_key")
