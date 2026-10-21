"""API response and request bodies."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    id: int
    instance_key: str
    title: str
    kind: str
    inbox_kind: str | None
    programme_ref: str | None
    state: str
    blocked_reason: str | None
    due_at: datetime | None
    due_tz: str
    provisional: bool
    estimated: bool
    slack_days: int | None
    critical: bool
    citations: list[dict]


class PlanOut(BaseModel):
    plan_id: int
    revision: int
    status: str
    tasks: list[TaskOut]


class InboxOut(BaseModel):
    items: list[TaskOut]


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict = {}


class CompleteOut(BaseModel):
    completed: bool


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any
    quote: str
    url: str
    status: Literal["confirmed", "unconfirmed", "stale"]
    conflict_note: str | None = None


class SupplyIn(ConfirmIn):
    """A fact keyed by (scope, ref, field, intake_year): adds one that was never seeded (review I2)."""
    scope: Literal["route", "programme"]
    ref: str
    field: str
    intake_year: int


class ConfirmOut(BaseModel):
    revised_plans: list[int]


class FactOut(BaseModel):
    """A fact as a student sees it: value, status, source link, quote, check date, conflict note."""
    field: str
    value: Any
    status: str
    source_url: str | None
    quote: str | None
    checked_at: datetime
    conflict_note: str | None


class AdminFactOut(FactOut):
    fact_id: int
    source: str
    evidence: list[dict] | None
    research_run_id: int | None


class ReadingOut(BaseModel):
    reading: str
    agent: str
    agent_version: int
    model: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: float
    error: str | None
    at: datetime


class ResearchRunOut(BaseModel):
    id: int
    programme_ref: str
    intake_year: int
    workflow_id: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    pages: int
    confirmed: int
    unconfirmed: int
    cost_usd: float
    readings: list[ReadingOut] = []


class ResearchRunsOut(BaseModel):
    runs: list[ResearchRunOut]


class ResearchStartOut(BaseModel):
    workflow_id: str
    enqueued: bool  # False: today's run for this programme already exists


class OpenFact(BaseModel):
    task_id: int
    plan_id: int
    instance_key: str
    state: str
    scope: str
    ref: str
    field: str
    intake_year: int | None = None
    fact: AdminFactOut | None = None  # None: the fact is missing (fact_missing)
    last_research_run: ResearchRunOut | None = None


class OpenFactsOut(BaseModel):
    items: list[OpenFact]


class ProgrammeOut(BaseModel):
    ref: str
    name: str
    university: str | None
    intake_year: int
    facts: list[FactOut]


class ProgrammesOut(BaseModel):
    programmes: list[ProgrammeOut]


class UpgradeOut(BaseModel):
    revision: int


# --- Slice 3: documents (spec §4) ------------------------------------------------------------------------------


class DocumentFieldOut(BaseModel):
    field: str
    value_read: Any
    check: Literal["ok", "check_failed", "missing"]
    reasons: list[str]
    value_confirmed: Any


class FindingItemOut(BaseModel):
    document_id: int
    value: str


class FindingOut(BaseModel):
    id: int
    kind: Literal["variant", "mismatch"]
    field: str
    items: list[FindingItemOut]
    status: Literal["open", "resolved"]
    resolution: Any = None


class DocumentOut(BaseModel):
    """A document as its student (or an admin) sees it. Never the file's bytes (S3-D10)."""

    id: int
    doc_type: str
    filename: str
    status: str
    detected_type: str | None
    pages: int | None
    error: str | None
    created_at: datetime
    read_at: datetime | None
    confirmed_at: datetime | None
    fields: list[DocumentFieldOut]
    findings: list[FindingOut]  # the open findings that name this document


class DocumentsOut(BaseModel):
    documents: list[DocumentOut]
    findings: list[FindingOut]  # all the student's open findings


class ConfirmDocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Any]


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any


class ProfileValueOut(BaseModel):
    key: str
    value: Any
    source_document_id: int | None
    confirmed_at: datetime


class ProfileOut(BaseModel):
    values: list[ProfileValueOut]
