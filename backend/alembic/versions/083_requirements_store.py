"""Evidence-backed opportunities and reviewed requirement versions.

Revision ID: 083
Revises: 082
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_opportunities",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route", JSONB(), nullable=False),
        sa.Column("institution", sa.Text()),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("level", sa.Text()),
        sa.Column("intake", sa.Text()),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("url LIKE 'https://%'", name="ck_opportunity_https_url"),
    )
    op.create_index("idx_opportunities_workspace_country", "pai_opportunities", ["workspace_id", "country"])
    op.create_table(
        "pai_requirement_sets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("opportunity_id", sa.Text(), sa.ForeignKey("pai_opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rules", JSONB(), nullable=False),
        sa.Column("fees", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("deadlines", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'proposed'")),
        sa.Column("reviewed_by", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('proposed', 'verified', 'expired')", name="ck_requirement_set_status"),
        sa.CheckConstraint("source_url LIKE 'https://%'", name="ck_requirement_set_https_url"),
        sa.CheckConstraint("version > 0", name="ck_requirement_set_version"),
        sa.UniqueConstraint("opportunity_id", "version", name="uq_requirement_set_version"),
    )
    op.create_index("idx_requirement_sets_opportunity_status", "pai_requirement_sets", ["opportunity_id", "status"])


def downgrade():
    op.drop_index("idx_requirement_sets_opportunity_status", table_name="pai_requirement_sets")
    op.drop_table("pai_requirement_sets")
    op.drop_index("idx_opportunities_workspace_country", table_name="pai_opportunities")
    op.drop_table("pai_opportunities")
