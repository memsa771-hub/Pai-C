"""Counselor-owned roadmap jobs dispatched by the shared Task Runtime."""

from app.pai_c.roadmaps.service import RoadmapService

JOB_MARK_STALE = "roadmaps.mark_stale"


async def mark_stale_job(job, db) -> dict:
    payload = job.payload or {}
    workspace_id = payload.get("workspace_id")
    if not workspace_id or workspace_id != job.workspace_id:
        raise ValueError("roadmap stale job requires its own workspace")
    reason = payload.get("reason")
    if not isinstance(reason, str):
        raise ValueError("roadmap stale job requires a reason")
    return {"marked_stale": RoadmapService(db).mark_stale(workspace_id, reason)}
