"""After a fact changes: complete the tasks waiting for it and revise the plans that use it (plan ruling R2-P4).

Used by the admin API (knowledge.manual) and by research. Plans change only through the kernel (invariant 1):
`complete_review` and `service.recompile` (which calls `kernel.revise`).
"""

from sqlalchemy import select

from app.os import models

T = models.tasks


def after_fact_change(service, kernel, scope: str, ref: str, field: str, fact_id: int, status: str | None,
                      complete: bool = True) -> list[int]:
    """Completes the fact's waiting confirm tasks (when `complete`) and revises every plan that uses the fact.

    Research passes `complete=False` for an unconfirmed fact: its tasks keep waiting for an admin, but the
    plans still move to the new value. Returns the ids of plans that got a new revision.
    """
    with service.engine.connect() as conn:
        waiting = conn.execute(select(T.c.id).where(
            T.c.tenant_id == kernel.tenant_id, T.c.instance_key == f"confirm_fact@{ref}:{field}",
            T.c.state == "waiting_review")).scalars().all()
        plan_ids = conn.execute(select(T.c.plan_id).distinct().where(
            T.c.tenant_id == kernel.tenant_id, T.c.fact_refs.contains([[scope, ref, field]]),
        ).order_by(T.c.plan_id)).scalars().all()
    if complete:
        for task_id in waiting:
            kernel.complete_review(task_id, {"fact_id": fact_id, "status": status})
    return [p for p in plan_ids if service.recompile(p, "fact_changed") is not None]
