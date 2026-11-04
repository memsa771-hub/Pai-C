"""Possibility dismissal: why a path was dismissed for the student (R-47 C1).

Revision ID: 123
Revises: 122

One nullable JSONB column on `pai_possibilities`: `dismissal`
({"reason": "student_excluded", "item_id", "quote", "at", "restored_at"?}).
A path the student excluded in chat is dismissed with the Vault option and
their own words; the student restoring it stamps `restored_at`, so the same
exclusion does not dismiss it again. Downgrade drops the column only.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "123"
down_revision = "122"
branch_labels = depends_on = None

TABLE = "pai_possibilities"


def upgrade():
    op.add_column(TABLE, sa.Column("dismissal", JSONB(), nullable=True))


def downgrade():
    op.drop_column(TABLE, "dismissal")
