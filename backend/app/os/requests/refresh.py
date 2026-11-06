"""Recompiles a student's plans when something that decides their requests changed (P1-T8, D-w8, D-w10): a document was
confirmed, deleted or its finding resolved, or an answer arrived. One recompile per open plan whose pinned playbook
declares `needs`; the kernel closes the answered request steps in that revision, so the plan, the inbox, the reminders
and the app notice all follow one change."""

import logging

from sqlalchemy import select

from app.os import models
from app.os.kernel.states import PLAN_OPEN
from app.os.requests import gate

log = logging.getLogger("app.os.requests.refresh")


def refresh(svc, student_ref: str, cause: str) -> int:
    """How many plans were revised. Nothing happens while the needs gate is off. A plan that cannot be recompiled is
    logged by error type only and left for the hourly recompile: the caller's own change has already been saved."""
    plans = svc.plans
    tenant = plans.kernel.tenant_id
    if gate.on(student_ref, engine=plans.engine, tenant_id=tenant) is None:
        return 0
    P = models.plans
    with plans.engine.connect() as conn:
        open_plans = conn.execute(select(P.c.id).where(
            P.c.tenant_id == tenant, P.c.student_ref == student_ref, P.c.status.in_(PLAN_OPEN)).order_by(P.c.id)
        ).scalars().all()
    revised = 0
    for plan_id in open_plans:
        try:
            if plans._pinned(plan_id).declares_needs and plans.recompile(plan_id, cause) is not None:
                revised += 1
        except Exception as e:  # noqa: BLE001  (never turn a saved change into an error; the hourly job is the backup)
            log.error("recompile after %s failed (%s)", cause, type(e).__name__)
    return revised
