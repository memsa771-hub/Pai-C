"""OS event v1 (master §9.1, P1 spec §3.9): a small notice PAI OS sends the Counsellor when a plan changes. IDs and
codes only; the Counsellor reads the plan view for detail. Frozen: a change is a new version file."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class OsEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.os_event.v1"] = Field("pai.os_event.v1", alias="schema")
    key: str = Field(min_length=1)  # the outbox key
    student_ref: str = Field(min_length=1)
    plan_id: int | None
    decision_version: int | None = Field(ge=1)
    kind: Literal["plan_created", "plan_revised", "plan_paused", "plan_stopped", "plan_finished", "step_done",
                  "student_needed", "deadline_at_risk", "proposal_waiting"]
    instance_key: str | None
    at: AwareDatetime
