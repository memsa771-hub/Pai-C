"""The yearly rollover (P2 spec §4.8; R-61, R-62) and the term backfill of old facts (plan D-t1-1).

A rollover opens an intake and copies the *structure* of the previous one: the (scope, ref, field, owner) keys, as
expected slots with no value. It never copies a value and never changes a fact of the previous intake (R-60). What a
slot still lacks is derived from `os_knowledge_facts`, so nothing is kept twice."""

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, and_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import models
from app.os.intakes.store import Intake, IntakeError, IntakeStore
from app.os.playbooks import Playbook

F = models.knowledge_facts
S = models.fact_slots


@dataclass(frozen=True)
class RolloverResult:
    intake: Intake
    previous: Intake | None
    slots_added: int


@dataclass(frozen=True)
class SlotRow:
    scope: str
    ref: str
    field: str
    owner_ref: str
    fact_class: str | None
    state: str  # `expected` (no fact for the intake yet), else the fact's status
    fact_id: int | None


def rollover(engine: Engine, tenant_id: str, *, region: str, family: str, term: str, year: int,
             extra_terms: tuple[str, ...] = ()) -> RolloverResult:
    """Opens (region, family, term, year) from the newest earlier intake of the same term and adds the expected slots.
    Safe to run again: an existing open intake is kept and only missing slots are added."""
    store = IntakeStore(engine, tenant_id)
    previous = store.previous(region, family, term, year)
    intake = store.get(region, family, term, year)
    if intake is None:
        intake = store.create(region, family, term, year, state="open",
                              opened_from_id=previous.id if previous else None, extra_terms=extra_terms)
    elif intake.state == "planned":
        intake = store.set_state(intake.id, "open")
    elif intake.state == "closed":
        raise IntakeError(f"intake {region}/{family}/{term}/{year} is closed")
    added = 0
    if previous is not None:
        with engine.begin() as conn:
            keys = conn.execute(select(F.c.scope, F.c.ref, F.c.field, F.c.owner_ref, F.c.fact_class).where(
                F.c.tenant_id == tenant_id, F.c.intake_term == term, F.c.intake_year == previous.year,
            ).order_by(F.c.scope, F.c.ref, F.c.field, F.c.owner_ref)).all()
            for k in keys:
                added += conn.execute(insert(S).values(
                    tenant_id=tenant_id, intake_id=intake.id, scope=k.scope, ref=k.ref, field=k.field,
                    owner_ref=k.owner_ref, fact_class=k.fact_class).on_conflict_do_nothing(
                    constraint="uq_os_fact_slots_key").returning(S.c.id)).first() is not None
    return RolloverResult(intake, previous, added)


def slot_report(engine: Engine, tenant_id: str, intake_id: int) -> list[SlotRow]:
    """Every expected slot of the intake with its state: `expected` until a fact exists for the intake's year (and
    term, or no recorded term), then that fact's status."""
    I = models.intakes
    q = (select(S, F.c.status, F.c.id.label("fact_id"))
         .select_from(S.join(I, and_(I.c.id == S.c.intake_id, I.c.tenant_id == S.c.tenant_id))
                      .outerjoin(F, and_(F.c.tenant_id == S.c.tenant_id, F.c.scope == S.c.scope, F.c.ref == S.c.ref,
                                         F.c.field == S.c.field, F.c.owner_ref == S.c.owner_ref,
                                         F.c.intake_term.in_([I.c.term, ""]), F.c.intake_year == I.c.year)))
         .where(S.c.tenant_id == tenant_id, S.c.intake_id == intake_id)
         .order_by(S.c.scope, S.c.ref, S.c.field, S.c.owner_ref))
    with engine.connect() as conn:
        rows = conn.execute(q).all()
    best: dict[tuple, object] = {}
    for r in rows:  # a fact whose term was never recorded ('') also fills the slot; the newest fact wins
        key = (r.scope, r.ref, r.field, r.owner_ref)
        if key not in best or (r.fact_id or 0) > (best[key].fact_id or 0):
            best[key] = r
    return [SlotRow(r.scope, r.ref, r.field, r.owner_ref, r.fact_class, r.status or "expected", r.fact_id)
            for r in best.values()]


EXPORT_COLUMNS = ("region", "family", "intake_term", "intake_year", "scope", "ref", "field", "owner_ref", "fact_class",
                  "previous_year", "previous_value", "previous_url", "previous_quote", "previous_status",
                  "new_value", "new_url", "new_quote")


def _cell(value) -> str:
    return "" if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)


def export_csv(engine: Engine, tenant_id: str, intake_id: int, path: Path) -> int:
    """Writes the intake's slots as a spreadsheet for the research batches: last year's value is filled in and
    labelled with its year; the `new_*` cells are empty. Returns the number of rows."""
    intake = IntakeStore(engine, tenant_id).by_id(intake_id)
    if intake is None:
        raise IntakeError(f"no intake {intake_id}")
    rows = slot_report(engine, tenant_id, intake_id)
    with engine.connect() as conn, path.open("w", newline="", encoding="utf-8") as fh:
        out = csv.DictWriter(fh, EXPORT_COLUMNS)
        out.writeheader()
        for r in rows:
            prev = conn.execute(select(F).where(
                F.c.tenant_id == tenant_id, F.c.scope == r.scope, F.c.ref == r.ref, F.c.field == r.field,
                F.c.owner_ref == r.owner_ref, F.c.intake_term == intake.term, F.c.intake_year < intake.year,
            ).order_by(F.c.intake_year.desc(), F.c.id.desc()).limit(1)).first()
            out.writerow({
                "region": intake.region, "family": intake.family, "intake_term": intake.term,
                "intake_year": intake.year, "scope": r.scope, "ref": r.ref, "field": r.field,
                "owner_ref": r.owner_ref, "fact_class": r.fact_class or "",
                "previous_year": prev.intake_year if prev else "", "previous_value": _cell(prev.value) if prev else "",
                "previous_url": prev.url if prev else "", "previous_quote": prev.quote if prev else "",
                "previous_status": prev.status if prev else "", "new_value": "", "new_url": "", "new_quote": "",
            })
    return len(rows)


@dataclass(frozen=True)
class Skipped:
    scope: str
    ref: str
    field: str
    intake_year: int
    reason: str  # unknown_ref | no_term | several_terms | key_taken


@dataclass(frozen=True)
class BackfillResult:
    updated: int
    skipped: list[Skipped]


def backfill_intake_terms(engine: Engine, tenant_id: str, playbooks: Mapping[tuple[str, int], Playbook]
                          ) -> BackfillResult:
    """P2-D5 / D-t1-1: facts from before P2 have `intake_term = ''`. Each gets the term its route's playbooks declare
    (`intake_terms`), when that is exactly one. A route with none or several, a ref that belongs to no known route,
    and a row whose new key is already taken are left alone and reported: no term is ever guessed."""
    terms_of: dict[str, set[str]] = {}
    for book in playbooks.values():
        terms_of.setdefault(book.key, set()).update(book.intake_terms)
    updated, skipped = 0, []
    with engine.begin() as conn:
        route_of = dict(conn.execute(select(models.programmes.c.ref, models.programmes.c.route_key).where(
            models.programmes.c.tenant_id == tenant_id)).all())
        rows = conn.execute(select(F).where(F.c.tenant_id == tenant_id, F.c.intake_term == "")
                            .order_by(F.c.id).with_for_update()).all()
        for r in rows:
            key = r.ref if r.scope == "route" else route_of.get(r.ref)
            terms = terms_of.get(key) if key is not None else None
            reason = ("unknown_ref" if terms is None else "no_term" if not terms
                      else "several_terms" if len(terms) > 1 else None)
            if reason is None:
                (term,) = terms
                taken = conn.execute(select(F.c.id).where(
                    F.c.tenant_id == tenant_id, F.c.scope == r.scope, F.c.ref == r.ref, F.c.field == r.field,
                    F.c.intake_term == term, F.c.intake_year == r.intake_year, F.c.owner_ref == r.owner_ref,
                )).first()
                if taken is not None:
                    reason = "key_taken"
            if reason is not None:
                skipped.append(Skipped(r.scope, r.ref, r.field, r.intake_year, reason))
                continue
            conn.execute(update(F).where(F.c.id == r.id).values(intake_term=term))
            updated += 1
    return BackfillResult(updated, skipped)
