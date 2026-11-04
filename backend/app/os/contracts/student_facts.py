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
    value: str | int | float | bool | list[str] | dict[str, str | int | float | bool | None] | None
    evidence: Literal["stated", "shown", "confirmed", "unknown"]
    vault_version: int = Field(ge=0)


class StudentFactsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.student_facts.v1"] = Field("pai.student_facts.v1", alias="schema")
    student_ref: str = Field(min_length=1)
    vault_version: int = Field(ge=0)
    built_at: AwareDatetime
    eligible_levels: list[Level]
    facts: list[StudentFact]

    @model_validator(mode="after")
    def _unique_keys(self) -> "StudentFactsV1":
        keys = [f.key for f in self.facts]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate fact key in facts")
        return self
