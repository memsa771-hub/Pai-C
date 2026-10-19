"""The OS HTTP API (spec §4.9): PlanSource (admin), PlanQuery and the student inbox."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app.os.api.deps import check_admin, current_student_ref, current_student_ref_for_write
from app.os.api.queries import inbox_items, plan_out
from app.os.api.schemas import (
    CompleteIn,
    CompleteOut,
    ConfirmIn,
    ConfirmOut,
    InboxOut,
    OpenFactsOut,
    PlanOut,
    SupplyIn,
    UpgradeOut,
)
from app.os.api.services import Services
from app.os.compiler import CompileError
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import IllegalTransition
from app.os.playbooks import PlaybookError
from app.os.workers import confirm_fact, open_confirm_tasks, supply_fact


def build_router(get_services: Callable[[], Services]) -> APIRouter:
    router = APIRouter(tags=["os"])

    def services() -> Services:
        return get_services()

    def require_admin(authorization: str | None = Header(None), svc: Services = Depends(services)) -> None:
        check_admin(svc.settings, authorization)

    @router.post("/plans", status_code=201, response_model=PlanOut, dependencies=[Depends(require_admin)])
    def post_plan(contract: RouteContract, response: Response, svc: Services = Depends(services)) -> dict:
        try:
            ref = svc.plans.start_plan(contract)
        except (PlaybookError, CompileError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        if not ref.created:
            response.status_code = 200
        return plan_out(svc.engine, svc.settings.tenant_id, ref.plan_id)

    @router.get("/plans/{plan_id}", response_model=PlanOut, dependencies=[Depends(require_admin)])
    def get_plan(plan_id: int, svc: Services = Depends(services)) -> dict:
        found = plan_out(svc.engine, svc.settings.tenant_id, plan_id)
        if found is None:
            raise HTTPException(status_code=404, detail="plan not found")
        return found

    @router.post("/plans/{plan_id}/upgrade", response_model=UpgradeOut, dependencies=[Depends(require_admin)])
    def upgrade(plan_id: int, svc: Services = Depends(services)) -> dict:
        try:
            return {"revision": svc.plans.upgrade(plan_id)}
        except KeyError:
            raise HTTPException(status_code=404, detail="plan not found") from None

    @router.get("/inbox", response_model=InboxOut)
    def inbox(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        return {"items": inbox_items(svc.engine, svc.settings.tenant_id, student)}

    @router.post("/inbox/{task_id}/complete", response_model=CompleteOut)
    def complete(task_id: int, body: CompleteIn | None = None,
                 student: str = Depends(current_student_ref_for_write),  # a write: needs write access (I6)
                 svc: Services = Depends(services)) -> dict:
        try:
            done = svc.kernel.complete_student_task(task_id, student, (body or CompleteIn()).payload)
        except (KeyError, PermissionError):
            raise HTTPException(status_code=404, detail="inbox item not found") from None
        except IllegalTransition as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        return {"completed": done}

    @router.post("/facts/{fact_id}/confirm", response_model=ConfirmOut, dependencies=[Depends(require_admin)])
    def confirm(fact_id: int, body: ConfirmIn, svc: Services = Depends(services)) -> dict:
        try:
            revised = confirm_fact(svc.plans, svc.knowledge, svc.kernel, fact_id, **body.model_dump())
        except KeyError:
            raise HTTPException(status_code=404, detail="fact not found") from None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"revised_plans": revised}

    @router.post("/facts", response_model=ConfirmOut, dependencies=[Depends(require_admin)])
    def supply(body: SupplyIn, svc: Services = Depends(services)) -> dict:
        try:
            revised = supply_fact(svc.plans, svc.knowledge, svc.kernel, **body.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"revised_plans": revised}

    @router.get("/facts/open", response_model=OpenFactsOut, dependencies=[Depends(require_admin)])
    def open_facts(svc: Services = Depends(services)) -> dict:
        return {"items": open_confirm_tasks(svc.engine, svc.settings.tenant_id)}

    return router
