"""A chat-asked path analysis is never swallowed by a quiet Vault-triggered run
(Task 3, fix round 2). Fake models only."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import BackgroundJob, EventRecord, StudentJourney
from app.pai_c.paths.analyzer import (JOB_ANALYZE_PATHS, ask_path_analysis, enqueue_path_analysis,
                                      path_analysis_job)
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import fake_post
from tests.test_path_analyzer import add_education, analysis, path, seed

MODEL = "app.pai_c.paths.analyzer.chat_completion"
POST = "app.pai_c.paths.analyzer.send_to_student"


def jobs(db, ws):
    return db.scalars(select(BackgroundJob).where(BackgroundJob.workspace_id == ws,
                                                  BackgroundJob.job_type == JOB_ANALYZE_PATHS)).all()


def posts(db, ws):
    return db.scalars(select(EventRecord).where(EventRecord.network_id == ws,
                                                EventRecord.source == "openagents:pai")).all()


async def finish(db, job):
    """Run a job the way the worker does: the handler, then the stored result."""
    result = await path_analysis_job(job, db)
    job.status, job.result = "succeeded", result
    db.commit()
    return result


@pytest.mark.asyncio
async def test_a_pending_vault_run_takes_over_the_asked_channel_and_posts_once():
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)
        add_education(student, db)  # the reconciler-free write: queue the quiet run by hand
        quiet = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        db.commit()
        asked = await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                        channel=turn.channel)
        db.commit()
        assert asked == quiet and len(jobs(db, student.workspace_id)) == 1
        job = db.get(BackgroundJob, quiet)
        assert job.payload["reason"] == "asked" and job.payload["channel"] == turn.channel
        assert job.payload["source_event_id"] == turn.source_event_id
        reply = json.dumps(analysis(path("electrical_engineering")))
        with patch(MODEL, AsyncMock(return_value=reply)), patch(POST, AsyncMock(side_effect=fake_post(student))):
            assert (await finish(db, job))["status"] == "posted"
        sent = posts(db, student.workspace_id)
    assert len(sent) == 1 and sent[0].target == turn.channel and sent[0].metadata_["paths_found"]


@pytest.mark.asyncio
async def test_a_finished_run_with_the_same_input_is_posted_without_a_new_job():
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)
        add_education(student, db)
        quiet = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        db.commit()
        reply = json.dumps(analysis(path("electrical_engineering"), message="Two fields fit what you shared."))
        with patch(MODEL, AsyncMock(return_value=reply)) as model, \
             patch(POST, AsyncMock(side_effect=fake_post(student))):
            assert (await finish(db, db.get(BackgroundJob, quiet)))["status"] == "stored"
            assert posts(db, student.workspace_id) == []
            asked = await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                            channel=turn.channel)
            db.commit()
            again = await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                            channel=turn.channel)
        assert asked == again == quiet and len(jobs(db, student.workspace_id)) == 1
        assert model.await_count == 1  # no second analysis
        sent = posts(db, student.workspace_id)
    assert len(sent) == 1  # the same turn asking twice posts once
    assert sent[0].payload["content"] == "Two fields fit what you shared."
    assert sent[0].target == turn.channel and sent[0].metadata_["paths_found"]


@pytest.mark.asyncio
async def test_a_finished_needs_education_run_posts_the_needs_line():
    from app.pai_c.paths.analyzer import policy
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)  # no education yet
        quiet = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        db.commit()
        with patch(POST, AsyncMock(side_effect=fake_post(student))):
            assert (await finish(db, db.get(BackgroundJob, quiet)))["status"] == "needs_education"
            assert await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                           channel=turn.channel) == quiet
        sent = posts(db, student.workspace_id)
    rules = policy()
    assert [event.payload["content"] for event in sent] == [rules["needs_education_messages"]["education"]]


def test_a_failing_stage_move_keeps_the_mirror_ready_and_the_text_job():
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    from app.pai_c.mirror import MirrorEngine
    from app.pai_c.mirror.text_job import JOB_MIRROR_TEXT
    from tests.counselor_fixtures import prepare
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _, journey, _ = prepare(student, db)
        candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type="vault_item", key="interest",
            proposed_value={"text": "Robotics"}, confidence=0.9, source_type="user_explicit",
            evidence={"quote": "q"}, allow_user_explicit=True)
        with patch.object(MirrorEngine, "ready", return_value=True), \
             patch("app.pai_c.mirror.engine.ready_from", return_value=True), \
             patch("app.pai_c.paths.analyzer.propose_after_paths", side_effect=RuntimeError("boom")):
            assert MemoryReconciler(db).reconcile(candidate).accepted
        db.commit()
        db.expire_all()
        assert db.get(StudentJourney, journey.id).current_stage == "MIRROR"
        assert db.scalar(select(BackgroundJob.id).where(BackgroundJob.workspace_id == ws,
                                                        BackgroundJob.job_type == JOB_MIRROR_TEXT))


@pytest.mark.asyncio
async def test_an_ask_while_the_run_is_running_is_posted_when_it_finishes():
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)
        add_education(student, db)
        quiet = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        job = db.get(BackgroundJob, quiet)
        job.status = "running"
        db.commit()
        reply = json.dumps(analysis(path("electrical_engineering")))

        async def model(**kwargs):
            # The student asks while the run is already past reading its payload.
            assert await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                           channel=turn.channel) == quiet
            db.commit()
            return reply

        with patch(MODEL, AsyncMock(side_effect=model)), patch(POST, AsyncMock(side_effect=fake_post(student))):
            assert (await finish(db, job))["status"] == "posted"
        assert len(jobs(db, student.workspace_id)) == 1
        sent = posts(db, student.workspace_id)
    assert len(sent) == 1 and sent[0].target == turn.channel
    assert sent[0].metadata_["paths_reply_to"] == turn.source_event_id


@pytest.mark.asyncio
async def test_a_retried_turn_after_the_run_posted_does_not_post_again():
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)
        add_education(student, db)
        quiet = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id, channel=turn.channel)
        db.commit()
        reply = json.dumps(analysis(path("electrical_engineering")))
        with patch(MODEL, AsyncMock(return_value=reply)), patch(POST, AsyncMock(side_effect=fake_post(student))):
            assert (await finish(db, db.get(BackgroundJob, quiet)))["status"] == "posted"
            await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                    channel=turn.channel)
        assert len(posts(db, student.workspace_id)) == 1


@pytest.mark.asyncio
async def test_an_ask_after_a_failed_run_retries_once_per_turn():
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)
        add_education(student, db)
        quiet = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        db.get(BackgroundJob, quiet).status = "failed"
        db.commit()
        retry = await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                        channel=turn.channel)
        db.commit()
        again = await ask_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                        channel=turn.channel)
        db.commit()
        job = db.get(BackgroundJob, retry)
        assert retry != quiet and again == retry and len(jobs(db, student.workspace_id)) == 2
        assert job.status == "pending" and job.payload["reason"] == "asked" and job.payload["channel"] == turn.channel
        assert job.idempotency_key.endswith(f":retry:{turn.source_event_id}")
