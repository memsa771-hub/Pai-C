"""Delivered fact proposals from confirmed PAI OS documents (P1-T7, R-16, D-y9).

Revision ID: 128
Revises: 127

New table `pai_document_proposals`: one row per delivered `fact_proposal.v1` (`key` unique), with the workspace, the
file it came from (null for an OS-only document) and the Vault candidate IDs it made. A repeat delivery finds its row
and proposes nothing. Deleting the workspace removes its rows. Downgrade drops the table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "128"
down_revision = "127"
branch_labels = depends_on = None

TABLE = "pai_document_proposals"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("file_id", sa.Text(), nullable=True),
        sa.Column("candidate_ids", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade():
    op.drop_table(TABLE)
