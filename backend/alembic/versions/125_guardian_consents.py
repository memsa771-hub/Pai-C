"""Guardian consent links (P1-T3, R-10).

Revision ID: 125
Revises: 124

New table `pai_guardian_consents`: one row per e-mailed guardian link and its outcome (the audit of the under-18
consent). Only the SHA-256 of the token is stored. Deleting the workspace removes its rows; deleting a decision row
keeps the audit (`decision_id` SET NULL). `expires_at` is null for a withdraw link (no fixed end). Downgrade drops the table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "125"
down_revision = "124"
branch_labels = depends_on = None

TABLE = "pai_guardian_consents"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("decision_id", UUID(as_uuid=False), sa.ForeignKey("pai_route_decisions.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("decision_version", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=sa.text("'agree'")),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text_version", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False, server_default=sa.text("'sent'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("purpose IN ('agree', 'withdraw')", name="ck_guardian_consent_purpose"),
        sa.CheckConstraint("outcome IN ('sent', 'agreed', 'withdrawn', 'expired', 'stale')",
                           name="ck_guardian_consent_outcome"),
    )
    op.create_index("idx_guardian_consents_workspace", TABLE, ["workspace_id", "created_at"])


def downgrade():
    op.drop_index("idx_guardian_consents_workspace", table_name=TABLE)
    op.drop_table(TABLE)
