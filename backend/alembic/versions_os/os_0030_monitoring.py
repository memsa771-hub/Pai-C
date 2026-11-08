"""P2-T7: season monitoring and student reports (P2 spec §4.7, P2-D20, P2-D22; R-27, R-28). A marker on facts that went
back to unconfirmed because a page changed or a student reported them (the compiler holds the steps they date), the
student reports, one row per monitoring run, and what monitoring has seen once (a change counts only when seen on two runs). Additive only.

Revision ID: os_0030
Revises: os_0029
Create Date: 2026-11-08

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "os_0030"
down_revision = "os_0029"
branch_labels = None
depends_on = None

S = "os"


def upgrade() -> None:
    op.add_column("os_knowledge_facts", sa.Column("recheck_reason", sa.Text), schema=S)
    op.create_check_constraint("ck_os_knowledge_facts_recheck", "os_knowledge_facts",
                               "recheck_reason IS NULL OR recheck_reason IN ('monitor', 'report', 'report_escalated')", schema=S)
    op.create_table(
        "os_fact_reports",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("fact_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_knowledge_facts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("review_item_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_review_items.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=S,
    )
    op.create_index("ix_os_fact_reports_student", "os_fact_reports", ["tenant_id", "student_ref", "created_at"], schema=S)
    op.create_index("ix_os_fact_reports_fact", "os_fact_reports", ["tenant_id", "fact_id"], schema=S)
    op.create_table(
        "os_monitor_seen",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("fact_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_knowledge_facts.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("first_run_id", sa.BigInteger, nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "fact_id", name="uq_os_monitor_seen_fact"),
        schema=S,
    )
    op.create_table(
        "os_monitor_runs",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("counts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("tenant_id", "run_date", name="uq_os_monitor_runs_day"),
        schema=S,
    )


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("os_fact_reports", "os_monitor_runs", "os_monitor_seen"):
        if conn.execute(sa.text(f"SELECT 1 FROM {S}.{table} LIMIT 1")).first():
            raise RuntimeError(f"os_0030 downgrade refused: {table} holds records (no silent loss)")
    if conn.execute(sa.text(f"SELECT 1 FROM {S}.os_knowledge_facts WHERE recheck_reason IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("os_0030 downgrade refused: facts are being re-checked (no silent loss)")
    op.drop_table("os_monitor_seen", schema=S)
    op.drop_table("os_monitor_runs", schema=S)
    op.drop_table("os_fact_reports", schema=S)
    op.drop_constraint("ck_os_knowledge_facts_recheck", "os_knowledge_facts", schema=S)
    op.drop_column("os_knowledge_facts", "recheck_reason", schema=S)
