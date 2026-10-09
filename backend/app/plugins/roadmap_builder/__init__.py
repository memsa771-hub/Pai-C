"""Owns roadmap_research and composes scoped research capabilities."""

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy

DEPENDENCIES = frozenset({
    "program.discover", "program.research", "qualification.recognize",
    "scholarship.discover", "gap.assess",
})


def on_run_status(db, run):
    """Move Counselor stages only from verified run state, never model prose."""
    from app.journey import JourneyService
    from app.pai_c.stages import ASSESSING, NEEDS_INFO, PROPOSED, RESEARCHING

    from app.pai_c.roadmaps.service import RoadmapService
    from app.pai_c.student_requests import StudentRequestService
    published = []
    if run.status in {"completed", "needs_user_action", "failed"}:
        published = RoadmapService(db).publish_from_run(run)
    StudentRequestService(db).sync_research_run(run)
    if run.status == "failed":
        from app.services.notify import notify_once
        notify_once(db, run.workspace_id, dedupe_key=f"research-failed:{run.id}",
                    source="system:roadmaps", title="Research needs another try",
                    message="PAI could not complete this route check",
                    link_url="/roadmaps")
    journey = JourneyService(db).ensure_counselor(run.workspace_id, actor="system:research")
    stage = journey.current_stage
    target = None
    if run.status in {"executing", "verifying"} and stage in {RESEARCHING, NEEDS_INFO}:
        target = ASSESSING
    elif (run.status == "needs_user_action" and stage == ASSESSING
          and (run.pending_action or {}).get("type") == "need_from_student"):
        target = NEEDS_INFO
    elif (run.status in {"completed", "failed", "needs_user_action"} and stage == ASSESSING and published
          and (((run.result or {}).get("capability_result") or {}).get("mirror_version") is not None
               or run.status != "needs_user_action")):
        target = PROPOSED
    if target:
        JourneyService(db).set_counselor_stage(run.workspace_id, journey.id, target,
                                               actor="system:research")


async def build(context, payload):
    from app.config import config
    from app.plugins._shared.budget import bounded_research
    import time

    started = time.monotonic()
    with bounded_research(
        queries=config.PAI_RESEARCH_MAX_QUERIES,
        fetches=config.PAI_RESEARCH_MAX_FETCHES,
        seconds=config.PAI_RESEARCH_MAX_SECONDS,
        workspace_id=context.workspace_id,
        mirror_version=payload["brief"].get("mirror_version"),
        scope=payload["brief"].get("research_kind", "roadmap_light"),
        refresh_key=payload["brief"].get("refresh_key"),
    ) as budget:
        result = await _build(context, payload)
        result["research_metrics"] = budget.usage() | {
            "elapsed_ms": round((time.monotonic() - started) * 1000)}
        return result


async def _build(context, payload):
    from app.pai_c.light_research import collect_light_research
    from app.pai_c.deep.roadmaps import build_mirror_roadmaps, lanes_for_mirror

    brief = dict(payload["brief"])
    custom = brief.get("custom_roadmap")
    brief["mirror"] = {**brief["mirror"], "roadmap_lanes": ([{
        "lane": "student_added", "why": custom["title"], "route": custom.get("route", {}),
        **{key: value for key, value in custom.get("route", {}).items() if key in {"url", "source_url"}}}]
        if custom else lanes_for_mirror(brief["mirror"]))}
    research = await collect_light_research(context, brief)
    research["decisive_fields"] = brief["decisive_fields"]
    return await build_mirror_roadmaps(brief, research)

def get_capabilities():
    return [CapabilityContract(
        id="roadmap.build", version="1.0.0", name="Roadmap research",
        description="Compose cited program research, qualification procedures and deterministic gaps.",
        input_schema={"type": "object", "properties": {
            "brief": {"type": "object"}}, "required": ["brief"]},
        output_schema={"type": "object", "properties": {
            "roadmaps": {"type": "array"}, "unconfirmed": {"type": "array"},
            "pending_action": {}},
            "required": ["roadmaps", "unconfirmed", "pending_action"]},
        handler=build, owns_task_types=frozenset({"roadmap_research"}),
        fallback_policy=FallbackPolicy.FORBIDDEN,
        vault_scopes=frozenset({"education", "goals", "preferences", "finance", "tests"}),
        permissions=frozenset(), required_tools=frozenset(),
        uses_capabilities=DEPENDENCIES, artifacts=frozenset({"roadmap"}),
        risk=CapabilityRisk.READ, timeout_seconds=300,
        evidence_expectations={"roadmaps": "proposed research with source URLs and checked_at"},
        run_status_hook=on_run_status,
    )]
