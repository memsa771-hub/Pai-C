"""Deadline engine: recompiles every active plan; dates and slack change only through kernel revisions."""

from sqlalchemy import Engine, select

from app.os import models


def run(service, engine: Engine) -> int:
    """Returns the number of plans that got a new revision."""
    with engine.connect() as conn:
        plan_ids = conn.execute(select(models.plans.c.id).where(
            models.plans.c.tenant_id == service.kernel.tenant_id,
            models.plans.c.status.in_(("active", "at_risk")),
        ).order_by(models.plans.c.id)).scalars().all()
    return sum(1 for plan_id in plan_ids if service.recompile(plan_id, "deadline_recompute") is not None)
