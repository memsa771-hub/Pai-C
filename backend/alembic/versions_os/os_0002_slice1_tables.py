"""Slice 1 tables: plans, tasks, revisions, runner, outbox, seeded Knowledge.

Revision ID: os_0002
Revises: os_0001
Create Date: 2026-10-18

Self-contained on purpose: it does not import app.os, so later model changes cannot rewrite history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "os_0002"
down_revision = "os_0001"
branch_labels = None
depends_on = None

S = "os"
TS = sa.DateTime(timezone=True)
NOW = sa.func.now()
TASK_STATES = (
    "pending", "ready", "running", "waiting_student", "waiting_review",
    "done", "failed", "skipped", "cancelled", "blocked",
)


def _id():
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", sa.Text, nullable=False)


def _in(column, values, name):
    return sa.CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=name)


def _fk(column, target, ondelete="CASCADE", nullable=False):
    return sa.Column(column, sa.BigInteger, sa.ForeignKey(f"os.{target}.id", ondelete=ondelete), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "os_plans", _id(), _tenant(),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("external_ref", sa.Text, nullable=False),
        sa.Column("student_ref", sa.Text, nullable=False),
        sa.Column("contract", JSONB, nullable=False),
        sa.Column("contract_sha256", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("current_revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "source", "external_ref", name="uq_os_plans_identity"),
        _in("status", ("active", "at_risk", "paused", "done"), "ck_os_plans_status"),
        schema=S,
    )
    op.create_table(
        "os_tasks", _id(), _tenant(), _fk("plan_id", "os_plans"),
        sa.Column("instance_key", sa.Text, nullable=False),
        sa.Column("template_key", sa.Text, nullable=False),
        sa.Column("task_type", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("inbox_kind", sa.Text),
        sa.Column("programme_ref", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="pending"),
        sa.Column("blocked_reason", sa.Text),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_days", sa.Integer, nullable=False, server_default="1"),
        sa.Column("earliest_start", TS),
        sa.Column("latest_start", TS),
        sa.Column("latest_finish", TS),
        sa.Column("due_at", TS),
        sa.Column("due_tz", sa.Text, nullable=False),
        sa.Column("provisional", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("estimated", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("slack_days", sa.Integer),
        sa.Column("critical", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("protected", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("citations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("fact_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("playbook_version", sa.Integer, nullable=False),
        sa.Column("result", JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("plan_id", "instance_key", name="uq_os_tasks_instance"),
        _in("state", TASK_STATES, "ck_os_tasks_state"),
        _in("kind", ("work", "student"), "ck_os_tasks_kind"),
        schema=S,
    )
    op.create_table(
        "os_task_edges", _id(), _tenant(), _fk("plan_id", "os_plans"),
        _fk("from_task", "os_tasks"), _fk("to_task", "os_tasks"),
        sa.Column("hard", sa.Boolean, nullable=False),
        sa.UniqueConstraint("from_task", "to_task", name="uq_os_task_edges"),
        schema=S,
    )
    op.create_table(
        "os_plan_revisions", _id(), _tenant(), _fk("plan_id", "os_plans"),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("cause", sa.Text, nullable=False),
        sa.Column("diff", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("plan_id", "number", name="uq_os_plan_revisions"),
        schema=S,
    )
    op.create_table(
        "os_playbook_pins", _id(), _tenant(),
        sa.Column("plan_id", sa.BigInteger, sa.ForeignKey("os.os_plans.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("playbook_key", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("pinned_at", TS, nullable=False, server_default=NOW),
        schema=S,
    )
    op.create_table(
        "os_enqueue_requests", _id(), _tenant(), _fk("task_id", "os_tasks"),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("sent", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("task_id", "attempt", name="uq_os_enqueue_requests"),
        schema=S,
    )
    op.create_table(
        "os_task_attempts", _id(), _tenant(), _fk("task_id", "os_tasks"),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("started_at", TS, nullable=False, server_default=NOW),
        sa.Column("ended_at", TS),
        sa.UniqueConstraint("task_id", "attempt", name="uq_os_task_attempts"),
        schema=S,
    )
    op.create_table(
        "os_events", _id(), _tenant(),
        _fk("plan_id", "os_plans", nullable=True),
        _fk("task_id", "os_tasks", ondelete="SET NULL", nullable=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("at", TS, nullable=False, server_default=NOW),
        schema=S,
    )
    op.create_index("ix_os_events_plan", "os_events", ["plan_id"], schema=S)
    op.create_table(
        "os_modules",
        sa.Column("module", sa.Text, primary_key=True),
        _tenant(),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        schema=S,
    )
    op.create_table(
        "os_outbox", _id(), _tenant(),
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("recipient", sa.Text, nullable=False),
        sa.Column("template", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("sent_at", TS),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_os_outbox_key"),
        _in("status", ("pending", "sent", "skipped"), "ck_os_outbox_status"),
        schema=S,
    )
    op.create_table(
        "os_knowledge_facts", _id(), _tenant(),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("ref", sa.Text, nullable=False),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("intake_year", sa.Integer, nullable=False),
        sa.Column("value", JSONB),
        sa.Column("quote", sa.Text, nullable=False, server_default=""),
        sa.Column("url", sa.Text, nullable=False, server_default=""),
        sa.Column("checked_at", TS, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("conflict_note", sa.Text),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "scope", "ref", "field", "intake_year", name="uq_os_knowledge_facts"),
        _in("scope", ("route", "programme"), "ck_os_knowledge_facts_scope"),
        _in("status", ("confirmed", "unconfirmed", "stale"), "ck_os_knowledge_facts_status"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_index("ix_os_events_plan", table_name="os_events", schema=S)
    for name in (
        "os_knowledge_facts", "os_outbox", "os_modules", "os_events", "os_task_attempts",
        "os_enqueue_requests", "os_playbook_pins", "os_plan_revisions", "os_task_edges",
        "os_tasks", "os_plans",
    ):
        op.drop_table(name, schema=S)
