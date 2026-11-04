"""Plan view v1 (P1 spec §3.9, master §9.1): what PAI OS returns for one student's plan, for the Counsellor to show.
Codes and IDs, not sentences; `title` is playbook route data. Frozen: a change is a new version file."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.os.contracts.decision_record import iso_country
from app.os.contracts.route_contract import IntakeRef
from app.os.contracts.route_contract_v2 import Level

Code = Annotated[str, Field(pattern=r"^[a-z_]+$")]


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class PlanRoute(_View):
    route_key: str
    origin_country: str
    destination_country: str
    level: Level
    target_intake: IntakeRef

    @field_validator("origin_country", "destination_country", mode="before")
    @classmethod
    def _country(cls, value: object) -> object:
        return iso_country(value)


class ConsentState(_View):
    student: Literal["given", "missing"]
    guardian: Literal["not_needed", "given", "missing"]


class StepNeed(_View):
    kind: Literal["fact", "document"]
    ref: str = Field(pattern=r"^[a-z_][a-z0-9_.]*$")
    evidence: Literal["stated", "shown", "confirmed"]


class PlanStep(_View):
    task_id: int
    instance_key: str
    template_key: str
    title: str  # playbook route data
    owner: Literal["student", "pai"]
    status: Literal["pending", "ready", "running", "waiting_student", "waiting_review", "done", "failed", "skipped",
                    "cancelled", "blocked"]  # the kernel states (app/os/kernel/states.py)
    blocked_reason: Code | None
    inbox_kind: Literal["provide", "approve", "act", "choose"] | None
    programme_ref: str | None
    due_at: AwareDatetime | None
    due_tz: str | None
    depends_on: list[str]  # instance keys
    provisional: bool
    estimated: bool
    needs: list[StepNeed]


class PlanRequest(_View):
    request_id: int
    need: StepNeed
    status: Literal["open", "answered"]
    due_at: AwareDatetime | None
    due_tz: str | None


class DocumentNeed(_View):
    doc_type: Code
    status: Literal["missing", "uploaded", "confirmed"]


class PlanChange(_View):
    revision: int = Field(ge=1)
    at: AwareDatetime
    cause: Code
    kind: Literal["added", "removed", "moved", "done", "revised"]
    instance_key: str | None


class PlanViewV1(_View):
    schema_: Literal["pai.plan_view.v1"] = Field("pai.plan_view.v1", alias="schema")
    student_ref: str = Field(min_length=1)
    state: Literal["empty", "active", "needs_student", "paused", "stopped", "finished"]
    stop_reason: Code | None
    plan_id: int | None
    decision_version: int | None = Field(ge=1)
    revision: int | None = Field(ge=1)
    route: PlanRoute | None
    pages: list[Code]
    consent: ConsentState | None
    steps: list[PlanStep]
    requests: list[PlanRequest]
    documents_needed: list[DocumentNeed]
    changes: list[PlanChange]
    proposals_waiting: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_state(self) -> "PlanViewV1":
        if (self.state == "empty") != (self.plan_id is None):
            raise ValueError("state is empty exactly when plan_id is None")
        if self.state != "empty" and (self.route is None or self.revision is None):
            raise ValueError("a plan needs a route and a revision")
        if self.stop_reason is not None and self.state != "stopped":
            raise ValueError("stop_reason only when state is stopped")
        return self
