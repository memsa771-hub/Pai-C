"""Slice 7: replanning (spec §3): proposals, plan overrides, support cases, the plan's `changes_paused` flag, and
Supervisor readings that belong to a plan.

Revision ID: os_0012
Revises: os_0011
Create Date: 2026-10-23

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0012"
down_revision = "os_0011"
branch_labels = None
depends_on = None

S = "os"
PROPOSAL_STATUSES = ("applied", "pending", "accepted", "declined", "expired", "refused")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _common() -> list:
    return [sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
            sa.Column("tenant_id", sa.Text, nullable=False),
            sa.Column("plan_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_plans.id", ondelete="CASCADE"), nullable=False)]


def upgrade() -> None:
    now = sa.func.now()
    op.create_table(
        "os_proposals", *_common(),
        sa.Column("event_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ops", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("refused", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("big", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source IN ('rules', 'supervisor')", name="ck_os_proposals_source"),
        sa.CheckConstraint(_in("status", PROPOSAL_STATUSES), name="ck_os_proposals_status"),
        sa.Index("ix_os_proposals_plan", "plan_id"),
        schema=S,
    )
    op.create_table(
        "os_plan_overrides", *_common(),
        sa.Column("proposal_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_proposals.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("op", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("op IN ('skip', 'cancel', 'cancel_programme', 'add', 'reprioritise')",
                           name="ck_os_plan_overrides_op"),
        sa.Index("ix_os_plan_overrides_plan", "plan_id"),
        schema=S,
    )
    op.create_table(
        "os_support_cases", *_common(),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("event_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("proposal_id", sa.BigInteger, sa.ForeignKey(f"{S}.os_proposals.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_os_support_cases_status"),
        schema=S,
    )
    op.add_column("os_plans", sa.Column("changes_paused", sa.Boolean, nullable=False,
                                        server_default=sa.text("false")), schema=S)
    op.add_column("os_agent_runs", sa.Column("plan_id", sa.BigInteger,
                                             sa.ForeignKey(f"{S}.os_plans.id", ondelete="SET NULL")), schema=S)
    op.create_unique_constraint("uq_os_agent_runs_plan", "os_agent_runs", ["plan_id", "reading"], schema=S)


def downgrade() -> None:
    op.drop_constraint("uq_os_agent_runs_plan", "os_agent_runs", type_="unique", schema=S)
    op.drop_column("os_agent_runs", "plan_id", schema=S)
    op.drop_column("os_plans", "changes_paused", schema=S)
    op.drop_table("os_support_cases", schema=S)
    op.drop_table("os_plan_overrides", schema=S)
    op.drop_table("os_proposals", schema=S)
