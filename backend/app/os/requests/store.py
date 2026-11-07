"""One open request per student and fact (P1-T8, D-w9; R-19, master 9.3 rule 7).

`os_student_requests` is a view of the plan's request steps, kept in step with them: the kernel calls `sync` inside the
transaction that creates, revises or closes a plan, so a row never disagrees with its step. A unique partial index
holds "one open row per student and fact" even when two plans revise at once. A row holds codes, keys and IDs, never a
value (R-01). Nothing here changes a plan or a task (invariant 1)."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import clock, models
from app.os.kernel.states import PLAN_CLOSED, PLAN_OPEN, TERMINAL
from app.os.requests import keys

R, T, P = models.student_requests, models.tasks, models.plans
_TERMINAL = tuple(s.value for s in TERMINAL)
ANSWERED, CANCELLED, OPEN = "answered", "cancelled", "open"
LOCK_CLASS = 7108  # pg_advisory_xact_lock(LOCK_CLASS, hash of tenant and student); 7007 is the per-plan replan lock


@dataclass(frozen=True)
class Request:
    id: int
    student_ref: str
    plan_id: int
    task_id: int | None
    kind: str  # provide | which_is_right
    need_kind: str  # fact | document
    need_ref: str
    evidence: str
    status: str
    closed_cause: str | None
    created_at: datetime
    closed_at: datetime | None
    title: str | None  # the step's title, its due date and zone (None when the step row is gone)
    due_at: datetime | None
    due_tz: str | None


def _select():
    return select(R, T.c.title, T.c.due_at, T.c.due_tz).select_from(R.outerjoin(T, T.c.id == R.c.task_id))


def _request(row) -> Request:
    return Request(id=row.id, student_ref=row.student_ref, plan_id=row.plan_id, task_id=row.task_id, kind=row.kind,
                   need_kind=row.need_kind, need_ref=row.need_ref, evidence=row.evidence, status=row.status,
                   closed_cause=row.closed_cause, created_at=row.created_at, closed_at=row.closed_at,
                   title=row.title, due_at=row.due_at, due_tz=row.due_tz if row.due_at else None)


def _live_steps(conn: Connection, tenant_id: str, plan_ids: Collection[int]):
    """The request steps of those plans that are still open: `(task id, plan id, parsed key, instance key)`, oldest
    first."""
    rows = conn.execute(select(T.c.id, T.c.plan_id, T.c.instance_key).where(
        T.c.tenant_id == tenant_id, T.c.plan_id.in_(list(plan_ids)), T.c.template_key.in_(keys.REQUEST_KINDS),
        T.c.state.not_in(_TERMINAL)).order_by(T.c.id)).all()
    return [(r.id, r.plan_id, k, r.instance_key) for r in rows if (k := keys.parse(r.instance_key)) is not None]


def _lock_student(conn: Connection, tenant_id: str, student: str) -> None:
    """One sync per student at a time, until the caller's transaction ends. Every read below happens after this, so a
    sync sees what the one before it committed (READ COMMITTED), and two plans cannot open facts in opposite orders."""
    conn.execute(select(func.pg_advisory_xact_lock(LOCK_CLASS, func.hashtext(f"{tenant_id}:{student}"))))


def sync(conn: Connection, tenant_id: str, plan_id: int, answered: Collection[str] = (),
         now: datetime | None = None) -> None:
    """Brings the student's rows in line with their request steps, in the caller's transaction. Takes the student's
    lock first. Closes before it opens, so a level change (the "tell us" step done, the "upload" step new) never meets
    its own unique index.

    1. Close: an open row of the plan whose step is gone or finished is `answered` when the step is done (or its key is
       in `answered`), else `cancelled`. A cancelled row whose fact another open plan of the student still asks for
       moves to that plan's step instead, so the fact keeps its one open row.
    2. Open, student-wide: each unfinished request step of any open plan of the student whose fact has no open row gets
       one, at that step's level, in (kind, ref) order. A fact whose open row some plan holds is not opened again (the
       plans share the row), and a row answered at one plan's level is reopened at another plan's level at once."""
    now = now or clock.now()
    student = conn.execute(select(P.c.student_ref).where(P.c.id == plan_id, P.c.tenant_id == tenant_id)).scalar()
    if student is None:
        return
    _lock_student(conn, tenant_id, student)
    closed_plan = conn.execute(select(P.c.status).where(P.c.id == plan_id)).scalar() == PLAN_CLOSED
    done_keys = set(answered)
    steps = {r.id: r for r in conn.execute(select(T.c.id, T.c.instance_key, T.c.state).where(
        T.c.tenant_id == tenant_id, T.c.plan_id == plan_id, T.c.template_key.in_(keys.REQUEST_KINDS))).all()}
    others = None
    for row in conn.execute(select(R).where(R.c.tenant_id == tenant_id, R.c.plan_id == plan_id,
                                            R.c.status == OPEN).order_by(R.c.id)).all():
        step = steps.get(row.task_id)
        if step is not None and step.state not in _TERMINAL:
            if step.instance_key not in done_keys:
                continue  # the step still asks: the row stays open
            outcome = ANSWERED
        else:
            outcome = ANSWERED if step is not None and step.state == "done" else CANCELLED
        if outcome == CANCELLED:
            if others is None:
                others = _live_steps(conn, tenant_id, _other_open_plans(conn, tenant_id, student, plan_id))
            heir = next(((tid, pid, k) for tid, pid, k, _ in others
                         if (k.need_kind, k.ref) == (row.need_kind, row.need_ref)), None)
            if heir is not None:
                conn.execute(update(R).where(R.c.id == row.id).values(
                    plan_id=heir[1], task_id=heir[0], kind=heir[2].template, evidence=heir[2].level))
                continue
        cause = "request_answered" if outcome == ANSWERED else ("plan_closed" if closed_plan else "step_removed")
        conn.execute(update(R).where(R.c.id == row.id).values(status=outcome, closed_cause=cause, closed_at=now))
    held = {(r.need_kind, r.need_ref) for r in conn.execute(select(R.c.need_kind, R.c.need_ref).where(
        R.c.tenant_id == tenant_id, R.c.student_ref == student, R.c.status == OPEN)).all()}
    wanted: dict[tuple[str, str], tuple] = {}
    for task_id, pid, k, instance_key in _live_steps(conn, tenant_id, _open_plans(conn, tenant_id, student)):
        fact = (k.need_kind, k.ref)
        if fact in held or (pid == plan_id and instance_key in done_keys):
            continue  # asked already, or answered just now though its step has not closed
        if fact not in wanted or (pid == plan_id and wanted[fact][0] != plan_id):  # this plan's step first
            wanted[fact] = (pid, task_id, k)
    for fact in sorted(wanted):
        pid, task_id, k = wanted[fact]
        conn.execute(pg_insert(R).values(
            tenant_id=tenant_id, student_ref=student, plan_id=pid, task_id=task_id, kind=k.template,
            need_kind=k.need_kind, need_ref=k.ref, evidence=k.level, status=OPEN, created_at=now,
        ).on_conflict_do_nothing())  # the lock makes a clash impossible; the unique index still keeps one


def _open_plans(conn: Connection, tenant_id: str, student: str) -> list[int]:
    return list(conn.execute(select(P.c.id).where(
        P.c.tenant_id == tenant_id, P.c.student_ref == student, P.c.status.in_(PLAN_OPEN))).scalars().all())


def _other_open_plans(conn: Connection, tenant_id: str, student: str, plan_id: int) -> list[int]:
    return list(conn.execute(select(P.c.id).where(
        P.c.tenant_id == tenant_id, P.c.student_ref == student, P.c.id != plan_id, P.c.status.in_(PLAN_OPEN))
    ).scalars().all())


def open_for(engine: Engine, tenant_id: str, student_ref: str, answered_since: datetime | None = None
             ) -> list[Request]:
    """The student's open requests, and with `answered_since` also those answered at or after it. Oldest first."""
    keep = R.c.status == OPEN
    if answered_since is not None:
        keep = keep | ((R.c.status == ANSWERED) & (R.c.closed_at >= answered_since))
    with engine.connect() as conn:
        return [_request(r) for r in conn.execute(_select().where(
            R.c.tenant_id == tenant_id, R.c.student_ref == student_ref, keep).order_by(R.c.id)).all()]


def for_plan(conn: Connection, tenant_id: str, plan_id: int) -> list[Request]:
    """What the plan shows: its own open and answered rows, and the student's open rows (held by another plan) for
    facts this plan also asks for. Oldest first."""
    student = conn.execute(select(P.c.student_ref).where(P.c.id == plan_id, P.c.tenant_id == tenant_id)).scalar()
    if student is None:
        return []
    shared = {(k.need_kind, k.ref) for _, _, k, _ in _live_steps(conn, tenant_id, [plan_id])}
    rows = conn.execute(_select().where(R.c.tenant_id == tenant_id, R.c.student_ref == student).order_by(R.c.id)).all()
    return [_request(r) for r in rows
            if (r.plan_id == plan_id and r.status in (OPEN, ANSWERED))
            or (r.status == OPEN and (r.need_kind, r.need_ref) in shared)]


def get(engine: Engine, tenant_id: str, request_id: int) -> Request | None:
    with engine.connect() as conn:
        row = conn.execute(_select().where(R.c.tenant_id == tenant_id, R.c.id == request_id)).first()
    return _request(row) if row is not None else None


def duplicates(engine: Engine, tenant_id: str) -> list[tuple[str, str, str, int]]:
    """Students with more than one open request for one fact: `(student, need kind, need ref, count)`. The unique index
    makes this empty; it is the master 9.3 rule 7 check the scripted flow runs."""
    with engine.connect() as conn:
        return [(r.student_ref, r.need_kind, r.need_ref, r.n) for r in conn.execute(
            select(R.c.student_ref, R.c.need_kind, R.c.need_ref, func.count().label("n")).where(
                R.c.tenant_id == tenant_id, R.c.status == OPEN)
            .group_by(R.c.student_ref, R.c.need_kind, R.c.need_ref).having(func.count() > 1)).all()]
