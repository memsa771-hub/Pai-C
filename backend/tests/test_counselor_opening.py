"""Offline first-completion opening, retry and identity contracts."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.database import Base
from app.models import BackgroundJob, Channel, ChannelMember, EventRecord, Workspace, User
from app.pai_c import opening
from app.pai_c.deep.context import _profile
from app.memory.vault import VaultService
from app.services.pai import ensure_primary_conversation
from scripts.counselor_eval_support import StudentSession
from tests.test_student_onboarding import db, ANSWERS


def test_onboarding_queues_opening_once_on_first_completion(db):
    from app.memory.onboarding import OnboardingService
    service = OnboardingService(db)
    workspace = db.info["workspace"]
    service.apply(workspace, ANSWERS, complete=False)
    assert db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == opening.JOB_OPENING)) is None
    service.apply(workspace, ANSWERS)
    db.commit()
    service.apply(workspace, ANSWERS)
    db.commit()
    jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == opening.JOB_OPENING)).all()
    assert len(jobs) == 1 and jobs[0].workspace_id == workspace.id


def test_primary_conversation_has_no_seeded_greeting():
    with StudentSession() as student, student.factory() as db:
        Base.metadata.create_all(student.engine, tables=[Channel.__table__, ChannelMember.__table__])
        workspace = db.get(Workspace, student.workspace_id)
        assert ensure_primary_conversation(db, workspace)
        assert not ensure_primary_conversation(db, workspace)
        assert db.scalar(select(EventRecord)) is None
        assert db.scalar(select(Channel)).name == "pai-counselor"


@pytest.mark.asyncio
async def test_opening_posts_once_and_rechecks_after_model():
    with StudentSession() as student, student.factory() as db:
        job = SimpleNamespace(id="opening-test", workspace_id=student.workspace_id, attempts=1, max_attempts=3)
        async def model(*args, **kwargs):
            assert not db.in_transaction()
            assert "This is the first message" in kwargs["system_prompt"]
            assert kwargs["messages"] == []
            return json.dumps({"reply": "Welcome. Tell me about yourself.", "moves": ["ask"], "action": {"type": "none"}})
        with patch.object(opening, "complete", AsyncMock(side_effect=model)) as fake:
            assert (await opening.opening_job(job, db))["status"] == "posted"
            assert (await opening.opening_job(job, db))["status"] == "already_posted"
            fake.assert_awaited_once()
        assert len(student.transcript) == 1


@pytest.mark.asyncio
async def test_opening_existing_pai_message_never_calls_model():
    with StudentSession() as student, student.factory() as db:
        await student.post_response(db, student.workspace_id, "channel/pai-counselor", "pai", "Existing reply.", 0)
        with patch.object(opening, "complete", AsyncMock()) as fake:
            result = await opening.opening_job(SimpleNamespace(id="job", workspace_id=student.workspace_id, attempts=1, max_attempts=3), db)
        assert result["status"] == "already_posted"
        fake.assert_not_awaited()


@pytest.mark.asyncio
async def test_opening_retries_then_posts_named_fallback():
    with StudentSession() as student, student.factory() as db:
        db.get(User, student.user_id).display_name = "Alex"
        db.commit()
        job = SimpleNamespace(id="job", workspace_id=student.workspace_id, attempts=1, max_attempts=2)
        with patch.object(opening, "complete", AsyncMock(side_effect=RuntimeError("offline"))):
            with pytest.raises(RuntimeError):
                await opening.opening_job(job, db)
            assert not student.transcript
            job.attempts = 2
            assert (await opening.opening_job(job, db))["status"] == "posted"
        assert student.transcript[-1]["content"] == config.PAI_OPENING_FALLBACK_REPLY.replace("{name}", "Alex")


def test_prefixed_identity_is_in_never_ask_block():
    with StudentSession() as student, student.factory() as db:
        from app.memory.field_definitions import VaultFieldDefinitionService
        VaultFieldDefinitionService(db).upsert_definition({
            "key": "identity.preferred_name", "category": "identity", "data_type": "string",
            "sensitivity": "normal", "validation_schema": {"type": "string"}, "conflict_policy": "latest_wins"})
        VaultService(db).apply_fact(student.workspace_id, "identity.preferred_name", "Alex", "user_explicit")
        db.commit()
        profile = _profile(db, student.workspace_id)
        assert profile["identity_never_ask"]["identity.preferred_name"]["value"] == "Alex"
        assert "identity.preferred_name" not in {entry["type"] for entry in profile["entries"]}


@pytest.mark.asyncio
async def test_opening_never_waits_behind_workspace_analysis():
    """Path analysis (counselor.paths) holds the workspace-analysis lock for a
    long model call; the opening only reads the Vault and runs at once."""
    from app.pai_c.deep.analysis import AnalysisOrderPending, _workspace_lock
    with StudentSession() as student, student.factory() as db:
        job = SimpleNamespace(id="opening-now", workspace_id=student.workspace_id, attempts=1, max_attempts=3)
        reply = json.dumps({"reply": "Welcome. Tell me about yourself."})
        with patch.object(opening, "complete", AsyncMock(return_value=reply)):
            async with _workspace_lock(db, student.workspace_id):  # a running counselor.paths job
                assert (await opening.opening_job(job, db))["status"] == "posted"
        assert len(student.transcript) == 1
        # A second run of the opening while one holds its own lock still waits (exactly once).
        async with _workspace_lock(db, student.workspace_id, scope=opening.JOB_OPENING):
            with pytest.raises(AnalysisOrderPending):
                await opening.opening_job(job, db)


def test_opening_is_claimed_before_queued_analysis():
    from app.capabilities.system import JOB_PRIORITY
    from app.jobs.service import BackgroundJobService
    from app.pai_c.paths.analyzer import JOB_ANALYZE_PATHS
    from app.runtime.task_runtime import enqueue
    assert JOB_PRIORITY[opening.JOB_OPENING] > JOB_PRIORITY.get(JOB_ANALYZE_PATHS, 0)
    with StudentSession() as student, student.factory() as db:
        paths = enqueue(db, job_type=JOB_ANALYZE_PATHS, workspace_id=student.workspace_id,
                        payload={"reason": "vault"}, idempotency_key="paths-1")
        first = enqueue(db, job_type=opening.JOB_OPENING, workspace_id=student.workspace_id,
                        payload={}, idempotency_key=f"counselor:opening:{student.workspace_id}")
        db.commit()
        assert first.priority == JOB_PRIORITY[opening.JOB_OPENING] and paths.priority == 0
        claimed = BackgroundJobService(db).claim(limit=1, worker_id="w")
        assert [job.job_type for job in claimed] == [opening.JOB_OPENING]
