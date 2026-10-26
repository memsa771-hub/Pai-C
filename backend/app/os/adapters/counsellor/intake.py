"""Route in (Slice 8 spec §2.3): one stored Counsellor decision becomes a plan, a plan revision, a replacement plan or
a refusal. Every plan change goes through the kernel (invariant 1). `process` can run again on the same decision
(a DBOS step after a crash) and change nothing more (invariant 8). The module switch is checked by the caller
(Task 5); the intake row's outcome is written by the caller from the result."""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import and_, insert, select

from app.os import models
from app.os.adapters.counsellor.escalation import intake_refused
from app.os.adapters.counsellor.store import Intake
from app.os.compiler import CompileError
from app.os.contracts.decision_record import DecisionRecordV1
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
SOURCE = "counsellor"
P = models.plans


@dataclass(frozen=True)
class IntakeResult:
    status: str  # planned | revised | replaced | refused
    reason: str | None = None
    plan_id: int | None = None


def _plans_of(svc, student_ref: str, source: str) -> list:
    with svc.engine.connect() as conn:
        return conn.execute(select(P.c.id, P.c.external_ref, P.c.status).where(
            P.c.tenant_id == svc.kernel.tenant_id, P.c.student_ref == student_ref, P.c.source == source)
            .order_by(P.c.id)).all()


def _refuse(svc, intake: Intake, reason: str, plan_id: int | None = None) -> IntakeResult:
    if reason in TO_COUNSELLOR:  # sent to the Counsellor by journey as `other`, once per decision
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


def process(svc, intake: Intake) -> IntakeResult:
    try:
        decision = DecisionRecordV1.model_validate(intake.export)
    except ValidationError:
        return _refuse(svc, intake, "invalid_export")
    if decision.authorized_at is None:
        return _refuse(svc, intake, "not_authorized")
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
    contract = decision.to_route_contract()
    theirs = _plans_of(svc, decision.student_ref, SOURCE)
    same = next((p for p in theirs if p.external_ref == contract.external_ref), None)
    if same is not None and same.status == PLAN_CLOSED:
        return _refuse(svc, intake, "plan_closed", same.id)
    try:
        if same is not None:
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
