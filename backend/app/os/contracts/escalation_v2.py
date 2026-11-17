"""Escalation v2 (P1 spec §3.9): v1 plus the decision version the problem belongs to. v1 is untouched. The note is a
fixed sentence per reason from config, never student or document text. Frozen: a change is a new version file."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class EscalationV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.escalation.v2"] = Field("pai.escalation.v2", alias="schema")
    key: str = Field(min_length=1)  # the outbox key: escalation:{case_id} or escalation:intake:{decision_id}
    case_id: int | None  # None for an intake refusal, which has no plan and no support case
    journey_id: str = Field(min_length=1)
    student_ref: str = Field(min_length=1)
    decision_version: int | None = Field(ge=1)  # None when no decision version applies
    reason: Literal["not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other"]
    note: str = Field(min_length=1, max_length=500)
    raised_at: AwareDatetime
