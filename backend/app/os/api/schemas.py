"""API response and request bodies."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice


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


class NoteOut(BaseModel):
    id: int
    programme_ref: str
    verdict: str
    payload: dict
    created_at: datetime


class InboxOut(BaseModel):
    items: list[TaskOut]
    notes: list[NoteOut] = []  # Slice 4: eligibility changes


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
    requested_programmes: list["RequestedProgrammeOut"] = []  # Slice 4 Q1: student requests research found nothing for


class ProgrammeOut(BaseModel):
    ref: str
    plan_id: int | None = None  # Slice 4: the plan it is in, for swap and remove
    rank: int | None = None
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


class DocTypeOut(BaseModel):
    key: str
    label: str


class DocumentsOut(BaseModel):
    documents: list[DocumentOut]
    findings: list[FindingOut]  # all the student's open findings
    doc_types: list[DocTypeOut]  # the configured types, for the upload choice (labels come from the YAML)


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


# --- Slice 4: self-serve start and eligibility (spec §4) -------------------------------------------------------


class RouteOut(BaseModel):
    key: str
    version: int
    origin: str
    destination: str
    level: str


class RoutesOut(BaseModel):
    routes: list[RouteOut]


class FactRefOut(BaseModel):
    field: str
    url: str
    status: str


class LineOut(BaseModel):
    check: str
    status: str
    have: Any = None
    need: Any = None
    provisional: bool = False
    needs: list[str] = []
    reason: str | None = None
    sources: list[FactRefOut] = []


class CardOut(BaseModel):
    programme_ref: str
    verdict: str
    lines: list[LineOut]


class RouteProgrammeOut(BaseModel):
    ref: str
    university: str
    name: str
    research_state: Literal["researched", "being_researched"]
    requested_by_student: bool
    confirmed_facts: int
    card: CardOut | None  # None while being researched, or on a route without eligibility rules


class RouteProgrammesOut(BaseModel):
    route: str
    intake_year: int
    programmes: list[RouteProgrammeOut]


class SuggestionOut(BaseModel):
    programme_ref: str
    university: str
    name: str
    confirmed_facts: int


class EligibilityOut(BaseModel):
    card: CardOut | None
    suggestions: list[SuggestionOut]


class SelfStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str
    intake: IntakeRef
    choices: list[ProgrammeChoice]


class SwapIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    out: str
    in_: str = Field(alias="in")


class ChoiceOut(BaseModel):
    programme_ref: str
    rank: int


class SelfPlanOut(PlanOut):
    programmes: list[ChoiceOut]


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str
    intake_year: int = Field(ge=2025, le=2100)
    university: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)


class RequestOut(BaseModel):
    programme_ref: str
    created: bool


class RequestedProgrammeOut(BaseModel):
    ref: str
    route_key: str
    university: str
    name: str
    start_urls: list[str]


OpenFactsOut.model_rebuild()  # it names RequestedProgrammeOut, defined below it


# --- Slice 5: statements (spec §4) -----------------------------------------------------------------------------

class InterviewItemOut(BaseModel):
    id: str
    prompt: str
    hint: str
    required: bool
    answer: str
    follow_up: bool  # asked by the Critic; open follow-ups come first


class InterviewOut(BaseModel):
    route: str
    questions: list[InterviewItemOut]
    missing: list[str]  # required questions (and open follow-ups) not answered yet


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(max_length=4000)


class AnswerOut(BaseModel):
    saved: bool
    drafting: int  # artifacts drafted again because the last open follow-up was answered


class StatementVersionOut(BaseModel):
    number: int
    text: str
    author: Literal["writer", "student"]
    words: int
    critic: dict | None
    flags: list[str]  # phrases we could not find in the student's answers or profile
    limit_words: int | None
    created_at: datetime


class ApprovalOut(BaseModel):
    version: int
    sha256: str
    approved_at: datetime


class StatementOut(BaseModel):
    id: int
    kind: Literal["sop", "cv"]
    programme_ref: str | None
    status: str
    version: StatementVersionOut | None  # the latest
    approval: ApprovalOut | None


class StatementsOut(BaseModel):
    statements: list[StatementOut]


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    programme_ref: str | None = None


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class ApproveOut(ApprovalOut):
    completed_tasks: list[int]


class PastedRulesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str | None = Field(None, max_length=4000)
    limit_words: int | None = Field(None, gt=0, le=100000)
    limit_chars: int | None = Field(None, gt=0, le=100000)
