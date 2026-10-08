"""Single Counselor entry point for research delegation.

Deep discovery stores questions only. PR 6 must mark the mirror summary as
confirmed before requesting roadmap_light. roadmap_deep is reserved until its
chosen-roadmap research implementation is introduced.
"""

from sqlalchemy import select

from app.journey import JourneyService
from app.models import ExecutionRun, Roadmap, RoadmapStudentState, Workspace
from app.counseling.research_flow import research_brief


async def request_research(kind: str, workspace_id: str, *, db, journey,
                           goals: list[dict], understanding: dict, tool_context,
                           refresh_key: str | None = None,
                           refresh_candidate: dict | None = None,
                           roadmap_id: str | None = None) -> dict | None:
    if kind not in {"roadmap_light", "roadmap_deep", "stale_refresh"}:
        raise ValueError("unknown Counselor research kind")
    if tool_context is None or tool_context.workspace_id != workspace_id:
        return None
    workspace = db.scalar(select(Workspace.id).where(
        Workspace.id == workspace_id, Workspace.status == "active"))
    if workspace is None or journey is None:
        return None
    journey = JourneyService(db).get(workspace_id, journey.id)
    if journey is None or journey.status != "active" or journey.journey_type != "counselor_decision":
        return None
    if kind == "roadmap_light":
        if refresh_key is not None or journey.current_stage != "RESEARCHING":
            return None
        if (
                journey.counselor_summary_draft or {}).get("status") != "confirmed":
            return None
    elif kind == "stale_refresh":
        if not refresh_key or journey.current_stage not in {"RESEARCHING", "PROPOSED", "CHOSEN"}:
            return None
        stale = db.scalar(select(Roadmap.id).where(
            Roadmap.workspace_id == workspace_id, Roadmap.journey_id == journey.id,
            Roadmap.generation_status == "stale").limit(1))
        if stale is None:
            return None
    else:
        chosen = db.scalar(select(Roadmap.id).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
                Roadmap.workspace_id == workspace_id, Roadmap.journey_id == journey.id,
                Roadmap.id == roadmap_id, RoadmapStudentState.chosen_at.is_not(None)))
        if journey.current_stage != "CHOSEN" or chosen is None:
            return None
        raise NotImplementedError("chosen roadmap deep research is deferred")
    return await _delegate_existing_research(
        db, workspace_id, journey, goals, understanding, tool_context,
        refresh_key=refresh_key, refresh_candidate=refresh_candidate)


async def _delegate_existing_research(db, workspace_id: str, journey, goals: list[dict],
                                     understanding: dict, tool_context,
                                     refresh_key: str | None = None,
                                     refresh_candidate: dict | None = None) -> dict | None:
    allowed_stage = journey.current_stage == "RESEARCHING" or (
        journey.current_stage in {"PROPOSED", "CHOSEN"} and refresh_key is not None)
    if not allowed_stage or not goals or tool_context is None:
        return None
    goal = next((item for item in goals if (item.get("details") or {}).get("underlying_objective")), None)
    if goal is None:
        return None
    key = f"{journey.id}:{goal['id']}" + (f":refresh:{refresh_key}" if refresh_key else "")
    prior = db.execute(select(ExecutionRun).where(
        ExecutionRun.workspace_id == workspace_id,
        ExecutionRun.task_type == "roadmap_research",
    ).order_by(ExecutionRun.created_at.desc()).limit(30)).scalars().all()
    if any((item.constraints or {}).get("research_key") == key for item in prior):
        return None
    draft = journey.counselor_summary_draft or {}
    brief = research_brief(goal, understanding,
                           draft.get("summary") if draft.get("status") == "confirmed" else None)
    if refresh_candidate:
        brief["refresh_candidate"] = refresh_candidate
    from app.tools import get_tool_executor
    return await get_tool_executor().execute("operator.delegate", {
        "objective": f"Research sourced routes for {brief['stated_preference']}",
        "task_type": "roadmap_research", "intent": "academic_planning",
        "constraints": {"research_key": key, "capability_input": {"brief": brief}},
        "context_refs": ["vault", "memory"],
    }, tool_context)
