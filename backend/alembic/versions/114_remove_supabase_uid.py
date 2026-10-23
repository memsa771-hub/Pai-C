"""Sign-in is Firebase only: drop the old Supabase identity column.

Revision ID: 114
Revises: 113

`users.supabase_uid` held the earlier Supabase user id. Accounts now link
by `firebase_uid` (and, on a first Firebase sign-in, by verified email), so
the column has no reader left. The old `pai_sessions` and `auth_identities`
tables are no longer used by the code but are kept: tables are never dropped.
"""
from alembic import op
import sqlalchemy as sa

revision = "114"
down_revision = "113"
branch_labels = depends_on = None


def upgrade():
    op.drop_column("users", "supabase_uid")


def downgrade():
    # The column comes back empty; the old Supabase ids are not restored.
    op.add_column("users", sa.Column("supabase_uid", sa.Text(), nullable=True))
