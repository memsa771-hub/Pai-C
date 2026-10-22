"""Tables of the PAI OS, all in schema `os` (SQLAlchemy Core): Slice 1, Slice 2's Knowledge tables, Slice 3's
Documents tables and Slice 4's self-serve tables.

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
    LargeBinary,
    Numeric,
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

FACT_SOURCES = ("seed", "manual", "research")

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
    # Token of the draft version last reported as skipped for this started/protected task, so a
    # revision reports the same difference once instead of on every recompute.
    Column("skipped_draft", Text),
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
    # Slice 2 (os_0003): where the fact came from, the research run that set it, and its evidence.
    Column("source", Text, nullable=False, server_default="seed"),
    Column("research_run_id", BigInteger, ForeignKey("os.os_research_runs.id", ondelete="SET NULL")),
    Column("evidence", JSONB),
    UniqueConstraint("tenant_id", "scope", "ref", "field", "intake_year", name="uq_os_knowledge_facts"),
    _in("scope", ("route", "programme"), "ck_os_knowledge_facts_scope"),
    _in("status", ("confirmed", "unconfirmed", "stale"), "ck_os_knowledge_facts_status"),
    _in("source", FACT_SOURCES, "ck_os_knowledge_facts_source"),
)

# --- Slice 2: Knowledge (spec 2026-10-19 §5) -------------------------------------------------------

programmes = Table(
    "os_programmes", md,
    _id(), _tenant(),
    Column("ref", Text, nullable=False),
    Column("route_key", Text, nullable=False),
    Column("university", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("aliases", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("start_urls", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("official_domains", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("status", Text, nullable=False, server_default="active"),
    Column("notes", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "ref", name="uq_os_programmes_ref"),
    _in("status", ("active", "excluded", "requested"), "ck_os_programmes_status"),  # requested: Slice 4
)

pages = Table(
    "os_pages", md,
    _id(), _tenant(),
    Column("url", Text, nullable=False),
    Column("final_url", Text),
    Column("http_status", Integer),
    Column("text", Text, nullable=False, server_default=""),
    Column("links", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("blocked", Text),
    Column("fetched_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "url", name="uq_os_pages_url"),
)

research_runs = Table(
    "os_research_runs", md,
    _id(), _tenant(),
    Column("programme_ref", Text, nullable=False),
    Column("intake_year", Integer, nullable=False),
    Column("workflow_id", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="running"),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("ended_at", DateTime(timezone=True)),
    Column("pages", Integer, nullable=False, server_default="0"),
    Column("confirmed", Integer, nullable=False, server_default="0"),
    Column("unconfirmed", Integer, nullable=False, server_default="0"),
    Column("cost_usd", Numeric(12, 6), nullable=False, server_default="0"),
    UniqueConstraint("tenant_id", "workflow_id", name="uq_os_research_runs_workflow"),
    _in("status", ("running", "done", "failed", "skipped_budget"), "ck_os_research_runs_status"),
)

agent_runs = Table(
    "os_agent_runs", md,
    _id(), _tenant(),
    # A reading belongs to a research run (Slice 2) or to a document (Slice 3, os_0004).
    Column("research_run_id", BigInteger, ForeignKey("os.os_research_runs.id", ondelete="CASCADE")),
    Column("document_id", BigInteger, ForeignKey("os.os_documents.id", ondelete="SET NULL")),
    Column("reading", Text, nullable=False),
    Column("agent", Text, nullable=False),
    Column("agent_version", Integer, nullable=False),
    Column("model", Text, nullable=False),
    Column("input_tokens", Integer, nullable=False, server_default="0"),
    Column("cached_tokens", Integer, nullable=False, server_default="0"),
    Column("output_tokens", Integer, nullable=False, server_default="0"),
    Column("cost_usd", Numeric(12, 6), nullable=False, server_default="0"),
    Column("error", Text),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("research_run_id", "reading", name="uq_os_agent_runs_reading"),
    UniqueConstraint("document_id", "reading", name="uq_os_agent_runs_document"),
)

# --- Slice 3: Documents (spec 2026-10-20 §3, os_0004) ------------------------------------------------------

DOCUMENT_STATUSES = ("uploaded", "reading", "read", "needs_student", "confirmed", "failed", "deleted")
FIELD_CHECKS = ("ok", "check_failed", "missing")

documents = Table(
    "os_documents", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("doc_type", Text, nullable=False),
    Column("type_version", Integer, nullable=False),
    Column("filename", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("size", Integer, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("pages", Integer),
    Column("status", Text, nullable=False, server_default="uploaded"),
    Column("detected_type", Text),
    Column("error", Text),
    _created(),
    Column("read_at", DateTime(timezone=True)),
    Column("confirmed_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
    Column("claimed_by", Text),  # the os.document workflow that claimed it for reading (os_0005)
    _in("status", DOCUMENT_STATUSES, "ck_os_documents_status"),
    # one live copy of a file per student; a deleted one may be uploaded again
    Index("uq_os_documents_sha", "tenant_id", "student_ref", "sha256", unique=True,
          postgresql_where=text("status <> 'deleted'")),
    Index("ix_os_documents_student", "tenant_id", "student_ref"),
)

document_files = Table(
    "os_document_files", md,
    Column("document_id", BigInteger, ForeignKey("os.os_documents.id", ondelete="CASCADE"), primary_key=True),
    _tenant(),
    Column("data", LargeBinary, nullable=False),
)

document_fields = Table(
    "os_document_fields", md,
    _id(), _tenant(),
    Column("document_id", BigInteger, ForeignKey("os.os_documents.id", ondelete="CASCADE"), nullable=False),
    Column("field", Text, nullable=False),
    Column("value_read", JSONB),
    Column("check_result", Text, nullable=False, server_default="ok"),  # not "check": a SQL keyword
    Column("reasons", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("value_confirmed", JSONB),
    Column("confirmed_by", Text),
    Column("confirmed_at", DateTime(timezone=True)),
    UniqueConstraint("document_id", "field", name="uq_os_document_fields"),
    _in("check_result", FIELD_CHECKS, "ck_os_document_fields_check"),
)

document_findings = Table(
    "os_document_findings", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("field", Text, nullable=False),
    Column("items", JSONB, nullable=False),  # [[document_id, value], ...]
    Column("status", Text, nullable=False, server_default="open"),
    Column("resolution", JSONB),
    _created(),
    Column("resolved_at", DateTime(timezone=True)),
    _in("kind", ("variant", "mismatch"), "ck_os_document_findings_kind"),
    _in("status", ("open", "resolved"), "ck_os_document_findings_status"),
    Index("ix_os_document_findings_student", "tenant_id", "student_ref"),
)

profile_values = Table(
    "os_profile_values", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("key", Text, nullable=False),
    Column("value", JSONB),
    Column("source_document_id", BigInteger, ForeignKey("os.os_documents.id", ondelete="SET NULL")),
    Column("confirmed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "student_ref", "key", name="uq_os_profile_values_key"),
)


# --- Slice 4: self-serve start and eligibility (spec 2026-10-21 §3, os_0006) ---------------------------------

programme_requests = Table(
    "os_programme_requests", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("route_key", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("programme_ref", Text, nullable=False),
    _created(),
    Index("ix_os_programme_requests_student", "tenant_id", "student_ref", "created_at"),
)

# The last verdict a student was told about, per plan and programme: a note only when it changes (S4-D7).
# Per plan (os_0007): the same programme can be in two of a student's plans (two intakes) with two verdicts.
eligibility_seen = Table(
    "os_eligibility_seen", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE"), nullable=False),
    Column("programme_ref", Text, nullable=False),
    Column("verdict", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "plan_id", "programme_ref", name="uq_os_eligibility_seen"),
)

eligibility_notes = Table(
    "os_eligibility_notes", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("programme_ref", Text, nullable=False),
    Column("verdict", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _created(),
    Column("read_at", DateTime(timezone=True)),
    Index("ix_os_eligibility_notes_student", "tenant_id", "student_ref"),
)
