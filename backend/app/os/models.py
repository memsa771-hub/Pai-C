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
    Column("changes_paused", Boolean, nullable=False, server_default=text("false")),  # Slice 7 (os_0012), S7-D9
    UniqueConstraint("tenant_id", "source", "external_ref", name="uq_os_plans_identity"),
    _in("status", ("active", "at_risk", "paused", "done", "closed"), "ck_os_plans_status"),  # closed: S8-D8
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
    _in("status", ("pending", "sent", "skipped", "blocked", "failed"), "ck_os_outbox_status"),
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
    # Slice 5 (os_0008): a Writer or Critic reading belongs to an artifact.
    Column("artifact_id", BigInteger, ForeignKey("os.os_artifacts.id", ondelete="SET NULL")),
    UniqueConstraint("artifact_id", "reading", name="uq_os_agent_runs_artifact"),
    # Slice 7 (os_0012): a Supervisor reading belongs to a plan.
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="SET NULL")),
    UniqueConstraint("plan_id", "reading", name="uq_os_agent_runs_plan"),
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
    # Slice 6a (os_0009): "document" (confirmed from a document) or "entered" (typed by the student)
    Column("source", Text, nullable=False, server_default="document"),
    CheckConstraint("source IN ('document', 'entered')", name="ck_os_profile_values_source"),
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


# --- Slice 5: statements (spec 2026-10-22 §3, os_0008) -------------------------------------------------------

ARTIFACT_KINDS = ('sop', 'cv', 'pack', 'visa')  # pack: Slice 6a (os_0010); visa: Slice 6b (os_0011)
ARTIFACT_STATUSES = ('empty', 'drafting', 'draft', 'needs_answers', 'failed', 'budget', 'approved',
                     'building', 'ready', 'incomplete')  # the last three: a pack (Slice 6a, os_0010)

statement_answers = Table(
    "os_statement_answers", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("question_id", Text, nullable=False),  # a route question's id, or "followup:<n>"
    Column("question", Text),  # the text of a follow-up question (route questions live in config)
    Column("answer", Text, nullable=False, server_default=""),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "student_ref", "question_id", name="uq_os_statement_answers"),
)

artifacts = Table(
    "os_artifacts", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("programme_ref", Text, nullable=False, server_default=""),  # "" = the base artifact
    Column("status", Text, nullable=False, server_default="empty"),
    Column("current_version", Integer),
    _created(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "student_ref", "kind", "programme_ref", name="uq_os_artifacts_key"),
    _in("kind", ARTIFACT_KINDS, "ck_os_artifacts_kind"),
    _in("status", ARTIFACT_STATUSES, "ck_os_artifacts_status"),
)

artifact_versions = Table(
    "os_artifact_versions", md,
    _id(), _tenant(),
    Column("artifact_id", BigInteger, ForeignKey("os.os_artifacts.id", ondelete="CASCADE"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("author", Text, nullable=False),
    Column("words", Integer, nullable=False),
    Column("critic", JSONB),
    Column("flags", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("limit_words", Integer),
    _created(),
    UniqueConstraint("artifact_id", "number", name="uq_os_artifact_versions"),
    _in("author", ('writer', 'student', 'system'), "ck_os_artifact_versions_author"),  # system: a pack manifest
)

approvals = Table(
    "os_approvals", md,
    _id(), _tenant(),
    Column("artifact_id", BigInteger, ForeignKey("os.os_artifacts.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("artifact_id", name="uq_os_approvals_artifact"),
)

statement_rules = Table(
    "os_statement_rules", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("programme_ref", Text, nullable=False),
    Column("prompt", Text),
    Column("limit_words", Integer),
    Column("limit_chars", Integer),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "student_ref", "programme_ref", name="uq_os_statement_rules"),
)

# --- Slice 6a: the application pack (spec 2026-10-22 §3, os_0009) ---------------------------------------------

pack_files = Table(
    "os_pack_files", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("programme_ref", Text, nullable=False),
    Column("item_key", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("size", Integer, nullable=False),
    Column("pages", Integer, nullable=False),
    Column("data", LargeBinary, nullable=False),
    _created(),
    UniqueConstraint("tenant_id", "student_ref", "sha256", name="uq_os_pack_files_sha"),
)

pack_items = Table(
    "os_pack_items", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("programme_ref", Text, nullable=False),
    Column("item_key", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("label", Text),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("kind IN ('added', 'ticked')", name="ck_os_pack_items_kind"),
    UniqueConstraint("tenant_id", "student_ref", "programme_ref", "item_key", "kind", name="uq_os_pack_items"),
)

# --- Slice 6b: the visa file (spec 2026-10-22 S6b §3, os_0011) ------------------------------------------------

visa_choices = Table(
    "os_visa_choices", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("programme_ref", Text),  # the programme the visa file is for; None until chosen
    Column("reduction", Numeric(14, 2), nullable=False, server_default="0"),  # other proof of funds, e.g. a scholarship
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "student_ref", name="uq_os_visa_choices"),
    CheckConstraint("reduction >= 0", name="ck_os_visa_choices_reduction"),
)

# --- Slice 7: replanning (spec 2026-10-23 S7 §3, os_0012) ---------------------------------------------------

PROPOSAL_STATUSES = ("applied", "pending", "accepted", "declined", "expired", "refused")
OVERRIDE_OPS = ("skip", "cancel", "cancel_programme", "add", "reprioritise")
# Slice 8 (spec S8-D10, S8-D12)
INTAKE_STATUSES = ("pending", "planned", "revised", "replaced", "refused")
INTAKE_REFUSALS = ("not_authorized", "invalid_export", "route_not_supported", "unknown_programme",
                   "self_serve_plan_open", "plan_closed")
COUNSELLOR_DELIVERY = ("pending", "sent", "refused")
ESCALATION_REASONS = ("not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other")


def _plan_fk() -> Column:
    return Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE"), nullable=False)


proposals = Table(
    "os_proposals", md,
    _id(), _tenant(), _plan_fk(),
    Column("event_ids", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source", Text, nullable=False),
    Column("ops", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("refused", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("big", Boolean, nullable=False, server_default=text("false")),
    Column("status", Text, nullable=False),
    Column("revision", Integer),
    Column("based_on", Text),  # the plan's contract SHA-256 when proposed (final review I4)
    Column("base_revision", Integer),  # and its revision: accepting after either changed is refused
    Column("expires_at", DateTime(timezone=True)),
    _created(),
    Column("answered_at", DateTime(timezone=True)),
    _in("source", ("rules", "supervisor"), "ck_os_proposals_source"),
    _in("status", PROPOSAL_STATUSES, "ck_os_proposals_status"),
    Index("ix_os_proposals_plan", "plan_id"),
)

plan_overrides = Table(
    "os_plan_overrides", md,
    _id(), _tenant(), _plan_fk(),
    Column("proposal_id", BigInteger, ForeignKey("os.os_proposals.id", ondelete="CASCADE"), nullable=False),
    Column("op", Text, nullable=False),
    Column("target", Text, nullable=False),  # an instance key, a template key, or a programme ref
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    _created(),
    _in("op", OVERRIDE_OPS, "ck_os_plan_overrides_op"),
    Index("ix_os_plan_overrides_plan", "plan_id"),
)

support_cases = Table(
    "os_support_cases", md,
    _id(), _tenant(), _plan_fk(),
    Column("student_ref", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("event_ids", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("proposal_id", BigInteger, ForeignKey("os.os_proposals.id", ondelete="SET NULL")),
    Column("status", Text, nullable=False, server_default="open"),
    Column("resolution", Text),
    _created(),
    Column("resolved_at", DateTime(timezone=True)),
    Column("counsellor_status", Text),  # Slice 8 (os_0013): delivery of a route problem to the Counsellor, S8-D12
    Column("counsellor_reason", Text),
    _in("status", ("open", "resolved"), "ck_os_support_cases_status"),
    _in("counsellor_status", COUNSELLOR_DELIVERY, "ck_os_support_cases_delivery"),
    _in("counsellor_reason", ESCALATION_REASONS, "ck_os_support_cases_counsellor_reason"),
)

# --- Slice 8: the Counsellor connection (os_0013) ------------------------------------------------------------------

counsellor_intake = Table(
    "os_counsellor_intake", md,
    _id(), _tenant(),
    Column("decision_id", Text, nullable=False),
    Column("student_ref", Text, nullable=False),
    Column("journey_id", Text, nullable=False),
    Column("export", JSONB, nullable=False),  # the decision record export as submitted (S8-D5)
    Column("export_sha256", Text, nullable=False),
    Column("chosen_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("reason", Text),  # a refusal (S8-D10)
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="SET NULL")),
    Column("counsellor_status", Text),  # a refusal sent to the Counsellor by journey (spec §2.5)
    _created(),
    Column("processed_at", DateTime(timezone=True)),
    UniqueConstraint("tenant_id", "decision_id", name="uq_os_counsellor_intake_decision"),
    _in("status", INTAKE_STATUSES, "ck_os_counsellor_intake_status"),
    _in("reason", INTAKE_REFUSALS, "ck_os_counsellor_intake_reason"),
    _in("counsellor_status", COUNSELLOR_DELIVERY, "ck_os_counsellor_intake_delivery"),
    Index("ix_os_counsellor_intake_pending", "tenant_id", "status", "student_ref", "chosen_at"),
)

counsellor_sweep = Table(
    "os_counsellor_sweep", md,
    Column("tenant_id", Text, primary_key=True),
    Column("mark", JSONB, nullable=False),  # the glue's sweep position: the last chosen_at and decision ID seen
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# --- Slice 9a: rehearsal mode (os_0014) ----------------------------------------------------------------------------

rehearsal_clock = Table(
    "os_rehearsal_clock", md,
    Column("tenant_id", Text, primary_key=True),
    # how far the rehearsal clock is moved; negative only when `start` set a day before the real date (os_0017)
    Column("offset_seconds", BigInteger, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# --- Slice 9a: pilot consent (os_0015) -----------------------------------------------------------------------------

consents = Table(
    "os_consents", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("terms_version", Integer, nullable=False),  # the pilot.vN.md the student agreed to
    Column("agreed_at", DateTime(timezone=True), nullable=False),  # from the shared clock
    UniqueConstraint("tenant_id", "student_ref", "terms_version", name="uq_os_consents_student_version"),
)
