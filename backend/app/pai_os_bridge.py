"""The glue between the Counsellor (PAI C) and PAI OS (PAI OS Slice 8 spec §2.7). Host code: the only file that
touches both products. Shared with the Counsellor team, who review every change.

- `decision_changed(workspace_id)`: the Counsellor calls it after a student's choice; the student's current
  decision record export goes to PAI OS (stored there; the OS worker plans it while its `counsellor` module is on).
- `sweep_once(db)`, every 5 minutes in the API process (`start_sweep`): decisions chosen since the last mark are
  submitted again (a lost nudge never loses a choice), then route problems PAI OS raised are handed to the
  Counsellor's escalation code.
- PAI OS never reads Counsellor tables: this file reads the decision records and the Counsellor's export function,
  and hands PAI OS the export. When PAI OS is not mounted, every function does nothing.
"""

import asyncio
import importlib
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.config import config
from app.models import DecisionRecord
from app.os import ports
from app.os.ports import escalation as os_escalation
from app.os.ports import plan_source

log = logging.getLogger("app.pai_os_bridge")
SWEEP_SECONDS = 300
EXPORT_MODULE = "app.pai_c.os_export"  # built by the Counsellor team (hand-over doc); until then: no export
# The Counsellor's escalation endpoint takes three reasons today; the hand-over asks for the five shared ones. Until
# then the other three go as `route_not_possible`, with the fixed note saying which it is.
_TODAY = {"blocking_gap": "blocking_gap", "all_rejected": "all_rejected"}
REFUSED = {404, 409, 422}


def current_export(db, workspace_id: str) -> dict | None:
    """The student's current decision record export (`pai.decision_record.v1`), or None: "not ready for PAI OS"."""
    try:
        module = importlib.import_module(EXPORT_MODULE)
    except ModuleNotFoundError:
        return None
    return module.decision_record_v1(db, workspace_id)


def decision_changed(workspace_id: str, db=None) -> str | None:
    """Hands the student's current export to PAI OS: `stored`, `duplicate` or `module_off`; None when there is no
    export yet or PAI OS is not mounted."""
    if db is None:
        from app.database import SessionLocal

        with SessionLocal() as session:
            return decision_changed(workspace_id, session)
    export = current_export(db, workspace_id)
    if export is None:
        return None
    try:
        return plan_source.submit_counsellor_decision(export)
    except ports.OsUnavailable:
        return None


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _submit_since_mark(db) -> int:
    mark = plan_source.sweep_mark()
    after = (datetime.fromisoformat(mark["chosen_at"]), mark["decision_id"]) if mark else None
    rows = db.execute(select(DecisionRecord.id, DecisionRecord.workspace_id, DecisionRecord.chosen_at)
                      .order_by(DecisionRecord.chosen_at, DecisionRecord.id)).all()
    rows = [r for r in rows if after is None or (_aware(r.chosen_at), r.id) > after]
    submitted = 0
    for workspace_id in dict.fromkeys(r.workspace_id for r in rows):  # each student once, oldest change first
        export = current_export(db, workspace_id)
        if export is not None:
            plan_source.submit_counsellor_decision(export)
            submitted += 1
    if rows:
        last = max(rows, key=lambda r: (_aware(r.chosen_at), r.id))
        plan_source.set_sweep_mark({"chosen_at": _aware(last.chosen_at).isoformat(), "decision_id": last.id})
    return submitted


def _deliver(db) -> dict:
    from app.routers.escalations import EscalationInput, escalate

    got = {"sent": 0, "refused": 0, "waiting": 0}
    for e in os_escalation.pending_counsellor_escalations():
        if not config.PAI_OS_SERVICE_TOKEN:
            got["waiting"] += 1  # not configured: tried again on the next sweep
            continue
        try:
            body = EscalationInput(workspace_id=e.student_ref, journey_id=e.journey_id,
                                   reason_type=_TODAY.get(e.reason, "route_not_possible"), details=e.note)
            escalate(body, db, x_pai_service_token=config.PAI_OS_SERVICE_TOKEN)
        except ValidationError:
            db.rollback()
            os_escalation.mark_counsellor_delivery(e.key, "refused", "HTTP 422")
            got["refused"] += 1
        except HTTPException as err:
            db.rollback()
            if err.status_code in REFUSED:
                os_escalation.mark_counsellor_delivery(e.key, "refused", f"HTTP {err.status_code}")
                got["refused"] += 1
            else:
                got["waiting"] += 1
        else:
            os_escalation.mark_counsellor_delivery(e.key, "sent")
            got["sent"] += 1
    return got


def sweep_once(db) -> dict:
    try:
        ports.services()
    except ports.OsUnavailable:
        return {"mounted": False}
    return {"submitted": _submit_since_mark(db), **_deliver(db)}


def _sweep_with_session() -> dict:
    from app.database import SessionLocal

    with SessionLocal() as db:
        return sweep_once(db)


def start_sweep() -> asyncio.Task:
    """Started from the app's lifespan only when PAI OS is mounted. Several API replicas may sweep at once: a repeat
    submit is a duplicate and a delivered escalation is no longer pending (PAI OS Slice 8 S8-D9)."""
    async def loop() -> None:
        while True:
            try:
                await asyncio.to_thread(_sweep_with_session)
            except Exception:  # noqa: BLE001  (logged; swept again in 5 minutes)
                log.exception("PAI OS sweep failed")
            await asyncio.sleep(SWEEP_SECONDS)

    return asyncio.create_task(loop())
