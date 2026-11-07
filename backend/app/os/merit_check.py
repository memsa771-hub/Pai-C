"""MeritCheck (P2 spec P2-D26, §4.10; master R-31, R-48): a student's merit aggregate from the Vault's marks and a
`verified` formula, or an honest "not confirmed" / "missing". It never predicts a chance: no such field exists.

Pure over a Knowledge port and the student's facts, so it is tested without a host. The aggregate uses the same
`weighted_aggregate` the eligibility code uses, scaled to the formula's total."""

from collections.abc import Sequence

from app.os.contracts.merit_check import (
    ClosingMerit,
    Formula,
    FormulaPart,
    MarkUsed,
    MeritCheckV1,
    PartStatus,
)
from app.os.contracts.programme_facts import SourceRef
from app.os.contracts.route_contract import IntakeRef
from app.os.contracts.student_facts import StudentFactsV1
from app.os.eligibility.methods import weighted_aggregate
from app.os.knowledge import KnowledgePort, display, merit
from app.os.knowledge.port import Fact

_RANK = {"unknown": 0, "stated": 1, "shown": 2, "confirmed": 3}


def _read(knowledge: KnowledgePort, ref: str, field: str, year: int, term: str) -> Fact | None:
    """The fact of exactly this intake: its term, else one whose term was never recorded. Another term never counts."""
    got = knowledge.programme_facts([ref], [field], year, intake_term=term).get((ref, field))
    if got is None:
        got = next((f for (r, n), f in knowledge.programme_facts([ref], [field], year).items()
                    if (r, n) == (ref, field) and f.intake_term == ""), None)
    return got


def _source(fact: Fact) -> SourceRef | None:
    return SourceRef(url=fact.url, quote=fact.quote, checked_at=fact.checked_at) if fact.url and fact.quote else None


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _formula_fact(knowledge: KnowledgePort, ref: str, intake: IntakeRef, category: str | None):
    """(field, fact) of the category's formula, else the general one; None when neither exists."""
    fields = [merit.field_for(merit.formula_field(), category)] if category else []
    fields.append(merit.formula_field())
    for field in dict.fromkeys(fields):
        fact = _read(knowledge, ref, field, intake.year, intake.term)
        if fact is not None:
            return field, fact
    return None


def _closing(knowledge: KnowledgePort, ref: str, intake: IntakeRef, category: str | None) -> list[ClosingMerit]:
    field = merit.field_for(merit.closing_field(), category)
    out = []
    for year in range(intake.year - 1, intake.year - 1 - merit.history_years(), -1):
        if year < 2025:  # IntakeRef's floor
            break
        fact = _read(knowledge, ref, field, year, intake.term)
        source = _source(fact) if fact is not None else None
        if fact is None or source is None:
            continue  # a merit with no sourced record is not listed
        try:
            value = merit.parse_closing(fact.value)
        except merit.MeritShapeError:
            continue
        shown = display(fact, field, intake_year=year, intake_term=intake.term)
        level = "verified" if shown.level == "verified" else "not_confirmed"
        out.append(ClosingMerit(
            intake=IntakeRef(term=fact.intake_term or intake.term, year=year),
            value=value.value if level == "verified" else None, list_number=value.list_number,
            list_complete=value.list_complete, level=level, source=source))
    return out


def build(knowledge: KnowledgePort, facts: StudentFactsV1, programme_ref: str, intake: IntakeRef,
          category: str | None, pairs: Sequence[tuple[str, str]]) -> MeritCheckV1:
    base = {"student_ref": facts.student_ref, "programme_ref": programme_ref, "intake": intake, "category": category}
    closing = _closing(knowledge, programme_ref, intake, category)
    found = _formula_fact(knowledge, programme_ref, intake, category)
    formula = None
    if found is not None:
        field, fact = found
        source = _source(fact)
        try:
            formula = merit.parse_formula(fact.value)
        except merit.MeritShapeError:
            formula = None
        if display(fact, field, intake_year=intake.year, intake_term=intake.term).level != "verified" or source is None:
            formula = None
    if formula is None:  # no formula, or one that is not verified: nothing is computed and nothing is guessed
        return MeritCheckV1(**base, status="not_confirmed", closing_merits=closing)

    total_of = dict(pairs)
    held = {f.key: f for f in facts.facts}
    used, parts, values, weights, totals = [], [], {}, {}, {}
    for part in formula.parts:
        obtained, total = held.get(part.marks_part), held.get(total_of.get(part.marks_part, ""))
        value = _number(obtained.value) if obtained and obtained.evidence != "unknown" else None
        out_of = _number(total.value) if total and total.evidence != "unknown" else None
        evidence = min((e.evidence for e in (obtained, total) if e is not None), key=_RANK.__getitem__,
                       default="unknown") if obtained is not None and total is not None else "unknown"
        known = value is not None and out_of is not None and out_of > 0 and 0 <= value <= out_of
        used.append(MarkUsed(key=part.marks_part, value=value if known else None, out_of=out_of if known else None,
                             evidence=evidence if known else "unknown"))
        parts.append(PartStatus(name=part.name, status="known" if known else "missing"))
        if known:
            values[part.name], weights[part.name], totals[part.name] = value, part.weight, out_of
    shown_formula = Formula(
        parts=[FormulaPart(name=p.name, marks_part=p.marks_part, weight=p.weight) for p in formula.parts],
        total=formula.total, owner_ref=found[1].owner_ref or None, level="verified", source=source)
    aggregate = None
    if all(p.status == "known" for p in parts):
        percent = weighted_aggregate(values, weights, totals)
        aggregate = round(percent * formula.total / 100, 6)
    return MeritCheckV1(**base, status="computed" if aggregate is not None else "missing", formula=shown_formula,
                        aggregate=aggregate, marks_used=used, parts=parts, closing_merits=closing)
