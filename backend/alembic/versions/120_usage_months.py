"""Monthly provider spend counter (the embeddings cap).

Revision ID: 120
Revises: 119

`pai_usage_months` holds one row per scope and calendar month ('YYYY-MM', UTC)
with the call count and the estimated USD spend. The model gateway adds to the
"embeddings" row on every embedding call and stops calling the provider once the
month reaches PAI_EMBEDDING_MONTHLY_CAP_USD. Additive only.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "120"
down_revision = "119"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "pai_usage_months",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("month", sa.Text(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("est_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("scope", "month", name="uq_usage_months_scope_month"),
    )


def downgrade():
    op.drop_table("pai_usage_months")
