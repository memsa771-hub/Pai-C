"""Authenticated student control over evidence-backed directions."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.api.response import success_response
from app.database import get_db
from app.routers.roadmaps import _authorized
from app.pai_c.possibilities import PossibilityService, PossibilityError

router = APIRouter(prefix="/v1/counselor/possibilities", tags=["Counselor"])


@router.get("")
def list_possibilities(network: str = Query(...), db=Depends(get_db),
                       x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    service = PossibilityService(db)
    return success_response({"possibilities": [service.serialize(row) for row in service.list(str(workspace.id))]})


class OwnPath(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    why: str = Field(default="", max_length=600)


def _counselor_channel(db, workspace_id: str) -> str | None:
    """Where the student talks to PAI: the target of their latest message."""
    from app.models import EventRecord
    return db.scalar(select(EventRecord.target).where(
        EventRecord.network_id == workspace_id, EventRecord.type == "workspace.message.posted",
        EventRecord.source.like("human:%")).order_by(EventRecord.timestamp.desc()).limit(1))


@router.post("")
def add_own_path(body: OwnPath, network: str = Query(...), db=Depends(get_db),
                 x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    """A path the student puts in themselves. The analyzer then checks it
    against them like any other; it is saved, never suggested back."""
    from app.journey import JourneyService
    from app.pai_c.paths.analyzer import enqueue_path_analysis
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(422, "A path needs a title")
    service = PossibilityService(db)
    journey = JourneyService(db).ensure_counselor(workspace_id)
    row = service.add(workspace_id, journey.id, title=title, why=body.why.strip() or title,
                      kind="student_added", source="student", status="saved")
    if row.status == "dismissed":
        # Typing a path in again is the clearest way to want it back.
        row, _ = service.transition(workspace_id, row.id, "save")
    enqueue_path_analysis(db, workspace_id, source_event_id=None, channel=None, reason="student_added")
    db.commit()
    return success_response(service.serialize(row))


@router.post("/analyze")
def analyze_paths(network: str = Query(...), db=Depends(get_db),
                  x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    """The student asks PAI to work out their paths now."""
    from app.pai_c.paths.analyzer import enqueue_path_analysis
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    job_id = enqueue_path_analysis(db, workspace_id, source_event_id=None,
                                   channel=_counselor_channel(db, workspace_id), reason="student")
    db.commit()
    return success_response({"job_id": job_id})


@router.post("/{possibility_id}/{action}")
async def change_possibility(possibility_id: str, action: str, network: str = Query(...), db=Depends(get_db),
                             x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    service = PossibilityService(db)
    previous_status = None
    try:
        if action == "explore":
            from app.routers.counselor_paths import explore
            await explore(possibility_id, network, db, x_workspace_token, authorization)
            row = service.get(workspace_id, possibility_id)
        else:
            row, _ = service.transition(workspace_id, possibility_id, action)
        db.commit()
        return success_response(service.serialize(row))
    except PossibilityError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        db.rollback()
        # The gateway commits before durable delegation. Restore the control on
        # a failed start; its research_key makes a later retry safe even when a
        # run was queued but the response was interrupted.
        if previous_status and previous_status != "exploring":
            row = service.get(workspace_id, possibility_id)
            if row.status == "exploring":
                row.status = previous_status
                db.commit()
        raise
