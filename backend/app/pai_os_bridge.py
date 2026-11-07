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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, func, select

from app.config import config
# Merge pai-c + pai-os: pai-c replaced the old decision-record table (migration 119) with `RouteDecision`
# (`pai_route_decisions`), which has the same id / workspace_id / chosen_at the sweep reads.
from app.models import OsOutbox, RouteDecision, User, VaultVersion, Workspace
from app.os import ports
from app.os.ports import choice_requests as os_choice_requests
from app.os.ports import escalation as os_escalation
from app.os.ports import os_events as os_events_port
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.ports import document_files as os_document_files, plan_source, student_facts as os_student_facts
from app.os.ports import fact_proposals as os_fact_proposals
from app.os.contracts.vault_event import VaultEventV1
from app.pai_c.connect import outbox
from app.pai_c.connect.flags import part_on

log = logging.getLogger("app.pai_os_bridge")
SWEEP_SECONDS = 300
# The Counsellor's escalation endpoint takes three reasons today; the hand-over asks for the five shared ones. Until
# then the other three go as `route_not_possible`, with the fixed note saying which it is.
_TODAY = {"blocking_gap": "blocking_gap", "all_rejected": "all_rejected"}
REFUSED = {404, 409, 422}


def deliver_pending(db, workspace_id: str | None = None) -> dict:
    """Sends the pending `decision` outbox rows to PAI OS (while CONNECT_HANDOFF is on) and the pending `vault_event`
    rows (while CONNECT_STUDENT_FACTS is on), oldest first, and commits its own status changes. An invalid payload is
    `not_sent` (`invalid_export`); `duplicate` and `module_off` count as delivered (the OS holds it). When PAI OS is
    not mounted the rows stay pending and the loop stops; any other error counts an attempt and goes on."""
    got = {"delivered": 0, "failed": 0, "not_sent": 0}
    kinds = {kind: (contract, send) for kind, part, contract, send in (
        ("decision", "CONNECT_HANDOFF", DecisionRecordV2, lambda p: plan_source.submit_decision(p)),
        ("vault_event", "CONNECT_STUDENT_FACTS", VaultEventV1, lambda p: os_student_facts.record_event(p))) if part_on(part)}
    if not kinds:
        return got
    for item in [i for i in outbox.pending_for(db, workspace_id) if i.kind in kinds]:
        item_id = item.id
        contract, send = kinds[item.kind]
        try:
            contract.model_validate(item.payload)
        except ValidationError:
            item.status, item.last_error = "not_sent", "invalid_export"
            db.commit()
            got["not_sent"] += 1
            continue
        try:
            send(item.payload)
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


def choice_enabled() -> bool:
    """True when the OS may send choice requests to the Counsellor: the hand-off part is on (P1-T6, R-07). The OS reads
    it through `mount_os(choice_enabled=)`; it cannot read host flags itself."""
    return part_on("CONNECT_HANDOFF")


def my_plan_enabled() -> bool:
    """True when the My plan part is on (P1-T9, R-53). The OS reads it through `mount_os(my_plan_enabled=)`; it cannot
    read host flags itself."""
    return part_on("CONNECT_MY_PLAN")


def request_choice(student_ref: str, origin: str, destination: str, level: str, intake: dict,
                   choices: list[dict]) -> dict | None:
    """The route builder's ChoiceSink (P1-T6, R-09): with the hand-off part on, the student's route, intake and places
    are written through the decision service and the new version goes to PAI OS. None while the part is off (then the
    builder works standalone). Opens its own session: PAI OS calls it from a request thread. Returns `{"outcome":
    "written" | "unchanged" | "refused", "decision_version", "code"}`; an error rolls back and is raised, so nothing
    is half written."""
    if not choice_enabled():
        return None
    from app.database import new_session
    from app.pai_c.roadmap.decisions import RouteDecisionService  # lazy: decisions.py imports this module

    try:
        workspace_id = str(uuid.UUID(student_ref))
    except (TypeError, ValueError):
        return {"outcome": "refused", "decision_version": None, "code": "choose_field_first"}
    with new_session() as db:
        try:
            outcome, version, code = RouteDecisionService(db).request_from_builder(
                workspace_id, origin, destination, level, intake, choices)
            db.commit()
        except Exception:
            db.rollback()
            raise
        if outcome in ("written", "unchanged"):
            try:  # best effort: the decision is committed, and the sweep delivers it anyway
                deliver_pending(db, workspace_id)
            except Exception as exc:  # noqa: BLE001
                log.error("PAI OS could not take the builder's decision now: %s", type(exc).__name__)
    return {"outcome": outcome, "decision_version": version, "code": code}


def self_serve_plan(workspace_id: str, journey_id: str | None = None) -> dict | None:
    """The student's open self-serve plan as `plan_query.self_serve_plan` gives it (P1-T6, R-08), for the adoption offer.
    `journey_id` is the student's active journey: without it the plan never reads as `identity_taken`.
    None when there is none, when the `counsellor` module is off, when PAI OS is not mounted and on any failure (logged by
    type only)."""
    if not counsellor_module_on():
        return None
    try:
        from app.os.ports import plan_query

        return plan_query.self_serve_plan(str(workspace_id), journey_id)
    except ports.OsUnavailable:
        return None
    except Exception as exc:  # noqa: BLE001
        log.error("the self-serve plan could not be read: %s", type(exc).__name__)
        return None


def request_adoption(workspace_id: str, plan_id: int, contract_sha256: str) -> str:
    """Records the student's agreement to adopt their self-serve plan on the OS side (P1-T6, R-08): "recorded",
    "not_found", "changed" (the plan is no longer the contract `contract_sha256` that was offered) or "module_off". "module_off" too when PAI OS is not mounted. Raises on any other failure, so the caller
    writes no decision for an agreement the OS did not take."""
    try:
        return plan_source.request_adoption(str(workspace_id), plan_id, contract_sha256)
    except ports.OsUnavailable:
        return "module_off"


def _deliver_choice_request(db, request) -> str:
    """Hands one choice request to the decision service and marks the answer on the OS side. The app transaction
    commits first, then the new version goes to the OS, then the OS is told (a crash in between repeats harmlessly:
    the request key makes the repeat a `duplicate`). Returns the outcome; an exception rolls back and leaves the row
    pending."""
    from app.pai_c.roadmap.decisions import RouteDecisionService  # lazy: decisions.py imports this module

    if not os_choice_requests.is_open(request.key):  # its proposal moved on: never applied again
        os_choice_requests.mark_delivery(request.key, "skipped")
        return "skipped"
    try:
        workspace_id = str(uuid.UUID(request.student_ref))
    except ValueError:
        outcome, detail = "refused", "no_decision"
    else:
        try:
            outcome, detail = RouteDecisionService(db).apply_choice_request(
                workspace_id, request.model_dump(mode="json", by_alias=True))
            db.commit()
        except Exception:
            db.rollback()
            raise
        if outcome in ("written", "duplicate"):
            deliver_pending(db, workspace_id)
    os_choice_requests.mark_delivery(request.key, outcome, detail if outcome in ("written", "duplicate") else None)
    return outcome


def deliver_choice_requests(db) -> dict:
    """Delivers the pending choice requests, oldest first (P1-T6, R-07). Only while CONNECT_HANDOFF is on. One failure
    leaves its row pending and never stops the others."""
    got = {"written": 0, "duplicate": 0, "stale": 0, "refused": 0, "failed": 0, "skipped": 0}
    if not choice_enabled():
        return got
    for request in os_choice_requests.pending():
        try:
            got[_deliver_choice_request(db, request)] += 1
        except ports.OsUnavailable:
            break
        except Exception as exc:  # noqa: BLE001  (class name only, no student data; the next sweep tries again)
            log.error("PAI OS choice request could not be delivered: %s", type(exc).__name__)
            got["failed"] += 1
    return got


def deliver_choice_request_now(key: str) -> None:
    """The post-commit nudge after the student accepted (`mount_os(on_choice_request=)`): delivers that one request
    in its own session, so the decision does not wait for the sweep. Never raises past the OS port's guard."""
    if not choice_enabled():
        return
    from app.database import new_session

    request = next((r for r in os_choice_requests.pending() if r.key == key), None)
    if request is None:
        return
    with new_session() as db:
        _deliver_choice_request(db, request)


def deliver_fact_proposals(db) -> dict:
    """Hands the pending fact proposals (P1-T7, R-16, D-y9) to the Vault's sink, oldest first. Only while the
    CONNECT_ONE_UPLOAD part is on. Each row: the sink writes its candidates, the app transaction commits, then the OS
    row is marked (a crash in between repeats harmlessly: the proposal key makes the repeat a `duplicate`). An error
    rolls back and leaves the row pending; one failure never stops the others."""
    from app.pai_c.connect import document_facts  # lazy: Counsellor code

    got = {"written": 0, "duplicate": 0, "refused": 0, "failed": 0}
    if not part_on("CONNECT_ONE_UPLOAD"):
        return got
    for proposal in os_fact_proposals.pending():
        try:
            outcome, detail = document_facts.apply(db, proposal.model_dump(mode="json", by_alias=True))
            db.commit()
            os_fact_proposals.mark(proposal.key, f"refused:{detail[0]}" if outcome == "refused" else outcome)
            got[outcome] += 1
        except ports.OsUnavailable:
            db.rollback()
            break
        except Exception as exc:  # noqa: BLE001  (class name only, no student data; the next sweep tries again)
            db.rollback()
            log.error("PAI OS fact proposal could not be delivered: %s", type(exc).__name__)
            got["failed"] += 1
            try:  # after MAX_ATTEMPTS the row is set aside, so it cannot starve the newer ones
                os_fact_proposals.record_failure(proposal.key)
            except Exception as inner:  # noqa: BLE001
                log.error("PAI OS fact proposal failure could not be counted: %s", type(inner).__name__)
    return got


def deliver_fact_proposal_now(key: str) -> None:
    """The post-commit nudge after the student confirmed a document (`mount_os(on_fact_proposal=)`): delivers that one
    proposal in its own session, so the facts do not wait for the sweep. Never raises past the OS port's guard."""
    if not part_on("CONNECT_ONE_UPLOAD"):
        return
    from app.database import new_session
    from app.pai_c.connect import document_facts

    proposal = next((p for p in os_fact_proposals.pending() if p.key == key), None)
    if proposal is None:
        return
    with new_session() as db:
        try:
            outcome, detail = document_facts.apply(db, proposal.model_dump(mode="json", by_alias=True))
            db.commit()
        except Exception:
            db.rollback()
            raise
        os_fact_proposals.mark(key, f"refused:{detail[0]}" if outcome == "refused" else outcome)


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


def _backfill_vault(db) -> None:
    """A student whose Vault version is above the one PAI OS holds gets a Vault event for the newest version, naming
    every key that changed since the OS copy (a write made while the part was off, or a lost row, leaves no event). A
    delivered row the OS lacks goes back to pending."""
    for row in db.scalars(select(VaultVersion).where(VaultVersion.version > 0)).all():
        try:
            ws, version = str(row.workspace_id), row.version
            held = os_student_facts.latest_vault_version(ws)
            if held is not None and held >= version:
                continue
            key = f"vault_event:{ws}:{version}"
            item = db.scalar(select(OsOutbox).where(OsOutbox.key == key))
            if item is None:
                keys = sorted(k for k, v in (row.key_versions or {}).items() if v > (held or 0))
                if not keys:
                    continue
                outbox.record_vault_event(db, ws, version, keys)
            elif item.status == "delivered":
                item.status, item.delivered_at = "pending", None
            else:
                continue
            db.commit()
        except Exception as exc:  # noqa: BLE001  (one student never stops the others; class name only)
            db.rollback()
            log.error("PAI OS vault backfill failed for one student: %s", type(exc).__name__)


def _is_fact_change(e) -> bool:
    """Whether the escalation was raised for a Vault fact change (R-22): a hand-off-only route problem."""
    try:
        return os_escalation.event_type_of(e.key) == "student_fact_changed"
    except ports.OsUnavailable:
        return False


def _deliver(db) -> dict:
    from app.routers.escalations import EscalationInput, escalate

    got = {"sent": 0, "refused": 0, "waiting": 0}
    for e in os_escalation.pending_counsellor_escalations():
        if not config.PAI_OS_SERVICE_TOKEN:
            got["waiting"] += 1  # not configured: tried again on the next sweep
            continue
        handoff = part_on("CONNECT_HANDOFF")
        if not handoff:
            try:
                fact_change = _is_fact_change(e)
                if fact_change:
                    # A fact change is a route problem only for the hand-off (R-22); without it the Counsellor was
                    # never told and still is not: no endpoint call; the row is dropped, the case left as it was.
                    os_escalation.drop_counsellor_escalation(e.key, "handoff_off")
            except Exception as exc:  # noqa: BLE001  (one bad row never ends the sweep; class name only)
                log.error("PAI OS escalation could not be checked for the hand-off: %s", type(exc).__name__)
                got["waiting"] += 1
                continue
            if fact_change:
                got["refused"] += 1
                continue
        try:
            if handoff:  # the five reasons go as they are, with the decision version they belong to
                body = EscalationInput(workspace_id=e.student_ref, journey_id=e.journey_id, reason_type=e.reason,
                                       details=e.note, decision_version=e.decision_version)
            else:
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
            if handoff:
                _pause_after_escalation(e)
            os_escalation.mark_counsellor_delivery(e.key, "sent")
            got["sent"] += 1
    return got


def _pause_after_escalation(e) -> None:
    """D-x7: the Counsellor took the escalation, so the student's plan pauses with the reason. A failure here never
    undoes the delivery (the Counsellor has the escalation), and the pause is not retried: the row is marked sent, so
    a plan that was not paused stays as it is. Both a failure and a plan not paused are logged."""
    try:
        paused = plan_source.pause_for_escalation(e.student_ref, e.decision_version, e.reason)
    except Exception as exc:  # noqa: BLE001  (class name only, no student data)
        log.error("PAI OS plan could not be paused after an escalation: %s", type(exc).__name__)
        return
    if not paused:
        log.warning("PAI OS plan was not paused after an escalation (%s): no open plan took it", e.reason)


OS_EVENT_TEXTS = Path(__file__).parent / "pai_c" / "connect" / "os_event_texts.yaml"


OS_EVENT_MAX_AGE = timedelta(hours=48)  # older events are skipped, so switching the part on later sends no flood


def deliver_os_events(db) -> dict:
    """Turns each pending `os_event` row into one app notification (the bell), never a chat message (R-45). The
    notice is the fixed copy of `os_event_texts.yaml` for its kind, keyed by the event key, so a repeat sweep makes
    none. A student without a workspace here is `refused`; any other error leaves the row pending for the next sweep."""
    from app.services.notify import notify_once

    got = {"sent": 0, "refused": 0, "waiting": 0, "stale": 0}
    oldest = datetime.now(timezone.utc) - OS_EVENT_MAX_AGE
    texts = yaml.safe_load(OS_EVENT_TEXTS.read_text(encoding="utf-8")) or {}
    got["stale"] += os_events_port.skip_stale_events(OS_EVENT_MAX_AGE)  # one statement, before the page is read
    for e in os_events_port.pending_events():
        copy = texts.get(e.kind)
        if e.at < oldest:  # too old to tell the student now: skipped, no notification
            os_events_port.mark_event_delivery(e.key, "refused")
            got["stale"] += 1
            continue
        try:
            if copy is None or db.get(Workspace, e.student_ref) is None:
                os_events_port.mark_event_delivery(e.key, "refused")
                got["refused"] += 1
                continue
            notify_once(db, e.student_ref, dedupe_key=e.key, source="system:pai-os", title=copy["title"],
                        message=copy["message"], priority=copy.get("priority", "normal"),
                        link_url=f"/{e.student_ref}?view=roadmap")
            db.commit()
        except Exception as exc:  # noqa: BLE001  (one event never stops the others; class name only, no student data)
            db.rollback()
            log.error("PAI OS event could not become a notification: %s", type(exc).__name__)
            got["waiting"] += 1
            continue
        os_events_port.mark_event_delivery(e.key, "sent")
        got["sent"] += 1
    return got


def sweep_once(db) -> dict:
    try:
        ports.services()
    except ports.OsUnavailable:
        return {"mounted": False}
    delivered = failed = 0
    try:
        if part_on("CONNECT_ONE_UPLOAD"):
            try:  # before the pending vault events go out, so the events these proposals raise leave in this sweep
                os_fact_proposals.backfill()
                deliver_fact_proposals(db)
            except Exception as exc:  # noqa: BLE001  (class name only; the rest of the sweep still runs)
                db.rollback()
                log.error("PAI OS sweep could not deliver fact proposals: %s", type(exc).__name__)
        handoff, facts = part_on("CONNECT_HANDOFF"), part_on("CONNECT_STUDENT_FACTS")
        if handoff or facts:
            if handoff:
                try:
                    deliver_choice_requests(db)  # before the pending decisions, so n+1 goes out in this sweep
                except Exception as exc:  # noqa: BLE001  (class name only; the decisions below still go out)
                    db.rollback()
                    log.error("PAI OS sweep could not deliver choice requests: %s", type(exc).__name__)
            first = deliver_pending(db)
            if handoff:
                _backfill(db)
            if facts:
                _backfill_vault(db)
            second = deliver_pending(db)
            delivered = first["delivered"] + second["delivered"]
            failed = first["failed"] + second["failed"]
    except Exception:  # noqa: BLE001  (logged; escalations still go out, and the next sweep tries again)
        db.rollback()
        log.exception("PAI OS sweep could not deliver decisions")
        failed += 1
    result = {"submitted": delivered, "failed": failed, **_deliver(db)}
    try:
        if part_on("CONNECT_ROADMAP_FROM_PLANVIEW"):
            result["events"] = deliver_os_events(db)
    except Exception:  # noqa: BLE001  (logged; the next sweep tries again)
        db.rollback()
        log.exception("PAI OS sweep could not deliver plan events")
    return result


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


def student_facts(student_ref: str) -> dict | None:
    """The student's StudentFacts (a dict valid as `StudentFactsV1`), built from their Vault (P1-T4, R-13). None while
    the CONNECT_STUDENT_FACTS flag is off and for a reference that names no workspace: PAI OS then uses its own
    profile values. Reads the plain flag, not `part_on`: PAI OS checks the `counsellor` module itself, and this runs in
    the worker, where the module switch cannot be asked of the API. Opens its own session: PAI OS calls it on its
    worker thread. A database error raises, so PAI OS retries."""
    if not config.CONNECT_STUDENT_FACTS:
        return None
    try:
        workspace_id = str(uuid.UUID(student_ref))
    except (TypeError, ValueError):
        return None
    from app.database import new_session
    from app.pai_c.connect import student_facts as builder

    with new_session() as db:
        return builder.build(db, workspace_id)


def fact_conflicts(student_ref: str) -> dict | None:
    """The student's open Vault conflicts on a mark or a test score, for PAI OS (P1-T8, D-w12; a dict valid as
    `FactConflictsV1`; `mount_os(fact_conflicts=)` and the worker's `OS_FACT_CONFLICTS`). None while the
    CONNECT_STUDENT_FACTS flag is off and for a reference that names no workspace. Reads the plain flag, as
    `student_facts` does, so the API and the worker agree. Opens its own session: PAI OS calls it on its worker thread.
    A database error raises, so PAI OS retries."""
    if not config.CONNECT_STUDENT_FACTS:
        return None
    try:
        workspace_id = str(uuid.UUID(student_ref))
    except (TypeError, ValueError):
        return None
    from app.database import new_session
    from app.pai_c.connect import fact_conflicts as builder

    with new_session() as db:
        return builder.build(db, workspace_id)


def answer_fact_question(student_ref: str, ref: str, key: str, choice: str, value=None) -> dict | None:
    """The student's answer to a "which is right" request, written to the Vault (P1-T8, D-w13; `mount_os(fact_answer=)`).
    Returns `{"status": "resolved" | "gone" | "refused", "code"}`, or None while the CONNECT_STUDENT_FACTS part is off
    (PAI OS answers 404), for a reference that names no workspace and on any failure (logged by type only). Opens its
    own session and commits only a resolved answer, so a refused one writes nothing."""
    if not part_on("CONNECT_STUDENT_FACTS"):
        return None
    try:
        workspace_id = str(uuid.UUID(student_ref))
    except (TypeError, ValueError):
        return None
    from app.database import new_session
    from app.pai_c.connect import fact_conflicts as builder

    with new_session() as db:
        try:
            outcome = builder.answer(db, workspace_id, ref, key, choice, value)
            if outcome["status"] == "resolved":
                db.commit()
            else:
                db.rollback()
        except Exception as exc:  # noqa: BLE001  (class name only: no ids, no values)
            db.rollback()
            log.error("a fact question could not be answered: %s", type(exc).__name__)
            return None
    return outcome


def documents_enabled() -> bool:
    """True when the one upload entry point is on: the CONNECT_ONE_UPLOAD part (P1-T7, R-01). The OS reads it through
    `mount_os(documents_enabled=)`; it cannot read host flags itself."""
    return part_on("CONNECT_ONE_UPLOAD")


def document_file_bytes(student_ref: str, file_ref: str) -> bytes:
    """The bytes of the student's stored file `file_ref`, for the OS reader (P1-T7, D-y6; `mount_os(document_files=)`
    and the worker's OS_DOCUMENT_FILES). The file must exist, belong to the workspace `student_ref` and be active (not
    trashed or deleted); anything else is `KeyError`, so another student's bytes are never returned. Opens its own
    session: PAI OS calls it on its worker thread. A storage failure raises; the port turns it into KeyError."""
    from app.database import new_session
    from app.files.storage import get_file_store
    from app.models import FileRecord

    with new_session() as db:
        record = db.get(FileRecord, str(file_ref))
        if record is None or str(record.workspace_id) != str(student_ref) or record.status != "active":
            raise KeyError(file_ref)
        storage_key = record.storage_key
    return get_file_store().read(storage_key)


def register_os_document(student_ref: str, doc_type: str, file_ref: str, filename: str, data: bytes) -> dict:
    """Makes the stored file an OS document of `doc_type` (P1-T7, R-01): `{"id", "status"}`, or `{"refused": code}`
    (`not_on`, `unknown_type`, `consent_needed`, `terms_not_set`, `not_readable`, `duplicate`). `not_on` too when PAI
    OS is not mounted. Any other failure is raised."""
    try:
        return os_document_files.register(str(student_ref), doc_type, str(file_ref), filename, data)
    except ports.OsUnavailable:
        return {"refused": "not_on"}
    except os_document_files.Refused as refused:
        return {"refused": refused.code}


def forget_os_document(workspace_id: str, file_id: str) -> bool:
    """Deletes the OS document linked to a Counsellor file the student trashed or deleted (P1-T7, D-y7). False when
    there is none and when PAI OS is not mounted. Raises on any other failure (the caller logs it by class name)."""
    try:
        return os_document_files.forget(str(workspace_id), str(file_id))
    except ports.OsUnavailable:
        return False


def document_types() -> list[dict]:
    """The document types a student can name on upload, `{key, label}` sorted by key (P1-T7, D-y5). `[]` when PAI OS is
    not mounted, and on any failure (logged)."""
    try:
        types = ports.services().document_types
        return [{"key": k, "label": types[k].label} for k in sorted(types)]
    except ports.OsUnavailable:
        return []
    except Exception:
        log.exception("document types could not be read; treated as none")
        return []


def _emit_file_deleted(db, workspace, file_id: str, filename: str) -> None:
    from app.security.event_identity import emit_internal_event

    try:
        asyncio.run(emit_internal_event(db, workspace, type="workspace.file.deleted", source="system:pai-os",
                                        target="core", payload={"file_id": file_id, "filename": filename}))
        db.commit()
    except Exception as exc:  # noqa: BLE001  (class name only)
        db.rollback()
        log.error("the file event of an OS delete could not be emitted: %s", type(exc).__name__)


def on_os_document_deleted(student_ref: str, file_ref: str) -> None:
    """The OS deleted a linked document: purge the Counsellor file the way `purge_trash` does (P1-T7, D-y7): its bytes,
    its document state, the unindex job and the record. Idempotent: a file that is already gone is a no-op. A failure
    is raised before the record is deleted, so the OS delete stays `deleted` and the file record stays. Opens its own
    session: PAI OS calls it on its request thread."""
    from app.database import new_session
    from app.documents.service import DocumentArtifactService
    from app.files.storage import get_file_store
    from app.models import FileRecord
    from app.routers.files import _enqueue_document_unindex

    with new_session() as db:
        record = db.get(FileRecord, str(file_ref))
        if record is None or str(record.workspace_id) != str(student_ref):
            return
        get_file_store().delete(record.storage_key)  # a missing object is a no-op in both stores
        DocumentArtifactService(db).purge_for_files(str(student_ref), [record.id])
        _enqueue_document_unindex(db, str(student_ref), [record.id])
        workspace = db.get(Workspace, str(student_ref))
        filename, record_id = record.filename, record.id
        db.delete(record)
        db.commit()
        if workspace is not None:  # the same file event the trash purge emits; a failure here never undoes the purge
            _emit_file_deleted(db, workspace, record_id, filename)


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


def list_routes() -> list[dict]:
    """The routes PAI OS serves, `{key, origin, destination, level, intake_terms}`. `[]` when PAI OS is not mounted, and
    on any failure (logged)."""
    try:
        from app.os.ports import plan_query

        return plan_query.routes()
    except ports.OsUnavailable:
        return []
    except Exception:
        log.exception("routes could not be read; treated as none")
        return []


class StepError(Exception):
    """A step could not be completed through PAI OS. `code` is not_found, not_yours, not_waiting, review_required,
    answer_required (a request step closes by the answer, never by a tick) or unavailable
    (PAI OS is not mounted or failed)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def plan_view(student_ref: str) -> dict | None:
    """The student's plan as PAI OS shows it (a JSON dict valid as `PlanViewV1`), each step carrying `review`: True
    when the step is closed by approving a pack or visa file, never by hand. None when PAI OS is not mounted, and on any
    failure (logged); the Counsellor then shows its own view."""
    try:
        from app.os.ports import plan_actions, plan_query

        view = plan_query.plan_view(student_ref).model_dump(mode="json", by_alias=True)
        review = plan_actions.review_templates()
    except ports.OsUnavailable:
        return None
    except Exception:
        log.exception("plan view could not be read; the Counsellor's own view is shown")
        return None
    for step in view["steps"]:
        step["review"] = step["template_key"] in review
    return view


def complete_step(student_ref: str, task_id: int, payload: dict | None = None) -> str:
    """The student's tick on a plan step, done through PAI OS: "done", or "already_done" on a repeat. Raises StepError."""
    from app.os.ports import plan_actions  # outside the try: an OS that is not installed is a plain import error

    try:
        return plan_actions.complete_step(student_ref, task_id, payload)
    except ports.OsUnavailable:
        raise StepError("unavailable") from None
    except plan_actions.StepActionError as exc:
        raise StepError(exc.code) from None
    except Exception:
        log.exception("a plan step could not be completed")
        raise StepError("unavailable") from None


def programmes_for(route_key: str, term: str, year: int) -> list[dict]:
    """The places for a route and intake, `{ref, name, university}`. `[]` when PAI OS is not mounted, and on any
    failure (logged)."""
    try:
        from app.os.contracts.route_contract import IntakeRef
        from app.os.ports import plan_query

        listing = plan_query.programme_list(route_key, IntakeRef(term=term, year=year))
        return [{"ref": p.programme_ref, "name": p.name, "university": p.university} for p in listing.programmes]
    except ports.OsUnavailable:
        return []
    except Exception:
        log.exception("programmes could not be read; treated as none")
        return []
