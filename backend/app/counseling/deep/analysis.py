"""Durable, ordered background updates to the private Counselor Notebook."""

import asyncio
import hashlib
import json
import logging
import weakref
from contextlib import asynccontextmanager

from sqlalchemy import select, text

from app.config import config
from app.counseling.deep.context import _json, _profile
from app.counseling.deep.coverage import enforce_mirror_readiness
from app.counseling.deep.notebook import NotebookService, NotebookVersionConflict
from app.counseling.deep.notebook_sanitize import sanitize_notebook
from app.counseling.deep.notebook_schema import CounselorNotebookData
from app.counseling.deep.prompts import load_prompt
from app.counseling.deep.usage import usage_callback
from app.counseling.stages import advance_discovery_stage
from app.inference.client import chat_completion
from app.jobs.service import BackgroundJobService, job_handlers
from app.journey import JourneyService
from app.memory.episodic import EpisodicMemoryService
from app.models import BackgroundJob, CounselorNotebookHistory, EventRecord, User, Workspace

logger = logging.getLogger(__name__)
JOB_ANALYZE = "counselor.analyze"
_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


class AnalysisOrderPending(Exception):
    """An older turn must finish its analysis before this one can apply."""


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
        job = BackgroundJobService(db).enqueue(
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
        BackgroundJob.status.in_(("pending", "running")),
    )).scalars().all()
    for other in rows:
        item = other.payload or {}
        earlier = (item.get("source_timestamp"), item.get("user_event_id"))
        if isinstance(earlier[0], int) and isinstance(earlier[1], str) and earlier < current_order:
            return True
    return False


def _input(db, workspace_id: str, student: EventRecord, assistant: EventRecord,
           notebook) -> str:
    rows = db.execute(select(EventRecord).where(
        EventRecord.network_id == workspace_id,
        EventRecord.type == "workspace.message.posted",
        EventRecord.source.in_((student.source, "openagents:pai")),
        EventRecord.timestamp <= assistant.timestamp,
    ).order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())
                      .limit(config.PAI_ANALYST_HISTORY_SIZE * 3)).scalars().all()
    transcript = []
    for row in rows:
        content = (row.payload or {}).get("content")
        if isinstance(content, str) and content.strip() and (row.payload or {}).get("message_type", "chat") == "chat":
            transcript.append({"role": "student" if row.source == student.source else "counselor",
                               "content": content[:1500], "event_id": row.id})
        if len(transcript) == config.PAI_ANALYST_HISTORY_SIZE:
            break
    transcript.reverse()
    episode = EpisodicMemoryService(db).recent(workspace_id, limit=1)
    return ("<notebook_schema>" + _json(CounselorNotebookData.model_json_schema())
            + "</notebook_schema>\n"
            + "<notebook>" + _json(notebook.model_dump(mode="json")) + "</notebook>\n"
            + "<profile>" + _json(_profile(db, workspace_id)) + "</profile>\n"
            + "<older_episode_summary>" + _json(episode[0].summary if episode else "")
            + "</older_episode_summary>\n"
            + "<transcript>" + _json(transcript) + "</transcript>\n"
            + "<latest_student_event_id>" + student.id + "</latest_student_event_id>")


async def _candidate(db, workspace_id: str, student: EventRecord,
                     assistant: EventRecord, previous):
    student_id = student.id
    analyst_input = _input(db, workspace_id, student, assistant, previous.notebook)
    # Do not hold read transactions or database connections across model calls.
    db.rollback()
    raw = await chat_completion(
        api_key=config.PAI_API_KEY, model=config.PAI_ANALYST_MODEL,
        messages=[{"role": "user", "content": analyst_input}],
        system_prompt=load_prompt("analyst"),
        response_format={"type": "json_object"},
        reasoning_effort=config.PAI_ANALYST_REASONING_EFFORT,
        base_url=config.PAI_BASE_URL,
        usage_callback=usage_callback("analyst", config.PAI_ANALYST_MODEL, student_id),
    )
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("analyst returned invalid JSON") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("notebook"), dict):
        raise ValueError("analyst returned no notebook")
    candidate, issues = sanitize_notebook(parsed["notebook"])
    return enforce_mirror_readiness(candidate), issues, []


def _advance_stage(db, workspace_id: str, notebook) -> None:
    journeys = JourneyService(db)
    journey = journeys.ensure_counselor(workspace_id, actor="system:counselor_analyst")
    workspace = db.get(Workspace, workspace_id)
    owner = db.get(User, workspace.owner_user_id) if workspace and workspace.owner_user_id else None
    advance_discovery_stage(
        journeys, workspace_id, journey,
        identity_ready=bool(owner and owner.onboarded_at),
        foundation_ready=bool(notebook.coverage.person and notebook.coverage.education),
        goal_records=[], actor="system:counselor_analyst", allow_auto_research=False,
    )
    db.commit()


async def analyze_job(job, db) -> dict:
    """Retryable worker handler. A bad analysis never runs in the reply path."""
    if not job.workspace_id:
        raise ValueError("analysis job requires a workspace")
    payload = job.payload or {}
    user_event_id = payload.get("user_event_id")
    assistant_event_id = payload.get("assistant_event_id")
    async with _workspace_lock(db, job.workspace_id):
        if _prior_job_pending(db, job):
            raise AnalysisOrderPending("earlier analysis pending")
        duplicate = db.execute(select(CounselorNotebookHistory.id).where(
            CounselorNotebookHistory.workspace_id == job.workspace_id,
            CounselorNotebookHistory.source_event_id == user_event_id,
        ).limit(1)).scalar_one_or_none()
        if duplicate:
            _advance_stage(db, job.workspace_id,
                           NotebookService(db).get(job.workspace_id).notebook)
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
        service = NotebookService(db)
        for attempt in range(2):
            previous = service.get(job.workspace_id)
            candidate, issues, removals = await _candidate(
                db, job.workspace_id, student, assistant, previous)
            try:
                snapshot, storage_issues = service.apply(
                    job.workspace_id, candidate, user_event_id,
                    expected_version=previous.version)
                _advance_stage(db, job.workspace_id, snapshot.notebook)
                return {"status": "applied", "version": snapshot.version,
                        "sanitized": len(issues) + len(storage_issues),
                        "sensitive_removed": len(removals), "model_calls": attempt + 1}
            except NotebookVersionConflict:
                db.rollback()
                if attempt:
                    raise
        raise AssertionError("unreachable analysis retry")


job_handlers.register(JOB_ANALYZE, analyze_job)
