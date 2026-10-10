"""Durable session lifecycle; the shared worker only knows job names."""
import time

from app.pai_c.memory import MemoryService
from app.runtime.task_runtime import enqueue

JOB_SWEEP = "session.sweep"
JOB_SUMMARIZE = "session.summarize"


async def sweep_job(job, db):
    sessions = MemoryService(db).ended_sessions(int(time.time() * 1000))
    for session in sessions:
        enqueue(db, job_type=JOB_SUMMARIZE, workspace_id=session["workspace_id"],
                payload=session,
                idempotency_key=f"session-summary:{session['workspace_id']}:{session['last_event_id']}")
    return {"sessions_enqueued": len(sessions)}


async def summarize_job(job, db):
    import json
    from app.inference.gateway import complete
    from app.pai_c.deep.prompts import load_prompt
    from app.pai_c.deep.polish import contains_blocked_script
    from app.pai_c.deep.analysis import AnalysisOrderPending
    from app.models import BackgroundJob
    from app.config import config
    from sqlalchemy import select
    if not job.workspace_id or (job.payload or {}).get("workspace_id") != job.workspace_id:
        raise ValueError("Session summary workspace mismatch")
    service = MemoryService(db)
    payload = job.payload
    if any(payload["last_event_id"] in (row.source_event_ids or [])
           for row in service.session_summaries(job.workspace_id, limit=None)):
        return {"status": "duplicate"}
    context = service.session_input(job.workspace_id, payload["first_event_id"], payload["last_event_id"])
    ids = {turn["id"] for turn in context["turns"]}
    pending = db.scalars(select(BackgroundJob).where(
        BackgroundJob.workspace_id == job.workspace_id,
        BackgroundJob.job_type == "counselor.analyze",
        BackgroundJob.status.in_(("pending", "running")))).all()
    if any((row.payload or {}).get("user_event_id") in ids for row in pending):
        raise AnalysisOrderPending("session analysis pending")
    db.rollback()
    raw = await complete("summarizer", messages=[{"role": "user", "content": json.dumps(context)}],
                         system_prompt=load_prompt("session_summary"),
                         response_format={"type": "json_object"}, turn_id=payload["last_event_id"])
    data = json.loads(raw)
    keys = ("discussed", "truth_map_changes", "open_threads", "commitments")
    if not isinstance(data, dict) or set(data) != set(keys) or any(not isinstance(data[k], list) for k in keys):
        raise ValueError("Invalid session summary shape")
    for key in ("discussed", "open_threads", "commitments"):
        if any(not isinstance(value, str) or not value.strip() for value in data[key]):
            raise ValueError("Invalid session summary text")
    if contains_blocked_script(json.dumps(data, ensure_ascii=False), config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
        raise ValueError("Blocked script in session summary")
    if any(change not in context["truth_map_changes"] for change in data["truth_map_changes"]):
        raise ValueError("Invented Truth Map change")
    student_texts = [turn["content"] for turn in context["turns"] if turn["role"] == "student"]
    if any(not any(quote in text for text in student_texts) for quote in data["commitments"]):
        raise ValueError("Commitment is not a student quotation")
    row = service.record_session_summary(job.workspace_id, data, context["turns"])
    return {"status": "saved", "episode_id": row.id}
