"""The admin list of consistency cases (P1-T10 A1, R-05): staff see what the nightly job found and resolve a case with a
note. Resolving changes nothing else: no plan, pause or event. Codes, IDs and the rule number only."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.os.api.services import Services
from app.os.consistency.store import Case, ConsistencyStore


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)


def case_out(c: Case) -> dict:
    return {"id": c.id, "student_ref": c.student_ref, "rule": c.rule, "plan_id": c.plan_id, "codes": c.codes,
            "status": c.status, "resolution": c.resolution, "first_seen_at": c.first_seen_at,
            "last_seen_at": c.last_seen_at, "resolved_at": c.resolved_at}


def add_consistency_routes(router: APIRouter, services: Callable[[], Services], require_admin) -> None:
    @router.get("/admin/consistency", dependencies=[Depends(require_admin)])
    def cases(status: str | None = None, svc: Services = Depends(services)) -> dict:
        if status not in (None, "open", "resolved"):
            raise HTTPException(status_code=422, detail="status must be open or resolved")
        return {"cases": [case_out(c) for c in ConsistencyStore(svc.engine, svc.settings.tenant_id).list(status)]}

    @router.post("/admin/consistency/{case_id}/resolve", dependencies=[Depends(require_admin)])
    def resolve(case_id: int, body: ResolveIn, svc: Services = Depends(services)) -> dict:
        store = ConsistencyStore(svc.engine, svc.settings.tenant_id)
        if store.get(case_id) is None:
            raise HTTPException(status_code=404, detail="case not found")
        if not store.resolve(case_id, body.note):
            raise HTTPException(status_code=409, detail="case is already resolved")
        return case_out(store.get(case_id))
