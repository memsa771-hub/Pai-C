"""P1-T10 Task A1: the consistency job's own tables (R-05, master 9.3). `os_consistency_cases` holds one case per student
and rule while open (codes, IDs and the rule number only: never a value, never student text); `os_consistency_runs`
holds one row per tenant and date, so only one replica runs the nightly job. Neither table is plan state and no plan
changes because of them.

Revision ID: os_0024
Revises: os_0023
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0024"
down_revision = "os_0023"
branch_labels = None
depends_on = None

S = "os"
CASES = "os_consistency_cases"
RUNS = "os_consistency_runs"
OPEN_INDEX = "uq_os_consistency_cases_open"


def upgrade() -> None:
    op.create_table(
        CASES,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("rule", sa.SmallInteger, nullable=False),
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_plans.id", ondelete="SET NULL")),
        sa.Column("codes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("rule BETWEEN 1 AND 8", name="ck_os_consistency_cases_rule"),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_os_consistency_cases_status"),
        schema=S,
    )
    # one open case per student, rule AND plan, so two plans never merge into one case (a case without a plan counts as 0)
    op.create_index(OPEN_INDEX, CASES, ["tenant_id", "student_ref", "rule", sa.text("coalesce(plan_id, 0)")], unique=True,
                    schema=S, postgresql_where=sa.text("status = 'open'"))
    op.create_table(
        RUNS,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("counts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("tenant_id", "run_date", name="uq_os_consistency_runs_date"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table(RUNS, schema=S)
    op.drop_table(CASES, schema=S)
