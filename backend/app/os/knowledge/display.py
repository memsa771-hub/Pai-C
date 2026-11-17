"""The one display rule for facts (P2 spec P2-D7, §4.4; master R-25, R-26, R-30). Every surface that shows a fact to a
student asks this function how: high-stakes facts show as fact only when `verified`; other facts from `confirmed`;
below that, "not confirmed" with the link. A fact of another intake always carries its year. An estimate always says
"estimated". The function decides the level only; the words on screen are the surface's copy (data)."""

from dataclasses import dataclass
from typing import Literal

from app.os.knowledge.fact_classes import fact_class, is_high_stakes
from app.os.knowledge.port import Fact

Level = Literal["verified", "confirmed", "not_confirmed", "estimated", "missing"]


@dataclass(frozen=True)
class Display:
    level: Level
    show_value: bool  # the value may be shown as a fact (else only the link, if any)
    high_stakes: bool
    fact_class: str
    other_intake: bool  # the fact is for another intake than the one asked for
    year_label: int | None  # the year to print next to the value; set whenever other_intake
    # Limit until T8: a fact whose term is '' (not recorded) is never "another intake" by term, and year_label is
    # the year only (no term). T8 adds the term to the label once terms are backfilled.


def display(fact: Fact | None, field: str, *, intake_year: int, intake_term: str | None = None,
            estimate: bool = False) -> Display:
    cls = fact_class(field, fact.fact_class if fact is not None else None)
    # an explicit class never makes a high-stakes field ordinary (no bypass of R-25)
    high = is_high_stakes(fact_class(field)) or is_high_stakes(cls)
    if estimate:
        return Display("estimated", True, high, cls, False, None)
    if fact is None:
        return Display("missing", False, high, cls, False, None)
    other = fact.intake_year != intake_year or (
        intake_term is not None and fact.intake_term not in ("", intake_term))
    year = fact.intake_year if other else None
    if fact.status == "verified":
        return Display("verified", True, high, cls, other, year)
    if fact.status == "confirmed" and not high:
        return Display("confirmed", True, high, cls, other, year)
    return Display("not_confirmed", False, high, cls, other, year)
