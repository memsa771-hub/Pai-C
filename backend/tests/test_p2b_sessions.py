"""Offline session ownership and boundary tests."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from app.config import config
from app.models import EventRecord, BackgroundJob
from app.pai_c.memory import MemoryService
from app.pai_c.sessions import sweep_job
from scripts.counselor_eval_support import StudentSession


def message(student, db, timestamp, content="A student statement", role="student"):
    event = EventRecord(id=str(uuid4()), network_id=student.workspace_id,
        type="workspace.message.posted",
        source=f"human:{student.user_id}" if role == "student" else "openagents:pai",
        target="channel/pai-counselor", timestamp=timestamp, payload={"content": content})
    db.add(event)
    db.commit()
    return event.id


def test_sweep_gap_and_idempotent_job():
    with StudentSession() as student, student.factory() as db:
        now = int(time.time() * 1000)
        event_id = message(student, db, now - 31 * 60_000)
        with patch.object(config, "PAI_SESSION_GAP_MINUTES", 30):
            assert MemoryService(db).ended_sessions(now - 2 * 60_000) == []
            asyncio.run(sweep_job(SimpleNamespace(), db))
            asyncio.run(sweep_job(SimpleNamespace(), db))
        rows = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "session.summarize")).all()
        assert len(rows) == 1
        assert rows[0].payload["last_event_id"] == event_id
        assert rows[0].payload["workspace_id"] == student.workspace_id


def test_sweep_keeps_previous_session_when_student_returns():
    with StudentSession() as student, student.factory() as db:
        now = int(time.time() * 1000)
        first = message(student, db, now - 60 * 60_000)
        message(student, db, now)
        sessions = MemoryService(db).ended_sessions(now)
        assert len(sessions) == 1
        assert sessions[0]["first_event_id"] == first


def test_summary_is_idempotent_and_return_visit():
    import json
    from unittest.mock import AsyncMock
    from app.pai_c.sessions import summarize_job
    with StudentSession() as student, student.factory() as db:
        now = int(time.time() * 1000)
        event_id = message(student, db, now - 60 * 60_000, "I will prepare a draft.")
        job = SimpleNamespace(workspace_id=student.workspace_id,
            payload={"workspace_id": student.workspace_id, "first_event_id": event_id, "last_event_id": event_id})
        data = {"discussed": ["Preparing a draft"], "truth_map_changes": [],
                "open_threads": [], "commitments": ["I will prepare a draft."]}
        model = AsyncMock(return_value=json.dumps(data))
        with patch("app.inference.gateway.complete", model):
            assert asyncio.run(summarize_job(job, db))["status"] == "saved"
            assert asyncio.run(summarize_job(job, db))["status"] == "duplicate"
        assert model.await_count == 1
        assert len(MemoryService(db).session_summaries(student.workspace_id)) == 1
        assert MemoryService(db).ended_sessions(now) == []
        message(student, db, now)
        assert MemoryService(db).is_return_visit(student.workspace_id)
        message(student, db, now + 1000)
        assert not MemoryService(db).is_return_visit(student.workspace_id)


def test_invented_summary_change_rejected():
    import json
    import pytest
    from unittest.mock import AsyncMock
    from app.pai_c.sessions import summarize_job
    with StudentSession() as student, student.factory() as db:
        event_id = message(student, db, int(time.time() * 1000) - 60 * 60_000)
        job = SimpleNamespace(workspace_id=student.workspace_id,
            payload={"workspace_id": student.workspace_id, "first_event_id": event_id, "last_event_id": event_id})
        data = {"discussed": [], "truth_map_changes": [{"field": "invented"}], "open_threads": [], "commitments": []}
        with patch("app.inference.gateway.complete", AsyncMock(return_value=json.dumps(data))):
            with pytest.raises(ValueError, match="Invented Truth Map change"):
                asyncio.run(summarize_job(job, db))
