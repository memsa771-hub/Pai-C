"""RouteContract v2 (P1 spec §3.9): v1 plus the `intermediate` level. v1 is untouched; a change is a new version file."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.os.contracts.decision_record import iso_country
from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice

Level = Literal["intermediate", "foundation", "bachelor", "master", "phd"]


def check_places(programmes: list[ProgrammeChoice]) -> None:
    """Shared by the v2 contracts: programme refs are unique and ranks run 1..n."""
    refs = [p.programme_ref for p in programmes]
    if len(set(refs)) != len(refs):
        raise ValueError("duplicate programme_ref in programmes")
    if sorted(p.rank for p in programmes) != list(range(1, len(refs) + 1)):
        raise ValueError("programme ranks must be 1..n")


class RouteContractV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    contract_version: Literal["2"]
    source: Literal["self_serve", "counsellor"]
    external_ref: str = Field(min_length=1)
    student_ref: str = Field(min_length=1)
    origin_country: str
    destination_country: str
    level: Level
    programmes: list[ProgrammeChoice] = Field(min_length=1, max_length=10)
    target_intake: IntakeRef

    @field_validator("external_ref", "student_ref", mode="before")
    @classmethod
    def _strip_refs(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("origin_country", "destination_country", mode="before")
    @classmethod
    def _normalise_country(cls, value: object) -> object:
        return iso_country(value)

    @model_validator(mode="after")
    def _check_programmes(self) -> "RouteContractV2":
        check_places(self.programmes)
        return self

    @property
    def dedupe_key(self) -> str:
        return f"{self.source}:{self.external_ref}:{self.contract_version}"
