"""The replan API (Slice 7 spec §4): the student's proposals and what changed in their plan, their answer, and the
admin support inbox. The student sees only their own plan's proposals; accepting re-checks the plan first."""

from collections.abc import Callable
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.os.kernel.states import PLAN_OPEN
from app.os import clock, models
from app.os.api import self_serve
from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.services import Services
from app.os.outbox import Outbox
from app.os.ports import choice_requests
from app.os.replan import choice_texts
from app.os.replan.apply import ProposalStale, Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.store import Proposal, ProposalStore, SupportStore

P = models.plans


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)
    unpause: bool = False


def replanner_for(svc: Services) -> Replanner:
    return Replanner(svc.engine, svc.plans, load_replan_configs(), Outbox(svc.engine, svc.settings.tenant_id),
                     escalations=svc.escalations)


def case_fields(c) -> dict:
    """A support case for the admin inbox; Slice 8 adds whether it went to the Counsellor and with which reason."""
    return {"id": c.id, "plan_id": c.plan_id, "student_ref": c.student_ref, "reason": c.reason,
            "event_ids": c.event_ids, "proposal_id": c.proposal_id, "status": c.status, "resolution": c.resolution,
            "created_at": c.created_at, "resolved_at": c.resolved_at, "counsellor_status": c.counsellor_status,
            "counsellor_reason": c.counsellor_reason}


EXPIRED_SHOWN = timedelta(days=7)  # an expired request stays in the student's list this long


def proposal_out(p: Proposal, settings=None) -> dict:
    """`status_note` (P1-T6) is the fixed sentence for a request, left out while its file is not approved."""
    key = "requested" if p.status == "requested" else "expired" if p.status == "expired" and p.request_outcome else None
    out = {"id": p.id, "plan_id": p.plan_id, "status": p.status, "big": p.big, "source": p.source, "ops": p.ops,
           "reasons": [] if p.source == "student" else [o["reason"] for o in p.ops], "revision": p.revision,
           "expires_at": p.expires_at, "created_at": p.created_at, "answered_at": p.answered_at}
    note = choice_texts.note(key, settings) if key and settings is not None else None
    if note is not None:  # only when set: a proposal without a request has exactly today's keys
        out["status_note"] = note
    if p.request_outcome is not None:
        out["request_outcome"] = p.request_outcome
    return out


def student_proposals(svc: Services, student: str) -> list[dict]:
    store = ProposalStore(svc.engine, svc.settings.tenant_id)
    found = [*store.pending_for(student), *store.requested_for(student, clock.now() - EXPIRED_SHOWN)]
    return [proposal_out(p, svc.settings) for p in sorted(found, key=lambda p: p.id)]


def changes_paused(svc: Services, student: str) -> bool:
    with svc.engine.connect() as conn:
        return bool(conn.execute(select(P.c.id).where(P.c.tenant_id == svc.settings.tenant_id,
                                                      P.c.student_ref == student, P.c.status.in_(PLAN_OPEN),
                                                      P.c.changes_paused.is_(True))).first())


def add_replan_routes(router: APIRouter, services: Callable[[], Services], require_admin) -> None:
    def own_plan(svc: Services, student: str, plan_id: int) -> None:
        with svc.engine.connect() as conn:
            owner = conn.execute(select(P.c.student_ref).where(P.c.tenant_id == svc.settings.tenant_id,
                                                               P.c.id == plan_id)).scalar()
        if owner != student:
            raise HTTPException(status_code=404, detail="plan not found")

    def plan_changes(svc: Services, plan_id: int) -> dict:
        found = ProposalStore(svc.engine, svc.settings.tenant_id).for_plan(plan_id)
        with svc.engine.connect() as conn:
            paused, contract = conn.execute(select(P.c.changes_paused, P.c.contract).where(P.c.id == plan_id)).one()
            # the names of every programme the plan had or a change names, removed ones too (Slice 9 Task 11): the
            # programmes page lists only those still in the plan, so the page cannot name a removed one by itself
            refs = {c["programme_ref"] for c in (contract or {}).get("programmes", [])}
            refs |= {op.get(k) for p in found for op in p.ops for k in ("programme_ref", "out_ref", "in_ref")}
            refs.discard(None)
            G = models.programmes
            names = dict(conn.execute(select(G.c.ref, G.c.name).where(
                G.c.tenant_id == svc.settings.tenant_id, G.c.ref.in_(refs))).all()) if refs else {}
        return {"changes": [{**proposal_out(p, svc.settings), "proposal_id": p.id, "at": p.answered_at or p.created_at}
                            for p in found if p.status in ("applied", "accepted") and p.ops
                            and p.revision is not None],  # a proposal that changed nothing is no entry (minor #7)
                "pending": [proposal_out(p, svc.settings) for p in found if p.status == "pending"],
                "changes_paused": paused, "plan_id": plan_id, "names": names}

    @router.get("/plans/{plan_id}/changes")
    def changes(plan_id: int, student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        own_plan(svc, student, plan_id)
        return plan_changes(svc, plan_id)

    @router.get("/changes")
    def my_changes(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        """The changes of the student's open plan (the screens do not know its id)."""
        plan = self_serve.student_plan(svc.plans, student)
        if plan is None:
            raise HTTPException(status_code=404, detail="no plan yet")
        return plan_changes(svc, plan.plan_id)

    def answer(svc: Services, student: str, proposal_id: int, accept: bool) -> dict:
        r = replanner_for(svc)
        try:
            if accept:
                revision = r.accept(student, proposal_id)
            else:
                r.decline(student, proposal_id)
                revision = None
        except PermissionError:
            raise HTTPException(status_code=404, detail="suggestion not found") from None
        except ProposalStale as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        status = "accepted" if accept else "declined"
        if accept:  # a choice change on a Counsellor plan is requested, not accepted (R-07)
            after = ProposalStore(svc.engine, svc.settings.tenant_id).get(proposal_id)
            if after is not None and after.status in ("requested", "refused"):
                status = after.status
                if status == "requested":
                    choice_requests.notify(choice_requests.key_of(proposal_id))  # the plan lock is released
        return {"status": status, "revision": revision}

    @router.post("/proposals/{proposal_id}/accept")
    def accept(proposal_id: int, student: str = Depends(current_student_ref_for_write),
               svc: Services = Depends(services)) -> dict:
        return answer(svc, student, proposal_id, True)

    @router.post("/proposals/{proposal_id}/decline")
    def decline(proposal_id: int, student: str = Depends(current_student_ref_for_write),
                svc: Services = Depends(services)) -> dict:
        return answer(svc, student, proposal_id, False)

    def case_out(svc: Services, c) -> dict:
        with svc.engine.connect() as conn:
            paused = conn.execute(select(P.c.changes_paused).where(P.c.id == c.plan_id)).scalar()
        return {**case_fields(c), "changes_paused": bool(paused)}

    @router.get("/admin/support", dependencies=[Depends(require_admin)])
    def support(status: str | None = None, svc: Services = Depends(services)) -> dict:
        return {"cases": [case_out(svc, c) for c in SupportStore(svc.engine, svc.settings.tenant_id).list(status)]}

    @router.post("/admin/support/{case_id}/resolve", dependencies=[Depends(require_admin)])
    def resolve(case_id: int, body: ResolveIn, svc: Services = Depends(services)) -> dict:
        store = SupportStore(svc.engine, svc.settings.tenant_id)
        if store.get(case_id) is None:
            raise HTTPException(status_code=404, detail="case not found")
        plan_id = store.resolve(case_id, body.note)
        if body.unpause:
            svc.kernel.set_changes_paused(plan_id, False)
        return case_out(svc, store.get(case_id))
