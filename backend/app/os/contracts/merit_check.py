"""MeritCheck v1 (P2 spec P2-D26, §4.10; master §9.1, R-31): OS → Counsellor, a merit formula (sourced), the student's
aggregate and the marks used with their evidence level, each part's status, and past closing merits by year (sourced).
It never predicts a chance: there is no such field. `computed` needs a verified formula. A closing merit from a list
that is not complete is "lowest on list N", never the closing merit. Frozen: a change is a new version."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.os.contracts.programme_facts import SourceRef
from app.os.contracts.route_contract import IntakeRef

Level = Literal["verified", "confirmed", "not_confirmed"]  # the programme_facts.v1 words


class FormulaPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    marks_part: str = Field(min_length=1)  # which marks the part uses, e.g. a named part of a qualification
    weight: float = Field(gt=0, le=1)


class Formula(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parts: list[FormulaPart] = Field(min_length=1)
    total: float = Field(gt=0)
    owner_ref: str | None = None
    level: Level
    source: SourceRef

    @model_validator(mode="after")
    def _weights(self) -> "Formula":
        if abs(sum(p.weight for p in self.parts) - 1.0) > 1e-6:
            raise ValueError("part weights must add up to 1")
        if len({p.name for p in self.parts}) != len(self.parts):
            raise ValueError("duplicate part")
        return self


class MarkUsed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    value: float | None = None
    out_of: float | None = Field(None, gt=0)
    evidence: Literal["stated", "shown", "confirmed", "unknown"]

    @model_validator(mode="after")
    def _unknown(self) -> "MarkUsed":
        if self.evidence == "unknown" and self.value is not None:
            raise ValueError("an unknown mark has no value")
        return self


class PartStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: Literal["known", "missing", "not_confirmed"]


class ClosingMerit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intake: IntakeRef
    value: float | None = None  # high-stakes: carried only at level verified (R-25)
    list_number: int | None = Field(None, ge=1)
    list_complete: bool  # false: the value is the lowest on list N, not the closing merit
    level: Level
    source: SourceRef

    @model_validator(mode="after")
    def _list(self) -> "ClosingMerit":
        if not self.list_complete and self.list_number is None:
            raise ValueError("a merit from a list that is not complete must name its list")
        if (self.value is not None) != (self.level == "verified"):
            raise ValueError("a closing merit carries a value only when verified")
        return self


class MeritCheckV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.merit_check.v1"] = Field("pai.merit_check.v1", alias="schema")
    student_ref: str = Field(min_length=1)
    programme_ref: str = Field(min_length=1)
    intake: IntakeRef
    category: str | None = None  # seat category registry id, when the formula depends on it
    status: Literal["computed", "not_confirmed", "missing"]
    formula: Formula | None = None
    aggregate: float | None = None
    marks_used: list[MarkUsed] = []
    parts: list[PartStatus] = []
    closing_merits: list[ClosingMerit] = []

    @model_validator(mode="after")
    def _status(self) -> "MeritCheckV1":
        if self.status == "computed":
            if self.formula is None or self.formula.level != "verified":
                raise ValueError("computed needs a verified formula")
            if self.aggregate is None or any(p.status != "known" for p in self.parts):
                raise ValueError("computed needs an aggregate and every part known")
        else:
            if self.aggregate is not None:
                raise ValueError(f"{self.status}: no aggregate")
        if self.status == "not_confirmed" and self.formula is not None and self.formula.level == "verified" \
                and all(p.status != "not_confirmed" for p in self.parts):
            raise ValueError("not_confirmed needs a formula or part that is not verified")
        if self.status == "missing" and not any(p.status == "missing" for p in self.parts):
            raise ValueError("missing needs a missing part")
        return self
