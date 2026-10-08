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
    if kind not in {"roadmap_light", "roadmap_deep", "stale_refresh"}:
        raise ValueError("unknown Counselor research kind")
    if tool_context is None or tool_context.workspace_id != workspace_id or journey is None:
        return None
    workspace = db.scalar(select(Workspace.id).where(
        Workspace.id == workspace_id, Workspace.status == "active").with_for_update())
    journey = JourneyService(db).get(workspace_id, journey.id)
    if not workspace or not journey or journey.status != "active" or not mirror_is_current(db, workspace_id):
        return None
    if kind == "roadmap_light" and (refresh_key is not None or journey.current_stage != "RESEARCHING"):
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
    key = f"{journey.id}:mirror:{brief['mirror_version']}" + (f":refresh:{refresh_key}" if refresh_key else "")
    prior = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
                        ExecutionRun.task_type == "roadmap_research")).all()
    if any((item.constraints or {}).get("research_key") == key for item in prior):
        return None
    if refresh_candidate:
        brief["refresh_candidate"] = refresh_candidate
    from app.tools import get_tool_executor
    return await get_tool_executor().execute("operator.delegate", {
        "objective": "Research decisive facts for the confirmed student routes and noted questions",
        "task_type": "roadmap_research", "intent": "academic_planning",
        "constraints": {"research_key": key, "mirror_version": brief["mirror_version"],
                        "capability_input": {"brief": brief}},
        "context_refs": ["vault", "memory"]}, tool_context)
