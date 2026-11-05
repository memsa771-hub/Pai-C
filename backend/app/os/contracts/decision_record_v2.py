"""Decision record export v2 (P1 spec §3.9): what the Counsellor hands PAI OS after a choice, a change or a withdrawal.
v1 is untouched. IDs and codes only, never the Truth Map or free text. `guardian_required` is decided by the
Counsellor (P1-D10), never by PAI OS. Frozen: a change is a new version file."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.os.contracts.decision_record import iso_country
from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice
from app.os.contracts.route_contract_v2 import Level, RouteContractV2, check_places


class DecisionRecordV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.decision_record.v2"] = Field(alias="schema")
    decision_id: str = Field(min_length=1)
    journey_id: str = Field(min_length=1)
    student_ref: str = Field(min_length=1)
    decision_version: int = Field(ge=1)
    status: Literal["chosen", "withdrawn"]
    chosen_at: AwareDatetime
    authorized_at: AwareDatetime | None = None
    guardian_required: bool = False
    guardian_authorized_at: AwareDatetime | None = None
    origin_country: str
    destination_country: str
    nationality: str | None = None
    level: Level
    path_ref: str | None = None
    os_supported: bool
    target_intake: IntakeRef | None = None
    programmes: list[ProgrammeChoice] = Field(default_factory=list, max_length=5)

    @field_validator("origin_country", "destination_country", "nationality", mode="before")
    @classmethod
    def _country(cls, value: object) -> object:
        return iso_country(value)

    @model_validator(mode="after")
    def _check_places(self) -> "DecisionRecordV2":
        check_places(self.programmes)
        if self.status == "chosen" and self.os_supported:
            if not self.programmes:
                raise ValueError("a chosen, supported route needs at least one programme")
            if self.target_intake is None:
                raise ValueError("a chosen, supported route needs a target_intake")
        return self

    @property
    def external_ref(self) -> str:
        return f"{self.journey_id}:{self.destination_country}:{self.level}"

    def to_route_contract(self) -> RouteContractV2:
        if self.status == "withdrawn" or not self.os_supported:
            raise ValueError("only a chosen, supported decision becomes a route contract")
        if self.target_intake is None:  # the validator guarantees it; kept explicit so it holds under python -O
            raise ValueError("a route contract needs a target_intake")
        return RouteContractV2(contract_version="2", source="counsellor", external_ref=self.external_ref,
                               student_ref=self.student_ref, origin_country=self.origin_country,
                               destination_country=self.destination_country, level=self.level,
                               programmes=list(self.programmes), target_intake=self.target_intake)
