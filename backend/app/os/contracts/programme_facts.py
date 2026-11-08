"""ProgrammeFacts v1 (P2 spec P2-D27, §4.4, §4.10; master §9.1, R-23, R-25, R-26): OS → Counsellor, a programme's
facts for one intake, each with its level, source, quote, checked date and intake. The level is the one display rule
(`knowledge/display.py`): a value travels only when it may be shown as a fact. Frozen: a change is a new version."""

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.os.contracts.route_contract import IntakeRef

Level = Literal["verified", "confirmed", "not_confirmed", "estimated", "missing"]
ReadMethod = Literal["fetch", "render", "ocr", "human", "model"]


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    checked_at: AwareDatetime


class FactEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    fact_class: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    high_stakes: bool
    level: Level
    value: Any = None  # only when level is verified, confirmed or estimated
    source: SourceRef | None = None  # the link is given whenever there is one, even when not confirmed
    fact_intake: IntakeRef | None = None  # the intake the fact belongs to
    other_intake: bool = False  # the fact is for another intake than the list's: always shown with its year
    owner_ref: str | None = None  # registry id of the body that sets the value (P2-D8)
    read_method: ReadMethod | None = None
    language: str | None = Field(None, pattern=r"^[a-z]{2,3}$")

    @model_validator(mode="after")
    def _level_rules(self) -> "FactEntry":
        if self.level in ("verified", "confirmed") and self.source is None:
            raise ValueError(f"a {self.level} fact needs its source")
        if self.level in ("not_confirmed", "missing") and self.value is not None:
            raise ValueError(f"a {self.level} fact carries no value")
        if self.level == "missing" and (self.source is not None or self.fact_intake is not None):
            raise ValueError("a missing fact has no source or intake")
        if self.level == "confirmed" and self.high_stakes:
            raise ValueError("a high-stakes fact shows as fact only when verified")
        if self.other_intake and self.fact_intake is None:
            raise ValueError("a fact of another intake must name its intake")
        return self


class ProgrammeFactsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.programme_facts.v1"] = Field("pai.programme_facts.v1", alias="schema")
    programme_ref: str = Field(min_length=1)
    route_key: str = Field(min_length=1)
    intake: IntakeRef
    facts: list[FactEntry]

    @model_validator(mode="after")
    def _intakes(self) -> "ProgrammeFactsV1":
        names = [f.field for f in self.facts]
        if len(names) != len(set(names)):
            raise ValueError("duplicate field")
        for f in self.facts:
            if f.fact_intake is not None:
                differs = f.fact_intake.year != self.intake.year or f.fact_intake.term != self.intake.term
                if differs != f.other_intake:
                    raise ValueError(f"{f.field}: other_intake must say whether the fact's intake differs")
        return self
