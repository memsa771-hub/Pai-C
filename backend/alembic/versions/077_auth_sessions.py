"""Stable provider identities and revocable PAI application sessions.

Revision ID: 077
Revises: 076
"""

from alembic import op
import sqlalchemy as sa

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=False),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.UniqueConstraint("provider", "provider_subject",
                            name="uq_auth_identity_provider_subject"),
    )
    op.create_index("idx_auth_identity_user", "auth_identities", ["user_id"])
    op.execute("""
        INSERT INTO auth_identities (user_id, provider, provider_subject, email)
        SELECT id, 'supabase', supabase_uid, email
        FROM users
        WHERE supabase_uid IS NOT NULL AND supabase_uid <> ''
        ON CONFLICT (provider, provider_subject) DO NOTHING
    """)
    op.create_table(
        "pai_sessions",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=False),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_token_hash", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_pai_session_user", "pai_sessions", ["user_id"])
    op.create_index("idx_pai_session_provider_token", "pai_sessions",
                    ["provider_token_hash"])


def downgrade():
    op.drop_index("idx_pai_session_provider_token", table_name="pai_sessions")
    op.drop_index("idx_pai_session_user", table_name="pai_sessions")
    op.drop_table("pai_sessions")
    op.drop_index("idx_auth_identity_user", table_name="auth_identities")
    op.drop_table("auth_identities")
