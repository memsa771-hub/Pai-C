"""RouteContract v1: the inbound contract every "way in" produces."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


class ProgrammeChoice(BaseModel):
    programme_ref: str = Field(min_length=1)
    rank: int = Field(ge=1)

    @field_validator("programme_ref", mode="before")
    @classmethod
    def _strip_ref(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class IntakeRef(BaseModel):
    term: str = Field(pattern=r"^[a-z_]+$")
    year: int = Field(ge=2025, le=2100)


class RouteContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    source: Literal["self_serve", "counsellor"]
    external_ref: str
    student_ref: str
    origin_country: str
    destination_country: str
    level: Literal["foundation", "bachelor", "master", "phd"]
    programmes: list[ProgrammeChoice] = Field(min_length=1, max_length=10)
    target_intake: IntakeRef

    @field_validator("origin_country", "destination_country", mode="before")
    @classmethod
    def _normalise_country(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        code = value.strip().upper()
        if not _COUNTRY_RE.match(code):
            raise ValueError("two-letter ISO 3166-1 code")
        return code

    @model_validator(mode="after")
    def _check_programmes(self) -> "RouteContract":
        refs = [p.programme_ref for p in self.programmes]
        if len(set(refs)) != len(refs):
            raise ValueError("duplicate programme_ref in programmes")
        if sorted(p.rank for p in self.programmes) != list(range(1, len(refs) + 1)):
            raise ValueError("programme ranks must be 1..n")
        return self

    @property
    def dedupe_key(self) -> str:
        return f"{self.source}:{self.external_ref}:{self.contract_version}"


def export_json_schema() -> dict:
    return RouteContract.model_json_schema()
