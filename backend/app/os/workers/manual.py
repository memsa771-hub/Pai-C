"""knowledge.manual: an admin confirms or corrects a seeded fact (Slice 1; the research agent from Slice 2)."""

from sqlalchemy import select

from app.os import models
from app.os.kernel import Kernel
from app.os.knowledge import SqlKnowledge

T = models.tasks


def confirm_fact(service, knowledge: SqlKnowledge, kernel: Kernel, fact_id: int, **fields) -> list[int]:
    """Updates the fact, completes its open confirm task, and revises every plan that uses it.

    Returns the ids of plans that got a new revision.
    """
    scope, ref, field, _ = knowledge.get(fact_id)
    knowledge.confirm(fact_id, **fields)
    with service.engine.connect() as conn:
        waiting = conn.execute(select(T.c.id).where(
            T.c.tenant_id == kernel.tenant_id, T.c.instance_key == f"confirm_fact@{ref}:{field}",
            T.c.state == "waiting_review")).scalars().all()
        plan_ids = conn.execute(select(T.c.plan_id).distinct().where(
            T.c.tenant_id == kernel.tenant_id, T.c.fact_refs.contains([[scope, ref, field]]),
        ).order_by(T.c.plan_id)).scalars().all()
    for task_id in waiting:
        kernel.complete_review(task_id, {"fact_id": fact_id, "status": fields.get("status")})
    return [p for p in plan_ids if service.recompile(p, "fact_changed") is not None]
