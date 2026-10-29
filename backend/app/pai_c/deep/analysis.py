"""Durable, ordered background updates to the private Counselor Notebook."""

import asyncio
import hashlib
import json
import re
import logging
import weakref
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.config import config
from app.pai_c.deep.context import _json, _profile
from app.pai_c.deep.notebook import NotebookVersionConflict
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.memory import MemoryService
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.planner.view import build_planner_view
from app.pai_c.planner.patch import apply_patch, PatchRejected, OPERATION
from app.pai_c.planner.plan import validate_plan, TurnPlan
from app.pai_c.playbooks.registry import available_playbooks
from app.pai_c.stages import advance_discovery_stage
from app.inference.gateway import complete as chat_completion, resolve_model
from app.runtime.task_runtime import enqueue
from app.jobs.service import JobDeferred
from app.journey import JourneyService
from app.models import BackgroundJob, CounselorNotebookHistory, EventRecord, User, Workspace, CounselorTurnDecision, PaiTurnPlan

logger = logging.getLogger(__name__)
JOB_ANALYZE = "counselor.analyze"
_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


class AnalysisOrderPending(JobDeferred):
    """An older turn must finish its analysis before this one can apply."""


class AnalysisPredecessorFailed(RuntimeError):
    """A prior turn needs replay before later evidence can be interpreted."""


class AnalysisPatchRejected(RuntimeError):
    """Both model attempts failed validation; preserve this job for replay.

    Not retried by the worker: the same turn gives the same rejection, so a
    retry only repeats two model calls per attempt (audit #9, retry storm)."""
    retryable = False


_KEY = re.compile(r"^[a-z_]{1,40}$")


def _patch_shape(parsed) -> str:
    """What a rejected patch looked like, never what it said: its top-level
    keys and each operation's keys (schema words only, no student text)."""
    if not isinstance(parsed, dict):
        return "keys=- ops=-"
    keys = ",".join(sorted(k for k in parsed if isinstance(k, str) and _KEY.match(k))) or "-"
    operations = parsed.get("patch") if isinstance(parsed.get("patch"), list) else []
    ops = ";".join(",".join(sorted(k for k in op if isinstance(k, str) and _KEY.match(k)))
                   if isinstance(op, dict) else "?" for op in operations[:20]) or "-"
    return f"keys={keys} ops={ops}"


def enqueue_turn_analysis(db, workspace_id: str, user_event_id: str,
                          assistant_event_id: str) -> str | None:
    """Queue after a successful human deep reply; never fail the reply."""
    if not user_event_id or not assistant_event_id:
        return None
    try:
        student = db.execute(select(EventRecord).where(
            EventRecord.id == user_event_id,
            EventRecord.network_id == workspace_id,
            EventRecord.source.like("human:%"),
        )).scalar_one_or_none()
        if student is None:
            return None
        job = enqueue(db,
            job_type=JOB_ANALYZE, workspace_id=workspace_id,
            payload={"user_event_id": user_event_id,
                     "assistant_event_id": assistant_event_id,
                     "source_timestamp": student.timestamp},
            idempotency_key=f"counselor:analyze:{workspace_id}:{user_event_id}",
        )
        db.commit()
        return job.id
    except Exception:
        db.rollback()
        logger.exception("counselor: failed to queue analysis turn_id=%s", user_event_id)
        return None


@asynccontextmanager
async def _workspace_lock(db, workspace_id: str):
    local = _locks.get(workspace_id)
    if local is None:
        local = asyncio.Lock()
        _locks[workspace_id] = local
    if local.locked():
        raise AnalysisOrderPending("workspace analysis already running")
    await local.acquire()
    connection = None
    acquired = False
    try:
        if db.bind.dialect.name == "postgresql":
            key = int.from_bytes(hashlib.blake2b(
                workspace_id.encode("utf-8"), digest_size=8).digest(), "big", signed=True)
            connection = db.bind.connect()
            acquired = bool(connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar_one())
            if not acquired:
                raise AnalysisOrderPending("workspace analysis already running")
        yield
    finally:
        if connection is not None:
            try:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            finally:
                connection.close()
        local.release()


def _prior_job_pending(db, job) -> bool:
    payload = job.payload or {}
    current_order = (payload.get("source_timestamp"), payload.get("user_event_id"))
    if not isinstance(current_order[0], int) or not isinstance(current_order[1], str):
        raise ValueError("analysis job has no source event order")
    rows = db.execute(select(BackgroundJob).where(
        BackgroundJob.workspace_id == job.workspace_id,
        BackgroundJob.job_type == JOB_ANALYZE,
        BackgroundJob.id != job.id,
        BackgroundJob.status.in_(("pending", "running", "failed")),
    )).scalars().all()
    for other in rows:
        item = other.payload or {}
        earlier = (item.get("source_timestamp"), item.get("user_event_id"))
        if isinstance(earlier[0], int) and isinstance(earlier[1], str) and earlier < current_order:
            if other.status == "failed":
                raise AnalysisPredecessorFailed("earlier analysis failed; replay required")
            return True
    return False


def replay_failed_analyses(db, workspace_id: str) -> int:
    """Operator recovery after fixing a permanent failure; retain original order.

    Reuse the existing rows and idempotency keys. Successful turns are never
    replayed, and live analyses cannot be reset beneath another worker.
    """
    workspace = db.scalar(select(Workspace).where(
        Workspace.id == workspace_id, Workspace.status == "active").with_for_update())
    if workspace is None:
        raise ValueError("active workspace required")
    jobs = db.scalars(select(BackgroundJob).where(
        BackgroundJob.workspace_id == workspace_id,
        BackgroundJob.job_type == JOB_ANALYZE,
        BackgroundJob.status.in_(("failed", "running")),
    ).with_for_update()).all()
    if any(job.status == "running" for job in jobs):
        raise RuntimeError("analysis is currently running")
    failed = [job for job in jobs if job.status == "failed"]
    for job in failed:
        job.status = "pending"
        job.attempts = 0
        job.available_at = datetime.now(timezone.utc)
        job.completed_at = None
        job.last_error = None
        job.locked_at = None
        job.locked_by = None
    db.flush()
    logger.info("counselor_analysis_replayed workspace_id=%s count=%d", workspace_id, len(failed))
    return len(failed)


def _input(db, workspace_id: str, student: EventRecord, assistant: EventRecord,
           notebook, *, view=None) -> str:
    rows = db.execute(select(EventRecord).where(
        EventRecord.network_id == workspace_id,
        EventRecord.type == "workspace.message.posted",
        EventRecord.source.in_((student.source, "openagents:pai")),
        EventRecord.timestamp <= assistant.timestamp,
    ).order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())
                      .limit(config.PAI_PLANNER_HISTORY_TURNS * 3)).scalars().all()
    transcript = []
    for row in rows:
        content = (row.payload or {}).get("content")
        if isinstance(content, str) and content.strip() and (row.payload or {}).get("message_type", "chat") == "chat":
            transcript.append({"role": "student" if row.source == student.source else "counselor",
                               "content": content[:1500], "event_id": row.id})
        if len(transcript) == config.PAI_PLANNER_HISTORY_TURNS:
            break
    transcript.reverse()
    # The counselor question the latest student message answers names its topic.
    asked = [row for row in transcript[:next((i for i, row in enumerate(transcript) if row["event_id"] == student.id),
                                             len(transcript))] if row["role"] == "counselor"]
    view = view if view is not None else build_planner_view(notebook)
    episode = MemoryService(db).session_summaries(workspace_id, limit=1)
    from app.pai_c.possibilities import PossibilityService
    dismissed = [row.title for row in PossibilityService(db).list(workspace_id) if row.status == "dismissed"]
    from app.pai_c.understanding.data import DATA_DIR
    capabilities = (DATA_DIR / "capability_mapping.json").read_text(encoding="utf-8")
    return ("<notebook_schema>" + _json({"notebook": CounselorNotebookData.analyst_schema(), "patch_operation": OPERATION.json_schema(), "plan": TurnPlan.model_json_schema()})
            + "</notebook_schema>\n"
            + "<understanding_spine>" + capabilities + "</understanding_spine>\n"
            + view.text + "\n<dismissed_possibilities>" + _json(dismissed) + "</dismissed_possibilities>\n"
            + "<profile>" + _json(_profile(db, workspace_id, student_text=(student.payload or {}).get("content") or "",
                                   trigger_text=asked[-1]["content"] if asked else "")) + "</profile>\n"
            + "<older_episode_summary>" + _json(episode[0].summary if episode else "")
            + "</older_episode_summary>\n"
            + "<transcript>" + _json(transcript) + "</transcript>\n"
            + "<latest_student_event_id>" + student.id + "</latest_student_event_id>")


async def _candidate(db, workspace_id: str, student: EventRecord,
                     assistant: EventRecord, previous):
    student_id = student.id
    query = (student.payload or {}).get("content", "")
    view = build_planner_view(previous.notebook)
    analyst_input = _input(db, workspace_id, student, assistant, previous.notebook, view=view)
    profile = MemoryService(db).profile(workspace_id)
    evidence_refs = {row["id"] for row in [*profile.facts.values(),
        *(row for rows in profile.records.values() for row in rows)]
        if row.get("id") and row.get("evidence_level") in {"shown", "confirmed"}}
    decision = db.scalar(select(CounselorTurnDecision).where(
        CounselorTurnDecision.workspace_id == workspace_id,
        CounselorTurnDecision.source_timestamp <= assistant.timestamp,
    ).order_by(CounselorTurnDecision.source_timestamp.desc(), CounselorTurnDecision.id.desc()).limit(1))
    wellbeing = decision is not None and decision.move == "wellbeing"
    db.rollback()
    recalled = await MemoryService(db).recall(workspace_id, query)
    analyst_input += "\n<semantic_recall>" + _json(recalled) + "</semantic_recall>"
    from app.workspace_language import workspace_language_block
    analyst_input += "\n" + workspace_language_block()
    from app.pai_c.deep.context import estimated_tokens
    logger.info("planner_input turn_id=%s history_limit=%d map_tokens=%d total_tokens=%d",
                student_id, config.PAI_PLANNER_HISTORY_TURNS, view.tokens, estimated_tokens(analyst_input))
    feedback = ""
    for attempt in range(2):
        db.rollback()
        raw = await chat_completion(role="analyst",
            api_key=config.PAI_API_KEY, model=resolve_model("analyst"),
            messages=[{"role": "user", "content": analyst_input}],
            system_prompt=load_prompt("planner") + "\n\n" + available_playbooks() + feedback,
            response_format={"type": "json_object"},
            reasoning_effort=config.PAI_ANALYST_REASONING_EFFORT,
            base_url=config.PAI_BASE_URL, turn_id=student_id)
        parsed = None
        try:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                raise PatchRejected(-1, "InvalidJSON") from None
            if not isinstance(parsed, dict):
                raise PatchRejected(-1, "InvalidOutputShape")
            candidate = apply_patch(previous.notebook, parsed.get("patch"), view.ids, query, evidence_refs=evidence_refs)
        except PatchRejected as exc:
            logger.warning("planner_patch_rejected turn_id=%s attempt=%d op_index=%d error_type=%s %s",
                           student_id, attempt + 1, exc.index, exc.error_type,
                           _patch_shape(parsed))
            if attempt:
                raise AnalysisPatchRejected(
                    f"planner patch rejected after correction: error_type={exc.error_type}") from None
            feedback = "\nThe previous patch was rejected: " + str(exc) + ". Return a corrected complete patch and plan."
            continue
        try:
            plan = validate_plan(parsed.get("plan"), wellbeing=wellbeing, view=view)
        except ValueError as exc:
            logger.warning("planner_plan_rejected error_type=%s", type(exc).__name__)
            plan = None
        return candidate, plan, attempt + 1
    raise AssertionError("unreachable patch retry")


def _advance_stage(db, workspace_id: str, notebook) -> None:
    journeys = JourneyService(db)
    journey = journeys.ensure_counselor(workspace_id, actor="system:counselor_analyst")
    workspace = db.get(Workspace, workspace_id)
    owner = db.get(User, workspace.owner_user_id) if workspace and workspace.owner_user_id else None
    advance_discovery_stage(
        journeys, workspace_id, journey,
        identity_ready=bool(owner and owner.onboarded_at),
        foundation_ready=MemoryService(db).foundation_ready(notebook),
        goal_records=[], actor="system:counselor_analyst",
    )
    # A notebook write can complete the Mirror (coverage reads notebook rows
    # too), and a card made ready before DIRECTION was reached has no later
    # Vault write to move it: sync here as the reconciler hook does.
    from app.pai_c.journey_sync import sync_counselor_stage
    try:
        with db.begin_nested():
            sync_counselor_stage(db, workspace_id, reason="analyst", actor="system:counselor_analyst")
    except Exception as exc:  # noqa: BLE001  the notebook write outranks the stage move
        logger.error("analyst_stage_sync_failed workspace_id=%s error_type=%s",
                     workspace_id, type(exc).__name__)
    db.commit()


async def analyze_job(job, db) -> dict:
    """Retryable worker handler. A bad analysis never runs in the reply path."""
    if not job.workspace_id:
        raise ValueError("analysis job requires a workspace")
    payload = job.payload or {}
    user_event_id = payload.get("user_event_id")
    assistant_event_id = payload.get("assistant_event_id")
    # Check order before taking the lock: a later turn must never hold the
    # workspace lock while an earlier turn is waiting for it.
    if _prior_job_pending(db, job):
        raise AnalysisOrderPending("earlier analysis pending")
    async with _workspace_lock(db, job.workspace_id):
        if _prior_job_pending(db, job):
            raise AnalysisOrderPending("earlier analysis pending")
        duplicate = db.execute(select(CounselorNotebookHistory.id).where(
            CounselorNotebookHistory.workspace_id == job.workspace_id,
            CounselorNotebookHistory.source_event_id == user_event_id,
        ).limit(1)).scalar_one_or_none()
        if duplicate:
            _advance_stage(db, job.workspace_id,
                           MemoryService(db).truth_map(job.workspace_id).notebook)
            return {"status": "duplicate"}
        student = db.execute(select(EventRecord).where(
            EventRecord.id == user_event_id,
            EventRecord.network_id == job.workspace_id,
            EventRecord.source.like("human:%"),
        )).scalar_one_or_none()
        assistant = db.execute(select(EventRecord).where(
            EventRecord.id == assistant_event_id,
            EventRecord.network_id == job.workspace_id,
            EventRecord.source == "openagents:pai",
        )).scalar_one_or_none()
        if student is None or assistant is None:
            raise ValueError("analysis source turn is unavailable")
        service = MemoryService(db)
        model_calls = 0
        for attempt in range(2):
            previous = service.truth_map(job.workspace_id)
            candidate, plan, calls = await _candidate(db, job.workspace_id, student, assistant, previous)
            model_calls += calls
            if candidate is None:
                return {"status": "patch_rejected", "model_calls": model_calls}
            try:
                if plan is not None:
                    db.add(PaiTurnPlan(workspace_id=job.workspace_id, source_event_id=user_event_id,
                        notebook_version=previous.version + 1, plan=plan.model_dump(mode="json")))
                snapshot, storage_issues = service.apply_truth_map(
                    job.workspace_id, candidate, user_event_id,
                    expected_version=previous.version)
                _advance_stage(db, job.workspace_id, snapshot.notebook)
                if plan is not None and plan.possibility is not None:
                    # The planner never writes a path: the analyzer is the one
                    # source of paths, so a proposed direction asks it to look.
                    from app.pai_c.paths.analyzer import enqueue_after_planner
                    enqueue_after_planner(db, job.workspace_id, source_event_id=user_event_id)
                    db.commit()
                return {"status": "applied", "version": snapshot.version,
                        "sanitized": len(storage_issues), "sensitive_removed": 0,
                        "model_calls": model_calls}
            except NotebookVersionConflict:
                db.rollback()
                if attempt:
                    raise
        raise AssertionError("unreachable analysis retry")


