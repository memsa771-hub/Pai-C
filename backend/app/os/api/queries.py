"""PlanQuery reads (reads are allowed outside the kernel; only writes are kernel-only)."""

from sqlalchemy import Engine, select

from app.os import models

T, P = models.tasks, models.plans


def task_out(row) -> dict:
    return {
        "id": row.id, "instance_key": row.instance_key, "title": row.title, "kind": row.kind,
        "inbox_kind": row.inbox_kind, "programme_ref": row.programme_ref, "state": row.state,
        "blocked_reason": row.blocked_reason, "due_at": row.due_at, "due_tz": row.due_tz,
        "provisional": row.provisional, "estimated": row.estimated, "slack_days": row.slack_days,
        "critical": row.critical, "citations": row.citations or [],
    }


def plan_out(engine: Engine, tenant_id: str, plan_id: int) -> dict | None:
    with engine.connect() as conn:
        plan = conn.execute(select(P).where(P.c.id == plan_id, P.c.tenant_id == tenant_id)).first()
        if plan is None:
            return None
        rows = conn.execute(select(T).where(T.c.plan_id == plan_id)
                            .order_by(T.c.due_at.asc().nulls_last(), T.c.instance_key)).all()
    return {"plan_id": plan.id, "revision": plan.current_revision, "status": plan.status,
            "tasks": [task_out(r) for r in rows]}


def inbox_items(engine: Engine, tenant_id: str, student_ref: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(T).join(P, P.c.id == T.c.plan_id).where(
            T.c.tenant_id == tenant_id, P.c.student_ref == student_ref, T.c.kind == "student",
            T.c.state == "waiting_student",
        ).order_by(T.c.due_at.asc().nulls_last(), T.c.id)).all()
    return [task_out(r) for r in rows]
