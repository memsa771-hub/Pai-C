"""Student facts v1 (master §9.1, P1 spec §3.9): what the Counsellor's Vault hands PAI OS about one student, each fact
with its evidence level (stated, shown, confirmed; unknown when nothing is held). Frozen: a change is a new version
file."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.os.contracts.route_contract_v2 import Level

FACT_KEY = r"^[a-z_]+(\.[a-z0-9_]+)*$"


class StudentFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=FACT_KEY)
    value: str | int | float | bool | list[str] | dict[str, str | int | float | bool | list[str] | None] | None
    evidence: Literal["stated", "shown", "confirmed", "unknown"]
    vault_version: int = Field(ge=0)
    document_ref: str | None = None  # the document a shown fact came from (R-54: source on screen)
    as_of: AwareDatetime | None = None  # when the fact was recorded or confirmed (R-54: date on screen)

    @model_validator(mode="after")
    def _unknown_has_no_value(self) -> "StudentFact":
        if self.evidence == "unknown" and self.value is not None:
            raise ValueError("an unknown fact has no value")
        return self


class StudentFactsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.student_facts.v1"] = Field("pai.student_facts.v1", alias="schema")
    student_ref: str = Field(min_length=1)
    vault_version: int = Field(ge=0)
    built_at: AwareDatetime
    eligible_levels: list[Level] | None  # None = unknown (e.g. the Vault has no education yet)
    facts: list[StudentFact]

    @model_validator(mode="after")
    def _unique_keys(self) -> "StudentFactsV1":
        keys = [f.key for f in self.facts]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate fact key in facts")
        if self.eligible_levels is not None and len(set(self.eligible_levels)) != len(self.eligible_levels):
            raise ValueError("duplicate level in eligible_levels")
        if any(f.vault_version > self.vault_version for f in self.facts):
            raise ValueError("a fact's vault_version cannot exceed the top-level vault_version")
        return self
