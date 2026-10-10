"""Durable, version-bound Mirror generation and confirmed research handoff."""

import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import config
from app.pai_c.deep.analysis import _workspace_lock
from app.pai_c.deep.context import build_context
from app.pai_c.deep.mirror_schema import CounselorMirror
from app.pai_c.deep.notebook import NotebookService
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.deep.sensitive import check_notebook_before_mirror
from app.pai_c.deep.turn_input import CounselorTurnInput, shared_history
from app.pai_c.posting import _post_response
from app.inference.gateway import complete as chat_completion, resolve_model
from app.runtime.task_runtime import enqueue
from app.journey import JourneyService
from app.models import BackgroundJob, EventRecord, Workspace

logger = logging.getLogger(__name__)
JOB_MIRROR = "counselor.mirror"
JOB_RESEARCH = "counselor.mirror_research"


def enqueue_mirror(db, turn: CounselorTurnInput) -> str | None:
    workspace = db.scalar(select(Workspace).where(
        Workspace.id == turn.workspace_id, Workspace.status == "active").with_for_update())
    if workspace is None:
        return None
    snapshot = NotebookService(db).get(turn.workspace_id)
    journey = JourneyService(db).ensure_counselor(turn.workspace_id)
    if not snapshot.notebook.mirror_ready or journey.current_stage != "DIRECTION":
        return None
    pending = db.scalar(select(BackgroundJob).where(
        BackgroundJob.workspace_id == turn.workspace_id, BackgroundJob.job_type == JOB_MIRROR,
        BackgroundJob.status.in_(("pending", "running"))))
    if pending:
        return pending.id
    prior = db.scalars(select(BackgroundJob).where(
        BackgroundJob.workspace_id == turn.workspace_id, BackgroundJob.job_type == JOB_MIRROR,
    )).all()
    attempts = [item for item in prior if (item.payload or {}).get("notebook_version") == snapshot.version]
    if attempts:
        draft = journey.counselor_summary_draft or {}
        if (len(attempts) >= 2 or draft.get("notebook_version") != snapshot.version
                or draft.get("status") not in {"failed", "needs_discovery"}):
            return attempts[-1].id
    attempt = len(attempts)
    try:
        job = enqueue(db,
            JOB_MIRROR, {"notebook_version": snapshot.version, "journey_id": journey.id,
                         "source_event_id": turn.source_event_id, "channel": turn.channel,
                         "mirror_attempt": attempt},
            workspace_id=turn.workspace_id,
            idempotency_key=f"counselor:mirror:{turn.workspace_id}:{snapshot.version}:{attempt}")
    except IntegrityError:
        # A different version won the partial-unique pending-job race.
        job = db.scalar(select(BackgroundJob).where(
            BackgroundJob.workspace_id == turn.workspace_id, BackgroundJob.job_type == JOB_MIRROR,
            BackgroundJob.status.in_(("pending", "running"))))
    return job.id if job else None


async def _publish(db, job, draft) -> dict:
    # Recovery after a post committed but the worker died before acknowledging
    # its job must reuse the existing message, not post a second card.
    message = db.scalar(select(EventRecord.id).where(
        EventRecord.network_id == job.workspace_id,
        EventRecord.metadata_["mirror_job_id"].as_string() == job.id,
        EventRecord.source == "openagents:pai"))
    if message:
        return {"status": "posted", "message_id": message}
    mirror = CounselorMirror.model_validate(draft["mirror"])
    source = db.scalar(select(EventRecord).where(
        EventRecord.id == job.payload.get("source_event_id"),
        EventRecord.network_id == job.workspace_id))
    from app.pai_c.runtime import _voice_reply_metadata

    voice_metadata = _voice_reply_metadata({"metadata": source.metadata_}) if source else None
    message = await _post_response(
        db, job.workspace_id, draft["channel"], "pai", mirror.spoken_reply(), 0,
        message_type="counselor_mirror",
        extra_payload={"mirror": mirror.model_dump(mode="json"), "version": draft["version"]},
        metadata={**(voice_metadata or {}), "mirror_job_id": job.id, "mirror_version": draft["version"]})
    if not message:
        raise RuntimeError("Mirror post was rejected")
    return {"status": "posted", "message_id": message}


async def mirror_job(job, db) -> dict:
    if not job.workspace_id:
        raise ValueError("Mirror job requires a workspace")
    payload = dict(job.payload or {})
    job_id = job.id
    async with _workspace_lock(db, job.workspace_id):
        journeys = JourneyService(db)
        journey = journeys.get(job.workspace_id, payload.get("journey_id"))
        if journey is None or journey.status != "active":
            return {"status": "inactive"}
        draft = journey.counselor_summary_draft or {}
        if draft.get("type") == "mirror" and draft.get("notebook_version") == payload.get("notebook_version"):
            if draft.get("status") in {"awaiting_confirmation", "confirmed"}:
                return await _publish(db, job, draft)
            if draft.get("status") not in {"failed", "needs_discovery"}:
                return {"status": "superseded"}
        snapshot = NotebookService(db).get(job.workspace_id)
        if (snapshot.version != payload.get("notebook_version")
                or not snapshot.notebook.mirror_ready or journey.current_stage != "DIRECTION"):
            return {"status": "not_ready_or_stale"}
        checked, removals = await check_notebook_before_mirror(job.workspace_id, db=db)
        if removals or not checked.notebook.mirror_ready:
            _record_failure(db, job, "needs_discovery", checked.version)
            return {"status": "needs_discovery"}
        student = db.scalar(select(EventRecord).where(
            EventRecord.id == payload.get("source_event_id"), EventRecord.network_id == job.workspace_id,
            EventRecord.source.like("human:%")))
        if student is None:
            raise ValueError("Mirror source student event is unavailable")
        turn = CounselorTurnInput(payload["channel"], job.workspace_id,
            str((student.payload or {}).get("content") or ""), (), None,
            student.id, student.timestamp, student.source)
        context = await build_context(db, job.workspace_id, turn)
        history = [{"role": item["role"], "content": item["content"]} for item in
                   shared_history(db, turn, student.source.removeprefix("human:"),
                                  limit=config.PAI_COUNSELOR_HISTORY_SIZE)]
        messages = [*history, {"role": "user", "content": turn.student_text}]
        prompt = load_prompt("mirror") + "\n\n" + context.text
        db.rollback()
        for attempt in range(2):
            db.rollback()
            raw = await chat_completion(role="mirror",
                api_key=config.PAI_API_KEY, model=resolve_model("mirror"),
                system_prompt=prompt, messages=messages, response_format={"type": "json_object"},
                reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT, base_url=config.PAI_BASE_URL,
                turn_id=turn.source_event_id)
            try:
                mirror = CounselorMirror.model_validate(json.loads(raw))
                break
            except (TypeError, ValueError):
                logger.warning("counselor_mirror_invalid job_id=%s attempt=%d", job_id, attempt + 1)
                if attempt:
                    _record_failure(db, job, "failed", checked.version)
                    return {"status": "invalid", "model_calls": 2}
                # Regenerate against the same checked context; no sensitive
                # recheck or broken draft is sent to the student.
                prompt += "\nReturn a complete JSON object conforming to every output rule."
        # Serialize publication with Notebook writes and workspace deletion.
        workspace = db.scalar(select(Workspace).where(
            Workspace.id == job.workspace_id, Workspace.status == "active").with_for_update())
        current = NotebookService(db).get(job.workspace_id) if workspace else None
        journey = journeys.get(job.workspace_id, payload["journey_id"])
        if (current is None or current.version != checked.version or journey is None
                or journey.current_stage != "DIRECTION"):
            db.rollback()
            return {"status": "superseded"}
        journey = journeys.set_counselor_summary(
            job.workspace_id, journey.id, mirror.model_dump(mode="json"), mirror.spoken_reply(),
            turn.source_event_id, notebook_version=checked.version, channel=turn.channel)
        # The draft is durable before posting so a worker retry can publish it
        # without making another model/sensitivity call.
        db.commit()
        return await _publish(db, job, journey.counselor_summary_draft)


def _record_failure(db, job, status, notebook_version):
    from app.models import StudentJourney

    row = db.scalar(select(StudentJourney).where(
        StudentJourney.id == job.payload["journey_id"], StudentJourney.workspace_id == job.workspace_id,
        StudentJourney.status == "active").with_for_update())
    if row is not None and row.current_stage == "DIRECTION":
        row.counselor_summary_draft = {"type": "mirror", "status": status,
            "notebook_version": notebook_version, "mirror_attempt": job.payload.get("mirror_attempt", 0),
            "version": (row.counselor_summary_draft or {}).get("version", 0)}
        db.commit()


def enqueue_confirmed_research(db, workspace_id: str, journey) -> str:
    version = journey.counselor_summary_draft["version"]
    job = enqueue(db,
        JOB_RESEARCH, {"journey_id": journey.id, "version": version}, workspace_id=workspace_id,
        idempotency_key=f"counselor:mirror-research:{workspace_id}:{journey.id}:{version}")
    return job.id


async def confirmed_research_job(job, db) -> dict:
    from app.research.gateway import request_research
    from app.memory.student_snapshot import StudentSnapshotService
    from app.memory.permissions import capabilities_for_agent
    from app.services.pai import PAI_ALLOWED_TOOLS, WorkspaceApi
    from app.tools import AUDIENCE_COUNSELOR, ToolContext

    async with _workspace_lock(db, job.workspace_id):
        journey = JourneyService(db).get(job.workspace_id, job.payload["journey_id"])
        draft = journey.counselor_summary_draft or {} if journey else {}
        if (not journey or journey.status != "active" or draft.get("status") != "confirmed"
                or draft.get("version") != job.payload["version"]):
            return {"status": "superseded"}
        request = journey.research_request or {}
        if request.get("handoff_status") == "done":
            return {"status": "duplicate"}
        snapshot = StudentSnapshotService(db).build(job.workspace_id)
        workspace = db.get(Workspace, job.workspace_id)
        ctx = ToolContext(workspace_id=job.workspace_id, agent_name="pai",
            api=WorkspaceApi(job.workspace_id, workspace.password_hash),
            conversation=draft["channel"].removeprefix("channel/"),
            allowed_tools=frozenset({"operator.delegate"}) & frozenset(PAI_ALLOWED_TOOLS),
            audience=AUDIENCE_COUNSELOR, granted_capabilities=capabilities_for_agent("pai"))
        outcome = await request_research("roadmap_light", job.workspace_id, trigger="mirror_confirmed", db=db, journey=journey,
            snapshot=snapshot, tool_context=ctx)
        if outcome is not None and not outcome.get("ok"):
            raise RuntimeError("Confirmed research handoff failed")
        from app.models import StudentJourney
        row = db.get(StudentJourney, journey.id)
        row.research_request = {**request, "handoff_status": "done", "delegated": bool(outcome)}
        db.commit()
        return {"status": "done", "delegated": bool(outcome)}


