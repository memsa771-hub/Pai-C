"""Read the reviewed goal summary without exposing internal Journey state."""

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select

from app.api.response import success_response
from app.database import get_db
from app.models import StudentJourney
from app.routers.roadmaps import _authorized

router = APIRouter(prefix="/v1/counselor", tags=["Counselor"])


@router.get("/summary")
def current_summary(network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None),
                    authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    row = db.execute(select(StudentJourney).where(
        StudentJourney.workspace_id == str(workspace.id),
        StudentJourney.journey_type == "counselor_decision",
        StudentJourney.status == "active").limit(1)).scalar_one_or_none()
    draft = (row.counselor_summary_draft or {}) if row else {}
    return success_response({"status": draft.get("status"),
                             "summary": draft.get("summary") or {},
                             "version": draft.get("version")})
