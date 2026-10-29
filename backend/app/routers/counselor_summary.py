"""Read the reviewed goal summary without exposing internal Journey state."""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.response import success_response
from app.database import get_db
from app.models import StudentJourneyEvent, CounselorMirrorFeedback, Workspace
from app.journey import JourneyService, JourneyError
from app.routers._workspace_auth import _authorized
from app.pai_c.summary_access import _journey

router = APIRouter(prefix="/v1/counselor", tags=["Counselor"])


@router.get("/summary")
def current_summary(network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None),
                    authorization: str | None = Header(None)):
    """The Mirror state card, computed from the Vault on this read."""
    from app.pai_c.mirror import MirrorEngine
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response({"type": "mirror_state", "card": MirrorEngine(db).build(str(workspace.id))})


class MirrorAction(BaseModel):
    version: int = Field(ge=1)


class MirrorEdit(MirrorAction):
    text: str = Field(min_length=1, max_length=8000)


class MirrorFeedback(MirrorAction):
    version: int = Field(ge=1, strict=True)
    understood: int = Field(ge=1, le=5, strict=True)
    certainty_after: int | None = Field(default=None, ge=0, le=10, strict=True)


@router.post("/summary/feedback")
def mirror_feedback(body: MirrorFeedback, network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None),
                    authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    # Serialize duplicate submissions; confirmation history survives draft changes.
    db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())
    proof = db.scalar(select(StudentJourneyEvent).where(
        StudentJourneyEvent.workspace_id == workspace_id,
        StudentJourneyEvent.event_type == "counselor.mirror.confirmed",
        StudentJourneyEvent.payload["mirror_version"].as_integer() == body.version,
    ).order_by(StudentJourneyEvent.created_at, StudentJourneyEvent.id).limit(1))
    if proof is None:
        raise HTTPException(409, "This Mirror version cannot be rated")
    row = db.scalar(select(CounselorMirrorFeedback).where(
        CounselorMirrorFeedback.workspace_id == workspace_id,
        CounselorMirrorFeedback.mirror_version == body.version))
    if row is None:
        row = CounselorMirrorFeedback(workspace_id=workspace_id, mirror_version=body.version,
            understood=body.understood, certainty_after=body.certainty_after,
            certainty_before=proof.payload.get("certainty_before"))
        db.add(row)
    db.commit()
    return success_response({"version": row.mirror_version, "understood": row.understood,
        "certainty_after": row.certainty_after, "certainty_before": row.certainty_before})


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
        from app.pai_c.possibilities import PossibilityService
        PossibilityService(db).from_mirror(journey)
        enqueue_confirmed_research(db, str(workspace.id), journey)
        # A confirmed Mirror is the moment for the full 360-degree look: the
        # analyzer fit-checks the Mirror's paths and adds any the evidence supports.
        from app.pai_c.paths.analyzer import enqueue_path_analysis, policy as path_policy
        if path_policy()["triggers"]["after_mirror_confirmed"]:
            draft = journey.counselor_summary_draft or {}
            enqueue_path_analysis(db, str(workspace.id), source_event_id=draft.get("source_event_id"),
                                  channel=draft.get("channel"), reason="mirror")
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
