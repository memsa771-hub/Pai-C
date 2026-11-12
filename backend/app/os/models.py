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
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
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
FACT_STATUSES = ("confirmed", "unconfirmed", "stale", "verified")  # P2-D6: `verified` is confirmed + two reviews
READ_METHODS = ("fetch", "render", "ocr", "human", "model")  # P2-D11/D18: how the fact's source text was read
REVISION_ACTIONS = ("insert", "change", "status", "undo")
REVIEWER_ROLES = ("checker", "approver", "admin")  # P2-D15
REVIEWER_KINDS = ("person", "ai")  # owner ruling 2026-11-07: an AI check may count as a check; a person can replace it
REVIEW_ITEM_KINDS = ("verify", "report", "change", "suspect_domain", "collect", "conflict", "import_dispute")
REVIEW_STEPS = ("check", "approve", "collect")
REVIEW_OUTCOMES = ("correct", "wrong", "unclear", "approve", "reject", "collected")
REVISION_CAUSES = ("seed", "manual", "research", "import", "review", "monitor", "report", "rollover")
FACT_REVISION_CAUSES = (*REVISION_CAUSES, "backfill")  # P2-T8: the intake_term backfill (fact revisions only)
FACT_SCOPES = ("route", "programme", "registry")  # P2-T2: `registry` = a fact about a registry entity
REGISTRY_KINDS = ("regulator", "board", "admission_body", "admission_system", "entry_test", "institution", "campus",
                  "seat_category", "calendar", "official_list")  # P2 spec §4.1: generic concepts; instances are data
REGISTRY_STATUSES = ("active", "closed", "merged", "renamed")
REGISTRY_LINK_RELS = ("uses_test", "has_category", "admits")
REGISTRY_LINK_TO = ("registry", "programme")
REGISTRY_REVISION_KINDS = ("entity", "link", "programme")  # what a registry revision is about (subject says which)

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
    # P2-T1 (os_0025): the intake term, the body that owns the value, its class, how it was read, its language.
    Column("intake_term", Text, nullable=False, server_default=""),
    Column("owner_ref", Text, nullable=False, server_default=""),
    Column("fact_class", Text),
    Column("read_method", Text),
    Column("language", Text),
    UniqueConstraint("tenant_id", "scope", "ref", "field", "intake_term", "intake_year", "owner_ref",
                     name="uq_os_knowledge_facts"),
    _in("scope", FACT_SCOPES, "ck_os_knowledge_facts_scope"),
    _in("status", FACT_STATUSES, "ck_os_knowledge_facts_status"),
    _in("source", FACT_SOURCES, "ck_os_knowledge_facts_source"),
    _in("read_method", READ_METHODS, "ck_os_knowledge_facts_read_method"),
    CheckConstraint("language ~ '^[a-z]{2,3}$'", name="ck_os_knowledge_facts_language"),
)

# P2-D9: append-only history of every fact insert, change, status change and undo, with its cause.
fact_revisions = Table(
    "os_fact_revisions", md,
    _id(), _tenant(),
    Column("fact_id", BigInteger, ForeignKey("os.os_knowledge_facts.id", ondelete="RESTRICT"), nullable=False),
    Column("action", Text, nullable=False),
    Column("before", JSONB),
    Column("after", JSONB, nullable=False),
    Column("cause", Text, nullable=False),
    Column("cause_ref", Text),
    Column("actor", Text),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _in("action", REVISION_ACTIONS, "ck_os_fact_revisions_action"),
    _in("cause", FACT_REVISION_CAUSES, "ck_os_fact_revisions_cause"),
    Index("ix_os_fact_revisions_fact", "tenant_id", "fact_id", "id"),
    Index("ix_os_fact_revisions_cause", "tenant_id", "cause", "cause_ref"),
)

# P2-T2 (P2 spec §4.1, P2-D2): the registry of institutions, bodies, systems, tests, categories, calendars and the
# official lists they came from. Standing facts are columns (P2-D4); cycle-bound facts are Knowledge facts of scope
# `registry`. Rows are never deleted: a closed or merged entity keeps its row (R-60).
registry = Table(
    "os_registry", md,
    _id(), _tenant(),
    Column("entity_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("parent_id", Text),
    Column("region", Text),
    Column("institution_type", Text),
    Column("name", Text, nullable=False),
    Column("aliases", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("official_domains", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("status", Text, nullable=False, server_default="active"),
    Column("successor_id", Text),
    Column("list_ids", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source_url", Text, nullable=False),
    Column("quote", Text, nullable=False, server_default=""),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("attrs", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _created(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "entity_id", name="uq_os_registry_entity"),
    _in("kind", REGISTRY_KINDS, "ck_os_registry_kind"),
    _in("status", REGISTRY_STATUSES, "ck_os_registry_status"),
    Index("ix_os_registry_kind_region", "tenant_id", "kind", "region"),
    Index("ix_os_registry_parent", "tenant_id", "parent_id"),
)

registry_revisions = Table(  # append only, like os_fact_revisions (P2-D9)
    "os_registry_revisions", md,
    _id(), _tenant(),
    Column("registry_id", BigInteger, ForeignKey("os.os_registry.id", ondelete="RESTRICT"), nullable=False),
    Column("kind", Text, nullable=False, server_default="entity"),  # entity | link | programme (what was changed)
    Column("subject", Text),  # link: 'rel:to_kind:to_id'; programme: its ref; entity: NULL
    Column("action", Text, nullable=False),
    Column("before", JSONB),
    Column("after", JSONB, nullable=False),
    Column("cause", Text, nullable=False),
    Column("cause_ref", Text),
    Column("actor", Text),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _in("kind", REGISTRY_REVISION_KINDS, "ck_os_registry_revisions_kind"),
    _in("action", REVISION_ACTIONS, "ck_os_registry_revisions_action"),
    _in("cause", REVISION_CAUSES, "ck_os_registry_revisions_cause"),
    Index("ix_os_registry_revisions_entity", "tenant_id", "registry_id", "id"),
)

registry_links = Table(  # an admission system's tests, seat categories and what it admits (P2 spec §4.1)
    "os_registry_links", md,
    _id(), _tenant(),
    Column("from_id", Text, nullable=False),
    Column("rel", Text, nullable=False),
    Column("to_kind", Text, nullable=False),
    Column("to_id", Text, nullable=False),
    _created(),
    UniqueConstraint("tenant_id", "from_id", "rel", "to_kind", "to_id", name="uq_os_registry_links"),
    _in("rel", REGISTRY_LINK_RELS, "ck_os_registry_links_rel"),
    _in("to_kind", REGISTRY_LINK_TO, "ck_os_registry_links_to_kind"),
    Index("ix_os_registry_links_to", "tenant_id", "to_kind", "to_id"),
)

# P2-T6 (os_0031): one row per spreadsheet import (P2 spec §4.6). Undo replays the revisions with cause_ref `import-<id>`.
imports = Table(
    "os_imports", md,
    _id(), _tenant(),
    Column("file_name", Text, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("decision_ref", Text),
    Column("batch_ref", Text, nullable=False, server_default=""),
    Column("actor", Text, nullable=False),
    Column("note_actor", Text),
    Column("status", Text, nullable=False, server_default="running"),
    Column("counts", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("programmes_created", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("report_path", Text),
    Column("report_csv", Text),
    Column("error", Text),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("undone_at", DateTime(timezone=True)),
    Column("undone_by", Text),
    _in("mode", ("owner_accepted", "reviewers"), "ck_os_imports_mode"),
    _in("status", ("running", "done", "failed", "undone"), "ck_os_imports_status"),
    CheckConstraint("mode <> 'owner_accepted' OR decision_ref IS NOT NULL", name="ck_os_imports_decision"),
    Index("uq_os_imports_live", "tenant_id", "sha256", unique=True,
          postgresql_where=text("status IN ('running', 'done', 'failed')")),
)

# P2-T5 (os_0026, P2 §4.5, P2-D15, P2-D16): reviewers, the review queue, every check, evidence files, attestations.
reviewers = Table(
    "os_reviewers", md,
    _id(), _tenant(),
    Column("ref", Text, nullable=False),  # the reviewer's id in checks and spreadsheets, e.g. a name or ai_check_1
    Column("display_name", Text, nullable=False),
    Column("identity", Text, nullable=False),  # the person or the model and prompt behind the ref; checks need two
    Column("role", Text, nullable=False),
    Column("kind", Text, nullable=False, server_default="person"),
    Column("token_hash", Text, nullable=False),  # sha256 of the personal token (the token is shown once)
    Column("active", Boolean, nullable=False, server_default=text("true")),
    _created(),
    Column("disabled_at", DateTime(timezone=True)),
    UniqueConstraint("tenant_id", "ref", name="uq_os_reviewers_ref"),
    UniqueConstraint("token_hash", name="uq_os_reviewers_token"),
    _in("role", REVIEWER_ROLES, "ck_os_reviewers_role"),
    _in("kind", REVIEWER_KINDS, "ck_os_reviewers_kind"),
)

review_items = Table(
    "os_review_items", md,
    _id(), _tenant(),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="open"),
    Column("resolution", Text),
    Column("fact_id", BigInteger, ForeignKey("os.os_knowledge_facts.id", ondelete="RESTRICT")),
    Column("subject", Text, nullable=False, server_default=""),  # what a fact-less item is about (a domain, a source)
    Column("field", Text),
    Column("intake_term", Text, nullable=False, server_default=""),
    Column("intake_year", Integer),
    Column("owner_ref", Text, nullable=False, server_default=""),
    Column("summary", Text, nullable=False, server_default=""),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("batch_ref", Text),
    Column("dedupe_key", Text, nullable=False),
    Column("join_count", Integer, nullable=False, server_default="0"),  # the same thing reported again joins the item
    Column("opened_by", Text, nullable=False, server_default="manual"),
    _created(),
    Column("closed_at", DateTime(timezone=True)),
    Column("closed_by", BigInteger, ForeignKey("os.os_reviewers.id", ondelete="RESTRICT")),
    _in("kind", REVIEW_ITEM_KINDS, "ck_os_review_items_kind"),
    _in("status", ("open", "closed"), "ck_os_review_items_status"),
    Index("uq_os_review_items_open", "tenant_id", "dedupe_key", unique=True, postgresql_where=text("status = 'open'")),
    Index("ix_os_review_items_list", "tenant_id", "status", "kind", "id"),
    Index("ix_os_review_items_batch", "tenant_id", "batch_ref"),
)

review_files = Table(
    "os_review_files", md,
    _id(), _tenant(),
    Column("item_id", BigInteger, ForeignKey("os.os_review_items.id", ondelete="RESTRICT"), nullable=False),
    Column("uploaded_by", BigInteger, ForeignKey("os.os_reviewers.id", ondelete="RESTRICT"), nullable=False),
    Column("filename", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("size", Integer, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("data", LargeBinary, nullable=False),
    _created(),
    Index("ix_os_review_files_item", "tenant_id", "item_id"),
)

fact_reviews = Table(
    "os_fact_reviews", md,
    _id(), _tenant(),
    Column("item_id", BigInteger, ForeignKey("os.os_review_items.id", ondelete="RESTRICT"), nullable=False),
    Column("fact_id", BigInteger, ForeignKey("os.os_knowledge_facts.id", ondelete="RESTRICT")),
    Column("reviewer_id", BigInteger, ForeignKey("os.os_reviewers.id", ondelete="RESTRICT"), nullable=False),
    Column("step", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("corrected_value", JSONB),
    Column("corrected_quote", Text),
    Column("note", Text),
    Column("evidence_file_id", BigInteger, ForeignKey("os.os_review_files.id", ondelete="RESTRICT")),
    Column("high_stakes", Boolean, nullable=False, server_default=text("true")),  # the need as of this review
    Column("fact_digest", Text),  # sha256 of the value, quote and URL the reviewer saw: a changed fact voids the item
    _created(),
    UniqueConstraint("item_id", "reviewer_id", name="uq_os_fact_reviews_reviewer"),
    _in("step", REVIEW_STEPS, "ck_os_fact_reviews_step"),
    _in("outcome", REVIEW_OUTCOMES, "ck_os_fact_reviews_outcome"),
    CheckConstraint("(step = 'check' AND outcome IN ('correct', 'wrong', 'unclear')) OR "
                    "(step = 'approve' AND outcome IN ('approve', 'reject')) OR "
                    "(step = 'collect' AND outcome = 'collected')", name="ck_os_fact_reviews_step_outcome"),
    Index("ix_os_fact_reviews_item", "tenant_id", "item_id"),
)

review_attestations = Table(
    "os_review_attestations", md,
    _id(), _tenant(),
    Column("reviewer_id", BigInteger, ForeignKey("os.os_reviewers.id", ondelete="RESTRICT"), nullable=False),
    Column("batch_ref", Text, nullable=False),
    _created(),
    UniqueConstraint("tenant_id", "reviewer_id", "batch_ref", name="uq_os_review_attestations"),
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
    # P2-T2 (os_0027): the programme level of the registry (P2 spec §4.1). All NULL for programmes outside it.
    Column("institution_id", Text),
    Column("campus_id", Text),
    Column("level", Text),
    Column("field", Text),
    Column("family", Text),
    Column("region", Text),
    UniqueConstraint("tenant_id", "ref", name="uq_os_programmes_ref"),
    Index("ix_os_programmes_institution", "tenant_id", "institution_id"),
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
    Column("read_method", Text, nullable=False, server_default="fetch"),  # P2-T4 (os_0030): how the text was read
    Column("language", Text),  # P2-T4: set only for a script the data maps to a language
    UniqueConstraint("tenant_id", "url", name="uq_os_pages_url"),
    _in("read_method", ("fetch", "render", "ocr", "human"), "ck_os_pages_read_method"),
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
    Column("file_ref", Text),  # P1-T7: the Counsellor file that holds the bytes (os_0022); no os_document_files row
    _in("status", DOCUMENT_STATUSES, "ck_os_documents_status"),
    # one live copy of a file per student; a deleted one may be uploaded again
    Index("uq_os_documents_sha", "tenant_id", "student_ref", "sha256", unique=True,
          postgresql_where=text("status <> 'deleted'")),
    Index("ix_os_documents_student", "tenant_id", "student_ref"),
    Index("uq_os_documents_file_ref", "tenant_id", "file_ref", unique=True,
          postgresql_where=text("file_ref IS NOT NULL AND status <> 'deleted'")),
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

PROPOSAL_STATUSES = ("applied", "pending", "accepted", "declined", "expired", "refused", "requested")  # P1-T6: requested
PROPOSAL_SOURCES = ("rules", "supervisor", "student")  # student: the builder's own swap and remove (P1-T6)
REQUEST_OUTCOMES = ("written", "duplicate", "stale", "refused")
OVERRIDE_OPS = ("skip", "cancel", "cancel_programme", "add", "reprioritise")
# Slice 8 (spec S8-D10, S8-D12)
INTAKE_STATUSES = ("pending", "planned", "revised", "replaced", "refused", "stale", "withdrawn", "unsupported",
                   "held", "paused")
INTAKE_REFUSALS = ("not_authorized", "invalid_export", "route_not_supported", "unknown_programme",
                   "self_serve_plan_open", "plan_closed")
INTAKE_REASONS = (*INTAKE_REFUSALS, "consent_missing")  # refusals, and why a decision is held or its plan paused (P1-D11)
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
    Column("base_decision_version", Integer),  # P1-T6 (os_0021): the decision version it was made against; NULL before
    Column("requested_version", Integer),  # the version n+1 the Counsellor wrote for the request
    Column("request_outcome", Text),  # the Counsellor's answer: written | duplicate | stale | refused
    _in("source", PROPOSAL_SOURCES, "ck_os_proposals_source"),
    _in("status", PROPOSAL_STATUSES, "ck_os_proposals_status"),
    _in("request_outcome", REQUEST_OUTCOMES, "ck_os_proposals_request_outcome"),  # NULL passes a CHECK: no answer yet
    Index("ix_os_proposals_plan", "plan_id"),
)

# P1-T6 (os_0021): the student's agreement to adopt an open self-serve plan as the Counsellor's plan (R-08, D-x6)
plan_adoptions = Table(
    "os_plan_adoptions", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    _plan_fk(),
    Column("contract_sha256", Text, nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("adopted_at", DateTime(timezone=True)),
    UniqueConstraint("tenant_id", "plan_id", name="uq_os_plan_adoptions_plan"),
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
    Column("decision_version", Integer),  # P1-T2 (os_0018): null for v1 rows
    Column("decision_status", Text),
    UniqueConstraint("tenant_id", "decision_id", name="uq_os_counsellor_intake_decision"),
    _in("status", INTAKE_STATUSES, "ck_os_counsellor_intake_status"),
    _in("reason", INTAKE_REASONS, "ck_os_counsellor_intake_reason"),
    _in("counsellor_status", COUNSELLOR_DELIVERY, "ck_os_counsellor_intake_delivery"),
    Index("ix_os_counsellor_intake_pending", "tenant_id", "status", "student_ref", "chosen_at"),
    Index("ix_os_counsellor_intake_version", "tenant_id", "student_ref", "decision_version"),
)

# --- P1-T4: Vault events from the Counsellor (os_0020) ---------------------------------------------------------------

vault_events = Table(
    "os_vault_events", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("vault_version", Integer, nullable=False),
    Column("keys", JSONB, nullable=False),  # StudentFacts keys that changed; never values
    Column("event", JSONB, nullable=False),  # the VaultEventV1 as submitted
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    _created(),
    UniqueConstraint("tenant_id", "student_ref", "vault_version", name="uq_os_vault_events_version"),
)

# --- P1-T8: one request per student and fact (os_0023) ---------------------------------------------------------------

student_requests = Table(
    "os_student_requests", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="CASCADE"), nullable=False),
    Column("task_id", BigInteger, ForeignKey("os.os_tasks.id", ondelete="SET NULL")),
    Column("kind", Text, nullable=False),  # provide | which_is_right
    Column("need_kind", Text, nullable=False),  # fact | document
    Column("need_ref", Text, nullable=False),  # a StudentFacts key or a document type: never a value
    Column("evidence", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="open"),
    Column("closed_cause", Text),
    _created(),
    Column("closed_at", DateTime(timezone=True)),
    _in("kind", ("provide", "which_is_right"), "ck_os_student_requests_kind"),
    _in("need_kind", ("fact", "document"), "ck_os_student_requests_need_kind"),
    _in("evidence", ("stated", "shown", "confirmed"), "ck_os_student_requests_evidence"),
    _in("status", ("open", "answered", "cancelled"), "ck_os_student_requests_status"),
    Index("ix_os_student_requests_plan", "tenant_id", "plan_id"),
    # R-19, master 9.3 rule 7: one open request per student and fact
    Index("uq_os_student_requests_open", "tenant_id", "student_ref", "need_kind", "need_ref", unique=True,
          postgresql_where=text("status = 'open'")),
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

# --- P1-T10: the consistency job's cases and runs (os_0024) ----------------------------------------------------------

consistency_cases = Table(
    "os_consistency_cases", md,
    _id(), _tenant(),
    Column("student_ref", Text, nullable=False),
    Column("rule", SmallInteger, nullable=False),  # master 9.3 rule 1-8
    Column("plan_id", BigInteger, ForeignKey("os.os_plans.id", ondelete="SET NULL")),
    Column("codes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),  # finding codes: never a value
    Column("status", Text, nullable=False, server_default="open"),
    Column("resolution", Text),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("resolved_at", DateTime(timezone=True)),
    CheckConstraint("rule BETWEEN 1 AND 8", name="ck_os_consistency_cases_rule"),
    _in("status", ("open", "resolved"), "ck_os_consistency_cases_status"),
    Index("uq_os_consistency_cases_open", "tenant_id", "student_ref", "rule", text("coalesce(plan_id, 0)"), unique=True,
          postgresql_where=text("status = 'open'")),
)

consistency_runs = Table(
    "os_consistency_runs", md,
    _id(), _tenant(),
    Column("run_date", Date, nullable=False),
    Column("mode", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("counts", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    UniqueConstraint("tenant_id", "run_date", name="uq_os_consistency_runs_date"),
)

# --- P2-T3: official-source allow-lists, page snapshots and original files (os_0028) ---------------------------------

SOURCE_TIERS = ("regulator", "board", "admission_body", "institution")
SOURCE_STATES = ("active", "suspect")
SNAPSHOT_READ_METHODS = ("fetch", "render", "ocr", "human")

# P2-D10: the reviewed allow-list (loaded from YAML) and each domain's runtime state. A row with `region`, `family` and
# `route_key` all '' is not an allow-list entry: it records that a domain outside the lists (for example a route
# profile's) was flagged suspect.
source_domains = Table(
    "os_source_domains", md,
    _id(), _tenant(),
    Column("domain", Text, nullable=False),
    Column("region", Text, nullable=False, server_default=""),
    Column("family", Text, nullable=False, server_default=""),
    Column("route_key", Text, nullable=False, server_default=""),
    Column("body_ref", Text, nullable=False, server_default=""),  # registry id of the body (T2); '' = not named
    Column("tier", Text),
    Column("list_ref", Text, nullable=False, server_default=""),  # the official list or page that names the domain
    Column("reviewed_by", Text, nullable=False, server_default=""),
    Column("state", Text, nullable=False, server_default="active"),
    Column("state_reason", Text),
    Column("state_since", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "domain", "region", "family", "route_key", name="uq_os_source_domains_entry"),
    CheckConstraint("tier IS NULL OR tier IN ('regulator', 'board', 'admission_body', 'institution')",
                    name="ck_os_source_domains_tier"),
    _in("state", SOURCE_STATES, "ck_os_source_domains_state"),
    Index("ix_os_source_domains_domain", "tenant_id", "domain"),
)

# P2-D11: what was read, as text (the review queue shows it; monitoring compares it). `flagged` is the integrity
# failure code of the read, NULL for a clean page; only clean snapshots are used as "the last snapshot".
page_snapshots = Table(
    "os_page_snapshots", md,
    _id(), _tenant(),
    Column("url", Text, nullable=False),
    Column("sha256", Text, nullable=False),  # of the text (normalised whitespace)
    Column("text", Text, nullable=False),
    Column("content_type", Text, nullable=False, server_default=""),
    Column("read_method", Text, nullable=False, server_default="fetch"),
    Column("language", Text),
    Column("links_total", Integer, nullable=False, server_default="0"),
    Column("links_off_list", Integer, nullable=False, server_default="0"),
    Column("flagged", Text),
    Column("original_too_large", Boolean, nullable=False, server_default=text("false")),  # PDF or image over the cap (review M5)
    Column("fetched_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "url", "sha256", name="uq_os_page_snapshots_url_hash"),
    _in("read_method", SNAPSHOT_READ_METHODS, "ck_os_page_snapshots_read_method"),
    CheckConstraint("language IS NULL OR language ~ '^[a-z]{2,4}$'", name="ck_os_page_snapshots_language"),
    Index("ix_os_page_snapshots_url", "tenant_id", "url", "fetched_at"),
)

source_files = Table(
    "os_source_files", md,
    _id(), _tenant(),
    Column("snapshot_id", BigInteger, ForeignKey("os.os_page_snapshots.id", ondelete="RESTRICT"), nullable=False),
    Column("sha256", Text, nullable=False),  # of the bytes
    Column("content_type", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("content", LargeBinary, nullable=False),
    _created(),
    UniqueConstraint("tenant_id", "snapshot_id", name="uq_os_source_files_snapshot"),
)

# --- P2-T4: sources that could not be read, waiting for a human to collect the value (os_0030) -----------------------

NOT_READABLE_STATES = ("open", "collected", "readable")

# R-72: `field = ''` is the source itself; one more row per field the source should have answered. T5's `collect`
# review item reads the open rows; a later successful read marks them `readable`.
not_readable = Table(
    "os_not_readable", md,
    _id(), _tenant(),
    Column("url", Text, nullable=False),
    Column("reason", Text, nullable=False),  # not_readable:render | not_readable:ocr | http_401 | unreadable_pdf ...
    Column("programme_ref", Text, nullable=False, server_default=""),
    Column("field", Text, nullable=False, server_default=""),
    Column("intake_year", Integer, nullable=False, server_default="0"),
    Column("snapshot_id", BigInteger),
    Column("state", Text, nullable=False, server_default="open"),
    Column("first_seen", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "url", "programme_ref", "field", "intake_year", name="uq_os_not_readable"),
    _in("state", NOT_READABLE_STATES, "ck_os_not_readable_state"),
)

# P2-T8 (os_0029): intakes as rows (P2-D23) and the keys a new intake expects (§4.8).
INTAKE_STATES = ("planned", "open", "current", "closed")

intakes = Table(
    "os_intakes", md,
    _id(), _tenant(),
    Column("region", Text, nullable=False),
    Column("family", Text, nullable=False),
    Column("term", Text, nullable=False),
    Column("year", Integer, nullable=False),
    Column("state", Text, nullable=False, server_default="planned"),
    Column("gate_passed_at", DateTime(timezone=True)),
    Column("opened_from_id", BigInteger, ForeignKey("os.os_intakes.id", ondelete="SET NULL")),
    _created(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "region", "family", "term", "year", name="uq_os_intakes_key"),
    _in("state", INTAKE_STATES, "ck_os_intakes_state"),
    CheckConstraint("term ~ '^[a-z_]+$'", name="ck_os_intakes_term"),
    CheckConstraint("state <> 'current' OR gate_passed_at IS NOT NULL", name="ck_os_intakes_current_gate"),
    Index("ix_os_intakes_term_year", "tenant_id", "term", "year"),
)

fact_slots = Table(
    "os_fact_slots", md,
    _id(), _tenant(),
    Column("intake_id", BigInteger, ForeignKey("os.os_intakes.id", ondelete="CASCADE"), nullable=False),
    Column("scope", Text, nullable=False),
    Column("ref", Text, nullable=False),
    Column("field", Text, nullable=False),
    Column("owner_ref", Text, nullable=False, server_default=""),
    Column("fact_class", Text),
    _created(),
    UniqueConstraint("tenant_id", "intake_id", "scope", "ref", "field", "owner_ref", name="uq_os_fact_slots_key"),
)
