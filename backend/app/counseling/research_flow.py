"""Server-owned handoff from accepted goal discovery to Operator research."""

from sqlalchemy import select

from app.models import ExecutionRun


def research_brief(goal: dict, understanding: dict) -> dict:
    from .context_projection import compact_student_context

    details = goal.get("details") or {}
    countries = details.get("target_countries") or []
    return {
        "goal_id": goal.get("id"),
        "stated_preference": details.get("stated_preference") or goal.get("title"),
        "underlying_objective": details.get("underlying_objective"),
        "drivers": details.get("drivers") or [],
        "constraints": details.get("constraints") or [],
        "country": countries[0] if len(countries) == 1 else "",
        "level": details.get("degree_level") or "",
        "intake": details.get("target_intake") or "",
        "profile_summary": compact_student_context(understanding, goal.get("title") or ""),
    }


async def delegate_research_if_ready(db, workspace_id: str, journey, goals: list[dict],
                                     understanding: dict, tool_context,
                                     refresh_key: str | None = None) -> dict | None:
    allowed_stage = journey.current_stage == "RESEARCHING" or (
        journey.current_stage == "CHOSEN" and refresh_key is not None)
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
    brief = research_brief(goal, understanding)
    from app.tools import get_tool_executor
    return await get_tool_executor().execute("operator.delegate", {
        "objective": f"Research sourced routes for {brief['stated_preference']}",
        "task_type": "roadmap_research", "intent": "academic_planning",
        "constraints": {"research_key": key, "capability_input": {"brief": brief}},
        "context_refs": ["vault", "memory"],
    }, tool_context)
