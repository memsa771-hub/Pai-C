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


def _research_brief(db, workspace_id, journey, snapshot=None, understanding=None):
    from app.pai_c.memory import MemoryService
    from app.memory.student_snapshot import StudentSnapshotService

    snapshot = snapshot or StudentSnapshotService(db).build(workspace_id)
    draft = journey.counselor_summary_draft or {}
    notebook = understanding if understanding is not None else MemoryService(db).understanding_summary(workspace_id)
    questions = db.scalars(select(CounselorNotedQuestion).where(
        CounselorNotedQuestion.workspace_id == workspace_id,
        CounselorNotedQuestion.needs_research.is_(True),
        CounselorNotedQuestion.status.in_(("open", "unanswered")))).all()
    goals = snapshot.records.get("goal", [])
    return {"mirror": draft.get("mirror") or {}, "mirror_version": draft.get("version"),
        "notebook": notebook, "goals": goals, "goal_id": goals[0].get("id") if goals else None,
        "profile": {"facts": snapshot.facts, "records": snapshot.records},
        "stated_preference": next((item["value"] for item in notebook["said"] if item["key"] == "stated_goal" and item["status"] == "active"), "") or
            next((item["picture"] for item in (draft.get("mirror") or {}).get("dimensions", [])
                  if item["key"] == "stated_goal"), ""),
        "questions": [{"id": item.id, "question": item.question_to_research} for item in questions],
        "decisive_fields": ["eligibility", "required_tests", "cost_range", "intake_window"]}


async def request_research(kind, workspace_id, *, db, journey, tool_context,
                           goals=None, snapshot=None, understanding=None, refresh_key=None, refresh_candidate=None,
                           roadmap_id=None, trigger=None, resume_run_id=None, resume_action=None, possibility_id=None):
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
            tool_context=tool_context, goals=goals, snapshot=snapshot, understanding=understanding, refresh_key=refresh_key,
            refresh_candidate=refresh_candidate, roadmap_id=roadmap_id, trigger=trigger,
            resume_run_id=resume_run_id, resume_action=resume_action, possibility_id=possibility_id)
    finally:
        if lock is not None:
            try:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            finally:
                lock.close()


async def _request_research(kind, workspace_id, *, db, journey, tool_context,
                           goals=None, snapshot=None, understanding=None, refresh_key=None, refresh_candidate=None,
                           roadmap_id=None, trigger=None, resume_run_id=None, resume_action=None, possibility_id=None):
    if kind in {"path_explain", "program_search"}:
        return await _request_path(db, workspace_id, journey, tool_context, possibility_id, kind)
    if kind not in {"roadmap_light", "roadmap_deep", "stale_refresh"}:
        raise ValueError("unknown Counselor research kind")
    trigger = trigger or ("stale_refresh" if kind == "stale_refresh" else
                          "route_retry" if roadmap_id and refresh_key else
                          "student_route" if roadmap_id else "mirror_confirmed")
    if trigger not in {"mirror_confirmed", "student_route", "route_retry", "stale_refresh", "student_answer"}:
        raise ValueError("unknown research trigger")
    if resume_run_id is not None:
        if trigger != "student_answer" or tool_context is None or tool_context.workspace_id != workspace_id:
            return None
        run = db.scalar(select(ExecutionRun).where(ExecutionRun.id == resume_run_id,
            ExecutionRun.workspace_id == workspace_id, ExecutionRun.status == "needs_user_action"))
        if run is None:
            return None
        # Resume the existing run, preserving its fact/approval checks and input.
        # The trigger is saved before handing it to Operator/worker dispatch.
        run.constraints = {**(run.constraints or {}), "trigger": trigger}
        db.commit()
        from app.services import operator
        return await operator.resume(tool_context, resume_run_id, resume_action)
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
    if kind == "roadmap_light" and trigger == "mirror_confirmed":
        # Confirmation creates paths; institution research requires a separate
        # explicit path-scoped where-to-study request.
        from app.pai_c.possibilities import PossibilityService
        PossibilityService(db).from_mirror(journey)
        db.commit()
        return {"ok": True, "data": {"status": "paths_ready", "mirror_version": (journey.counselor_summary_draft or {}).get("version")}}
    brief = _research_brief(db, workspace_id, journey, snapshot, understanding)
    brief["research_kind"] = kind
    brief["refresh_key"] = refresh_key
    if target and target.origin == "student_added":
        brief["custom_roadmap"] = {"id": target.id, "title": target.title, "route": target.route or {}}
    if target and target.origin == "operator_suggested":
        from app.models import PaiPossibility
        from app.pai_c.possibilities import PossibilityService
        possibility = db.scalar(select(PaiPossibility).where(
            PaiPossibility.workspace_id == workspace_id, PaiPossibility.roadmap_id == target.id))
        if possibility is None:
            return None
        brief["mirror"] = {**brief["mirror"], "roadmap_lanes": [{"lane": target.lane,
            "why": possibility.why, "route": PossibilityService(db).research_route(possibility),
            "evidence": [item["text"] for item in possibility.evidence]}]}
        brief["possibility_id"] = possibility.id
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
        "constraints": {"trigger": trigger, "research_key": key, "mirror_version": brief["mirror_version"],
                        **({"roadmap_id": target.id} if target and target.origin in {"student_added", "operator_suggested"} else {}),
                        "capability_input": {"brief": brief}},
        "context_refs": ["vault", "memory"]}
    db.commit()
    return await _delegate(payload, tool_context)


async def _request_path(db, workspace_id, journey, tool_context, possibility_id, kind):
    from app.pai_c.possibilities import PossibilityService
    from app.pai_c.paths.explain import policy
    from app.tools import get_tool_executor
    if not tool_context or tool_context.workspace_id != workspace_id or not journey or not mirror_is_current(db, workspace_id):
        return None
    row = PossibilityService(db).get(workspace_id, possibility_id)
    if row.journey_id != journey.id or row.status == "dismissed":
        return None
    version = journey.counselor_summary_draft["version"]
    key = f"{kind}:{row.id}:mirror:{version}"
    if kind == "program_search":
        explanations = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
            ExecutionRun.task_type == "path_explain", ExecutionRun.status == "completed")).all()
        if not any((run.constraints or {}).get("possibility_id") == row.id and
                   (run.constraints or {}).get("mirror_version") == version for run in explanations):
            return None
    runs = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
        ExecutionRun.task_type == kind).order_by(ExecutionRun.created_at.desc())).all()
    previous = next((run for run in runs if (run.constraints or {}).get("possibility_id") == row.id
        and (run.constraints or {}).get("mirror_version") == version and run.status != "failed"), None)
    if previous:
        reusable = True
        if kind == "program_search" and previous.status == "completed":
            from app.pai_c.paths.programs import reusable_program_run
            reusable = reusable_program_run(db, previous, PossibilityService(db).research_route(row))
        if kind == "path_explain" and previous.status == "completed":
            from app.pai_c.paths.explain import current_path_result
            _, expired = current_path_result((previous.result or {}).get('capability_result') or {})
            reusable = not expired
        if reusable:
            return {"ok": True, "data": {"run_id": previous.id, "status": previous.status, "resumed": True}}
        # A new explicit request may refresh expired evidence; GET never queues work.
        key += f":refresh:{previous.id}"
    brief = {"possibility_id": row.id, "title": row.title, "why": row.why,
        "evidence": row.evidence or [], "mirror_version": version}
    if kind == "program_search":
        from app.pai_c.memory import MemoryService
        brief["route"] = PossibilityService(db).research_route(row)
        brief["facts"] = MemoryService(db).comparable_facts(workspace_id)
    payload = {"objective": policy()["program_objective" if kind == "program_search" else "objective"], "task_type": kind,
        "constraints": {"trigger": "student_route", "research_key": key, "mirror_version": version,
            "possibility_id": row.id, "capability_input": {"brief": brief}}, "context_refs": []}
    db.commit()
    return await _delegate(payload, tool_context)


async def _delegate(payload, tool_context):
    from app.tools import get_tool_executor
    return await get_tool_executor().execute("operator.delegate", payload, tool_context)
