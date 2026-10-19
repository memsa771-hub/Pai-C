"""Inbox reminders on the parent spec's cadence (§3.2), written to the outbox with a slot key."""

from datetime import datetime, timedelta

from sqlalchemy import Engine, insert, select

from app.os import models
from app.os.outbox import Outbox

T, P = models.tasks, models.plans


def reminder_slot(now: datetime, due_at: datetime | None, slack_days: int | None) -> str | None:
    """The cadence window `now` falls in. One reminder per task per window (the outbox key holds it)."""
    if due_at is None:
        return None
    left = due_at - now
    if left <= timedelta(0):
        return f"esc:{now:%Y-%m-%d}"
    if left < timedelta(hours=48):
        return f"h12:{now:%Y-%m-%d}:{now.hour // 12}"
    if slack_days is None:
        return None
    if slack_days > 14:
        return f"w:{now:%G-%V}"
    if slack_days >= 7:
        return f"d3:{now.toordinal() // 3}"
    return f"d:{now:%Y-%m-%d}"


def run_reminders(engine: Engine, outbox: Outbox, now: datetime, tenant_id: str) -> int:
    with engine.connect() as conn:
        rows = conn.execute(select(T.c.id, T.c.plan_id, T.c.title, T.c.due_at, T.c.due_tz, T.c.slack_days,
                                   P.c.student_ref).join(P, P.c.id == T.c.plan_id).where(
            T.c.tenant_id == tenant_id, T.c.state == "waiting_student", T.c.due_at.is_not(None),
        ).order_by(T.c.id)).all()
    added = 0
    for r in rows:
        slot = reminder_slot(now, r.due_at, r.slack_days)
        if slot is None:
            continue
        payload = {"task_id": r.id, "title": r.title, "due_at": r.due_at.isoformat(), "due_tz": r.due_tz,
                   "slot": slot}
        if outbox.add(f"reminder:{r.id}:{slot}", "email", r.student_ref, "inbox_reminder", payload):
            added += 1
            if slot.startswith("esc:"):  # slack is gone: Slice 7's rules act on this event
                with engine.begin() as conn:
                    conn.execute(insert(models.events).values(
                        tenant_id=tenant_id, plan_id=r.plan_id, task_id=r.id, type="escalate", payload=payload))
    return added
