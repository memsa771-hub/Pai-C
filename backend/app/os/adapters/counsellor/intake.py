"""Route in (Slice 8 spec §2.3): one stored Counsellor decision becomes a plan, a plan revision, a replacement plan or
a refusal. Every plan change goes through the kernel (invariant 1). `process` can run again on the same decision
(a DBOS step after a crash) and change nothing more (invariant 8). The module switch is checked by the caller
(Task 5); the intake row's outcome is written by the caller from the result."""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import and_, insert, select

from app.os import models
from app.os.adapters.counsellor.escalation import intake_refused
from app.os.adapters.counsellor.store import Intake, IntakeStore
from app.os.compiler import CompileError
from app.os.contracts.decision_record import DecisionRecordV1
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import StaleDraft
from app.os.kernel.states import PLAN_CLOSED, PLAN_OPEN
from app.os.knowledge.programmes import ProgrammeStore
from app.os.playbooks import PlaybookError, select_playbook

REFUSALS = ("not_authorized", "invalid_export", "route_not_supported", "unknown_programme", "self_serve_plan_open",
            "plan_closed")
TO_COUNSELLOR = REFUSALS[:4]  # should never arrive, so the Counsellor hears of them (`other`, by journey)
SELF_SERVE_REASON = "A Counsellor decision arrived while the student has an open self-serve plan: a person decides."
CLOSED_REASON = "A Counsellor decision names a route whose plan was closed: a person decides."
CONSENT_MISSING = "consent_missing"
SOURCE = "counsellor"
V2_SCHEMA = "pai.decision_record.v2"
P = models.plans


@dataclass(frozen=True)
class IntakeResult:
    status: str  # planned | revised | replaced | refused | stale | withdrawn | unsupported | held | paused
    reason: str | None = None
    plan_id: int | None = None


def _plans_of(svc, student_ref: str, source: str) -> list:
    with svc.engine.connect() as conn:
        return conn.execute(select(P.c.id, P.c.external_ref, P.c.status).where(
            P.c.tenant_id == svc.kernel.tenant_id, P.c.student_ref == student_ref, P.c.source == source)
            .order_by(P.c.id)).all()


def _superseded(svc, intake: Intake) -> bool:
    """A newer decision for the same journey is already in: this refusal is outdated, and telling the Counsellor
    would take a student whose current decision is fine back to choosing (final review I3)."""
    I = models.counsellor_intake
    with svc.engine.connect() as conn:
        return conn.execute(select(I.c.id).where(
            I.c.tenant_id == svc.kernel.tenant_id, I.c.journey_id == intake.journey_id,
            I.c.chosen_at > intake.chosen_at).limit(1)).first() is not None


def _refuse(svc, intake: Intake, reason: str, plan_id: int | None = None) -> IntakeResult:
    if reason in TO_COUNSELLOR:  # sent to the Counsellor by journey as `other`, once per decision
        if not _superseded(svc, intake):
            intake_refused(svc.engine, svc.kernel.tenant_id, intake)
    else:  # a person decides: a support case on the plan concerned, once per decision
        svc.escalations.escalate(plan_id, [_intake_event(svc, plan_id, intake, reason)],
                                 SELF_SERVE_REASON if reason == "self_serve_plan_open" else CLOSED_REASON)
    return IntakeResult("refused", reason, plan_id)


def _intake_event(svc, plan_id: int, intake: Intake, reason: str) -> int:
    """The `counsellor_intake` event the support case names, so a repeat finds the same case. Not a replan event
    type: the replan job never picks it up."""
    E = models.events
    with svc.engine.begin() as conn:
        found = conn.execute(select(E.c.id).where(and_(
            E.c.tenant_id == svc.kernel.tenant_id, E.c.plan_id == plan_id, E.c.type == "counsellor_intake",
            E.c.payload["decision_id"].astext == intake.decision_id))).scalar()
        if found is not None:
            return found
        return conn.execute(insert(E).values(
            tenant_id=svc.kernel.tenant_id, plan_id=plan_id, type="counsellor_intake",
            payload={"decision_id": intake.decision_id, "refused": reason}).returning(E.c.id)).scalar_one()


def _revise(svc, plan_id: int, contract: RouteContract, cause: str) -> None:
    """The same route with new places, order or intake: the plan's contract changes as a revision (like a Slice 4
    swap); started and done tasks are kept by the kernel's revision rules."""
    for _ in range(3):
        _, sha = svc.plans._contract(plan_id)
        draft = svc.plans.compile(contract, svc.plans._pinned(plan_id), plan_id)
        try:
            svc.kernel.change_contract(plan_id, contract, draft, cause, based_on=sha)
            return
        except StaleDraft:
            continue
    raise StaleDraft(f"plan {plan_id} kept changing during the Counsellor revision")


def _v1_contract(decision: DecisionRecordV2) -> RouteContract:
    """The plan engine takes the v1 contract (D-b): a v2 decision of one of the four v1 levels converts to it."""
    two = decision.to_route_contract()
    return RouteContract(contract_version="1", source="counsellor", external_ref=two.external_ref,
                         student_ref=two.student_ref, origin_country=two.origin_country,
                         destination_country=two.destination_country, level=two.level,
                         programmes=two.programmes, target_intake=two.target_intake)


def _close_all(svc, decision: DecisionRecordV2, cause: str, status: str) -> IntakeResult:
    """Every open Counsellor plan of the student is closed by the kernel (one active choice per student)."""
    closed = [p.id for p in _plans_of(svc, decision.student_ref, SOURCE) if p.status in PLAN_OPEN]
    for plan_id in closed:
        svc.kernel.close_plan(plan_id, f"{cause}:{decision.decision_id}")
    return IntakeResult(status, None, closed[-1] if closed else None)


def _withdraw(svc, decision: DecisionRecordV2) -> IntakeResult:
    """The student withdrew the decision: every open Counsellor plan of the student is closed (R-06)."""
    return _close_all(svc, decision, "withdrawn", "withdrawn")


def _unsupported(svc, decision: DecisionRecordV2) -> IntakeResult:
    """The student moved to a route the OS cannot run: the old route's plan is over (row 6.3) and nothing is planned
    for the new one (row 6.14)."""
    return _close_all(svc, decision, "unsupported", "unsupported")


def _consent_missing(decision: DecisionRecordV2) -> bool:
    return decision.authorized_at is None or (decision.guardian_required and decision.guardian_authorized_at is None)


def _hold_or_pause(svc, decision: DecisionRecordV2) -> IntakeResult:
    """A consent is missing (P1-D11): an open plan on this route is paused (no reminders, no promotion) and a
    decision with no plan yet is held. Neither is escalated: the Counsellor already asks the student or guardian.
    A repeat changes nothing more."""
    plan = next((p for p in _plans_of(svc, decision.student_ref, SOURCE)
                 if p.external_ref == decision.to_route_contract().external_ref and p.status in PLAN_OPEN), None)
    if plan is None:
        return IntakeResult("held", CONSENT_MISSING)
    svc.kernel.pause_plan(plan.id, CONSENT_MISSING)  # False when it is already paused
    return IntakeResult("paused", CONSENT_MISSING, plan.id)


def process(svc, intake: Intake) -> IntakeResult:
    if intake.export.get("schema") == V2_SCHEMA:
        try:
            decision = DecisionRecordV2.model_validate(intake.export)
        except ValidationError:
            return _refuse(svc, intake, "invalid_export")
        newest = IntakeStore(svc.engine, svc.kernel.tenant_id).newest_other_version(decision.student_ref, intake.id)
        if newest is not None and decision.decision_version <= newest:
            return IntakeResult("stale")  # any newer stored version wins, pending or processed (R-02)
        if decision.status == "withdrawn":
            return _withdraw(svc, decision)
        if not decision.os_supported:
            return _unsupported(svc, decision)
    else:
        try:
            decision = DecisionRecordV1.model_validate(intake.export)
        except ValidationError:
            return _refuse(svc, intake, "invalid_export")
    if isinstance(decision, DecisionRecordV2):
        if _consent_missing(decision):
            return _hold_or_pause(svc, decision)
    elif decision.authorized_at is None:
        return _refuse(svc, intake, "not_authorized")
    if isinstance(decision, DecisionRecordV2) and decision.level == "intermediate":
        return _refuse(svc, intake, "route_not_supported")  # intermediate waits for the v2 plan engine (D-b)
    try:
        book = select_playbook(svc.plans.playbooks, decision.origin_country, decision.destination_country,
                               decision.level)
    except PlaybookError:
        return _refuse(svc, intake, "route_not_supported")
    known = {p.ref for p in ProgrammeStore(svc.engine, svc.kernel.tenant_id).active(book.key)}
    if any(p.programme_ref not in known for p in decision.programmes):
        return _refuse(svc, intake, "unknown_programme")
    own = [p for p in _plans_of(svc, decision.student_ref, "self_serve") if p.status in PLAN_OPEN]
    if own:
        return _refuse(svc, intake, "self_serve_plan_open", own[-1].id)
    contract = _v1_contract(decision) if isinstance(decision, DecisionRecordV2) else decision.to_route_contract()
    theirs = _plans_of(svc, decision.student_ref, SOURCE)
    same = next((p for p in theirs if p.external_ref == contract.external_ref), None)
    if same is not None and same.status == PLAN_CLOSED:
        return _refuse(svc, intake, "plan_closed", same.id)
    try:
        if same is not None:
            if same.status == "paused":  # the consent is back (P1-D11)
                svc.kernel.resume_plan(same.id)
            _revise(svc, same.id, contract, f"counsellor:{decision.decision_id}")
            plan_id, status = same.id, "revised"
        else:
            plan_id, status = svc.plans.start_plan(contract).plan_id, "planned"
    except CompileError:
        return _refuse(svc, intake, "route_not_supported")
    others = [p for p in theirs if p.id != plan_id and p.status in PLAN_OPEN]
    for p in others:  # a new country or level: the old route's plan is over (S8-D8)
        svc.kernel.close_plan(p.id, f"superseded:{plan_id}")
    return IntakeResult("replaced" if others else status, None, plan_id)
