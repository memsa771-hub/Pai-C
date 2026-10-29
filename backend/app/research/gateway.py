"""One research gateway. Path research is keyed by the Vault version it read
(FOUR_FEATURES_SPEC 2.3): a stored run is current while the Vault is unchanged,
and a path can be explored as soon as it exists."""

from sqlalchemy import select

from app.memory.completeness import vault_version
from app.models import ExecutionRun


async def request_research(kind, workspace_id, *, db, journey, tool_context,
                           refresh_key=None, trigger=None, resume_run_id=None, resume_action=None,
                           possibility_id=None):
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
            tool_context=tool_context, refresh_key=refresh_key, trigger=trigger,
            resume_run_id=resume_run_id, resume_action=resume_action, possibility_id=possibility_id)
    finally:
        if lock is not None:
            try:
                lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            finally:
                lock.close()


async def _request_research(kind, workspace_id, *, db, journey, tool_context,
                            refresh_key=None, trigger=None, resume_run_id=None, resume_action=None,
                            possibility_id=None):
    if kind == "information":
        from app.pai_c.myths import enqueue_information
        if tool_context is None or tool_context.workspace_id != workspace_id:
            return None
        job = enqueue_information(db, workspace_id, refresh_key)
        return {"ok": bool(job), "data": {"job_id": job.id if job else None}}
    if kind == "myth_check":
        from app.pai_c.myths import enqueue_check
        if tool_context is None or tool_context.workspace_id != workspace_id:
            return None
        job = enqueue_check(db, workspace_id, possibility_id or "", refresh_key)
        return {"ok": bool(job), "data": {"job_id": job.id if job else None}}
    if kind in {"path_explain", "program_search"}:
        return await _request_path(db, workspace_id, journey, tool_context, possibility_id, kind)
    if kind == "resume":
        return await _resume(db, workspace_id, tool_context, resume_run_id, resume_action, trigger)
    raise ValueError("unknown Counselor research kind")


async def _resume(db, workspace_id, tool_context, run_id, action, trigger):
    """Accepted student evidence resumes the same paused run."""
    if (trigger != "student_answer" or run_id is None or tool_context is None
            or tool_context.workspace_id != workspace_id):
        return None
    run = db.scalar(select(ExecutionRun).where(ExecutionRun.id == run_id,
        ExecutionRun.workspace_id == workspace_id, ExecutionRun.status == "needs_user_action"))
    if run is None:
        return None
    # The trigger is saved before handing it to Operator/worker dispatch.
    run.constraints = {**(run.constraints or {}), "trigger": "student_answer"}
    db.commit()
    from app.services import operator
    return await operator.resume(tool_context, run_id, action)


async def _request_path(db, workspace_id, journey, tool_context, possibility_id, kind):
    from app.pai_c.possibilities import PossibilityService
    from app.pai_c.paths.explain import policy
    if not tool_context or tool_context.workspace_id != workspace_id or not journey:
        return None
    row = PossibilityService(db).get(workspace_id, possibility_id)
    if row.journey_id != journey.id or row.status == "dismissed":
        return None
    version = vault_version(db, workspace_id)
    key = f"{kind}:{row.id}:vault:{version}"
    if kind == "program_search":
        explanations = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
            ExecutionRun.task_type == "path_explain", ExecutionRun.status == "completed")).all()
        if not any((run.constraints or {}).get("possibility_id") == row.id and
                   (run.constraints or {}).get("vault_version") == version for run in explanations):
            return None
    runs = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
        ExecutionRun.task_type == kind).order_by(ExecutionRun.created_at.desc())).all()
    previous = next((run for run in runs if (run.constraints or {}).get("possibility_id") == row.id
        and (run.constraints or {}).get("vault_version") == version and run.status != "failed"), None)
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
        "evidence": row.evidence or [], "vault_version": version}
    if kind == "program_search":
        from app.pai_c.memory import MemoryService
        brief["route"] = PossibilityService(db).research_route(row)
        brief["facts"] = MemoryService(db).comparable_facts(workspace_id)
    payload = {"objective": policy()["program_objective" if kind == "program_search" else "objective"], "task_type": kind,
        "constraints": {"trigger": "student_route", "research_key": key, "vault_version": version,
            "possibility_id": row.id, "capability_input": {"brief": brief}}, "context_refs": []}
    db.commit()
    return await _delegate(payload, tool_context)


async def _delegate(payload, tool_context):
    from app.tools import get_tool_executor
    return await get_tool_executor().execute("operator.delegate", payload, tool_context)
