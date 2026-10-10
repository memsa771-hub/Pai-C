"""Authenticated student roadmap list and choice actions."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import get_db
from app.api.response import success_response
from app.models import Roadmap
from app.pai_c.roadmaps.service import RoadmapError, RoadmapService
from app.research.requirements import RequirementStore, ResearchEvidenceError
from app.routers.network import _resolve_workspace, _verify_workspace_access

router = APIRouter(prefix="/v1/roadmaps", tags=["Roadmaps"])
logger = logging.getLogger(__name__)


class FlagAction(BaseModel):
    value: bool


class ChoiceAction(BaseModel):
    confirm_token: str
    choice_channel: Literal["chat", "voice", "roadmaps"] = "roadmaps"


class CustomGoal(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    country: str | None = Field(default=None, max_length=100)
    level: str | None = Field(default=None, max_length=100)
    field: str | None = Field(default=None, max_length=120)
    why: str | None = Field(default=None, max_length=500)


def _authorized(db, network, token, authorization):
    workspace = _resolve_workspace(db, network)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not _verify_workspace_access(workspace, token, authorization):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return workspace


def _result(action, db):
    try:
        result = action()
    except RoadmapError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return success_response(result)


@router.get("")
def list_roadmaps(network: str = Query(...), filter: Literal["all", "favorites", "exploring", "dismissed"] = "all",
                  db=Depends(get_db), x_workspace_token: str | None = Header(None),
                  authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: {"roadmaps": RoadmapService(db).list(str(workspace.id), filter, presented=True)}, db)


@router.get("/{roadmap_id}")
def get_roadmap(roadmap_id: str, network: str = Query(...), db=Depends(get_db),
                x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: RoadmapService(db).get_detail(str(workspace.id), roadmap_id, presented=True), db)


@router.post("/requirements/{requirement_id}/report")
def report_wrong_requirement(requirement_id: str, network: str = Query(...), db=Depends(get_db),
                             x_workspace_token: str | None = Header(None),
                             authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    try:
        row = RequirementStore(db).report_wrong_info(str(workspace.id), requirement_id)
    except ResearchEvidenceError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return success_response({"requirement_id": row.id, "status": row.status,
                             "message": "Thanks. PAI will recheck this source."})


@router.post("/{roadmap_id}/retry")
async def retry_roadmap(roadmap_id: str, network: str = Query(...), db=Depends(get_db),
                        x_workspace_token: str | None = Header(None),
                        authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    try:
        objective, constraints = RoadmapService(db).prepare_retry(workspace_id, roadmap_id)
    except RoadmapError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    from app.memory.permissions import capabilities_for_agent
    from app.services.pai import PAI_AGENT_NAME, PAI_ALLOWED_TOOLS, PAI_PRIMARY_CHANNEL, WorkspaceApi
    from app.tools import AUDIENCE_COUNSELOR, ToolContext

    context = ToolContext(
        workspace_id=workspace_id, agent_name=PAI_AGENT_NAME,
        api=WorkspaceApi(workspace_id, workspace.password_hash),
        conversation=PAI_PRIMARY_CHANNEL,
        allowed_tools=frozenset({"operator.delegate"}) & frozenset(PAI_ALLOWED_TOOLS),
        audience=AUDIENCE_COUNSELOR,
        granted_capabilities=capabilities_for_agent(PAI_AGENT_NAME),
    )
    from app.research.gateway import request_research
    from app.journey import JourneyService
    target = db.get(Roadmap, roadmap_id)
    journey = JourneyService(db).get(workspace_id, target.journey_id)
    delegated = await request_research("roadmap_light", workspace_id, db=db,
        journey=journey, tool_context=context, roadmap_id=roadmap_id, trigger="route_retry",
        refresh_key=constraints["research_key"],
        refresh_candidate=((constraints.get("capability_input") or {}).get("brief") or {}).get("refresh_candidate"))
    row = db.get(Roadmap, roadmap_id)
    if not delegated or not delegated.get("ok"):
        row.generation_status = "failed"
        row.stale_reason = "Research could not start; try again later"
        db.commit()
        raise HTTPException(status_code=503, detail=row.stale_reason)
    row.execution_run_id = delegated["data"]["run_id"]
    db.commit()
    return success_response(RoadmapService(db).get(workspace_id, roadmap_id))


@router.post("/{roadmap_id}/focus")
async def focus_roadmap(roadmap_id: str, network: str = Query(...), db=Depends(get_db),
                  x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    try:
        current, state = RoadmapService(db)._require(str(workspace.id), roadmap_id)
    except RoadmapError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    first_focus = state.focused_at is None
    title = current.title
    result = _result(lambda: RoadmapService(db).focus(str(workspace.id), roadmap_id), db)
    if first_focus:
        from app.pai_c.posting import _build_conversation_context, _post_response
        from app.pai_c.deep.turn import run_deep_turn
        from app.pai_c.deep.turn_input import CounselorTurnInput
        from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL
        try:
            target = f"channel/{PAI_PRIMARY_CHANNEL}"
            history = _build_conversation_context(db, str(workspace.id), target,
                                                  PAI_AGENT_NAME, exclude_event_id="", max_chars=3000)
            turn = CounselorTurnInput(
                channel=target, workspace_id=str(workspace.id),
                student_text=f"I opened the roadmap named {title}.",
                attachments=(), session_id=None, source_event_id="",
                timestamp=None, source=f"human:{workspace.owner_user_id}",
            )
            response = await run_deep_turn(db, turn, roadmap_id=roadmap_id, history=history)
            opening = response.reply
            if opening:
                await _post_response(db, str(workspace.id), target,
                                     PAI_AGENT_NAME, opening, depth=0)
        except Exception as exc:
            # The persisted focus remains usable on the next ordinary turn.
            db.rollback()
            logger.warning("roadmap discussion failed roadmap_id=%s error_type=%s",
                           roadmap_id, type(exc).__name__)
    return result


@router.post("/{roadmap_id}/rethink")
def rethink_roadmap(roadmap_id: str, network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: RoadmapService(db).rethink(str(workspace.id), roadmap_id), db)


@router.post("/{roadmap_id}/favorite")
def favorite_roadmap(roadmap_id: str, body: FlagAction, network: str = Query(...),
                     db=Depends(get_db), x_workspace_token: str | None = Header(None),
                     authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: RoadmapService(db).set_flag(str(workspace.id), roadmap_id, "favorite", body.value), db)


@router.post("/{roadmap_id}/exploring")
def exploring_roadmap(roadmap_id: str, body: FlagAction, network: str = Query(...),
                      db=Depends(get_db), x_workspace_token: str | None = Header(None),
                      authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: RoadmapService(db).set_flag(str(workspace.id), roadmap_id, "exploring", body.value), db)


@router.post("/{roadmap_id}/dismiss")
def dismiss_roadmap(roadmap_id: str, network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: RoadmapService(db).dismiss(str(workspace.id), roadmap_id, True), db)


@router.post("/{roadmap_id}/restore")
def restore_roadmap(roadmap_id: str, network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: RoadmapService(db).dismiss(str(workspace.id), roadmap_id, False), db)


@router.post("/{roadmap_id}/choice-token")
def choice_token(roadmap_id: str, network: str = Query(...), db=Depends(get_db),
                 x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    roadmap, state = RoadmapService(db)._require(str(workspace.id), roadmap_id)
    if state.presented_at is None or state.dismissed_at or roadmap.generation_status != "ready":
        raise HTTPException(status_code=409, detail="Only a presented, ready route can be chosen")
    return success_response({"confirm_token": RoadmapService.choice_token(roadmap, workspace.password_hash)})


@router.post("/{roadmap_id}/choose")
def choose_roadmap(roadmap_id: str, body: ChoiceAction, network: str = Query(...),
                   db=Depends(get_db), x_workspace_token: str | None = Header(None),
                   authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _result(lambda: RoadmapService(db).choose(str(workspace.id), roadmap_id,
                                                     body.confirm_token, workspace.password_hash,
                                                     choice_channel=body.choice_channel), db)


@router.post("/custom")
async def add_custom_goal(body: CustomGoal, network: str = Query(...), db=Depends(get_db),
                          x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    from app.research.gateway import mirror_is_current, request_research
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    from app.journey import JourneyService
    from app.services.pai import PAI_AGENT_NAME, PAI_ALLOWED_TOOLS, PAI_PRIMARY_CHANNEL, WorkspaceApi
    from app.memory.permissions import capabilities_for_agent
    from app.tools import AUDIENCE_COUNSELOR, ToolContext

    if not mirror_is_current(db, workspace_id):
        raise HTTPException(status_code=409, detail="Confirm your current Mirror with PAI before researching a route")
    details = {"stated_preference": body.title, "direction_status": "exploring"}
    if body.country:
        details["target_countries"] = [body.country]
    if body.level:
        details["degree_level"] = body.level
    if body.field:
        details["field_of_study"] = body.field
    if body.why:
        details["underlying_objective"] = body.why
    candidate = MemoryCandidateService(db).propose(
        workspace_id, "student_record", key="goal",
        proposed_value={"goal_type": "education", "title": body.title,
                        "commitment": "exploratory", "details": details},
        source_type="user_explicit", allow_user_explicit=True,
        input_channel="profile", confidence=1.0)
    result = MemoryReconciler(db).reconcile(candidate)
    if not result.accepted or not result.result_id:
        db.commit()  # Keep the candidate and its conflict or rejection history.
        raise HTTPException(status_code=409, detail="The goal needs review in Profile before research")
    journey = JourneyService(db).ensure_counselor(workspace_id, actor="human:student")
    if journey.current_stage == "PROPOSED":
        journey = JourneyService(db).set_counselor_stage(
            workspace_id, journey.id, "RESEARCHING", actor="human:student")
    card = RoadmapService(db).create_custom(
        workspace_id, journey.id, result.result_id, body.title,
        {"country": body.country, "level": body.level, "field": body.field})
    db.commit()
    if card["generation_status"] == "ready" or (card["generation_status"] == "generating" and card["execution_run_id"]):
        return success_response(card)
    context = ToolContext(
        workspace_id=workspace_id, agent_name=PAI_AGENT_NAME,
        api=WorkspaceApi(workspace_id, workspace.password_hash),
        conversation=PAI_PRIMARY_CHANNEL,
        allowed_tools=frozenset({"operator.delegate"}) & frozenset(PAI_ALLOWED_TOOLS),
        audience=AUDIENCE_COUNSELOR,
        granted_capabilities=capabilities_for_agent(PAI_AGENT_NAME),
    )
    delegated = await request_research("roadmap_light", workspace_id, db=db,
        journey=journey, tool_context=context, roadmap_id=card["id"], trigger="student_route")
    row = db.get(Roadmap, card["id"])
    if delegated and delegated.get("ok"):
        row.execution_run_id = delegated["data"]["run_id"]
    else:
        row.generation_status = "failed"
    db.commit()
    return success_response(RoadmapService(db).get(workspace_id, card["id"]))
