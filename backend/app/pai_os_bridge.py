"""The glue between the Counsellor (PAI C) and PAI OS (PAI OS Slice 8 spec §2.7). Host code: the only file that
touches both products. Shared with the Counsellor team, who review every change.

- `deliver_pending(db, workspace_id)`: the roadmap router calls it right after a choice or withdrawal commits; the
  pending decision outbox rows go to PAI OS (stored there; the OS worker plans them while its `counsellor` module is on).
- `sweep_once(db)`, every 5 minutes in the API process (`start_sweep`): delivers what is still pending, queues the newest
  decision of a student PAI OS is behind on (version compare), then hands route problems PAI OS raised to the
  Counsellor's escalation code.
- PAI OS never reads Counsellor tables: this file reads the outbox and hands PAI OS the export. When PAI OS is not mounted, every function does nothing.
- `recipient_email(student_ref)` (PAI OS Slice 9b): the email a student signed up with, for PAI OS's reminders. The
  API gets it through `mount_os(recipient_lookup=)`, the worker through `OS_RECIPIENT_LOOKUP=app.pai_os_bridge:
  recipient_email`.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, func, select

from app.config import config
# Merge pai-c + pai-os: pai-c replaced the old decision-record table (migration 119) with `RouteDecision`
# (`pai_route_decisions`), which has the same id / workspace_id / chosen_at the sweep reads.
from app.models import OsOutbox, RouteDecision, User, Workspace
from app.os import ports
from app.os.ports import escalation as os_escalation
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.ports import plan_source
from app.pai_c.connect import outbox
from app.pai_c.connect.flags import part_on

log = logging.getLogger("app.pai_os_bridge")
SWEEP_SECONDS = 300
# The Counsellor's escalation endpoint takes three reasons today; the hand-over asks for the five shared ones. Until
# then the other three go as `route_not_possible`, with the fixed note saying which it is.
_TODAY = {"blocking_gap": "blocking_gap", "all_rejected": "all_rejected"}
REFUSED = {404, 409, 422}


def deliver_pending(db, workspace_id: str | None = None) -> dict:
    """Sends the pending `decision` outbox rows to PAI OS, oldest first, and commits its own status changes. An invalid
    payload is `not_sent` (`invalid_export`); `duplicate` and `module_off` count as delivered (the OS holds it). When
    PAI OS is not mounted the rows stay pending and the loop stops; any other error counts an attempt and goes on."""
    got = {"delivered": 0, "failed": 0, "not_sent": 0}
    if not part_on("CONNECT_HANDOFF"):
        return got
    for item in [i for i in outbox.pending_for(db, workspace_id) if i.kind == "decision"]:
        item_id = item.id
        try:
            DecisionRecordV2.model_validate(item.payload)
        except ValidationError:
            item.status, item.last_error = "not_sent", "invalid_export"
            db.commit()
            got["not_sent"] += 1
            continue
        try:
            plan_source.submit_decision(item.payload)
        except ports.OsUnavailable:
            break
        except Exception as exc:  # noqa: BLE001  (a code is kept, never the message; the sweep tries again)
            db.rollback()
            log.exception("PAI OS could not take outbox row %s", item_id)
            item = db.get(OsOutbox, item_id)
            item.attempts += 1
            item.last_error = type(exc).__name__
            db.commit()
            got["failed"] += 1
            continue
        item.status, item.last_error, item.delivered_at = "delivered", None, datetime.now(timezone.utc)
        db.commit()
        got["delivered"] += 1
    return got


def _backfill(db) -> None:
    """A student whose newest decision version is above the one PAI OS holds, and whose newest row has no outbox row
    (the decision was made while the part was off), gets that row now; a delivered row the OS lacks goes back to pending. Only the newest version is queued."""
    newest = (select(RouteDecision.workspace_id, func.max(RouteDecision.decision_version).label("version"))
              .group_by(RouteDecision.workspace_id).subquery())
    rows = db.scalars(select(RouteDecision).join(newest, and_(
        RouteDecision.workspace_id == newest.c.workspace_id,
        RouteDecision.decision_version == newest.c.version))).all()
    for row in rows:
        try:
            held = plan_source.latest_version(row.workspace_id)
            if held is not None and held >= row.decision_version:
                continue
            key = f"decision:{row.workspace_id}:{row.decision_version}"
            item = db.scalar(select(OsOutbox).where(OsOutbox.key == key))
            if item is None:
                outbox.record(db, row)
            elif item.status == "delivered":  # the OS is behind a version we sent: send it again (attempts untouched)
                item.status, item.delivered_at = "pending", None
            else:
                continue
            db.commit()
        except Exception as exc:  # noqa: BLE001  (one student never stops the others; class name only, no student data)
            db.rollback()
            log.error("PAI OS backfill failed for one student: %s", type(exc).__name__)


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
    delivered = failed = 0
    try:
        if part_on("CONNECT_HANDOFF"):
            first = deliver_pending(db)
            _backfill(db)
            second = deliver_pending(db)
            delivered = first["delivered"] + second["delivered"]
            failed = first["failed"] + second["failed"]
    except Exception:  # noqa: BLE001  (logged; escalations still go out, and the next sweep tries again)
        db.rollback()
        log.exception("PAI OS sweep could not deliver decisions")
        failed += 1
    return {"submitted": delivered, "failed": failed, **_deliver(db)}


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


def recipient_email(student_ref: str) -> str | None:
    """The email address of the student's PAI account: the active workspace `student_ref` names, then its owner. None
    for an unknown or inactive workspace and for one with no owner (agent-made or legacy); PAI OS then blocks the
    message as `no_address`. A database error raises, so PAI OS retries. Opens its own session: PAI OS calls it on its
    worker thread."""
    try:
        workspace_id = str(uuid.UUID(student_ref))
    except (TypeError, ValueError):
        return None
    from app.database import new_session

    with new_session() as db:
        return db.execute(select(User.email).join(Workspace, Workspace.owner_user_id == User.id)
                          .where(Workspace.id == workspace_id, Workspace.status == "active")).scalar_one_or_none()


def counsellor_module_on() -> bool:
    """True when the OS `counsellor` module is switched on. False when PAI OS is not mounted, and on any failure."""
    try:
        return bool(plan_source.counsellor_enabled())
    except ports.OsUnavailable:
        return False
    except Exception:
        log.exception("counsellor module switch could not be read; treated as off")
        return False


def route_supported(origin: str, destination: str, level: str) -> bool:
    """True when PAI OS has a playbook for the route. False when PAI OS is not mounted, and on any failure (logged)."""
    try:
        return bool(plan_source.supports(origin, destination, level))
    except ports.OsUnavailable:
        return False
    except Exception:
        log.exception("route support could not be read; treated as not supported")
        return False
