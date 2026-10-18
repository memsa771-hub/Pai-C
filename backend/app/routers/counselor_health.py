"""Authenticated Counselor readiness and daily diagnostics."""
from fastapi import APIRouter, Depends, Header, Query
from app.database import get_db
from app.api.response import success_response
from app.routers.roadmaps import _authorized
from app.pai_c.reliability import health

router=APIRouter(prefix='/v1/counselor',tags=['Counselor'])


@router.get('/health')
def counselor_health(network: str=Query(...), db=Depends(get_db),
    x_workspace_token: str | None=Header(None), authorization: str | None=Header(None)):
    workspace=_authorized(db,network,x_workspace_token,authorization)
    return success_response(health(db,str(workspace.id)))
