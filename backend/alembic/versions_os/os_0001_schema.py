"""Create the os schema.

Revision ID: os_0001
Revises:
Create Date: 2026-10-12
"""

from alembic import op

revision = "os_0001"
down_revision = None
branch_labels = ("os",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS os")


def downgrade() -> None:
    # No CASCADE: Postgres refuses to drop the schema while it still holds objects.
    op.execute("DROP SCHEMA IF EXISTS os")
