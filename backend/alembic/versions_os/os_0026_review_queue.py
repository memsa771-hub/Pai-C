"""P2-T5: reviewers, the review queue, every check, evidence files and batch attestations (P2 spec §4.5, P2-D15,
P2-D16; R-25, R-42, R-72, R-75). New tables only; no existing table changes.

Revision ID: os_0026
Revises: os_0025
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "os_0026"
down_revision = "os_0025"
branch_labels = None
depends_on = None

S = "os"


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _fk(table: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{S}.{table}.id", ondelete="RESTRICT")


def upgrade() -> None:
    op.create_table(
        "os_reviewers", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("ref", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("identity", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False, server_default="person"),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        _created(),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "ref", name="uq_os_reviewers_ref"),
        sa.UniqueConstraint("token_hash", name="uq_os_reviewers_token"),
        sa.CheckConstraint("role IN ('checker', 'approver', 'admin')", name="ck_os_reviewers_role"),
        sa.CheckConstraint("kind IN ('person', 'ai')", name="ck_os_reviewers_kind"),
        schema=S,
    )
    op.create_table(
        "os_review_items", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text),
        sa.Column("fact_id", sa.BigInteger, _fk("os_knowledge_facts")),
        sa.Column("subject", sa.Text, nullable=False, server_default=""),
        sa.Column("field", sa.Text),
        sa.Column("intake_term", sa.Text, nullable=False, server_default=""),
        sa.Column("intake_year", sa.Integer),
        sa.Column("owner_ref", sa.Text, nullable=False, server_default=""),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("batch_ref", sa.Text),
        sa.Column("dedupe_key", sa.Text, nullable=False),
        sa.Column("join_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("opened_by", sa.Text, nullable=False, server_default="manual"),
        _created(),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by", sa.BigInteger, _fk("os_reviewers")),
        sa.CheckConstraint("kind IN ('verify', 'report', 'change', 'suspect_domain', 'collect', 'conflict', "
                           "'import_dispute')", name="ck_os_review_items_kind"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_os_review_items_status"),
        schema=S,
    )
    op.create_index("uq_os_review_items_open", "os_review_items", ["tenant_id", "dedupe_key"], unique=True,
                    schema=S, postgresql_where=sa.text("status = 'open'"))
    op.create_index("ix_os_review_items_list", "os_review_items", ["tenant_id", "status", "kind", "id"], schema=S)
    op.create_index("ix_os_review_items_batch", "os_review_items", ["tenant_id", "batch_ref"], schema=S)
    op.create_table(
        "os_review_files", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("item_id", sa.BigInteger, _fk("os_review_items"), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger, _fk("os_reviewers"), nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        _created(),
        schema=S,
    )
    op.create_index("ix_os_review_files_item", "os_review_files", ["tenant_id", "item_id"], schema=S)
    op.create_table(
        "os_fact_reviews", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("item_id", sa.BigInteger, _fk("os_review_items"), nullable=False),
        sa.Column("fact_id", sa.BigInteger, _fk("os_knowledge_facts")),
        sa.Column("reviewer_id", sa.BigInteger, _fk("os_reviewers"), nullable=False),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("corrected_value", JSONB),
        sa.Column("corrected_quote", sa.Text),
        sa.Column("note", sa.Text),
        sa.Column("evidence_file_id", sa.BigInteger, _fk("os_review_files")),
        sa.Column("high_stakes", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("fact_digest", sa.Text),
        _created(),
        sa.UniqueConstraint("item_id", "reviewer_id", name="uq_os_fact_reviews_reviewer"),
        sa.CheckConstraint("step IN ('check', 'approve', 'collect')", name="ck_os_fact_reviews_step"),
        sa.CheckConstraint("outcome IN ('correct', 'wrong', 'unclear', 'approve', 'reject', 'collected')",
                           name="ck_os_fact_reviews_outcome"),
        sa.CheckConstraint("(step = 'check' AND outcome IN ('correct', 'wrong', 'unclear')) OR "
                           "(step = 'approve' AND outcome IN ('approve', 'reject')) OR "
                           "(step = 'collect' AND outcome = 'collected')", name="ck_os_fact_reviews_step_outcome"),
        schema=S,
    )
    op.create_index("ix_os_fact_reviews_item", "os_fact_reviews", ["tenant_id", "item_id"], schema=S)
    op.create_table(
        "os_review_attestations", _id(),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("reviewer_id", sa.BigInteger, _fk("os_reviewers"), nullable=False),
        sa.Column("batch_ref", sa.Text, nullable=False),
        _created(),
        sa.UniqueConstraint("tenant_id", "reviewer_id", "batch_ref", name="uq_os_review_attestations"),
        schema=S,
    )


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("os_fact_reviews", "os_review_attestations", "os_review_items", "os_reviewers"):
        if conn.execute(sa.text(f"SELECT 1 FROM {S}.{table} LIMIT 1")).first():
            raise RuntimeError(f"os_0026 downgrade refused: {table} holds records (no silent loss)")
    for table in ("os_review_attestations", "os_fact_reviews", "os_review_files", "os_review_items", "os_reviewers"):
        op.drop_table(table, schema=S)
