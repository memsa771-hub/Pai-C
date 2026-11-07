"""P2-T1: Knowledge facts per intake and owner, the `verified` level, and append-only fact history (P2 spec P2-D5,
P2-D6, P2-D8, P2-D9; R-25, R-60, R-75). Existing rows keep today's meaning: `intake_term` and `owner_ref` are '' ("not
recorded" / "no owner"), the other new columns NULL. T8 backfills `intake_term` from each route's playbook (plan D-t1-1).

Revision ID: os_0025
Revises: os_0024
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0025"
down_revision = "os_0024"
branch_labels = None
depends_on = None

S = "os"
F = "os_knowledge_facts"
R = "os_fact_revisions"
OLD_KEY = ["tenant_id", "scope", "ref", "field", "intake_year"]
NEW_KEY = ["tenant_id", "scope", "ref", "field", "intake_term", "intake_year", "owner_ref"]


def upgrade() -> None:
    op.add_column(F, sa.Column("intake_term", sa.Text, nullable=False, server_default=""), schema=S)
    op.add_column(F, sa.Column("owner_ref", sa.Text, nullable=False, server_default=""), schema=S)
    op.add_column(F, sa.Column("fact_class", sa.Text), schema=S)
    op.add_column(F, sa.Column("read_method", sa.Text), schema=S)
    op.add_column(F, sa.Column("language", sa.Text), schema=S)
    op.drop_constraint("ck_os_knowledge_facts_status", F, schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_status", F,
                               "status IN ('confirmed', 'unconfirmed', 'stale', 'verified')", schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_read_method", F,
                               "read_method IN ('fetch', 'render', 'ocr', 'human', 'model')", schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_language", F, "language ~ '^[a-z]{2,3}$'", schema=S)
    op.drop_constraint("uq_os_knowledge_facts", F, schema=S)
    op.create_unique_constraint("uq_os_knowledge_facts", F, NEW_KEY, schema=S)
    op.create_table(
        R,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("fact_id", sa.BigInteger, sa.ForeignKey(f"{S}.{F}.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB, nullable=False),
        sa.Column("cause", sa.Text, nullable=False),
        sa.Column("cause_ref", sa.Text),
        sa.Column("actor", sa.Text),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action IN ('insert', 'change', 'status', 'undo')", name="ck_os_fact_revisions_action"),
        sa.CheckConstraint("cause IN ('seed', 'manual', 'research', 'import', 'review', 'monitor', 'report', "
                           "'rollover')", name="ck_os_fact_revisions_cause"),
        schema=S,
    )
    op.create_index("ix_os_fact_revisions_fact", R, ["tenant_id", "fact_id", "id"], schema=S)
    op.create_index("ix_os_fact_revisions_cause", R, ["tenant_id", "cause", "cause_ref"], schema=S)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.{F} WHERE status = 'verified' LIMIT 1")).first():
        raise RuntimeError("os_0025 downgrade refused: verified facts exist (no silent loss)")
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.{F} GROUP BY {', '.join(OLD_KEY)} HAVING count(*) > 1 LIMIT 1")).first():
        raise RuntimeError("os_0025 downgrade refused: facts differ only by intake term or owner")
    op.drop_table(R, schema=S)
    op.drop_constraint("uq_os_knowledge_facts", F, schema=S)
    op.create_unique_constraint("uq_os_knowledge_facts", F, OLD_KEY, schema=S)
    op.drop_constraint("ck_os_knowledge_facts_language", F, schema=S)
    op.drop_constraint("ck_os_knowledge_facts_read_method", F, schema=S)
    op.drop_constraint("ck_os_knowledge_facts_status", F, schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_status", F,
                               "status IN ('confirmed', 'unconfirmed', 'stale')", schema=S)
    for col in ("language", "read_method", "fact_class", "owner_ref", "intake_term"):
        op.drop_column(F, col, schema=S)
