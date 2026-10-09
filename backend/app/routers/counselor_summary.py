"""Read the reviewed goal summary without exposing internal Journey state."""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.response import success_response
from app.database import get_db
from app.models import StudentJourney
from app.journey import JourneyService, JourneyError
from app.routers.roadmaps import _authorized
from app.pai_c.summary_access import _journey

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
    if draft.get("type") == "mirror":
        return success_response({"type": "mirror", "status": draft.get("status"),
                                 "mirror": draft.get("mirror"), "version": draft.get("version")})
    return success_response({"status": draft.get("status"),
                             "summary": draft.get("summary") or {},
                             "version": draft.get("version")})


class MirrorAction(BaseModel):
    version: int = Field(ge=1)


class MirrorEdit(MirrorAction):
    text: str = Field(min_length=1, max_length=8000)


@router.post("/summary/confirm")
def confirm_summary(body: MirrorAction, network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None),
                    authorization: str | None = Header(None)):
    from app.pai_c.deep.mirror import enqueue_confirmed_research

    workspace = _authorized(db, network, x_workspace_token, authorization)
    row = _journey(db, str(workspace.id))
    try:
        journey = JourneyService(db).queue_counselor_research(
            str(workspace.id), row.id, str(uuid4()), actor="human:mirror_confirmation",
            expected_version=body.version)
        enqueue_confirmed_research(db, str(workspace.id), journey)
        db.commit()
    except JourneyError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return success_response({"status": "confirmed", "version": body.version})


@router.post("/summary/edit")
def edit_summary(body: MirrorEdit, background_tasks: BackgroundTasks, network: str = Query(...),
                 db=Depends(get_db), x_workspace_token: str | None = Header(None),
                 authorization: str | None = Header(None)):
    from app.routers.events import SendEventRequest, send_event

    workspace = _authorized(db, network, x_workspace_token, authorization)
    row = _journey(db, str(workspace.id))
    if not body.text.strip():
        raise HTTPException(422, "A correction is required")
    channel = row.counselor_summary_draft["channel"]
    try:
        JourneyService(db).request_counselor_summary_changes(
            str(workspace.id), row.id, body.version, actor="human:mirror_edit")
        # Reuse credential-derived event identity, all pipeline guards, posting,
        # and the normal background Counselor/extraction/Analyst hooks.
        result = send_event(SendEventRequest(
            network=str(workspace.id), type="workspace.message.posted", target=channel,
            payload={"content": body.text.strip(), "message_type": "chat"},
            metadata={"target_agents": ["pai"], "mirror_edit_version": body.version}),
            background_tasks, db, x_workspace_token, authorization, None)
        if not isinstance(result, dict) or result.get("code") != 0:
            db.rollback()
        return result
    except JourneyError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
