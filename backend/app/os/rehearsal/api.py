"""The rehearsal admin calls (spec §2.2, §5). build_router adds them only when rehearsal mode is on, so on a pilot
server they do not exist (404)."""

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.os import clock
from app.os.rehearsal.store import ClockStore
from app.os.rehearsal.tick import enqueue_tick, tick_status

PREFIX = "/admin/rehearsal"
DAY_SECONDS = 86400


class AdvanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(ge=1, le=60)


class AdvanceOut(BaseModel):
    offset_days: float
    now: datetime


class TickOut(BaseModel):
    tick_id: str


class TickStatusOut(BaseModel):
    status: Literal["running", "done", "error"]
    ran: list[str]
    failed: list[str]


def add_rehearsal_routes(router: APIRouter, services: Callable, require_admin) -> None:
    admin = [Depends(require_admin)]

    @router.post(f"{PREFIX}/advance", response_model=AdvanceOut, dependencies=admin)
    def advance(body: AdvanceIn, svc=Depends(services)) -> dict:
        moved = ClockStore(svc.engine, svc.settings.tenant_id).advance(body.days)
        return {"offset_days": moved.total_seconds() / DAY_SECONDS, "now": clock.now()}

    @router.post(f"{PREFIX}/tick", response_model=TickOut, dependencies=admin)
    def tick(svc=Depends(services)) -> dict:
        return {"tick_id": enqueue_tick(svc.dbos_client(), svc.settings.tenant_id)}

    @router.get(f"{PREFIX}/tick/{{tick_id}}", response_model=TickStatusOut, dependencies=admin)
    def get_tick(tick_id: str, svc=Depends(services)) -> dict:
        found = tick_status(svc.dbos_client(), svc.settings.tenant_id, tick_id)
        if found is None:
            raise HTTPException(status_code=404, detail="tick not found")
        return found
