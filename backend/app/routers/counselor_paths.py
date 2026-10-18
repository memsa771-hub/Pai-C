"""Path-scoped exploration; shared research gateway owns durable work."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from app.api.response import success_response
from app.database import get_db
from app.journey import JourneyService
from app.models import ExecutionRun
from app.pai_c.memory import MemoryService
from app.pai_c.possibilities import PossibilityService, PossibilityError
from app.routers.roadmaps import _authorized

router = APIRouter(prefix="/v1/counselor/paths", tags=["Counselor"])


def path_row(db, workspace_id, path_id):
    try:
        return PossibilityService(db).get(workspace_id, path_id)
    except PossibilityError as exc:
        raise HTTPException(404, "Path not found") from exc


def tool_context(workspace, db):
    from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL, WorkspaceApi
    from app.tools import AUDIENCE_COUNSELOR, ToolContext
    return ToolContext(workspace_id=str(workspace.id), agent_name=PAI_AGENT_NAME,
        api=WorkspaceApi(str(workspace.id), workspace.password_hash), conversation=PAI_PRIMARY_CHANNEL,
        allowed_tools=frozenset({"operator.delegate"}), audience=AUDIENCE_COUNSELOR,
        granted_capabilities=MemoryService(db).agent_capabilities(PAI_AGENT_NAME))


@router.get("/{path_id}")
def get_path(path_id: str, network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    row = path_row(db, str(workspace.id), path_id)
    journey = JourneyService(db).get(str(workspace.id), row.journey_id)
    version = (journey.counselor_summary_draft or {}).get("version")
    runs = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == str(workspace.id),
        ExecutionRun.task_type == "path_explain").order_by(ExecutionRun.created_at.desc())).all()
    run = next((item for item in runs if (item.constraints or {}).get("possibility_id") == row.id
                and (item.constraints or {}).get("mirror_version") == version), None)
    result = ((run.result or {}).get("capability_result") or {}) if run and run.status == "completed" else {}
    return success_response({"possibility": PossibilityService.serialize(row), "status": run.status if run else "not_started",
        "path": result.get("path"), "facts": result.get("facts", []), "missing": result.get("missing", []),
        "run_id": run.id if run else None})


@router.post("/{path_id}/explore")
async def explore(path_id: str, network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    row = path_row(db, workspace_id, path_id)
    from app.research.gateway import mirror_is_current, request_research
    if not mirror_is_current(db, workspace_id):
        raise HTTPException(409, "Confirm your current Mirror before exploring")
    try:
        row, _ = PossibilityService(db).transition(workspace_id, path_id, "explore")
    except PossibilityError as exc:
        raise HTTPException(409, str(exc)) from exc
    outcome = await request_research("path_explain", workspace_id, db=db,
        journey=JourneyService(db).get(workspace_id, row.journey_id), tool_context=tool_context(workspace, db),
        possibility_id=path_id, trigger="student_route")
    if not outcome or not outcome.get("ok"):
        db.rollback()
        raise HTTPException(503, "Path explanation could not start. Try again")
    db.commit()
    return success_response(outcome["data"])
