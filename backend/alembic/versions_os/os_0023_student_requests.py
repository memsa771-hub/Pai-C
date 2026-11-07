"""P1-T8 Task 3: the table `os_student_requests` keeps one request per student and fact (R-19, master 9.3 rule 7). A row
says which fact or document the student is asked for, at which evidence level, which plan step asks, and whether it is
open, answered or cancelled. Codes, keys and IDs only: it never holds a fact value (R-01). A unique partial index allows
one open row per tenant, student and fact.

Revision ID: os_0023
Revises: os_0022
Create Date: 2026-11-07

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op

revision = "os_0023"
down_revision = "os_0022"
branch_labels = None
depends_on = None

S = "os"
T = "os_student_requests"
OPEN_INDEX = "uq_os_student_requests_open"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_tasks.id", ondelete="SET NULL")),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("need_kind", sa.Text, nullable=False),
        sa.Column("need_ref", sa.Text, nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("closed_cause", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(_in("kind", ("provide", "which_is_right")), name="ck_os_student_requests_kind"),
        sa.CheckConstraint(_in("need_kind", ("fact", "document")), name="ck_os_student_requests_need_kind"),
        sa.CheckConstraint(_in("evidence", ("stated", "shown", "confirmed")), name="ck_os_student_requests_evidence"),
        sa.CheckConstraint(_in("status", ("open", "answered", "cancelled")), name="ck_os_student_requests_status"),
        schema=S,
    )
    op.create_index("ix_os_student_requests_plan", T, ["tenant_id", "plan_id"], schema=S)
    op.create_index(OPEN_INDEX, T, ["tenant_id", "student_ref", "need_kind", "need_ref"], unique=True, schema=S,
                    postgresql_where=sa.text("status = 'open'"))


def downgrade() -> None:
    op.drop_table(T, schema=S)
