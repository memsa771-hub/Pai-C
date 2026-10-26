"""Escalation v1 (Slice 8 spec §2.5, S8-D12): a route problem PAI OS hands to the Counsellor, who decides with the
student. The note is a fixed sentence per reason from config, never student or document text. Frozen."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class EscalationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.escalation.v1"] = Field("pai.escalation.v1", alias="schema")
    key: str = Field(min_length=1)  # the outbox key: escalation:{case_id} or escalation:intake:{decision_id}
    case_id: int | None  # None for an intake refusal, which has no plan and no support case
    journey_id: str = Field(min_length=1)
    student_ref: str = Field(min_length=1)
    reason: Literal["not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other"]
    note: str = Field(min_length=1, max_length=500)
    raised_at: AwareDatetime
