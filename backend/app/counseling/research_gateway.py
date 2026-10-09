"""One research gateway, authorized by a versioned confirmed Mirror."""

from sqlalchemy import select

from app.journey import JourneyService
from app.models import CounselorNotedQuestion, ExecutionRun, Roadmap, RoadmapStudentState, Workspace


def mirror_is_current(db, workspace_id, version=None):
    journey = next((item for item in JourneyService(db).list_active(workspace_id)
                    if item.journey_type == "counselor_decision"), None)
    draft = (journey.counselor_summary_draft or {}) if journey else {}
    return bool(draft.get("type") == "mirror" and draft.get("status") == "confirmed"
                and (version is None or draft.get("version") == version))


def _research_brief(db, workspace_id, journey, snapshot=None):
    from app.counseling.deep.notebook import NotebookService
    from app.memory.student_snapshot import StudentSnapshotService

    snapshot = snapshot or StudentSnapshotService(db).build(workspace_id)
    draft = journey.counselor_summary_draft or {}
    notebook = NotebookService(db).get(workspace_id).notebook.model_dump(mode="json")
    questions = db.scalars(select(CounselorNotedQuestion).where(
        CounselorNotedQuestion.workspace_id == workspace_id,
        CounselorNotedQuestion.status.in_(("open", "unanswered")))).all()
    goals = snapshot.records.get("goal", [])
    return {"mirror": draft.get("mirror") or {}, "mirror_version": draft.get("version"),
        "notebook": notebook, "goals": goals, "goal_id": goals[0].get("id") if goals else None,
        "profile": {"facts": snapshot.facts, "records": snapshot.records},
        "stated_preference": (notebook.get("stated_goal") or {}).get("text") or
            next((item["picture"] for item in (draft.get("mirror") or {}).get("dimensions", [])
                  if item["key"] == "stated_goal"), ""),
        "questions": [{"id": item.id, "question": item.question_to_research} for item in questions],
        "decisive_fields": ["eligibility", "required_tests", "cost_range", "intake_window"]}


async def request_research(kind, workspace_id, *, db, journey, tool_context,
                           goals=None, snapshot=None, refresh_key=None, refresh_candidate=None,
                           roadmap_id=None):
    """Serialize gateway requests without holding row locks across Operator calls."""
    from sqlalchemy import text
    import hashlib
    lock = None
    key = int.from_bytes(hashlib.sha256(workspace_id.encode()).digest()[:8], "big", signed=True)
    try:
        if db.get_bind().dialect.name == "postgresql":
            lock = db.get_bind().connect()
            if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
                lock.close()
                lock = None
                return {"ok": False, "error": {"code": "research_busy"}}
        return await _request_research(kind, workspace_id, db=db, journey=journey,
            tool_context=tool_context, goals=goals, snapshot=snapshot, refresh_key=refresh_key,
            refresh_candidate=refresh_candidate, roadmap_id=roadmap_id)
    finally:
        if lock is not None:
            try:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            finally:
                lock.close()


async def _request_research(kind, workspace_id, *, db, journey, tool_context,
                           goals=None, snapshot=None, refresh_key=None, refresh_candidate=None,
                           roadmap_id=None):
    if kind not in {"roadmap_light", "roadmap_deep", "stale_refresh"}:
        raise ValueError("unknown Counselor research kind")
    if tool_context is None or tool_context.workspace_id != workspace_id or journey is None:
        return None
    workspace = db.scalar(select(Workspace.id).where(
        Workspace.id == workspace_id, Workspace.status == "active"))
    journey = JourneyService(db).get(workspace_id, journey.id)
    if not workspace or not journey or journey.status != "active" or not mirror_is_current(db, workspace_id):
        return None
    target = db.scalar(select(Roadmap).where(Roadmap.id == roadmap_id,
        Roadmap.workspace_id == workspace_id, Roadmap.journey_id == journey.id)) if roadmap_id else None
    if roadmap_id and target is None:
        return None
    if kind == "roadmap_light" and ((journey.current_stage != "RESEARCHING" and
            not (journey.current_stage == "CHOSEN" and target and refresh_key)) or
            (refresh_key is not None and target is None)):
        return None
    if kind == "stale_refresh":
        if not refresh_key or journey.current_stage not in {"RESEARCHING", "PROPOSED", "CHOSEN"}:
            return None
        if not db.scalar(select(Roadmap.id).where(Roadmap.workspace_id == workspace_id,
                Roadmap.journey_id == journey.id, Roadmap.generation_status == "stale").limit(1)):
            return None
    if kind == "roadmap_deep":
        chosen = db.scalar(select(Roadmap.id).join(RoadmapStudentState).where(
            Roadmap.workspace_id == workspace_id, Roadmap.id == roadmap_id,
            Roadmap.journey_id == journey.id, RoadmapStudentState.chosen_at.is_not(None)))
        if journey.current_stage != "CHOSEN" or not chosen:
            return None
        raise NotImplementedError("chosen roadmap deep research is deferred")
    brief = _research_brief(db, workspace_id, journey, snapshot)
    brief["research_kind"] = kind
    brief["refresh_key"] = refresh_key
    if target and target.origin == "student_added":
        brief["custom_roadmap"] = {"id": target.id, "title": target.title, "route": target.route or {}}
    key = f"{journey.id}:mirror:{brief['mirror_version']}" + (f":refresh:{refresh_key}" if refresh_key else "")
    if target:
        key += f":route:{target.id}"
    prior = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
                        ExecutionRun.task_type == "roadmap_research")).all()
    existing = next((item for item in prior if (item.constraints or {}).get("research_key") == key), None)
    if existing:
        return {"ok": True, "data": {"run_id": existing.id, "status": existing.status, "resumed": True}}
    if refresh_candidate:
        brief["refresh_candidate"] = refresh_candidate
    from app.tools import get_tool_executor
    payload = {
        "objective": "Research decisive facts for the confirmed student routes and noted questions",
        "task_type": "roadmap_research", "intent": "academic_planning",
        "constraints": {"research_key": key, "mirror_version": brief["mirror_version"],
                        **({"roadmap_id": target.id} if target and target.origin == "student_added" else {}),
                        "capability_input": {"brief": brief}},
        "context_refs": ["vault", "memory"]}
    db.commit()
    return await get_tool_executor().execute("operator.delegate", payload, tool_context)
