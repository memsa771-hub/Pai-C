"""The 11 scored fields: the agent's output shape, canonical forms and matching against the key.

Design §4. `canon` is used to decide whether two readings agree; `match_key` and `scorable` decide
whether the agent's value equals the answer key's.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

T = TypeVar("T")

Language = Literal["english", "english_or_german", "mostly_english", "german"]
Route = Literal["uni_assist", "uni_assist_vpd", "direct"]
Cefr = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
MonthDay = Annotated[str, StringConstraints(pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")]
Intake = Literal["winter", "summer"]
TestName = Literal["TestAS", "GATE", "GRE", "dMat", "other"]


class English(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cefr: Cefr | None = None
    ielts: float | None = None
    toefl_ibt: int | None = None
    pte: int | None = None
    moi_accepted: bool | None = Field(None, description="Is a medium-of-instruction letter accepted instead of a test?")


class German(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["none", "A1", "A2", "B1", "B2", "C1", "C2"] = Field(description="'none' if no German is needed")
    when: str | None = Field(None, description="When it must be shown, e.g. 'with the application'")


class Grade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    german_max: float | None = Field(None, description="Worst accepted grade on the German scale (1.0 best, 4.0 pass)")
    percent_min: float | None = None


class Admission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    any_of: list[TestName] = Field(description="Tests that satisfy the requirement; empty if no test is required")


class Found(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    value: T
    quote: str = Field(description="The sentence that states the fact, copied word for word from the page")
    url: str = Field(description="The URL of the page the quote is on, exactly as given in the PAGE header")
    cycle: str | None = Field(
        None, description="The intake or year the page gives for this fact, copied from the page (e.g. 'WS 2026/27'); null if none")


class Reading(BaseModel):
    """One reading of a programme's pages, for a non-EU applicant to the winter intake. None = not found."""

    model_config = ConfigDict(extra="forbid")
    language_of_instruction: Found[Language] | None = None
    tuition_fee_non_eu_eur: Found[float] | None = Field(None, description="Tuition per semester in EUR; 0 if none")
    semester_contribution_eur: Found[float] | None = None
    deadline_open: Found[MonthDay] | None = Field(None, description="First day of the non-EU winter application window, MM-DD")
    deadline_close: Found[MonthDay] | None = Field(None, description="Last day of the non-EU winter application window, MM-DD")
    application_route: Found[Route] | None = None
    english_requirement: Found[English] | None = None
    german_requirement: Found[German] | None = None
    grade_requirement: Found[Grade] | None = None
    admission_test: Found[Admission] | None = None
    intakes: Found[list[Intake]] | None = None


FIELDS: tuple[str, ...] = tuple(Reading.model_fields)

# Dates and money count only for a named cycle (Spike 5 §1); the rest are procedural rules.
CYCLE_BOUND = frozenset({"deadline_open", "deadline_close", "tuition_fee_non_eu_eur", "semester_contribution_eur"})

ENGLISH_KEYS = ("cefr", "ielts", "toefl_ibt", "pte", "moi_accepted")
_TESTS = {"testas": "TestAS", "gate": "GATE", "gre": "GRE", "dmat": "dMat"}


def _dump(value: Any) -> Any:
    return value.model_dump() if isinstance(value, BaseModel) else value


def canon(field: str, value: Any) -> Any:
    """A hashable form; two readings agree when their canons are equal."""
    v = _dump(value)
    if isinstance(v, float):
        return round(v, 2)
    if field == "intakes":
        return tuple(sorted(set(v)))
    if field == "admission_test":
        return tuple(sorted(set(v["any_of"])))
    if field == "german_requirement":
        return v["level"]
    if isinstance(v, dict):
        return tuple(sorted((k, round(x, 2) if isinstance(x, float) else x) for k, x in v.items() if x is not None))
    return v


def named_tests(entries: list[str]) -> set[str]:
    """Answer-key admission tests are prose ('GRE Q160 V145 AW4.5'); keep the test names."""
    names = set()
    for e in entries:
        for word in re.findall(r"[A-Za-z]+", e):
            if word.lower() in _TESTS:
                names.add(_TESTS[word.lower()])
    return names


def scorable(field: str, key: Any) -> bool:
    """Whether the key value says something the matcher can check."""
    if key is None:
        return False
    if field == "english_requirement":
        return any(key.get(k) is not None for k in ENGLISH_KEYS)
    if field == "grade_requirement":
        return key.get("german_max") is not None or key.get("percent_min") is not None
    if field == "semester_contribution_eur":
        return key.get("value") is not None
    if field == "admission_test":
        return bool(named_tests(key.get("any_of", [])))
    return True


def match_key(field: str, key: Any, agent: Any) -> bool:
    a = _dump(agent)
    if field == "semester_contribution_eur":
        tolerance = 0.10 * key["value"] if key.get("approx") else 1.0
        return abs(float(a) - float(key["value"])) <= tolerance
    if field == "tuition_fee_non_eu_eur":
        return float(a) == float(key)
    if field == "english_requirement":
        return all(a.get(k) == key[k] for k in ENGLISH_KEYS if key.get(k) is not None)
    if field == "german_requirement":
        return a["level"] == key["level"]
    if field == "grade_requirement":
        return all(a.get(k) == key[k] for k in ("german_max", "percent_min") if key.get(k) is not None)
    if field == "admission_test":
        return set(a["any_of"]) - {"other"} == named_tests(key["any_of"])
    if field == "intakes":
        return set(a) == set(key)
    return a == key
