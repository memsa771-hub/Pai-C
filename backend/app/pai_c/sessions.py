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
