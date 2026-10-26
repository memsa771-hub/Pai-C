"""PlanSummary v1 (Slice 8 spec §2.4, S8-D13): what the Counsellor may show of a PAI OS plan. Built on every read,
never stored. No document values, answers, statement text, admin notes or Supervisor reasons. Frozen."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.os.contracts.route_contract import IntakeRef

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class SummaryRoute(BaseModel):
    model_config = _FROZEN

    origin_country: str
    destination_country: str
    level: Literal["foundation", "bachelor", "master", "phd"]
    target_intake: IntakeRef


class Deadline(BaseModel):
    model_config = _FROZEN

    title: str  # the playbook's step name
    template_key: str
    programme_ref: str | None
    due_at: AwareDatetime
    due_tz: str  # the deadline's own time zone (invariant 13)


class WaitingItem(BaseModel):
    model_config = _FROZEN

    title: str
    template_key: str
    programme_ref: str | None
    due_at: AwareDatetime | None  # some student steps have no date
    due_tz: str | None


class BlockedItem(BaseModel):
    model_config = _FROZEN

    title: str
    template_key: str
    reason: str = Field(pattern=r"^[a-z_]+$")  # a reason code, never free text


class PlanSummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.plan_summary.v1"] = Field("pai.plan_summary.v1", alias="schema")
    student_ref: str
    plan_id: int
    route: SummaryRoute
    built_at: AwareDatetime
    state: Literal["finished", "paused", "needs_student", "on_track"]
    next_deadlines: list[Deadline] = Field(max_length=3)
    waiting_on_student: list[WaitingItem]
    blocked: list[BlockedItem]
    support_case_open: bool
