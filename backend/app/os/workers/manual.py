"""knowledge.manual: an admin confirms, corrects or supplies a fact (Slice 1; the research agent from Slice 2)."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.os import models
from app.os.compiler import CONFIRM_TYPE
from app.os.kernel import TERMINAL, Kernel
from app.os.knowledge import Fact, SqlKnowledge

T = models.tasks


def _after_fact_change(service, kernel: Kernel, scope: str, ref: str, field: str, fact_id: int,
                       status: str) -> list[int]:
    """Completes the fact's waiting confirm tasks and revises every plan that uses the fact."""
    with service.engine.connect() as conn:
        waiting = conn.execute(select(T.c.id).where(
            T.c.tenant_id == kernel.tenant_id, T.c.instance_key == f"confirm_fact@{ref}:{field}",
            T.c.state == "waiting_review")).scalars().all()
        plan_ids = conn.execute(select(T.c.plan_id).distinct().where(
            T.c.tenant_id == kernel.tenant_id, T.c.fact_refs.contains([[scope, ref, field]]),
        ).order_by(T.c.plan_id)).scalars().all()
    for task_id in waiting:
        kernel.complete_review(task_id, {"fact_id": fact_id, "status": status})
    return [p for p in plan_ids if service.recompile(p, "fact_changed") is not None]


def confirm_fact(service, knowledge: SqlKnowledge, kernel: Kernel, fact_id: int, **fields) -> list[int]:
    """Confirms or corrects an existing fact by id. The value is checked before anything is stored.

    Returns the ids of plans that got a new revision.
    """
    scope, ref, field, _ = knowledge.get(fact_id)
    service.check_fact_value(field, fields.get("value"))
    knowledge.confirm(fact_id, **fields)
    return _after_fact_change(service, kernel, scope, ref, field, fact_id, fields.get("status"))


def supply_fact(service, knowledge: SqlKnowledge, kernel: Kernel, *, scope: str, ref: str, field: str,
                intake_year: int, value, quote: str, url: str, status: str,
                conflict_note: str | None = None) -> list[int]:
    """Adds or replaces a fact by its key, e.g. one that was never seeded (review I2)."""
    service.check_fact_value(field, value)
    fact = Fact(value=value, quote=quote, url=url, checked_at=datetime.now(timezone.utc),
                intake_year=intake_year, status=status, conflict_note=conflict_note)  # validates trust rules
    fact_id = knowledge.upsert(scope, ref, field, fact)
    return _after_fact_change(service, kernel, scope, ref, field, fact_id, status)


def open_confirm_tasks(engine, tenant_id: str) -> list[dict]:
    """Facts the plans are waiting for: every confirm_fact task that is not finished."""
    with engine.connect() as conn:
        rows = conn.execute(select(T.c.id, T.c.plan_id, T.c.instance_key, T.c.state, T.c.fact_refs).where(
            T.c.tenant_id == tenant_id, T.c.task_type == CONFIRM_TYPE,
            T.c.state.not_in([s.value for s in TERMINAL]),
        ).order_by(T.c.plan_id, T.c.id)).all()
    items = []
    for r in rows:
        scope, ref, field = r.fact_refs[0]
        items.append({"task_id": r.id, "plan_id": r.plan_id, "instance_key": r.instance_key, "state": r.state,
                      "scope": scope, "ref": ref, "field": field})
    return items
