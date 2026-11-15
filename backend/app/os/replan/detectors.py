"""The R-39 replan events (master R-39, ADR-001 D12): found from registry and Knowledge fact changes and from the
student's answers to steps. What raises each one is data (`event_triggers.yaml`): a Knowledge field or a fact class,
never a region, body or institution name (invariant 12).

Trust: the event records the fact's status (`confirmed`). A fact that only lost trust (same value, now unconfirmed or
stale) raises nothing; the recheck rules already hold the steps it dates (P2-D20). The rules give these events no plan
change of their own (rules.RECORD_ONLY), so an unconfirmed fact never moves a plan through them; the compiler's own
trust rules (a step dated by an unconfirmed fact stays provisional) are unchanged.

Nothing here writes to the Counsellor's outbox: these events are not chat messages (R-45)."""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import yaml
from sqlalchemy import Connection, Engine, desc, select

from app.os import models
from app.os.knowledge.fact_classes import classes, fact_class
from app.os.knowledge.port import CONFIRMED_LEVELS
from app.os.replan import events as ev

log = logging.getLogger("app.os.replan.detectors")
TRIGGERS_FILE = Path(__file__).with_name("event_triggers.yaml")
PUBLISHED, NOT_LISTED, NEXT_ROUND = "merit_list.published", "merit_list.not_listed", "merit_list.next_round"
FEE_DUE, RESULT, SCHEDULE = "fee_deposit.due", "test.result_published", "admission.schedule_changed"
R39 = (PUBLISHED, NOT_LISTED, NEXT_ROUND, FEE_DUE, RESULT, SCHEDULE)
F, RV, T, P = models.knowledge_facts, models.fact_revisions, models.tasks, models.plans
CLOSED = ("done", "cancelled", "skipped")


@dataclass(frozen=True)
class Triggers:
    merit_list_fields: frozenset[str]
    result_fields: frozenset[str]
    fee_classes: frozenset[str]
    schedule_classes: frozenset[str]
    answers: Mapping[str, Mapping[str, object]]  # event type -> the values an answer must carry


@cache
def triggers(path: Path = TRIGGERS_FILE) -> Triggers:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    facts, answers = raw.get("facts") or {}, raw.get("answers") or {}
    known = classes()
    got = Triggers(frozenset(facts.get("merit_list_fields") or ()), frozenset(facts.get("result_fields") or ()),
                   frozenset(facts.get("fee_classes") or ()), frozenset(facts.get("schedule_classes") or ()),
                   {k: dict(v) for k, v in answers.items()})
    bad = sorted(c for c in got.fee_classes | got.schedule_classes if c not in known)
    if bad:
        raise ValueError(f"{path.name}: unknown fact classes {bad}")
    stray = sorted(k for k in got.answers if k not in R39 or not got.answers[k])
    if stray:
        raise ValueError(f"{path.name}: answers name no R-39 event or no value: {stray}")
    return got


def day_of(value) -> date | None:
    """The day of a date fact ("YYYY-MM-DD" or {"date": ...}); None for any other value (an amount, a text)."""
    raw = value.get("date") if isinstance(value, dict) else value
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Found:
    type: str
    previous: date | None
    day: date


def found(field: str, cls: str, old_value, new_value, today: date, trig: Triggers | None = None) -> list[Found]:
    """The R-39 events one change of a date fact gives (pure). `old_value` is None for a new fact."""
    trig = trig or triggers()
    new, old = day_of(new_value), day_of(old_value)
    if new is None:
        return []
    out: list[Found] = []
    next_round = field in trig.merit_list_fields and old is not None and old <= today and new > old
    if next_round:
        out.append(Found(NEXT_ROUND, old, new))
    elif field in trig.merit_list_fields and new <= today:
        out.append(Found(PUBLISHED, old, new))
    if field in trig.result_fields and new <= today:
        out.append(Found(RESULT, old, new))
    if cls in trig.fee_classes and old != new:
        out.append(Found(FEE_DUE, old, new))
    if cls in trig.schedule_classes and old is not None and old != new and not next_round:
        out.append(Found(SCHEDULE, old, new))
    return out


def _change(conn: Connection, tenant_id: str, fact_id: int):
    """(before, after) of the fact's last revision, as stored snapshots; (None, row) when it has none."""
    rv = conn.execute(select(RV.c.before, RV.c.after, RV.c.action).where(
        RV.c.tenant_id == tenant_id, RV.c.fact_id == fact_id).order_by(desc(RV.c.id)).limit(1)).first()
    if rv is not None:
        return rv.before, rv.after, rv.action
    row = conn.execute(select(F.c.value, F.c.status, F.c.fact_class).where(F.c.id == fact_id)).first()
    if row is None:
        return None, None, None
    return None, {"value": row.value, "status": row.status, "fact_class": row.fact_class}, "insert"


def _record(conn: Connection, tenant_id: str, plan_id: int, f: Found, scope: str, ref: str, field: str,
            fact_id: int | None, status: str | None, intake_year: int) -> bool:
    confirmed = status in CONFIRMED_LEVELS
    moved = f"{f.previous.isoformat() if f.previous else 'none'}>" if f.type in (SCHEDULE, NEXT_ROUND, FEE_DUE) else ""
    dedupe = f"{scope}:{ref}:{field}:{intake_year}:{moved}{f.day.isoformat()}" + ("" if confirmed else ":unconfirmed")
    payload = {"scope": scope, "ref": ref, "field": field, "fact_id": fact_id, "intake_year": intake_year,
               "date": f.day.isoformat(), "previous": f.previous.isoformat() if f.previous else None,
               "status": status, "confirmed": confirmed, "text": f.type,
               "programme_ref": ref if scope == "programme" else None}
    return ev.record(conn, tenant_id, plan_id, f.type, payload, dedupe) is not None


def on_fact_change(engine: Engine, tenant_id: str, plan_ids: Iterable[int], scope: str, ref: str, field: str,
                   fact_id: int, intake_year: int, today: date) -> int:
    """Records the R-39 events of a fact change on each plan that uses the fact (`after_fact_change`, row 6.10).
    Returns how many were recorded."""
    plan_ids = list(plan_ids)
    if not plan_ids:
        return 0
    with engine.connect() as conn:
        before, after, action = _change(conn, tenant_id, fact_id)
    if after is None:
        return 0
    status = after.get("status")
    if action == "status" and status not in CONFIRMED_LEVELS:
        return 0  # trust only dropped: the recheck rules hold the steps (P2-D20); no new event
    cls = fact_class(field, after.get("fact_class"))
    hits = found(field, cls, before.get("value") if before else None, after.get("value"), today)
    recorded = 0
    for plan_id in plan_ids:
        with engine.begin() as conn:
            recorded += sum(_record(conn, tenant_id, plan_id, f, scope, ref, field, fact_id, status, intake_year)
                            for f in hits)
    return recorded


def detect_reached(engine: Engine, tenant_id: str, plan_id: int, today: date) -> int:
    """The replan sweep: `merit_list.published` and `test.result_published` for each list or result day of a fact the
    plan's open steps use that has now come (no fact changed, the day arrived). Deduped as on a fact change."""
    trig = triggers()
    fields = sorted(trig.merit_list_fields | trig.result_fields)
    with engine.connect() as conn:
        year = conn.execute(select(P.c.contract["target_intake"]["year"].as_integer()).where(
            P.c.tenant_id == tenant_id, P.c.id == plan_id)).scalar()
        refs = conn.execute(select(T.c.fact_refs).where(
            T.c.tenant_id == tenant_id, T.c.plan_id == plan_id, T.c.state.not_in(CLOSED))).scalars().all()
        used = {tuple(r) for rs in refs for r in (rs or []) if len(r) == 3 and r[2] in fields}
        if year is None or not used:
            return 0
        rows = conn.execute(select(F.c.id, F.c.scope, F.c.ref, F.c.field, F.c.value, F.c.status, F.c.fact_class).where(
            F.c.tenant_id == tenant_id, F.c.intake_year == year, F.c.owner_ref == "",
            F.c.field.in_(fields)).order_by(F.c.id)).all()
    recorded = 0
    for r in rows:
        if (r.scope, r.ref, r.field) not in used or r.status == "stale":  # a stale fact says nothing about today
            continue
        hits = [f for f in found(r.field, fact_class(r.field, r.fact_class), r.value, r.value, today)
                if f.type in (PUBLISHED, RESULT)]
        with engine.begin() as conn:
            recorded += sum(_record(conn, tenant_id, plan_id, Found(f.type, None, f.day), r.scope, r.ref, r.field,
                                    r.id, r.status, year) for f in hits)
    return recorded


def on_answer(conn: Connection, tenant_id: str, plan_id: int, task_id: int, instance_key: str,
              programme_ref: str | None, answer: Mapping) -> int:
    """The R-39 events the student's answer to a step gives (in the kernel's transaction). Returns how many."""
    recorded = 0
    for type_, want in triggers().answers.items():
        if all(answer.get(k) == v for k, v in want.items()):
            recorded += ev.record(conn, tenant_id, plan_id, type_,
                                  {"programme_ref": programme_ref, "instance_key": instance_key, "text": type_},
                                  f"task:{task_id}", task_id) is not None
    return recorded
