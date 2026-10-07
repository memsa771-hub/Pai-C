"""Shared student requests for paused research and future OS work.

Revision ID: 092
Revises: 091
"""

from alembic import op
import sqlalchemy as sa

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_student_requests",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("execution_run_id", sa.Text(), sa.ForeignKey("execution_runs.id", ondelete="SET NULL")),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("accepts_upload", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("asked_at", sa.DateTime(timezone=True)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source IN ('research', 'os')", name="ck_student_request_source"),
        sa.CheckConstraint("status IN ('open', 'answered', 'withdrawn')", name="ck_student_request_status"),
        sa.UniqueConstraint("execution_run_id", "item_key", name="uq_student_request_run_item"),
    )
    op.create_index("idx_student_requests_workspace_status", "pai_student_requests", ["workspace_id", "status", "created_at"])


def downgrade():
    op.drop_index("idx_student_requests_workspace_status", table_name="pai_student_requests")
    op.drop_table("pai_student_requests")
