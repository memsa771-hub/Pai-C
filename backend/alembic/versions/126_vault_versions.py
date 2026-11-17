"""The per-student Vault version (P1-T4, R-13, P1-D15).

Revision ID: 126
Revises: 125

New table `pai_vault_versions`: one row per workspace with the Vault `version` and `key_versions` (StudentFacts key
to the version that last changed it). Rows exist only for students whose Vault changed while CONNECT_STUDENT_FACTS was
on. Deleting the workspace removes its row. Downgrade drops the table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "126"
down_revision = "125"
branch_labels = depends_on = None

TABLE = "pai_vault_versions"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("key_versions", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade():
    op.drop_table(TABLE)
