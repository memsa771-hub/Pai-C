"""Read-only Counselor choice hand-off for the student and PAI OS: the active
route decision (pai_route_decisions), or null."""

from fastapi import APIRouter, Depends, Header, Query

from app.api.response import success_response
from app.database import get_db
from app.pai_c.roadmap.decisions import RouteDecisionService
from app.routers._workspace_auth import _authorized

router = APIRouter(prefix="/v1/decision-records", tags=["Counselor decisions"])


@router.get("/current")
def current_decision(network: str = Query(...), db=Depends(get_db),
                     x_workspace_token: str | None = Header(None),
                     authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response(RouteDecisionService(db).current(str(workspace.id)))
