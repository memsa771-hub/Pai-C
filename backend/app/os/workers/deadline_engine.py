"""Deadline engine: recompiles every active plan; dates and slack change only through kernel revisions. Slice 7: it
also records the replan events it sees: a critical step past its deadline, and a plan that no longer compiles."""

import logging

from sqlalchemy import Engine, insert, select

from app.os import models
from app.os.compiler import CompileError
from app.os.replan import events

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
            events.detect_at_risk(engine, tenant, plan_id)
        except CompileError as e:  # the route no longer works for this plan (S7-D2 route_invalid)
            log.warning("plan %s no longer compiles: %s", plan_id, e)
            with engine.begin() as conn:
                sha = conn.execute(select(models.plans.c.contract_sha256).where(
                    models.plans.c.id == plan_id)).scalar_one()
                events.record(conn, tenant, plan_id, "route_invalid", {"error": str(e)[:300]}, f"{sha}:{e}"[:200])
        except Exception as e:  # noqa: BLE001  (isolate the failure; it is recorded, not retried)
            log.exception("recompute failed for plan %s", plan_id)
            with engine.begin() as conn:
                conn.execute(insert(models.events).values(
                    tenant_id=tenant, plan_id=plan_id, type="recompute_failed",
                    payload={"error": f"{type(e).__name__}: {e}"}))
    return revised
