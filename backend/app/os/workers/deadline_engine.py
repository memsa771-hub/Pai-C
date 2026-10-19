"""Deadline engine: recompiles every active plan; dates and slack change only through kernel revisions."""

import logging

from sqlalchemy import Engine, insert, select

from app.os import models

log = logging.getLogger("app.os.deadline_engine")


def run(service, engine: Engine) -> int:
    """Returns the number of plans that got a new revision. A plan that fails is logged as a
    `recompute_failed` event and skipped, so one bad plan never stops the others (review I3)."""
    tenant = service.kernel.tenant_id
    with engine.connect() as conn:
        plan_ids = conn.execute(select(models.plans.c.id).where(
            models.plans.c.tenant_id == tenant, models.plans.c.status.in_(("active", "at_risk")),
        ).order_by(models.plans.c.id)).scalars().all()
    revised = 0
    for plan_id in plan_ids:
        try:
            if service.recompile(plan_id, "deadline_recompute") is not None:
                revised += 1
        except Exception as e:  # noqa: BLE001  (isolate the failure; it is recorded, not retried)
            log.exception("recompute failed for plan %s", plan_id)
            with engine.begin() as conn:
                conn.execute(insert(models.events).values(
                    tenant_id=tenant, plan_id=plan_id, type="recompute_failed",
                    payload={"error": f"{type(e).__name__}: {e}"}))
    return revised
