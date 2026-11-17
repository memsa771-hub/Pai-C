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
    for wanted in (term, ""):  # the asked term, else rows whose term was never recorded: each an exact filter
        got = knowledge.programme_facts([ref], [field], year, intake_term=wanted).get((ref, field))
        if got is not None:
            return got
    return None


def _source(fact: Fact) -> SourceRef | None:
    return SourceRef(url=fact.url, quote=fact.quote, checked_at=fact.checked_at) if fact.url and fact.quote else None


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _formula_fact(knowledge: KnowledgePort, ref: str, intake: IntakeRef, category: str | None):
    """(field, fact, by_category) of the category's formula, else the general one; None when neither exists."""
    fields = [merit.field_for(merit.formula_field(), category)] if category else []
    fields.append(merit.formula_field())
    for field in dict.fromkeys(fields):
        fact = _read(knowledge, ref, field, intake.year, intake.term)
        if fact is not None:
            return field, fact, field != merit.formula_field()
    return None


def _closing(knowledge: KnowledgePort, ref: str, intake: IntakeRef, category: str | None) -> list[ClosingMerit]:
    field = merit.field_for(merit.closing_field(), category)
    out = []
    for year in range(intake.year - 1, intake.year - 1 - merit.history_years(), -1):
        if year < merit.intake_year_floor():
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
            intake=IntakeRef(term=merit.term_of(fact.intake_term), year=year),
            value=value.value if level == "verified" else None, list_number=value.list_number,
            list_complete=value.list_complete, level=level, source=source))
    return out


def build(knowledge: KnowledgePort, facts: StudentFactsV1, programme_ref: str, intake: IntakeRef,
          category: str | None, pairs: Sequence[tuple[str, str]]) -> MeritCheckV1:
    base = {"student_ref": facts.student_ref, "programme_ref": programme_ref, "intake": intake}
    closing = _closing(knowledge, programme_ref, intake, category)
    found = _formula_fact(knowledge, programme_ref, intake, category)
    formula = None
    # `category` in the answer means "the formula depends on it" (the contract's words): it is echoed only when a
    # category-specific formula was used. The general formula answers with no category.
    answered_category = category
    if found is not None:
        field, fact, by_category = found
        answered_category = category if by_category else None
        source = _source(fact)
        try:
            formula = merit.parse_formula(fact.value)
        except merit.MeritShapeError:
            formula = None
        if display(fact, field, intake_year=intake.year, intake_term=intake.term).level != "verified" or source is None:
            formula = None
    if formula is None:  # no formula, or one that is not verified: nothing is computed and nothing is guessed
        return MeritCheckV1(**base, category=answered_category, status="not_confirmed", closing_merits=closing)

    totals_of: dict[str, list[str]] = {}
    for value_key, total_key in pairs:
        totals_of.setdefault(value_key, []).append(total_key)
    held = {f.key: f for f in facts.facts}
    used, parts, values, weights, totals = [], [], {}, {}, {}
    for part in formula.parts:
        # The reason a part is not known sits in the contract's own words: `missing` = nothing held (absent), `not_confirmed`
        # = marks are held but cannot be used (impossible: above their total, or two different totals held).
        obtained = held.get(part.marks_part)
        value = _number(obtained.value) if obtained and obtained.evidence != "unknown" else None
        total_facts = [held[k] for k in totals_of.get(part.marks_part, ()) if k in held and held[k].evidence != "unknown"
                       and _number(held[k].value) is not None]
        out_ofs = sorted({_number(t.value) for t in total_facts})
        out_of = out_ofs[0] if len(out_ofs) == 1 else None  # two different totals: not guessed
        evidence = min((e.evidence for e in (obtained, *total_facts) if e is not None), key=_RANK.__getitem__,
                       default="unknown") if value is not None and total_facts else "unknown"
        if value is None or not out_ofs:
            status = "missing"
        elif len(out_ofs) > 1 or out_ofs[0] <= 0 or not 0 <= value <= out_ofs[0]:
            status = "not_confirmed"
        else:
            status = "known"
        if status == "missing":
            used.append(MarkUsed(key=part.marks_part, evidence="unknown"))
        else:  # what the Vault holds is shown, so the reason is visible
            used.append(MarkUsed(key=part.marks_part, value=value, out_of=out_of if out_of and out_of > 0 else None,
                                 evidence=evidence))
        parts.append(PartStatus(name=part.name, status=status))
        if status == "known":
            values[part.name], weights[part.name], totals[part.name] = value, part.weight, out_of
    shown_formula = Formula(
        parts=[FormulaPart(name=p.name, marks_part=p.marks_part, weight=p.weight) for p in formula.parts],
        total=formula.total, owner_ref=found[1].owner_ref or None, level="verified", source=source)
    aggregate = None
    if all(p.status == "known" for p in parts):
        percent = weighted_aggregate(values, weights, totals)
        aggregate = round(percent * formula.total / 100, 6)
    status = ("computed" if aggregate is not None
              else "missing" if any(p.status == "missing" for p in parts) else "not_confirmed")
    return MeritCheckV1(**base, category=answered_category, status=status, formula=shown_formula,
                        aggregate=aggregate, marks_used=used, parts=parts, closing_merits=closing)
