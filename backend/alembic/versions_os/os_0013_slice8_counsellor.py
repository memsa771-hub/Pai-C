"""Slice 8: the Counsellor connection (spec §3): the intake of decision record exports, the glue's sweep mark, the
`closed` plan status, the Counsellor delivery columns on support cases, and the `counsellor` module row, off.

Revision ID: os_0013
Revises: os_0012
Create Date: 2026-10-26

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0013"
down_revision = "os_0012"
branch_labels = None
depends_on = None

S = "os"
INTAKE_STATUSES = ("pending", "planned", "revised", "replaced", "refused")
REFUSALS = ("not_authorized", "invalid_export", "route_not_supported", "unknown_programme", "self_serve_plan_open",
            "plan_closed")
DELIVERY = ("pending", "sent", "refused")
ESCALATION_REASONS = ("not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other")
OLD_PLAN_STATUSES = ("active", "at_risk", "paused", "done")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _plan_status(values: tuple[str, ...]) -> None:
    op.drop_constraint("ck_os_plans_status", "os_plans", type_="check", schema=S)
    op.create_check_constraint("ck_os_plans_status", "os_plans", _in("status", values), schema=S)


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "os_counsellor_intake",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("decision_id", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("journey_id", sa.Text, nullable=False),
        sa.Column("export", JSONB, nullable=False),
        sa.Column("export_sha256", sa.Text, nullable=False),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text),
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_plans.id", ondelete="SET NULL")),
        sa.Column("counsellor_status", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "decision_id", name="uq_os_counsellor_intake_decision"),
        sa.CheckConstraint(_in("status", INTAKE_STATUSES), name="ck_os_counsellor_intake_status"),
        sa.CheckConstraint(_in("reason", REFUSALS), name="ck_os_counsellor_intake_reason"),
        sa.CheckConstraint(_in("counsellor_status", DELIVERY), name="ck_os_counsellor_intake_delivery"),
        sa.Index("ix_os_counsellor_intake_pending", "tenant_id", "status", "student_ref", "chosen_at"),
        schema=S,
    )
    op.create_table(
        "os_counsellor_sweep",
        sa.Column("tenant_id", sa.Text, primary_key=True),
        sa.Column("mark", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        schema=S,
    )
    _plan_status((*OLD_PLAN_STATUSES, "closed"))
    op.add_column("os_support_cases", sa.Column("counsellor_status", sa.Text), schema=S)
    op.add_column("os_support_cases", sa.Column("counsellor_reason", sa.Text), schema=S)
    op.create_check_constraint("ck_os_support_cases_delivery", "os_support_cases", _in("counsellor_status", DELIVERY),
                               schema=S)
    op.create_check_constraint("ck_os_support_cases_counsellor_reason", "os_support_cases",
                               _in("counsellor_reason", ESCALATION_REASONS), schema=S)
    op.execute("INSERT INTO os.os_modules (module, tenant_id, enabled) VALUES ('counsellor', 'pai', false) "
               "ON CONFLICT (module) DO NOTHING")


def downgrade() -> None:
    op.execute("DELETE FROM os.os_modules WHERE module = 'counsellor'")
    op.execute("UPDATE os.os_plans SET status = 'done' WHERE status = 'closed'")  # over either way; the nearest old one
    op.drop_constraint("ck_os_support_cases_counsellor_reason", "os_support_cases", type_="check", schema=S)
    op.drop_constraint("ck_os_support_cases_delivery", "os_support_cases", type_="check", schema=S)
    op.drop_column("os_support_cases", "counsellor_reason", schema=S)
    op.drop_column("os_support_cases", "counsellor_status", schema=S)
    _plan_status(OLD_PLAN_STATUSES)
    op.drop_table("os_counsellor_sweep", schema=S)
    op.drop_table("os_counsellor_intake", schema=S)
