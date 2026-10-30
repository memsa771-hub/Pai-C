"""PlanSummary v1 (Slice 8 spec §2.4, S8-D13): what the Counsellor may show of a student's PAI OS plan. Built from
the plan on every read, never stored, read-only. It holds step names, dates and codes only: no document values,
answers, statement text, admin notes or Supervisor reasons."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, exists, select

from app.os import models
from app.os.contracts.plan_summary import BlockedItem, Deadline, PlanSummaryV1, SummaryRoute, WaitingItem
from app.os.kernel.states import PLAN_CLOSED, TERMINAL

P, T, PR, C = models.plans, models.tasks, models.proposals, models.support_cases
_CODE = re.compile(r"^[a-z_]+$")
_OVER = [s.value for s in TERMINAL]


def _plan(conn, tenant_id: str, student_ref: str):
    """The student's newest plan still being worked on; else their newest finished one; never a closed one."""
    mine = select(P).where(P.c.tenant_id == tenant_id, P.c.student_ref == student_ref)
    row = conn.execute(mine.where(P.c.status.not_in(("done", PLAN_CLOSED))).order_by(P.c.id.desc())).first()
    return row or conn.execute(mine.where(P.c.status == "done").order_by(P.c.id.desc())).first()


def _local(at: datetime | None, tz: str | None) -> datetime | None:
    return at.astimezone(ZoneInfo(tz)) if at is not None and tz else at


def build_summary(engine: Engine, tenant_id: str, student_ref: str, now: datetime) -> PlanSummaryV1 | None:
    with engine.connect() as conn:
        plan = _plan(conn, tenant_id, student_ref)
        if plan is None:
            return None
        tasks = conn.execute(select(T).where(T.c.tenant_id == tenant_id, T.c.plan_id == plan.id)
                             .order_by(T.c.due_at.asc().nulls_last(), T.c.id)).all()
        proposal = conn.execute(select(exists().where(PR.c.tenant_id == tenant_id, PR.c.plan_id == plan.id,
                                                      PR.c.status == "pending"))).scalar()
        case_open = conn.execute(select(exists().where(C.c.tenant_id == tenant_id, C.c.plan_id == plan.id,
                                                       C.c.status == "open"))).scalar()
    waiting = [WaitingItem(title=t.title, template_key=t.template_key, programme_ref=t.programme_ref,
                           due_at=_local(t.due_at, t.due_tz), due_tz=t.due_tz if t.due_at else None)
               for t in tasks if t.kind == "student" and t.state == "waiting_student"]
    if plan.status == "done":
        state = "finished"
    elif plan.status == "paused" or plan.changes_paused:
        state = "paused"
    elif waiting or proposal:
        state = "needs_student"
    else:
        state = "on_track"
    deadlines = [Deadline(title=t.title, template_key=t.template_key, programme_ref=t.programme_ref,
                          due_at=_local(t.due_at, t.due_tz), due_tz=t.due_tz)
                 for t in tasks if t.state not in _OVER and t.due_at is not None and t.due_at > now][:3]
    blocked = [BlockedItem(title=t.title, template_key=t.template_key,
                           reason=t.blocked_reason if t.blocked_reason and _CODE.match(t.blocked_reason) else "blocked")
               for t in tasks if t.state == "blocked"]
    c = plan.contract
    return PlanSummaryV1(
        student_ref=student_ref, plan_id=plan.id, built_at=now, state=state,
        route=SummaryRoute(origin_country=c["origin_country"], destination_country=c["destination_country"],
                           level=c["level"], target_intake=c["target_intake"]),
        next_deadlines=deadlines, waiting_on_student=waiting, blocked=blocked, support_case_open=bool(case_open))
