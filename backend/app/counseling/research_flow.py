"""Server-owned handoff from accepted goal discovery to Operator research."""

def research_brief(goal: dict, understanding: dict, summary: dict | None = None) -> dict:
    from .context_projection import compact_student_context

    details = goal.get("details") or {}
    countries = details.get("target_countries") or []
    summary = summary or {}
    family = (summary.get("family_wish") or {}).get("value")
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
        "family_wish": family if isinstance(family, dict) else None,
    }


async def delegate_research_if_ready(db, workspace_id: str, journey, goals: list[dict],
                                     understanding: dict, tool_context,
                                     refresh_key: str | None = None,
                                     refresh_candidate: dict | None = None) -> dict | None:
    """Compatibility entry for existing legacy and reconciliation callers."""
    from app.counseling.research_gateway import request_research

    return await request_research(
        "stale_refresh" if refresh_key else "roadmap_light", workspace_id,
        db=db, journey=journey, goals=goals, understanding=understanding,
        tool_context=tool_context, refresh_key=refresh_key,
        refresh_candidate=refresh_candidate)
