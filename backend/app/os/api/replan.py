"""The replan API (Slice 7 spec §4): the student's proposals and what changed in their plan, their answer, and the
admin support inbox. The student sees only their own plan's proposals; accepting re-checks the plan first."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.os import models
from app.os.api import self_serve
from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.services import Services
from app.os.outbox import Outbox
from app.os.replan.apply import ProposalStale, Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.store import Proposal, ProposalStore, SupportStore

P = models.plans


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)
    unpause: bool = False


def replanner_for(svc: Services) -> Replanner:
    return Replanner(svc.engine, svc.plans, load_replan_configs(), Outbox(svc.engine, svc.settings.tenant_id))


def proposal_out(p: Proposal) -> dict:
    return {"id": p.id, "plan_id": p.plan_id, "status": p.status, "big": p.big, "source": p.source, "ops": p.ops,
            "reasons": [o["reason"] for o in p.ops], "revision": p.revision, "expires_at": p.expires_at,
            "created_at": p.created_at, "answered_at": p.answered_at}


def student_proposals(svc: Services, student: str) -> list[dict]:
    return [proposal_out(p) for p in ProposalStore(svc.engine, svc.settings.tenant_id).pending_for(student)]


def changes_paused(svc: Services, student: str) -> bool:
    with svc.engine.connect() as conn:
        return bool(conn.execute(select(P.c.id).where(P.c.tenant_id == svc.settings.tenant_id,
                                                      P.c.student_ref == student, P.c.status != "done",
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
            paused = conn.execute(select(P.c.changes_paused).where(P.c.id == plan_id)).scalar_one()
        return {"changes": [{**proposal_out(p), "proposal_id": p.id, "at": p.answered_at or p.created_at}
                            for p in found if p.status in ("applied", "accepted") and p.ops],
                "pending": [proposal_out(p) for p in found if p.status == "pending"],
                "changes_paused": paused, "plan_id": plan_id}

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
        return {"status": "accepted" if accept else "declined", "revision": revision}

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
        return {"id": c.id, "plan_id": c.plan_id, "student_ref": c.student_ref, "reason": c.reason,
                "event_ids": c.event_ids, "proposal_id": c.proposal_id, "status": c.status,
                "resolution": c.resolution, "created_at": c.created_at, "resolved_at": c.resolved_at,
                "changes_paused": bool(paused)}

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
