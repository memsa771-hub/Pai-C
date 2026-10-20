"""After a fact changes: complete the tasks waiting for it and revise the plans that use it (plan ruling R2-P4).

Used by the admin API (knowledge.manual), research and the freshness sweeper. Plans change only through the
kernel (invariant 1): `complete_review` and `service.recompile` (which calls `kernel.revise`). Only plans for
the fact's intake year are touched (handoff M17).
"""

from sqlalchemy import select

from app.os import models

T = models.tasks
P = models.plans


def after_fact_change(service, kernel, scope: str, ref: str, field: str, fact_id: int, status: str | None,
                      intake_year: int, complete: bool = True) -> list[int]:
    """Completes the fact's waiting confirm tasks (when `complete`) and revises every plan for `intake_year`
    that uses the fact.

    Research passes `complete=False` for an unconfirmed fact, and the sweeper for a stale one: their tasks keep
    waiting, but the plans still move to the new value. Returns the ids of plans that got a new revision.
    """
    year = P.c.contract["target_intake"]["year"].as_integer()
    in_year = select(P.c.id).where(P.c.tenant_id == kernel.tenant_id, year == intake_year)
    with service.engine.connect() as conn:
        waiting = conn.execute(select(T.c.id).where(
            T.c.tenant_id == kernel.tenant_id, T.c.instance_key == f"confirm_fact@{ref}:{field}",
            T.c.state == "waiting_review", T.c.plan_id.in_(in_year))).scalars().all()
        plan_ids = conn.execute(select(T.c.plan_id).distinct().where(
            T.c.tenant_id == kernel.tenant_id, T.c.fact_refs.contains([[scope, ref, field]]),
            T.c.plan_id.in_(in_year),
        ).order_by(T.c.plan_id)).scalars().all()
    if complete:
        for task_id in waiting:
            kernel.complete_review(task_id, {"fact_id": fact_id, "status": status})
    return [p for p in plan_ids if service.recompile(p, "fact_changed") is not None]
