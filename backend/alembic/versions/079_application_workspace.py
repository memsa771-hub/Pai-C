"""Application workspace catalog, saved schools, plans and requirements.

Revision ID: 079
Revises: 078
"""
from alembic import op
import sqlalchemy as sa

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pai_institutions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner_workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("country_code", sa.Text(), nullable=False),
        sa.Column("city", sa.Text()),
        sa.Column("website_url", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False, server_default="student"),
        sa.Column("provider", sa.Text()),
        sa.Column("provider_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_pai_institution_search", "pai_institutions", ["country_code", "normalized_name"])
    op.create_index("uq_pai_institution_owner_country_name", "pai_institutions", ["owner_workspace_id", "country_code", "normalized_name"], unique=True)
    op.create_index("uq_pai_institution_provider", "pai_institutions", ["provider", "provider_id"], unique=True)
    op.create_table(
        "pai_saved_institutions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution_id", sa.Text(), sa.ForeignKey("pai_institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("workspace_id", "institution_id", name="uq_pai_saved_institution"),
    )
    op.create_table(
        "pai_application_plans",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(as_uuid=False), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("institution_id", sa.Text(), sa.ForeignKey("pai_institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("program_name", sa.Text()),
        sa.Column("intake", sa.Text()),
        sa.Column("route", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="planning"),
        sa.Column("status_origin", sa.Text(), nullable=False, server_default="student"),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("application_url", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("external_provider", sa.Text()),
        sa.Column("external_id", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("submission_reference", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_pai_application_plans_ws_status", "pai_application_plans", ["workspace_id", "status"])
    op.create_index("idx_pai_application_plans_ws_deadline", "pai_application_plans", ["workspace_id", "deadline_at"])
    op.execute("CREATE UNIQUE INDEX uq_pai_application_plan_identity ON pai_application_plans "
               "(workspace_id, institution_id, lower(coalesce(program_name, '')), lower(coalesce(intake, '')))")
    op.create_table(
        "pai_application_requirements",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("application_id", sa.Text(), sa.ForeignKey("pai_application_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="other"),
        sa.Column("status", sa.Text(), nullable=False, server_default="todo"),
        sa.Column("source_type", sa.Text(), nullable=False, server_default="student"),
        sa.Column("source_checked_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("source_url", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("kanban_tasks.id", ondelete="SET NULL")),
        sa.Column("file_id", sa.Text(), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_pai_application_requirements_app", "pai_application_requirements", ["application_id", "position"])
    op.create_table(
        "pai_application_routines",
        sa.Column("application_id", sa.Text(), sa.ForeignKey("pai_application_plans.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("routine_id", sa.Text(), sa.ForeignKey("routines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_pai_application_routines_routine", "pai_application_routines", ["routine_id"])


def downgrade():
    op.drop_table("pai_application_routines")
    op.drop_table("pai_application_requirements")
    op.drop_table("pai_application_plans")
    op.drop_table("pai_saved_institutions")
    op.drop_table("pai_institutions")
