"""Slice 1 tables of the PAI OS, all in schema `os` (SQLAlchemy Core).

Only `app.os.kernel` writes os_plans, os_tasks, os_task_edges and os_plan_revisions (invariant 1).
Every timestamp is timezone-aware (invariant 13) and every table carries tenant_id.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.os.db import OsBase

TASK_STATES = (
    "pending", "ready", "running", "waiting_student", "waiting_review",
    "done", "failed", "skipped", "cancelled", "blocked",
)

md = OsBase.metadata


def _id() -> Column:
    return Column("id", BigInteger, Identity(), primary_key=True)


def _tenant() -> Column:
    return Column("tenant_id", Text, nullable=False)


def _created() -> Column:
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now())


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    listed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({listed})", name=name)


plans = Table(
    "os_plans", md,
    _id(), _tenant(),
    Column("source", Text, nullable=False),
    Column("external_ref", Text, nullable=False),
    Column("student_ref", Text, nullable=False),
    Column("contract", JSONB, nullable=False),
    Column("contract_sha256", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("current_revision", Integer, nullable=False, server_default="1"),
    _created(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "source", "external_ref", name="uq_os_plans_identity"),
    _in("status", ("active", "at_risk", "paused", "done"), "ck_os_plans_status"),
)

tasks = Table(
    "os_tasks", md,
    _id(), _tenant(),
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE"), nullable=False),
    Column("instance_key", Text, nullable=False),
    Column("template_key", Text, nullable=False),
    Column("task_type", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("inbox_kind", Text),
    Column("programme_ref", Text),
    Column("title", Text, nullable=False),
    Column("state", Text, nullable=False, server_default="pending"),
    Column("blocked_reason", Text),
    Column("attempt", Integer, nullable=False, server_default="0"),
    Column("duration_days", Integer, nullable=False, server_default="1"),
    Column("earliest_start", DateTime(timezone=True)),
    Column("latest_start", DateTime(timezone=True)),
    Column("latest_finish", DateTime(timezone=True)),
    Column("due_at", DateTime(timezone=True)),
    Column("due_tz", Text, nullable=False),
    Column("provisional", Boolean, nullable=False, server_default=text("false")),
    Column("estimated", Boolean, nullable=False, server_default=text("false")),
    Column("slack_days", Integer),
    Column("critical", Boolean, nullable=False, server_default=text("false")),
    Column("protected", Boolean, nullable=False, server_default=text("false")),
    Column("citations", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("fact_refs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("playbook_version", Integer, nullable=False),
    Column("result", JSONB),
    _created(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("plan_id", "instance_key", name="uq_os_tasks_instance"),
    _in("state", TASK_STATES, "ck_os_tasks_state"),
    _in("kind", ("work", "student"), "ck_os_tasks_kind"),
)

task_edges = Table(
    "os_task_edges", md,
    _id(), _tenant(),
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE"), nullable=False),
    Column("from_task", BigInteger, ForeignKey("os.os_tasks.id", ondelete="CASCADE"), nullable=False),
    Column("to_task", BigInteger, ForeignKey("os.os_tasks.id", ondelete="CASCADE"), nullable=False),
    Column("hard", Boolean, nullable=False),
    UniqueConstraint("from_task", "to_task", name="uq_os_task_edges"),
)

plan_revisions = Table(
    "os_plan_revisions", md,
    _id(), _tenant(),
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("cause", Text, nullable=False),
    Column("diff", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _created(),
    UniqueConstraint("plan_id", "number", name="uq_os_plan_revisions"),
)

playbook_pins = Table(
    "os_playbook_pins", md,
    _id(), _tenant(),
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("playbook_key", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("pinned_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

enqueue_requests = Table(
    "os_enqueue_requests", md,
    _id(), _tenant(),
    Column("task_id", BigInteger, ForeignKey("os.os_tasks.id", ondelete="CASCADE"), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("sent", Boolean, nullable=False, server_default=text("false")),
    _created(),
    UniqueConstraint("task_id", "attempt", name="uq_os_enqueue_requests"),
)

task_attempts = Table(
    "os_task_attempts", md,
    _id(), _tenant(),
    Column("task_id", BigInteger, ForeignKey("os.os_tasks.id", ondelete="CASCADE"), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("workflow_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("ended_at", DateTime(timezone=True)),
    UniqueConstraint("task_id", "attempt", name="uq_os_task_attempts"),
)

events = Table(
    "os_events", md,
    _id(), _tenant(),
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE")),
    Column("task_id", BigInteger, ForeignKey("os.os_tasks.id", ondelete="SET NULL")),
    Column("type", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_os_events_plan", "plan_id"),
)

modules = Table(
    "os_modules", md,
    Column("module", Text, primary_key=True),
    _tenant(),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
)

outbox = Table(
    "os_outbox", md,
    _id(), _tenant(),
    Column("idempotency_key", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("recipient", Text, nullable=False),
    Column("template", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    _created(),
    Column("sent_at", DateTime(timezone=True)),
    UniqueConstraint("tenant_id", "idempotency_key", name="uq_os_outbox_key"),
    _in("status", ("pending", "sent", "skipped"), "ck_os_outbox_status"),
)

knowledge_facts = Table(
    "os_knowledge_facts", md,
    _id(), _tenant(),
    Column("scope", Text, nullable=False),
    Column("ref", Text, nullable=False),
    Column("field", Text, nullable=False),
    Column("intake_year", Integer, nullable=False),
    Column("value", JSONB),
    Column("quote", Text, nullable=False, server_default=""),
    Column("url", Text, nullable=False, server_default=""),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("conflict_note", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "scope", "ref", "field", "intake_year", name="uq_os_knowledge_facts"),
    _in("scope", ("route", "programme"), "ck_os_knowledge_facts_scope"),
    _in("status", ("confirmed", "unconfirmed", "stale"), "ck_os_knowledge_facts_status"),
)
