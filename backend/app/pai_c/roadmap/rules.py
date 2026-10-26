"""Admission rules per study field, read from policy/admission_rules.json.

Eligibility is data, not code: correcting a percent floor or a bridge step is
an edit to the JSON. A field's own rule wins over its family's rule, and a
rule with null values means "not researched", never "no requirement".
"""

from dataclasses import dataclass
from functools import lru_cache

from app.pai_c.paths.fields import study_fields
from app.pai_c.policy.controller import load_data


@dataclass(frozen=True)
class Step:
    group: str
    step: str
    source: str
    scope_fields: tuple[str, ...] | None = None


@dataclass(frozen=True)
class EntryTest:
    name: str
    body: str
    pass_percent: float | None
    source: str


@dataclass(frozen=True)
class Rule:
    groups_open: list[str] | None  # None: use open_to from study_fields.json
    groups_with_step: tuple[Step, ...]
    min_percent: float | None
    required_subjects: list[str]
    entry_tests: tuple[EntryTest, ...]
    years: int | None
    fee_band_per_year: object  # the JSON key carries the currency; code files keep currency tokens out
    sources: list[str]
    confidence: str
    years_by_field: dict[str, int] | None = None  # per-field override of years in a shared rule

    def years_for(self, field_key: str) -> int | None:
        return (self.years_by_field or {}).get(field_key, self.years)


@lru_cache(maxsize=1)
def _data() -> dict:
    return load_data("admission_rules.json")


def _rule(row: dict) -> Rule:
    return Rule(
        groups_open=row["groups_open"], min_percent=row["min_percent"],
        groups_with_step=tuple(Step(s["group"], s["step"], s["source"],
                                    tuple(s["scope_fields"]) if s.get("scope_fields") else None)
                               for s in row.get("groups_with_step", [])),
        required_subjects=list(row["required_subjects"]),
        entry_tests=tuple(EntryTest(t["name"], t["body"], t.get("pass_percent"), t["source"])
                          for t in row.get("entry_tests", [])),
        years=row["years"], fee_band_per_year=next((v for k, v in row.items() if k.startswith("fee_band")), None),
        sources=list(row["sources"]), confidence=row["confidence"], years_by_field=row.get("years_by_field"))


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, Rule], dict[str, Rule]]:
    by_field: dict[str, Rule] = {}
    by_family: dict[str, Rule] = {}
    for row in _data()["rules"]:
        target = row["applies_to"]
        rule = _rule(row)
        by_field.update({key: rule for key in target.get("fields", [])})
        if "family" in target:
            by_family[target["family"]] = rule
    return by_field, by_family


def rule_for(field_key: str) -> Rule | None:
    by_field, by_family = _index()
    if field_key in by_field:
        return by_field[field_key]
    field = study_fields().get(field_key)
    return by_family.get(field.family) if field else None


def ibcc_percent(grades: list[str]) -> float | None:
    """Average IBCC percentage of A-level/O-level grades; None when a grade is unknown."""
    table = _data()["equivalence"]["o_level_a_level"]
    marks = dict(table["grade_to_pak_marks_a_level_o_level"], **{"A*": table["a_star_percent"]})
    values = [marks.get(str(g).strip().upper()) for g in grades]
    if not values or any(not isinstance(v, (int, float)) for v in values):
        return None
    return sum(values) / len(values)
