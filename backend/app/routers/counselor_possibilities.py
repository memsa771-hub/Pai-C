"""Authenticated student control over evidence-backed directions."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
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


@router.post("/{possibility_id}/{action}")
async def change_possibility(possibility_id: str, action: str, network: str = Query(...), db=Depends(get_db),
                             x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    service = PossibilityService(db)
    previous_status = None
    try:
        if action == "explore":
            previous_status = service.get(workspace_id, possibility_id).status
            row, changed = service.prepare_explore(workspace_id, possibility_id)
            if changed:
                from app.journey import JourneyService
                from app.models import Roadmap
                from app.pai_c.memory import MemoryService
                from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL, WorkspaceApi
                from app.tools import AUDIENCE_COUNSELOR, ToolContext
                from app.research.gateway import request_research
                roadmap = db.get(Roadmap, row.roadmap_id)
                if not roadmap.execution_run_id:
                    context = ToolContext(workspace_id=workspace_id, agent_name=PAI_AGENT_NAME,
                        api=WorkspaceApi(workspace_id, workspace.password_hash), conversation=PAI_PRIMARY_CHANNEL,
                        allowed_tools=frozenset({"operator.delegate"}), audience=AUDIENCE_COUNSELOR,
                        granted_capabilities=MemoryService(db).agent_capabilities(PAI_AGENT_NAME))
                    delegated = await request_research("roadmap_light", workspace_id, db=db,
                        journey=JourneyService(db).get(workspace_id, row.journey_id), tool_context=context,
                        roadmap_id=row.roadmap_id, trigger="student_route")
                    if not delegated or not delegated.get("ok"):
                        raise HTTPException(503, "Research could not start")
                    roadmap.execution_run_id = delegated["data"]["run_id"]
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
