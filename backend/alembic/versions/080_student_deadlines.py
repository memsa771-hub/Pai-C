"""Student deadlines, reminder settings and notification idempotency.

Revision ID: 080
Revises: 079
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("idx_pai_application_plans_deadline", "pai_application_plans", ["deadline_at"])
    op.create_index("idx_pai_application_requirements_due", "pai_application_requirements", ["due_at"])
    op.add_column("notifications", sa.Column("dedupe_key", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_notifications_workspace_dedupe", "notifications", ["workspace_id", "dedupe_key"])
    op.create_table(
        "pai_student_deadlines",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default="other"),
        sa.Column("notes", sa.Text()),
        sa.Column("source_url", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_pai_student_deadlines_workspace_due", "pai_student_deadlines", ["workspace_id", "due_on"])
    op.create_index("idx_pai_student_deadlines_due", "pai_student_deadlines", ["due_on"])
    op.create_table(
        "pai_deadline_settings",
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="UTC"),
        sa.Column("reminder_days", JSONB(), nullable=False, server_default=sa.text("'[7,1,0]'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade():
    op.drop_table("pai_deadline_settings")
    op.drop_table("pai_student_deadlines")
    op.drop_index("idx_pai_application_requirements_due", table_name="pai_application_requirements")
    op.drop_index("idx_pai_application_plans_deadline", table_name="pai_application_plans")
    op.drop_constraint("uq_notifications_workspace_dedupe", "notifications", type_="unique")
    op.drop_column("notifications", "dedupe_key")
