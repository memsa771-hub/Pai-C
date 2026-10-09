"""One workspace-scoped read surface for research and future OS requests."""

from typing import Literal

from fastapi import APIRouter, Depends, Header, Query

from app.api.response import success_response
from app.pai_c.student_requests import StudentRequestService
from app.database import get_db
from app.routers.roadmaps import _authorized

router = APIRouter(prefix="/v1/student-requests", tags=["Student requests"])


@router.get("")
def list_requests(network: str = Query(...), status: Literal["open", "answered", "withdrawn", "all"] = "open",
                  db=Depends(get_db), x_workspace_token: str | None = Header(None),
                  authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response({"requests": StudentRequestService(db).list(str(workspace.id), status=status)})
