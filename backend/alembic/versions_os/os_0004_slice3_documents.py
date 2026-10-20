"""Slice 3 tables: documents, their files, fields and findings, and the student's confirmed profile values.
os_agent_runs rows may now belong to a document instead of a research run.

Revision ID: os_0004
Revises: os_0003
Create Date: 2026-10-20

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0004"
down_revision = "os_0003"
branch_labels = None
depends_on = None

S = "os"
TS = sa.DateTime(timezone=True)
NOW = sa.func.now()
EMPTY_LIST = sa.text("'[]'::jsonb")
STATUSES = ("uploaded", "reading", "read", "needs_student", "confirmed", "failed", "deleted")


def _id():
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", sa.Text, nullable=False)


def _in(column, values, name):
    return sa.CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=name)


def _doc_fk(ondelete):
    return sa.ForeignKey(f"{S}.os_documents.id", ondelete=ondelete)


def upgrade() -> None:
    op.create_table(
        "os_documents", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("doc_type", sa.Text, nullable=False),
        sa.Column("type_version", sa.Integer, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("pages", sa.Integer),
        sa.Column("status", sa.Text, nullable=False, server_default="uploaded"),
        sa.Column("detected_type", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("read_at", TS),
        sa.Column("confirmed_at", TS),
        sa.Column("deleted_at", TS),
        _in("status", STATUSES, "ck_os_documents_status"),
        schema=S,
    )
    op.create_index("uq_os_documents_sha", "os_documents", ["tenant_id", "student_ref", "sha256"], unique=True,
                    postgresql_where=sa.text("status <> 'deleted'"), schema=S)
    op.create_index("ix_os_documents_student", "os_documents", ["tenant_id", "student_ref"], schema=S)
    op.create_table(
        "os_document_files",
        sa.Column("document_id", sa.BigInteger, _doc_fk("CASCADE"), primary_key=True),
        _tenant(),
        sa.Column("data", sa.LargeBinary, nullable=False),
        schema=S,
    )
    op.create_table(
        "os_document_fields", _id(), _tenant(),
        sa.Column("document_id", sa.BigInteger, _doc_fk("CASCADE"), nullable=False),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("value_read", JSONB),
        sa.Column("check_result", sa.Text, nullable=False, server_default="ok"),
        sa.Column("reasons", JSONB, nullable=False, server_default=EMPTY_LIST),
        sa.Column("value_confirmed", JSONB),
        sa.Column("confirmed_by", sa.Text),
        sa.Column("confirmed_at", TS),
        sa.UniqueConstraint("document_id", "field", name="uq_os_document_fields"),
        _in("check_result", ("ok", "check_failed", "missing"), "ck_os_document_fields_check"),
        schema=S,
    )
    op.create_table(
        "os_document_findings", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("items", JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("resolution", JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("resolved_at", TS),
        _in("kind", ("variant", "mismatch"), "ck_os_document_findings_kind"),
        _in("status", ("open", "resolved"), "ck_os_document_findings_status"),
        schema=S,
    )
    op.create_index("ix_os_document_findings_student", "os_document_findings", ["tenant_id", "student_ref"], schema=S)
    op.create_table(
        "os_profile_values", _id(), _tenant(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("value", JSONB),
        sa.Column("source_document_id", sa.BigInteger, _doc_fk("SET NULL")),
        sa.Column("confirmed_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "student_ref", "key", name="uq_os_profile_values_key"),
        schema=S,
    )
    op.alter_column("os_agent_runs", "research_run_id", nullable=True, schema=S)
    op.add_column("os_agent_runs", sa.Column("document_id", sa.BigInteger, _doc_fk("SET NULL")), schema=S)
    op.create_unique_constraint("uq_os_agent_runs_document", "os_agent_runs", ["document_id", "reading"], schema=S)


def downgrade() -> None:
    op.drop_constraint("uq_os_agent_runs_document", "os_agent_runs", type_="unique", schema=S)
    op.drop_column("os_agent_runs", "document_id", schema=S)
    op.execute(f"DELETE FROM {S}.os_agent_runs WHERE research_run_id IS NULL")
    op.alter_column("os_agent_runs", "research_run_id", nullable=False, schema=S)
    for name in ("os_profile_values", "os_document_findings", "os_document_fields", "os_document_files",
                 "os_documents"):
        op.drop_table(name, schema=S)
