"""Choice request v1 (master §9.1, P1 spec §3.9): a change of places or intake that PAI OS proposes and the Counsellor
puts to the student. IDs and codes only. Dropping every place is not a choice request (R-22: that is an escalation). Frozen: a change is a new version file."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice
from app.os.contracts.route_contract_v2 import check_places


class ChoiceRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.choice_request.v1"] = Field("pai.choice_request.v1", alias="schema")
    key: str = Field(min_length=1)
    student_ref: str = Field(min_length=1)
    journey_id: str = Field(min_length=1)
    proposal_id: int
    based_on_version: int = Field(ge=1)  # the decision version the proposal was made against
    programmes: list[ProgrammeChoice] | None = Field(default=None, min_length=1, max_length=5)
    target_intake: IntakeRef | None = None
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def _check(self) -> "ChoiceRequestV1":
        if self.programmes is None and self.target_intake is None:
            raise ValueError("a choice request changes programmes, target_intake or both")
        if self.programmes is not None:
            check_places(self.programmes)
        return self
