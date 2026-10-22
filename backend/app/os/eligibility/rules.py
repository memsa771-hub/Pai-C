"""Eligibility rules as route data (Slice 4 spec S4-D2, invariant 12).

Python knows only generic checks (grade, language, test) and generic grade methods. Each route's playbook says which
checks run, with its own numbers, its own research facts and the student's profile keys (Slice 3's
"<doc_type>.<field>"). A route that names a fact or profile key that does not exist fails at startup.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Method = Literal["linear_scale", "threshold", "weighted_aggregate"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Target(_Model):
    """The destination scale for `linear_scale`."""

    best: float
    worst_pass: float
    decimals: int = Field(1, ge=0, le=3)
    rounding: Literal["truncate", "round"] = "round"


class GradeScale(_Model):
    """A grade scale the student's value can be on, with a provisional minimum pass until theirs is confirmed."""

    best: float
    provisional_min_pass: float
    value: str  # profile key of the student's grade on this scale
    min_pass: str | None = None  # profile key of their institution's confirmed minimum pass (S4-D6)
    min_pass_scale: str | None = None  # profile key of the best grade that letter's scale has; must equal `best`
    scale_value: str | None = None  # profile key of the best grade the student's own scale has; must equal `best`


class GradeCheck(_Model):
    method: Method
    requirement: str  # research fact field
    part: str | None = None  # key inside the fact's value
    better: Literal["lower", "higher"]
    target: Target | None = None  # linear_scale
    weights: dict[str, float] = {}  # weighted_aggregate: profile key -> weight
    totals: dict[str, str] = {}  # weighted_aggregate: profile key -> the profile key it is out of (as a percentage)
    scales: list[str] = []  # linear_scale / threshold: grade_scales keys, tried in order

    @model_validator(mode="after")
    def _method_inputs(self) -> "GradeCheck":
        if self.method == "linear_scale" and self.target is None:
            raise ValueError("a linear_scale grade check needs a target")
        if self.method == "weighted_aggregate" and not self.weights:
            raise ValueError("a weighted_aggregate grade check needs weights")
        if self.method != "weighted_aggregate" and not self.scales:
            raise ValueError(f"a {self.method} grade check needs scales")
        return self


class LanguageCheck(_Model):
    language: str
    requirement: str
    level_key: str | None = None
    scores: dict[str, str] = {}  # score key in the fact -> profile key
    none_values: list[str] = ["none"]


class TestCheck(_Model):
    requirement: str
    list_key: str = "any_of"


class EligibilityRules(_Model):
    grade: list[GradeCheck] = []  # tried in order: the first whose requirement part is present decides
    language: list[LanguageCheck] = []
    test: TestCheck | None = None
    grade_scales: dict[str, GradeScale] = {}

    @model_validator(mode="after")
    def _scales_exist(self) -> "EligibilityRules":
        for g in self.grade:
            for s in g.scales:
                if s not in self.grade_scales:
                    raise ValueError(f"grade check on {g.requirement}: unknown scale '{s}'")
        return self

    def fact_fields(self) -> set[str]:
        return ({g.requirement for g in self.grade} | {lc.requirement for lc in self.language}
                | ({self.test.requirement} if self.test else set()))

    def profile_fields(self) -> set[str]:
        keys = {s.value for s in self.grade_scales.values()}
        keys |= {k for s in self.grade_scales.values() for k in (s.min_pass, s.min_pass_scale, s.scale_value) if k}
        for g in self.grade:
            keys |= set(g.weights) | set(g.totals.values())
        for lc in self.language:
            keys |= set(lc.scores.values())
        return keys


class SelfServe(_Model):
    choose_task: str | None = None  # the playbook task the route builder completes (S4-D9)


def profile_keys(types: Mapping) -> set[str]:
    """Every profile key Slice 3 can set: "<doc_type>.<field>"."""
    return {f"{t.key}.{f.name}" for t in types.values() for f in t.fields}


def check_rules(book, fact_fields: set[str] | None, keys: set[str]) -> None:
    """Every fact and profile key the playbook's rules name must exist (`fact_fields=None`: no research profile for
    this route, so facts are not checked). Raises PlaybookError naming the playbook and the field."""
    from app.os.playbooks.loader import PlaybookError  # imported here: the loader imports the playbook models

    rules = book.eligibility
    where = f"{book.key} v{book.version}"
    if book.self_serve and book.self_serve.choose_task:
        if book.self_serve.choose_task not in {t.template_key for t in book.tasks}:
            raise PlaybookError(f"{where}: self_serve.choose_task '{book.self_serve.choose_task}' is not a task")
    if rules is None:
        return
    if fact_fields is not None:
        unknown = sorted(rules.fact_fields() - fact_fields)
        if unknown:
            raise PlaybookError(f"{where}: eligibility names unknown research facts {unknown}")
    unknown = sorted(rules.profile_fields() - keys)
    if unknown:
        raise PlaybookError(f"{where}: eligibility names unknown profile keys {unknown}")
