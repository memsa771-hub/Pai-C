"""Research refresh and accepted-evidence resume jobs; queue identifiers retained."""
from sqlalchemy import select
from app.pai_c.memory import MemoryService

JOB_RESUME_RESEARCH = "memory.resume_research"
JOB_REFRESH_RESEARCH = "research.refresh_stale"


async def refresh_stale_research(job, db) -> dict:
    """A reported or expired source starts a fresh Counselor research run."""
    from app.research.gateway import request_research
    from app.journey import JourneyService
    from app.memory.permissions import capabilities_for_agent
    from app.memory.student_snapshot import StudentSnapshotService
    from app.models import Opportunity, RequirementSet, Roadmap, Workspace
    from app.services.pai import PAI_AGENT_NAME, PAI_ALLOWED_TOOLS, PAI_PRIMARY_CHANNEL, WorkspaceApi
    from app.tools import AUDIENCE_COUNSELOR, ToolContext

    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None:
        return {"delegated": False}
    journey = JourneyService(db).ensure_counselor(job.workspace_id)
    stale = db.execute(select(Roadmap.id).where(
        Roadmap.workspace_id == job.workspace_id, Roadmap.journey_id == journey.id,
        Roadmap.generation_status == "stale").limit(1)).first()
    if journey.current_stage not in {"PROPOSED", "CHOSEN"} or not stale:
        return {"delegated": False}
    snapshot = StudentSnapshotService(db).build(job.workspace_id)
    goals = snapshot.records.get("goal", [])
    understanding = MemoryService(db).understanding_summary(job.workspace_id)
    if journey.current_stage == "PROPOSED":
        journey = JourneyService(db).set_counselor_stage(
            job.workspace_id, journey.id, "RESEARCHING", actor="system:source_review")
    db.commit()
    context = ToolContext(
        workspace_id=job.workspace_id, agent_name=PAI_AGENT_NAME,
        api=WorkspaceApi(job.workspace_id, workspace.password_hash),
        conversation=PAI_PRIMARY_CHANNEL,
        allowed_tools=frozenset({"operator.delegate"}) & frozenset(PAI_ALLOWED_TOOLS),
        audience=AUDIENCE_COUNSELOR,
        granted_capabilities=capabilities_for_agent(PAI_AGENT_NAME),
    )
    requirement_id = (job.payload or {}).get("requirement_id")
    refresh_candidate = None
    if requirement_id:
        pair = db.execute(select(RequirementSet, Opportunity).join(Opportunity).where(
            RequirementSet.id == requirement_id,
            Opportunity.workspace_id == job.workspace_id)).first()
        if pair:
            _, opportunity = pair
            refresh_candidate = {"url": opportunity.url,
                                 "lanes": [row.lane for row in db.scalars(select(Roadmap).where(
                                     Roadmap.workspace_id == job.workspace_id,
                                     Roadmap.journey_id == journey.id,
                                     Roadmap.generation_status == "stale"))
                                     if (row.route or {}).get("url") == opportunity.url and row.lane],
                                 "title": opportunity.route.get("title") or opportunity.institution or "Route",
                                 "country": opportunity.country,
                                 "level": opportunity.level,
                                 "intake": opportunity.intake}
    result = await request_research(
        "stale_refresh", job.workspace_id, trigger="stale_refresh", db=db, journey=journey, goals=goals,
        snapshot=snapshot, understanding=understanding, tool_context=context,
        refresh_key=requirement_id or job.id, refresh_candidate=refresh_candidate)
    return {"delegated": bool(result and result.get("ok"))}


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
            "roadmap_light", job.workspace_id, db=db, journey=None, tool_context=ctx,
            trigger="student_answer", resume_run_id=run_id,
            resume_action={"candidate_id": candidate.id})
        accepted = bool(result and result.get("ok") and result.get("data", {}).get("resumed"))
        resumed += int(accepted)
        if accepted:
            from app.pai_c.student_requests import StudentRequestService
            for field in matching_fields[run_id]:
                StudentRequestService(db).mark_answered(job.workspace_id, run_id, field)
            db.commit()
    # Resume permitted research from the canonical snapshot without a new chat
    # turn; discovery alone must not bypass the mirror-confirmation gate.
    from app.research.gateway import request_research
    from app.pai_c.stages import advance_discovery_stage
    from app.journey import JourneyService
    from app.memory.student_snapshot import StudentSnapshotService
    from app.memory.permissions import capabilities_for_agent
    from app.services.pai import PAI_AGENT_NAME, PAI_ALLOWED_TOOLS, PAI_PRIMARY_CHANNEL
    from app.tools import AUDIENCE_COUNSELOR

    snapshot = StudentSnapshotService(db).build(job.workspace_id)
    owner = db.get(User, workspace.owner_user_id) if workspace.owner_user_id else None
    journeys = JourneyService(db)
    journey = journeys.ensure_counselor(job.workspace_id, actor="system:reconciliation")
    journey = advance_discovery_stage(
        journeys, job.workspace_id, journey,
        identity_ready=bool(owner and owner.onboarded_at),
        foundation_ready=MemoryService(db).foundation_ready(MemoryService(db).truth_map(job.workspace_id).notebook),
        goal_records=snapshot.records.get("goal", []), actor="system:reconciliation")
    from app.models import Roadmap
    stale = db.execute(select(Roadmap.id).where(
        Roadmap.workspace_id == job.workspace_id,
        Roadmap.journey_id == journey.id,
        Roadmap.generation_status == "stale",
    ).limit(1)).first() is not None
    refresh_key = None
    if journey.current_stage == "PROPOSED" and stale:
        journey = journeys.set_counselor_stage(
            job.workspace_id, journey.id, "RESEARCHING", actor="system:reconciliation")
        refresh_key = candidate.id
    elif journey.current_stage == "CHOSEN" and stale:
        refresh_key = candidate.id
    may_delegate = _research_delegate_allowed(journey, refresh_key)
    db.commit()
    if not may_delegate:
        return {"resumed": resumed, "delegated": False}
    counselor_ctx = ToolContext(
        workspace_id=job.workspace_id, agent_name=PAI_AGENT_NAME,
        api=WorkspaceApi(job.workspace_id, workspace.password_hash),
        conversation=PAI_PRIMARY_CHANNEL,
        allowed_tools=frozenset({"operator.delegate"}) & frozenset(PAI_ALLOWED_TOOLS),
        audience=AUDIENCE_COUNSELOR,
        granted_capabilities=capabilities_for_agent(PAI_AGENT_NAME),
    )
    delegated = await request_research(
        "stale_refresh" if refresh_key else "roadmap_light", job.workspace_id,
        db=db, journey=journey, goals=snapshot.records.get("goal", []),
        snapshot=snapshot, understanding=MemoryService(db).understanding_summary(job.workspace_id), tool_context=counselor_ctx, refresh_key=refresh_key, trigger="student_answer")
    return {"resumed": resumed, "delegated": bool(delegated and delegated.get("ok"))}


def _research_delegate_allowed(journey, refresh_key: str | None) -> bool:
    """PR 6 mirror confirmation must set counselor_summary_draft.status='confirmed'."""
    if refresh_key is not None or journey.current_stage in {"PROPOSED", "CHOSEN"}:
        return True
    return (journey.current_stage == "RESEARCHING"
            and (journey.counselor_summary_draft or {}).get("status") == "confirmed")


