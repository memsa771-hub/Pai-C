"""Accepted-evidence resume job; queue identifier retained."""
from sqlalchemy import select
from app.pai_c.memory import MemoryService

JOB_RESUME_RESEARCH = "memory.resume_research"


async def resume_research(job, db) -> dict:
    """Accepted canonical evidence resumes only matching paused runs."""
    from app.research.gateway import request_research
    from app.models import ExecutionRun, MemoryCandidate, User, Workspace
    from app.services.pai import WorkspaceApi
    from app.tools import ToolContext

    candidate = db.get(MemoryCandidate, (job.payload or {}).get("candidate_id"))
    if candidate is None or candidate.workspace_id != job.workspace_id or candidate.status != "accepted":
        return {"resumed": 0}
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None:
        return {"resumed": 0}
    runs = db.execute(select(ExecutionRun).where(
        ExecutionRun.workspace_id == job.workspace_id,
        ExecutionRun.status == "needs_user_action",
    )).scalars().all()
    matching = []
    matching_fields = {}
    for run in runs:
        pending = run.pending_action or {}
        fields = {str(item.get("field")) for item in pending.get("items") or []
                  if isinstance(item, dict)}
        if (pending.get("kind") == "fact" and candidate.reconciled_at
                and candidate.reconciled_at >= run.created_at and (candidate.key in fields or
                any(field.startswith(str(candidate.key) + marker) for field in fields
                    for marker in (".", "[")))):
            matching.append(run.id)
            matching_fields[run.id] = [field for field in fields if candidate.key == field or
                                        any(field.startswith(str(candidate.key) + marker)
                                            for marker in (".", "["))]
    db.rollback()
    ctx = ToolContext(workspace_id=job.workspace_id, agent_name="pai-operator",
                      api=WorkspaceApi(job.workspace_id, workspace.password_hash))
    resumed = 0
    for run_id in matching:
        result = await request_research(
            "resume", job.workspace_id, db=db, journey=None, tool_context=ctx,
            trigger="student_answer", resume_run_id=run_id,
            resume_action={"candidate_id": candidate.id})
        accepted = bool(result and result.get("ok") and result.get("data", {}).get("resumed"))
        resumed += int(accepted)
        if accepted:
            from app.pai_c.student_requests import StudentRequestService
            for field in matching_fields[run_id]:
                StudentRequestService(db).mark_answered(job.workspace_id, run_id, field)
            db.commit()
    # Accepted evidence may also complete discovery; the stage moves without a
    # new chat turn. Nothing here starts research on its own.
    from app.pai_c.stages import advance_discovery_stage
    from app.journey import JourneyService
    from app.memory.student_snapshot import StudentSnapshotService

    snapshot = StudentSnapshotService(db).build(job.workspace_id)
    owner = db.get(User, workspace.owner_user_id) if workspace.owner_user_id else None
    journeys = JourneyService(db)
    journey = journeys.ensure_counselor(job.workspace_id, actor="system:reconciliation")
    advance_discovery_stage(
        journeys, job.workspace_id, journey,
        identity_ready=bool(owner and owner.onboarded_at),
        foundation_ready=MemoryService(db).foundation_ready(MemoryService(db).truth_map(job.workspace_id).notebook),
        goal_records=snapshot.records.get("goal", []), actor="system:reconciliation")
    db.commit()
    return {"resumed": resumed, "delegated": False}
