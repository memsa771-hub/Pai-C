"""Path-scoped exploration; shared research gateway owns durable work.

A finished explanation or program search is never hidden: reads return the
latest finished run with `stale: true` when the path-relevant Vault changed
since it ran (pai_c/paths/currency.py), and a new request re-runs it. No Mirror
confirmation is needed (FOUR_FEATURES_SPEC 2.3)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from app.api.response import success_response
from app.database import get_db
from app.journey import JourneyService
from app.models import ExecutionRun
from app.pai_c.memory import MemoryService
from app.pai_c.possibilities import PossibilityService, PossibilityError
from app.routers._workspace_auth import _authorized
from pydantic import BaseModel, ConfigDict
from typing import Literal

router = APIRouter(prefix="/v1/counselor/paths", tags=["Counselor"])


class ProgramConsent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    explore_places: Literal[True]


class TryItConsent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accepted: Literal[True]


@router.post('/{path_id}/try-it')
def accept_try_it(path_id: str, body: TryItConsent, network: str=Query(...), db=Depends(get_db),
    x_workspace_token: str | None=Header(None), authorization: str | None=Header(None)):
    from app.pai_c.checkins import schedule
    workspace = _authorized(db, network, x_workspace_token, authorization)
    wid = str(workspace.id)
    path = path_row(db, wid, path_id)
    # The latest finished explanation, stale or not: its activity still stands.
    _, run = path_runs(db, wid, path.id, 'path_explain')
    if path.status == 'dismissed' or not run or not (((run.result or {}).get('capability_result') or {}).get('path') or {}).get('try_it'):
        raise HTTPException(409, 'An explained path activity is required')
    job = schedule(db, wid, 'try_it', run.id)
    db.commit()
    return success_response({'status': 'scheduled', 'available_at': job.available_at.isoformat()})


def path_runs(db, workspace_id, possibility_id, task_type):
    """(latest run, latest completed run) of one kind for one path."""
    runs = [run for run in db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
        ExecutionRun.task_type == task_type).order_by(ExecutionRun.created_at.desc())).all()
        if (run.constraints or {}).get('possibility_id') == possibility_id]
    return (runs[0] if runs else None), next((run for run in runs if run.status == 'completed'), None)


def stale(db, workspace_id, run) -> bool:
    from app.pai_c.paths.currency import current_relevance, is_stale
    return bool(run) and is_stale(run, current_relevance(db, workspace_id))


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
    run, done = path_runs(db, str(workspace.id), row.id, "path_explain")
    result = ((done.result or {}).get("capability_result") or {}) if done else {}
    from app.pai_c.paths.explain import current_path_result
    result, expired = current_path_result(result)
    # `status: stale` is expired world facts; `stale: true` is a Vault change since the run.
    return success_response({"possibility": PossibilityService.serialize(row),
        "status": "stale" if expired and run is done else run.status if run else "not_started",
        "stale": stale(db, str(workspace.id), done),
        "path": result.get("path"), "facts": result.get("facts", []), "missing": result.get("missing", []),
        "run_id": run.id if run else None})


@router.post("/{path_id}/explore")
async def explore(path_id: str, network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    row = path_row(db, workspace_id, path_id)
    from app.research.gateway import request_research
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


@router.post('/{path_id}/programs')
async def search_programs(path_id: str, body: ProgramConsent, network: str = Query(...), db=Depends(get_db),
    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    row = path_row(db, str(workspace.id), path_id)
    from app.research.gateway import request_research
    outcome = await request_research('program_search', str(workspace.id), db=db,
        journey=JourneyService(db).get(str(workspace.id), row.journey_id),
        tool_context=tool_context(workspace, db), possibility_id=path_id, trigger='student_route')
    if outcome is None:
        raise HTTPException(409, 'Explore this path first')
    if not outcome.get('ok'):
        raise HTTPException(503, 'Program search could not start. Try again')
    return success_response(outcome['data'])


@router.get('/{path_id}/programs')
def get_programs(path_id: str, network: str = Query(...), db=Depends(get_db),
    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    row = path_row(db, str(workspace.id), path_id)
    run, done = path_runs(db, str(workspace.id), row.id, 'program_search')
    result = ((done.result or {}).get('capability_result') or {}) if done else {}
    from app.pai_c.paths.programs import current_programs, reusable_program_run
    result, _ = current_programs(db, str(workspace.id), result,
        MemoryService(db).comparable_facts(str(workspace.id)))
    status = run.status if run else 'not_started'
    if done and not reusable_program_run(db, done, PossibilityService(db).research_route(row)):
        if run is done:
            status = 'stale'
        # A changed destination/level must not display the previous route's programs.
        result['programs'] = []
    return success_response({'status': status, 'stale': stale(db, str(workspace.id), done),
        'programs': result.get('programs', []), 'missing': result.get('missing', [])})
