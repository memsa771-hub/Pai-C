# -*- coding: utf-8 -*-
"""
PAI Operator — runs PAI C's background research as capability workflows.

PAI Counselor is the student's only voice. When a turn needs research (path
explanation, program search, myth check), Counselor delegates through
``operator.delegate``; that creates an ``ExecutionRun`` row, queues a durable
``operator.run`` job and returns immediately, so chat never waits on it.
``operator.status`` reads the row back in a later turn.

A run executes exactly one installed capability workflow
(``app/plugins``) with the fixed ``capability_input`` Counselor supplied:
no Operator model call, no generic tool-using agent. ``delegate`` refuses a
task type no installed capability owns. Operator has no channel and no memory
of its own; results reach the student only through Counselor.
"""

import json as _json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.config import config
from app.database import new_session
from app.models import ExecutionRun
from app.services import pai

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Identity — mirrors pai.py's constants section. No PAI_AGENT_TYPE, no
# WorkspaceMember: see module docstring for why that's deliberate.
# ---------------------------------------------------------------------------

PAI_OPERATOR_AGENT_NAME = "pai-operator"
# Terminal states a run can end in.
STATUS_COMPLETED = "completed"
STATUS_NEEDS_USER_ACTION = "needs_user_action"
STATUS_FAILED = "failed"
_TERMINAL = frozenset({STATUS_COMPLETED, STATUS_FAILED})
_OUTCOMES = frozenset({STATUS_COMPLETED, STATUS_NEEDS_USER_ACTION, STATUS_FAILED})

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mark_plan_progress(plan: list[dict], completed_ids: Any, all_completed: bool) -> list[dict]:
    """Apply VERIFY-phase findings onto the plan's per-step status — the only
    place plan progress ever changes, so "N/M steps completed" always
    reflects what verification actually confirmed, not what tools were
    merely called (see the ExecutionRun docstring in app/models.py)."""
    if not plan:
        return plan
    completed = set(completed_ids) if isinstance(completed_ids, list) else set()
    updated = []
    marked_working = False
    for step in plan:
        status = "completed" if (all_completed or step["id"] in completed) else "pending"
        if status == "pending" and not marked_working:
            status = "working"
            marked_working = True
        updated.append({**step, "status": status})
    return updated


def serialize_run(run: ExecutionRun) -> dict:
    """The shape both the frontend (GET /v1/operator/runs) and the
    operator.status tool return — one source of truth for it."""
    return {
        "id": run.id,
        "workspace_id": run.workspace_id,
        "requested_by": run.requested_by,
        "objective": run.objective,
        "task_type": run.task_type,
        "constraints": run.constraints or {},
        "context_refs": run.context_refs or [],
        "status": run.status,
        "current_step": run.current_step,
        "plan": run.plan or [],
        "completed_steps": run.completed_steps or [],
        "tool_calls": run.tool_calls or [],
        "missing": run.missing or [],
        "approval_required_for": run.approval_required_for,
        "pending_action": run.pending_action,
        "error": run.error,
        "result": run.result,
        "verification": run.verification,
        "result_type": run.result_type,
        "result_artifact_id": run.result_artifact_id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _publish_run_updated(workspace_id: str, run: ExecutionRun) -> None:
    """Best-effort SSE nudge so the frontend can refetch instead of polling
    blind. Never allowed to fail the run it's reporting on."""
    try:
        from app.infrastructure import cache
        event = {
            "id": str(uuid.uuid4()),
            "type": "workspace.operator.run_updated",
            "source": f"openagents:{PAI_OPERATOR_AGENT_NAME}",
            "target": "core",
            "payload": serialize_run(run),
            "metadata": {},
            "timestamp": int(time.time() * 1000),
        }
        cache.publish_event(
            f"ws:{workspace_id}:events",
            _json.dumps(event, default=str, separators=(",", ":")).encode(),
        )
    except Exception:
        logger.exception("operator: failed to publish run update for %s", run.id)


async def _post_result(
    db: Any, workspace_id: str, channel_target: Optional[str],
    run_id: str, status: str, message: str,
) -> None:
    """Auto-post the finished run's outcome into the thread it was delegated
    from — the same event-pipeline path a Counselor reply already
    uses (see ``counseling.posting.send_to_student``), so the student sees the result
    the moment it's ready instead of having to ask "did it work?" in a later
    turn. Posted as PAI Counselor (``pai.PAI_AGENT_NAME``): Operator never
    speaks to the student directly, only Counselor does.

    Carries ``message_type: "operator_result"`` plus the run id/status as
    event metadata (never surfaced as text) so the frontend can attribute
    this message to PAI Operator's execution intelligence instead of
    rendering it as an ordinary Counselor reply — see the module docstring's
    "Operator result attribution" note.

    Best-effort — a failure here must never surface as the run itself
    failing; the ExecutionRun row (already committed by the caller) remains
    the source of truth either way.
    """
    if not channel_target or not message:
        return
    try:
        from app.pai_c.posting import _build_conversation_context, send_to_student
        db.rollback()
        run = db.get(ExecutionRun, run_id)
        context_current = bool(run and _result_context_current(db, run))
        if run is not None and str(run.workspace_id) == workspace_id and run.result:
            if not context_current:
                message = ("The background work is complete. I can interpret it for you "
                           "after we confirm that my understanding of your situation is accurate.")
            else:
                handoff = {
                    "objective": run.objective, "constraints": run.constraints,
                    "status": status, "result": run.result,
                    "verification": run.verification, "missing": run.missing,
                    "approval_required_for": run.approval_required_for,
                }
                history = _build_conversation_context(
                    db, workspace_id, channel_target, pai.PAI_AGENT_NAME,
                    exclude_event_id="", max_chars=12000,
                )
                db.rollback()
                try:
                    from app.pai_c.orchestrator import handle_research_result
                    explained = await handle_research_result(workspace_id, history, handoff)
                    if explained:
                        message = explained
                except Exception:
                    # Persisted evidence remains available through operator.status.
                    # Do not send raw internal output as if Counselor interpreted it.
                    logger.exception("operator: counselor handoff failed for %s", run_id)
                    message = (
                        "The background work has returned, but I couldn't prepare its explanation. "
                        "Ask me to review the findings and I'll pick up from the saved result."
                    )
        response_metadata = {"execution_run_id": run_id, "execution_status": status}
        await send_to_student(
            db, workspace_id, channel_target, pai.PAI_AGENT_NAME, message, depth=0,
            message_type="operator_result",
            metadata=response_metadata,
        )
    except Exception:
        logger.exception("operator: failed to auto-post result to %s", channel_target)


def _terminal_message(status: str, summary: Optional[str], missing: Any, verification: dict) -> str:
    """Compose the chat message for a run's terminal state — what the
    student actually sees, in PAI Counselor's voice."""
    if status == STATUS_COMPLETED:
        return summary or "Done."
    if status == STATUS_NEEDS_USER_ACTION:
        parts = [summary] if summary else []
        approval = verification.get("approval_required_for")
        if approval:
            parts.append(f"I need your go-ahead before continuing: {approval}.")
        if isinstance(missing, list) and missing:
            parts.append("Still missing: " + ", ".join(str(m) for m in missing) + ".")
        return " ".join(p for p in parts if p) or "I need a bit more from you before I can finish this."
    return summary or "I ran into an issue and couldn't finish this — let me know if you'd like me to try again."


def is_available() -> bool:
    """Operator shares Counselor's server credentials — nothing to check
    beyond whether PAI itself is configured."""
    return bool(config.PAI_ENABLED and config.PAI_API_KEY)


# ---------------------------------------------------------------------------
# Tool-facing entry points — called from app/tools/builtin/operator.py
# ---------------------------------------------------------------------------

async def delegate(ctx, objective: str, constraints: Optional[dict], context_refs: Optional[list],
                   intent: Optional[str] = None, task_type: Optional[str] = None) -> dict:
    """Create an ExecutionRun and schedule its execution in the background.

    Returns immediately — the caller (PAI Counselor's tool loop) gets an
    acknowledgement, not the finished result, so chat is never blocked on
    however long the actual work takes.
    """
    objective = (objective or "").strip()
    task_type = (task_type or "").strip() or None
    if not objective:
        return {"ok": False, "error": {"code": "invalid_arguments", "message": "objective is required"}}
    if task_type is not None and not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", task_type):
        return {"ok": False, "error": {"code": "invalid_arguments", "message": "task_type must be a stable lowercase identifier"}}
    if not is_available():
        return {"ok": False, "error": {"code": "operator_unavailable", "message": "PAI Operator is not configured on the server"}}
    from app.capabilities import get_capability_registry
    if (get_capability_registry().owner_for_task_type(task_type) is None
            or not isinstance((constraints or {}).get("capability_input"), dict)):
        return {"ok": False, "error": {"code": "unsupported_task",
                                       "message": "Operator runs only installed capability workflows with fixed input"}}

    # `ctx.conversation` is the same thread id PAI Counselor's own tool
    # context carries (see counseling.runtime._run_turn) — reconstruct
    # the event target so the finished run can post its result back into the
    # exact thread the objective came from, the way any other agent reply does.
    channel_target = f"channel/{ctx.conversation}" if getattr(ctx, "conversation", None) else None
    context_refs = context_refs if context_refs is not None else ["vault", "memory", "episodes"]
    constraints = dict(constraints or {})
    if intent:
        constraints["student_intent"] = intent

    db = new_session()
    try:
        existing = db.execute(select(ExecutionRun).where(
            ExecutionRun.workspace_id == ctx.workspace_id,
            ExecutionRun.channel_target == channel_target,
            ExecutionRun.objective == objective,
            ExecutionRun.task_type == task_type,
            ExecutionRun.status.notin_(_TERMINAL),
        ).order_by(ExecutionRun.created_at.desc()).limit(1)).scalar_one_or_none()
        if existing is not None and (existing.constraints or {}) == constraints:
            if existing.status != STATUS_NEEDS_USER_ACTION:
                _enqueue_run(db, existing)
                db.commit()
            return {"ok": True, "data": {"run_id": existing.id, "status": existing.status,
                                          "objective": objective, "already_running": True}}
        run = ExecutionRun(
            workspace_id=ctx.workspace_id,
            requested_by=ctx.source,
            channel_target=channel_target,
            objective=objective,
            task_type=task_type,
            constraints=constraints or {},
            context_refs=context_refs or [],
            status="pending",
            current_step="Queued",
        )
        db.add(run)
        db.flush()
        _enqueue_run(db, run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        data = {"run_id": run_id, "status": run.status, "objective": objective, "task_type": task_type}
    finally:
        db.close()

    return {"ok": True, "data": data}


def _baseline_is_current(db, workspace_id: str) -> bool:
    from app.research.gateway import mirror_is_current
    return mirror_is_current(db, workspace_id)


def _result_context_current(db, run: ExecutionRun) -> bool:
    return _baseline_is_current(db, run.workspace_id)


async def resume(ctx, run_id: str, action: dict) -> dict:
    """Resume the same paused ExecutionRun with structured human input."""
    if not run_id or not isinstance(action, dict) or not action:
        return {"ok": False, "error": {"code": "invalid_arguments", "message": "run_id and action are required"}}
    db = new_session()
    try:
        run = db.execute(select(ExecutionRun).where(
            ExecutionRun.id == run_id, ExecutionRun.workspace_id == ctx.workspace_id,
        ).with_for_update()).scalar_one_or_none()
        if run is None:
            return {"ok": False, "error": {"code": "not_found", "message": "run not found"}}
        if run.status != STATUS_NEEDS_USER_ACTION or not run.pending_action:
            return {"ok": False, "error": {"code": "not_paused", "message": "run is not waiting for user action"}}
        pending = dict(run.pending_action)
        kind = pending.get("kind")
        if kind == "fact":
            from app.models import MemoryCandidate
            candidate = db.execute(select(MemoryCandidate).where(
                MemoryCandidate.id == action.get("candidate_id"),
                MemoryCandidate.workspace_id == ctx.workspace_id,
                MemoryCandidate.status == "accepted",
            )).scalar_one_or_none()
            fields = {str(item.get("field")) for item in pending.get("items") or []}
            if candidate is None or not candidate.reconciled_at or candidate.reconciled_at < run.created_at or (candidate.key not in fields and
                                     not any(field.startswith(str(candidate.key) + marker) for field in fields
                                             for marker in (".", "["))):
                return {"ok": False, "error": {"code": "fact_not_accepted", "message": "A matching accepted fact is required"}}
        if kind == "approval" and action.get("approved") is not True:
            run.resume_input = {"pending_action": pending, "response": action, "received_at": _now().isoformat()}
            run.pending_action = None
            run.status = STATUS_FAILED
            run.current_step = "The student declined the requested action"
            run.error = "approval declined"
            run.completed_at = _now()
            db.commit()
            return {"ok": True, "data": {"run_id": run_id, "status": STATUS_FAILED, "resumed": False}}
        if kind == "text" and not str(action.get("text") or action.get("value") or "").strip():
            return {"ok": False, "error": {"code": "action_incomplete", "message": "text is required"}}
        if kind == "file" and not str(action.get("file_id") or "").strip():
            return {"ok": False, "error": {"code": "action_incomplete", "message": "file_id is required"}}
        if kind == "choice" and action.get("choice") not in (pending.get("options") or []):
            return {"ok": False, "error": {"code": "action_incomplete", "message": "a listed choice is required"}}
        if kind == "profile_conflict":
            from app.memory.errors import MemoryDataError
            from app.memory.profile_issues import ProfileIssueService
            try:
                resolution = ProfileIssueService(db).resolve(
                    ctx.workspace_id, str(action.get("issue_id") or ""),
                    str(action.get("resolution_action") or ""),
                    value=action.get("value"), note=action.get("note"),
                )
            except MemoryDataError as exc:
                return {"ok": False, "error": {"code": "action_incomplete", "message": str(exc)}}
            if not resolution.get("resolved"):
                return {"ok": False, "error": {"code": "conflict_unresolved", "message": str(resolution.get("reason") or "profile conflict remains unresolved")}}
        resume_count = int((run.resume_input or {}).get("resume_count", 0)) + 1
        run.resume_input = {"pending_action": pending, "response": action,
                            "received_at": _now().isoformat(), "resume_count": resume_count}
        run.pending_action = None
        run.status = "pending"
        run.current_step = "Resuming with the student's response"
        run.completed_at = None
        _enqueue_run(db, run)
        db.commit()
    finally:
        db.close()
    return {"ok": True, "data": {"run_id": run_id, "status": "pending", "resumed": True}}


# ---------------------------------------------------------------------------
# Execution: one installed capability workflow with fixed input
# ---------------------------------------------------------------------------

async def _execute(
    run_id: str, workspace_id: str, api: Any,
    objective: str, constraints: dict, context_refs: list,
    channel_target: Optional[str] = None, resume_payload: Optional[dict] = None,
) -> None:
    db = new_session()
    try:
        run = db.get(ExecutionRun, run_id)
        if not run:
            logger.error("operator: run %s vanished before execution started", run_id)
            return

        def set_status(status: str, **fields: Any) -> None:
            run.status = status
            for key, value in fields.items():
                setattr(run, key, value)
            from app.capabilities import get_capability_registry
            owner_for_update = get_capability_registry().owner_for_task_type(run.task_type)
            if owner_for_update and owner_for_update.run_status_hook:
                owner_for_update.run_status_hook(db, run)
            db.commit()
            db.refresh(run)
            _publish_run_updated(workspace_id, run)

        from app.capabilities import get_capability_registry
        from app.capabilities.execution_policy import resolve_run_policy
        workflow_policy = resolve_run_policy(get_capability_registry(), run.task_type, run.resume_input)
        capability_input = (run.constraints or {}).get("capability_input")
        if workflow_policy.owner and isinstance(capability_input, dict):
            await _execute_workflow(db, run, api, workflow_policy, capability_input, set_status)
            return

        raise RuntimeError("Operator runs only installed capability workflows with fixed input")
    except Exception as exc:
        logger.exception("operator: run %s failed unexpectedly", run_id)
        try:
            run = db.get(ExecutionRun, run_id)
            if run:
                run.status = STATUS_FAILED
                run.error = str(exc)[:500]
                run.completed_at = _now()
                db.commit()
                _publish_run_updated(workspace_id, run)
                await _post_result(db, workspace_id, channel_target, run_id, STATUS_FAILED, "I ran into an unexpected issue and had to stop working on that — want me to try again?")
        except Exception:
            logger.exception("operator: failed to record failure for run %s", run_id)
    finally:
        db.close()


async def _execute_workflow(db, run, api, policy, capability_input, set_status):
    """Fixed input uses the ordinary checked tool path, never an Operator model."""
    from app.tools import AUDIENCE_OPERATOR, ToolContext, get_tool_executor, get_tool_registry
    from app.memory.permissions import OPERATOR_CAPABILITIES

    owner = policy.owner
    registry = get_tool_registry()
    available = frozenset(tool.name for tool in registry.for_audience(AUDIENCE_OPERATOR)
                          if registry.permits(tool, OPERATOR_CAPABILITIES))
    resume_state = run.resume_input or {}
    pending = resume_state.get("pending_action") or {}
    response = resume_state.get("response") or {}
    approved = frozenset({pending["capability_id"]}) if (
        pending.get("purpose") == "capability_invoke" and response.get("approved") is True
        and pending.get("capability_id")
    ) else frozenset()
    context = ToolContext(
        workspace_id=run.workspace_id, agent_name=PAI_OPERATOR_AGENT_NAME, api=api,
        allowed_tools=policy.allowed_tools(available), audience=AUDIENCE_OPERATOR,
        granted_capabilities=OPERATOR_CAPABILITIES, approved_capabilities=approved,
        required_capability_id=owner.id,
    )
    plan = list(run.plan or []) or [{"id": "objective", "title": run.objective, "status": "working"}]
    set_status("executing", plan=plan, current_step=plan[0]["title"], pending_action=None)
    args = {"capability_id": owner.id, "input": capability_input}
    db.rollback()
    outcome = await get_tool_executor().execute("capability.invoke", args, context)
    calls = list(run.tool_calls or []) + [{"tool": "capability.invoke", "arguments": args,
                                          "ok": bool(outcome.get("ok"))}]
    observations = list((run.result or {}).get("observations") or []) + [{
        "tool": "capability.invoke", "ok": bool(outcome.get("ok")), "url": None,
        "observed_at": _now().isoformat(), "data": _json.dumps(outcome, default=str)[:6000],
    }]
    error = outcome.get("error") or {}
    payload = (outcome.get("data") or {}).get("result") if outcome.get("ok") else None
    payload = payload if isinstance(payload, dict) else {}
    pending_action = error.get("pending_action") if error.get("code") == "approval_required" else payload.get("pending_action")
    summary = payload.get("summary") or payload.get("final_message") or error.get("message")
    if isinstance(pending_action, dict) and pending_action:
        status = STATUS_NEEDS_USER_ACTION
        if pending_action.get("type") == "need_from_student":
            items = [item for item in pending_action.get("items") or [] if isinstance(item, dict) and item.get("field")]
            pending_action = {"kind": "fact", "type": "need_from_student", "items": items,
                              "required": True, "title": "One detail will help me finish the research",
                              "prompt": str(items[0].get("reason") if items else "Please share the missing detail")}
            summary = summary or "I need one detail to finish comparing these routes."
        summary = summary or "Your input is needed to continue."
    elif not outcome.get("ok") or payload.get("status") == STATUS_FAILED:
        status = STATUS_FAILED
        pending_action = None
        summary = summary or f"{owner.name} could not complete the owned task; generic fallback is forbidden."
    else:
        status = STATUS_COMPLETED
        pending_action = None
        summary = summary or f"{owner.name} completed the requested work."
    plan = _mark_plan_progress(plan, None, status == STATUS_COMPLETED)
    result = {"summary": summary, "final_message": payload.get("final_message"), "plan": plan,
              "tool_calls": calls, "observations": observations[-12:], "artifact_id": None,
              "capability_result": payload or None}
    verification = {"status": status, "summary": summary, "missing": payload.get("missing") or [],
                    "approval_required_for": pending_action.get("title") if pending_action and pending_action.get("kind") == "approval" else None}
    set_status(status, current_step=summary, pending_action=pending_action,
               completed_at=None if status == STATUS_NEEDS_USER_ACTION else _now(),
               error=str(error.get("message") or payload.get("error") or "owned capability failed")[:500] if status == STATUS_FAILED else None,
               plan=plan, completed_steps=[item["title"] for item in plan if item["status"] == "completed"],
               tool_calls=calls, result=result, verification=verification,
               result_type="research" if pending_action and pending_action.get("type") == "need_from_student" else "text",
               result_artifact_id=None, missing=verification["missing"],
               approval_required_for=verification["approval_required_for"])
    await _post_result(db, run.workspace_id, run.channel_target, run.id, status,
                       _terminal_message(status, summary, verification["missing"], verification))


async def run_operator_job(job, db):
    """Durable adapter: existing run policy chooses workflow or agent execution."""
    from app.models import Workspace
    run = db.get(ExecutionRun, (job.payload or {}).get("run_id"))
    if run is None or run.workspace_id != job.workspace_id:
        raise LookupError("Execution run is unavailable in this workspace")
    if run.status in _TERMINAL or run.status == STATUS_NEEDS_USER_ACTION:
        return {"run_id": run.id, "status": run.status}
    if getattr(job, "idempotency_key", None) not in (None, _run_job_key(run)):
        return {"run_id": run.id, "status": "superseded"}
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None:
        raise LookupError("Workspace is unavailable")
    args = (run.id, run.workspace_id, pai.WorkspaceApi(workspace.id, workspace.password_hash),
            run.objective, run.constraints or {}, run.context_refs or [], run.channel_target)
    resume_payload = (run.resume_input or {}).get("response")
    db.rollback()
    await _execute(*args, resume_payload=resume_payload)
    db.expire_all()
    run = db.get(ExecutionRun, job.payload["run_id"])
    return {"run_id": run.id, "status": run.status}


def _run_job_key(run):
    count = int((run.resume_input or {}).get("resume_count", 0))
    return f"operator:{run.id}:resume:{count}"


def _enqueue_run(db, run):
    from app.runtime.task_runtime import enqueue
    return enqueue(db, "operator.run", {"run_id": run.id},
                   workspace_id=run.workspace_id, idempotency_key=_run_job_key(run))
