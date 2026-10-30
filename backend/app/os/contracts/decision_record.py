"""Decision record export v1 (Slice 8 spec §2.1, S8-D5): what the Counsellor hands PAI OS after a student's choice.
IDs and codes only, never the Truth Map or free text. Frozen: a change is a v2 file with both teams' sign-off."""

import re
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice, RouteContract

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def iso_country(value: object) -> object:
    if not isinstance(value, str):
        return value
    code = value.strip().upper()
    if not _COUNTRY_RE.match(code):
        raise ValueError("two-letter ISO 3166-1 code")
    return code


class DecisionRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.decision_record.v1"] = Field(alias="schema")
    decision_id: str = Field(min_length=1)
    journey_id: str = Field(min_length=1)
    student_ref: str = Field(min_length=1)  # the Counsellor workspace ID, already the OS student ref
    chosen_at: AwareDatetime
    authorized_at: AwareDatetime | None = None  # the student's hand-off consent (S8-D7); missing → refused, not invalid
    origin_country: str  # "Stated" by the student in the Counsellor's Vault
    destination_country: str
    nationality: str | None = None  # kept in the export only; not used in v1
    level: Literal["foundation", "bachelor", "master", "phd"]
    target_intake: IntakeRef  # any lowercase term (winter, fall, spring): each playbook decides its terms
    programmes: list[ProgrammeChoice] = Field(min_length=1, max_length=5)

    @field_validator("origin_country", "destination_country", "nationality", mode="before")
    @classmethod
    def _country(cls, value: object) -> object:
        return iso_country(value)

    @model_validator(mode="after")
    def _check_programmes(self) -> "DecisionRecordV1":
        refs = [p.programme_ref for p in self.programmes]
        if len(set(refs)) != len(refs):
            raise ValueError("duplicate programme_ref in programmes")
        if sorted(p.rank for p in self.programmes) != list(range(1, len(refs) + 1)):
            raise ValueError("programme ranks must be 1..n")
        return self

    @property
    def external_ref(self) -> str:
        """One plan per journey and route (S8-D8): a new destination or level is a new plan."""
        return f"{self.journey_id}:{self.destination_country}:{self.level}"

    def to_route_contract(self) -> RouteContract:
        return RouteContract(contract_version="1", source="counsellor", external_ref=self.external_ref,
                             student_ref=self.student_ref, origin_country=self.origin_country,
                             destination_country=self.destination_country, level=self.level,
                             programmes=list(self.programmes), target_intake=self.target_intake)
