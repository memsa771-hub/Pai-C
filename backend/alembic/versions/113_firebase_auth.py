"""Firebase Auth: the sign-in identity on each account, and known devices.

Revision ID: 113
Revises: 112

`users.firebase_uid` links a Firebase Auth uid to the existing account (and
its Vault); `auth_devices` remembers where a student has signed in so a new
device triggers a sign-in alert. Additive only: existing users, their
`supabase_uid` and the old session tables are left as they are.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "113"
down_revision = "112"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column("firebase_uid", sa.Text(), nullable=True))
    op.create_index("uq_users_firebase_uid", "users", ["firebase_uid"], unique=True,
                    postgresql_where=sa.text("firebase_uid IS NOT NULL"))
    op.create_table(
        "auth_devices",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_hash", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("user_id", "device_hash", name="uq_auth_device_user_hash"),
    )


def downgrade():
    op.drop_table("auth_devices")
    op.drop_index("uq_users_firebase_uid", table_name="users")
    op.drop_column("users", "firebase_uid")
