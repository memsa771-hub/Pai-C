"""Eligibility change notes (Slice 4 spec S4-D7).

Two existing hooks call in: a fact changed (Slice 2's `after_fact_change`) or the student confirmed a value (Slice 3's
confirm and resolve). Each chosen programme of each affected plan is re-evaluated with the plan's **pinned** playbook
rules. When a programme's verdict differs from the last one the student was told about (`os_eligibility_seen`), one
note goes to their inbox with the reason and up to 3 swap suggestions. The first evaluation of a programme only records
its verdict. Each (student, programme) is updated in one statement, so a replay or a retried step writes nothing more.
"""

from dataclasses import asdict

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models
from app.os.documents.store import ProfileStore
from app.os.eligibility.evaluate import Card, evaluate
from app.os.eligibility.swaps import suggest
from app.os.knowledge.requests import visible_programmes

P, SEEN, NOTES = models.plans, models.eligibility_seen, models.eligibility_notes


def profile_of(plans, student_ref: str) -> dict:
    return {v["key"]: v["value"] for v in ProfileStore(plans.engine, plans.kernel.tenant_id).all(student_ref)}


def programme_cards(plans, rules, refs: list[str], year: int, profile: dict) -> dict[str, tuple[Card, int]]:
    """Each programme's card and how many of its facts are confirmed."""
    raw = plans.knowledge.programme_facts(refs, sorted(rules.fact_fields()), year)
    out = {}
    for ref in refs:
        facts = {field: f for (r, field), f in raw.items() if r == ref}
        out[ref] = (evaluate(rules, ref, facts, profile), sum(f.confirmed for f in facts.values()))
    return out


def _plan(plans, plan_id: int):
    contract, _ = plans._contract(plan_id)
    return contract, plans._pinned(plan_id)


def cards_for(plans, student_ref: str, plan_id: int) -> dict[str, Card]:
    """The student's chosen programmes in this plan, each evaluated with the plan's pinned rules ({} without rules)."""
    contract, book = _plan(plans, plan_id)
    if book.eligibility is None:
        return {}
    refs = [p.programme_ref for p in contract.programmes]
    cards = programme_cards(plans, book.eligibility, refs, contract.target_intake.year, profile_of(plans, student_ref))
    return {ref: card for ref, (card, _) in cards.items()}


def _line(ln) -> dict:
    d = asdict(ln)
    d["sources"] = [{"field": s["field"], "url": s["url"], "status": s["status"]} for s in d["sources"]]
    return d


def _record(plans, student_ref: str, plan_id: int, card: Card, suggestions) -> bool:
    """Compare with the last verdict told; on a change, store it and write one note. True if a note was written."""
    tenant = plans.kernel.tenant_id
    with plans.engine.begin() as conn:
        first = conn.execute(pg_insert(SEEN).values(
            tenant_id=tenant, student_ref=student_ref, programme_ref=card.programme_ref, verdict=card.verdict,
        ).on_conflict_do_nothing(constraint="uq_os_eligibility_seen").returning(SEEN.c.id)).scalar()
        if first is not None:
            return False  # the first evaluation: nothing changed for the student yet
        old = conn.execute(select(SEEN.c.verdict).where(
            SEEN.c.tenant_id == tenant, SEEN.c.student_ref == student_ref, SEEN.c.programme_ref == card.programme_ref,
        ).with_for_update()).scalar_one()
        if old == card.verdict:
            return False
        conn.execute(update(SEEN).where(
            SEEN.c.tenant_id == tenant, SEEN.c.student_ref == student_ref, SEEN.c.programme_ref == card.programme_ref,
        ).values(verdict=card.verdict, updated_at=func.now()))
        conn.execute(insert(NOTES).values(
            tenant_id=tenant, student_ref=student_ref, programme_ref=card.programme_ref, verdict=card.verdict,
            payload={"plan_id": plan_id, "programme_ref": card.programme_ref, "verdict": card.verdict, "previous": old,
                     "lines": [_line(ln) for ln in card.lines], "suggestions": suggestions()}))
    return True


def _check_plan(plans, student_ref: str, plan_id: int, only: str | None = None) -> int:
    contract, book = _plan(plans, plan_id)
    if book.eligibility is None:
        return 0
    rules, year = book.eligibility, contract.target_intake.year
    chosen = [p.programme_ref for p in contract.programmes]
    profile = profile_of(plans, student_ref)
    mine = programme_cards(plans, rules, [r for r in chosen if only is None or r == only], year, profile)

    def suggestions_for(card):
        def make() -> list[str]:
            if card.verdict != "likely_below":
                return []
            others = [p.ref for p in visible_programmes(plans.engine, plans.kernel.tenant_id, book.key, year)]
            cands = programme_cards(plans, rules, others, year, profile)
            return [s.programme_ref for s in suggest(card, list(cands.values()), set(chosen))]
        return make

    return sum(_record(plans, student_ref, plan_id, card, suggestions_for(card)) for card, _ in mine.values())


def _plans_of(plans, *, student_ref: str | None = None, intake_year: int | None = None) -> list[tuple[int, str, dict]]:
    q = select(P.c.id, P.c.student_ref, P.c.contract).where(P.c.tenant_id == plans.kernel.tenant_id)
    if student_ref is not None:
        q = q.where(P.c.student_ref == student_ref)
    if intake_year is not None:
        q = q.where(P.c.contract["target_intake"]["year"].as_integer() == intake_year)
    with plans.engine.connect() as conn:
        return [(r.id, r.student_ref, r.contract) for r in conn.execute(q.order_by(P.c.id)).all()]


def on_profile_change(plans, student_ref: str) -> int:
    """After the student confirmed or resolved a value: re-check every programme in their plans. Returns notes written."""
    return sum(_check_plan(plans, student_ref, plan_id) for plan_id, _, _ in _plans_of(plans, student_ref=student_ref))


def on_fact_change(plans, programme_ref: str, intake_year: int) -> int:
    """After a programme's fact changed: re-check that programme for every student who chose it for that intake."""
    n = 0
    for plan_id, student_ref, contract in _plans_of(plans, intake_year=intake_year):
        if any(p["programme_ref"] == programme_ref for p in contract.get("programmes", [])):
            n += _check_plan(plans, student_ref, plan_id, only=programme_ref)
    return n
