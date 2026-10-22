"""Slice 5: statements (spec §3): interview answers, artifacts with immutable versions, approvals, pasted rules.

Revision ID: os_0008
Revises: os_0007
Create Date: 2026-10-22

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0008"
down_revision = "os_0007"
branch_labels = None
depends_on = None

S = "os"


def _id():
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", sa.Text, nullable=False)


def _now(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "os_statement_answers", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("question_id", sa.Text, nullable=False),
        sa.Column("question", sa.Text),
        sa.Column("answer", sa.Text, nullable=False, server_default=""),
        _now("updated_at"),
        sa.UniqueConstraint("tenant_id", "student_ref", "question_id", name="uq_os_statement_answers"),
        schema=S)
    op.create_table(
        "os_artifacts", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="empty"),
        sa.Column("current_version", sa.Integer),
        _now("created_at"), _now("updated_at"),
        sa.UniqueConstraint("tenant_id", "student_ref", "kind", "programme_ref", name="uq_os_artifacts_key"),
        sa.CheckConstraint("kind IN ('sop', 'cv')", name="ck_os_artifacts_kind"),
        sa.CheckConstraint("status IN ('empty', 'drafting', 'draft', 'needs_answers', 'failed', 'approved')", name="ck_os_artifacts_status"),
        schema=S)
    op.create_table(
        "os_artifact_versions", _id(), _tenant(),
        sa.Column("artifact_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_artifacts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column("words", sa.Integer, nullable=False),
        sa.Column("critic", JSONB),
        sa.Column("flags", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("limit_words", sa.Integer),
        _now("created_at"),
        sa.UniqueConstraint("artifact_id", "number", name="uq_os_artifact_versions"),
        sa.CheckConstraint("author IN ('writer', 'student')", name="ck_os_artifact_versions_author"),
        schema=S)
    op.create_table(
        "os_approvals", _id(), _tenant(),
        sa.Column("artifact_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_artifacts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        _now("approved_at"),
        sa.UniqueConstraint("artifact_id", name="uq_os_approvals_artifact"),
        schema=S)
    op.create_table(
        "os_statement_rules", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("programme_ref", sa.Text, nullable=False),
        sa.Column("prompt", sa.Text),
        sa.Column("limit_words", sa.Integer),
        sa.Column("limit_chars", sa.Integer),
        _now("updated_at"),
        sa.UniqueConstraint("tenant_id", "student_ref", "programme_ref", name="uq_os_statement_rules"),
        schema=S)
    op.add_column("os_agent_runs", sa.Column("artifact_id", sa.BigInteger), schema=S)
    op.create_foreign_key("os_agent_runs_artifact_id_fkey", "os_agent_runs", "os_artifacts", ["artifact_id"], ["id"],
                          source_schema=S, referent_schema=S, ondelete="SET NULL")
    op.create_unique_constraint("uq_os_agent_runs_artifact", "os_agent_runs", ["artifact_id", "reading"], schema=S)


def downgrade() -> None:
    op.drop_constraint("uq_os_agent_runs_artifact", "os_agent_runs", schema=S, type_="unique")
    op.drop_constraint("os_agent_runs_artifact_id_fkey", "os_agent_runs", schema=S, type_="foreignkey")
    op.drop_column("os_agent_runs", "artifact_id", schema=S)
    for t in ("os_statement_rules", "os_approvals", "os_artifact_versions", "os_artifacts", "os_statement_answers"):
        op.drop_table(t, schema=S)
