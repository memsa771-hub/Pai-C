"""Fact conflicts v1 (P1-T8 D-w12, master §9): the facts of one student that the Counsellor's Vault holds in question,
each with the two values and where each came from. The OS reads it live and never stores a value (R-01). Only keys of
the StudentFacts allow-list ever appear (education and test scores): never a name, a date of birth or a document
number. `answers` is what the Vault's own card offers; the OS shows only those and sends the student's choice back.
Frozen: a change is a new version file."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.os.contracts.student_facts import FACT_KEY

Answer = Literal["keep_current", "accept_proposed", "provide_new"]


class ConflictValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    side: Literal["current", "proposed"]
    value: str | int | float
    evidence: Literal["stated", "shown", "confirmed", "unknown"]
    document_ref: str | None = None  # the document this side came from (the Counsellor file, or `os:<id>`)
    as_of: AwareDatetime | None = None


class FactConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: Annotated[str, Field(pattern=r"^profile_issue:[A-Za-z0-9-]+$")]
    key: str = Field(pattern=FACT_KEY)
    values: list[ConflictValue] = Field(min_length=2, max_length=2)
    answers: list[Answer] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _one_of_each_side(self) -> "FactConflict":
        if sorted(v.side for v in self.values) != ["current", "proposed"]:
            raise ValueError("a conflict has one current value and one proposed value")
        if len(set(self.answers)) != len(self.answers):
            raise ValueError("duplicate answer")
        return self


class FactConflictsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.fact_conflicts.v1"] = Field("pai.fact_conflicts.v1", alias="schema")
    student_ref: str = Field(min_length=1)
    vault_version: int = Field(ge=0)
    built_at: AwareDatetime
    conflicts: list[FactConflict]

    @model_validator(mode="after")
    def _unique_keys(self) -> "FactConflictsV1":
        keys = [c.key for c in self.conflicts]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate fact key in conflicts")
        return self
