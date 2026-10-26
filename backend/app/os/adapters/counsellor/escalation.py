"""The Counsellor escalation adapter (Slice 8 spec §2.5, S8-D12). After the standalone support case, a route problem
on a Counsellor plan is also written to the outbox (channel `counsellor`, key `escalation:{case_id}`, an EscalationV1
payload) for the host's glue to deliver. Only while the module is on; system problems stay in the support inbox.
The note is a fixed sentence per reason from notes.yaml, never student, document or Supervisor text."""

from datetime import datetime, timezone
from functools import cache
from pathlib import Path

import yaml
from sqlalchemy import Engine, select, update

from app.os import models
from app.os.adapters.counsellor import manifest
from app.os.adapters.counsellor.store import Intake, IntakeStore
from app.os.adapters.standalone.escalation import CompositeSink, StandaloneSink
from app.os.contracts.escalation import EscalationV1
from app.os.outbox import Outbox
from app.os.replan import events
from app.os.replan.apply import BROKEN_REASON, LIMIT_REASON, REFUSED_REASON
from app.os.replan.rules import REASONS
from app.os.replan.run import BUDGET_REASON, HANDOVER_PREFIX, INVALID_REASON
from app.os.replan.store import SupportStore

NOTES_PATH = Path(__file__).with_name("notes.yaml")
REASON_CODES = ("not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other")
CHANNEL = "counsellor"
_SYSTEM = (LIMIT_REASON, REFUSED_REASON, REASONS["failed"], BUDGET_REASON, INVALID_REASON)
_SYSTEM_PREFIXES = (HANDOVER_PREFIX, "The plan kept changing")  # no Supervisor; a stale draft (ReplanFailed)
_BY_EVENT = {"route_invalid": "not_eligible", "admission_rejected": "all_rejected",
             "deadline_at_risk": "deadline_passed", "escalate": "blocking_gap", "document_missing": "blocking_gap"}


@cache
def _notes(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [r for r in REASON_CODES if not isinstance(raw.get(r), str) or not raw[r].strip()]
    if missing:
        raise ValueError(f"{path.name}: no note for {', '.join(missing)}")
    return {r: raw[r].strip() for r in REASON_CODES}


def load_notes(path: Path = NOTES_PATH) -> dict[str, str]:
    return _notes(path)


def reason_for(event_type: str, reason: str) -> str | None:
    """The shared reason for a support case, or None for a system problem (spec §2.5 table)."""
    if reason.startswith(BROKEN_REASON):  # the plan no longer compiles: the route itself does not hold
        return "not_eligible"
    if reason in _SYSTEM or reason.startswith(_SYSTEM_PREFIXES):
        return None
    return _BY_EVENT.get(event_type)


def journey_of(external_ref: str) -> str:
    """`{journey_id}:{destination}:{level}` (S8-D8) → the journey ID."""
    return external_ref.rsplit(":", 2)[0]


def _payload(key: str, case_id: int | None, journey_id: str, student_ref: str, reason: str,
             notes: dict[str, str]) -> dict:
    return EscalationV1(key=key, case_id=case_id, journey_id=journey_id, student_ref=student_ref, reason=reason,
                        note=notes[reason], raised_at=datetime.now(timezone.utc)).model_dump(mode="json", by_alias=True)


class CounsellorSink:
    """Runs after the standalone sink (CompositeSink); returns the case id it found, or 0 when nothing was sent."""

    def __init__(self, engine: Engine, tenant_id: str, notes: dict[str, str] | None = None) -> None:
        self.engine, self.tenant_id = engine, tenant_id
        self.notes = notes or load_notes()
        self.cases, self.outbox = SupportStore(engine, tenant_id), Outbox(engine, tenant_id)

    def escalate(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        if not event_ids or not manifest.is_enabled(self.engine, self.tenant_id):
            return 0
        P = models.plans
        with self.engine.connect() as conn:
            plan = conn.execute(select(P.c.source, P.c.external_ref, P.c.student_ref).where(
                P.c.tenant_id == self.tenant_id, P.c.id == plan_id)).first()
        event = events.get(self.engine, self.tenant_id, event_ids[0])
        code = reason_for(event.type, reason) if event is not None else None
        case = self.cases.for_event(event_ids[0])
        if plan is None or plan.source != manifest.NAME or code is None or case is None:
            return 0
        key = f"escalation:{case.id}"
        self.outbox.add(key, CHANNEL, plan.student_ref, "escalation",
                        _payload(key, case.id, journey_of(plan.external_ref), plan.student_ref, code, self.notes))
        C = models.support_cases
        with self.engine.begin() as conn:  # also on a repeat: the outbox row is the one written first
            conn.execute(update(C).where(C.c.tenant_id == self.tenant_id, C.c.id == case.id,
                                         C.c.counsellor_status.is_(None))
                         .values(counsellor_status="pending", counsellor_reason=code))
        return case.id


def escalation_sink(engine: Engine, tenant_id: str) -> CompositeSink:
    """Every escalation of the API and the worker: the support case always; then the Counsellor, for its own plans'
    route problems while its module is on. Loads the notes, so a missing note stops startup."""
    return CompositeSink([StandaloneSink(engine, tenant_id), CounsellorSink(engine, tenant_id, load_notes())])


def intake_refused(engine: Engine, tenant_id: str, intake: Intake) -> None:
    """A refused decision of S8-D10's first four has no plan and no case: it is sent by journey as `other`."""
    key = f"escalation:intake:{intake.decision_id}"
    Outbox(engine, tenant_id).add(key, CHANNEL, intake.student_ref, "escalation",
                                  _payload(key, None, intake.journey_id, intake.student_ref, "other", load_notes()))
    if intake.counsellor_status is None:
        IntakeStore(engine, tenant_id).set_counsellor_status(intake.decision_id, "pending")
