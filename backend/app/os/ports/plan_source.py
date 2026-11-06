"""The PlanSource port (Slice 8 spec §2.2, S8-D6): the host hands PAI OS a Counsellor decision export. It is only
stored here (one insert, no planning in the request); the worker's `counsellor.intake` job plans it. Submitting the
same decision again is harmless (S8-D9)."""

import hashlib
import json
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import clock, models, ports
from app.os.adapters.counsellor import manifest
from app.os.adapters.counsellor.escalation import applied_version
from app.os.adapters.counsellor.store import IntakeStore, SweepStore
from app.os.kernel.states import PLAN_OPEN
from app.os.playbooks import PlaybookError, select_playbook

_NEEDED = ("decision_id", "journey_id", "student_ref", "chosen_at")


def export_sha256(export: dict) -> str:
    canonical = json.dumps(export, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def submit_counsellor_decision(export: dict) -> Literal["stored", "duplicate", "module_off"]:
    """Stores the export as pending, even while the module is off (it waits until switched on). The rest of the
    export is checked by the worker, which refuses an invalid one with a reason; only an export missing what the
    intake row is keyed on cannot be stored (ValueError)."""
    missing = [k for k in _NEEDED if not export.get(k)]
    if missing:
        raise ValueError(f"export lacks {', '.join(missing)}")
    svc = ports.services()
    tenant = svc.settings.tenant_id
    stored = IntakeStore(svc.engine, tenant).add(export, export_sha256(export))
    if not manifest.is_enabled(svc.engine, tenant):
        return "module_off"
    return "stored" if stored else "duplicate"


def submit_decision(export: dict) -> Literal["stored", "duplicate", "module_off"]:
    """Like `submit_counsellor_decision` for a v2 export: it also needs `decision_version` and `status`, and stores
    them. Each version is a row of its own; the worker applies only versions newer than the newest applied."""
    missing = [k for k in ("decision_version", "status") if not export.get(k)]
    if missing:
        raise ValueError(f"export lacks {', '.join(missing)}")
    return submit_counsellor_decision(export)


def latest_version(student_ref: str) -> int | None:
    """The highest decision version stored for the student (None when none is)."""
    svc = ports.services()
    return IntakeStore(svc.engine, svc.settings.tenant_id).latest_version(student_ref)


def supports(origin: str, destination: str, level: str) -> bool:
    """Whether a playbook exists for the route (every level, intermediate too: D-u)."""
    try:
        select_playbook(ports.services().plans.playbooks, origin, destination, level)
    except PlaybookError:
        return False
    return True


def counsellor_enabled() -> bool:
    """Whether the `counsellor` module is on: while it is off the glue's sweep submits nothing (S8-D2)."""
    svc = ports.services()
    return manifest.is_enabled(svc.engine, svc.settings.tenant_id)


def sweep_mark() -> dict | None:
    """The glue's sweep position (the last chosen_at and decision ID it submitted)."""
    svc = ports.services()
    return SweepStore(svc.engine, svc.settings.tenant_id).mark()


def set_sweep_mark(mark: dict) -> None:
    svc = ports.services()
    SweepStore(svc.engine, svc.settings.tenant_id).set_mark(mark)


def pause_for_escalation(student_ref: str, decision_version: int | None, reason: str) -> bool:
    """The host sent an escalation to the Counsellor (D-x7): the student's open Counsellor plan is paused with the
    reason code. When a version is given, only a plan that has applied that version or a newer one is paused (the
    Counsellor refuses an escalation for a choice that was since changed; a plan that has not reached the version
    yet is not the one it is about). A plan already paused for a missing consent takes the escalation reason, which
    a later consent never replaces. False when there is no such plan or it is closed."""
    svc = ports.services()
    tenant = svc.settings.tenant_id
    P = models.plans
    with svc.engine.connect() as conn:
        ids = conn.execute(select(P.c.id).where(
            P.c.tenant_id == tenant, P.c.student_ref == student_ref, P.c.source == manifest.NAME,
            P.c.status.in_(PLAN_OPEN)).order_by(P.c.id.desc())).scalars().all()
    for plan_id in ids:
        held = applied_version(svc.engine, tenant, plan_id)
        if decision_version is None or (held is not None and held >= decision_version):
            return svc.kernel.pause_plan(plan_id, reason) or svc.kernel.set_pause_reason(plan_id, reason)
    return False


def request_adoption(student_ref: str, plan_id: int) -> Literal["recorded", "not_found", "module_off"]:
    """The student agreed to adopt their open self-serve plan as the Counsellor's plan (P1-T6, R-08, D-x6). The intent
    is one row per plan, keyed on the plan's contract as it is now; asking again renews it (idempotent). Intake adopts
    the plan only while the plan is still that contract and the Counsellor's decision is the same choice. `not_found`
    when the plan is not this student's, not open or not self-serve."""
    svc = ports.services()
    tenant = svc.settings.tenant_id
    if not manifest.is_enabled(svc.engine, tenant):
        return "module_off"
    P = models.plans
    with svc.engine.begin() as conn:
        sha = conn.execute(select(P.c.contract_sha256).where(
            P.c.id == plan_id, P.c.tenant_id == tenant, P.c.student_ref == student_ref, P.c.source == "self_serve",
            P.c.status.in_(PLAN_OPEN)).with_for_update()).scalar()
        if sha is None:
            return "not_found"
        A = models.plan_adoptions
        stmt = pg_insert(A).values(tenant_id=tenant, student_ref=student_ref, plan_id=plan_id, contract_sha256=sha,
                                   requested_at=clock.now())
        conn.execute(stmt.on_conflict_do_update(constraint="uq_os_plan_adoptions_plan", set_={
            "contract_sha256": sha, "requested_at": clock.now(), "adopted_at": None}))
    return "recorded"
