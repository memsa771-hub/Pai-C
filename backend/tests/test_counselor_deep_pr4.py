"""Offline Analyst ordering, storage, stage and failure boundaries."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import config
from app.counseling import runtime
from app.counseling.deep.analysis import (
    AnalysisOrderPending, _workspace_lock, analyze_job, enqueue_turn_analysis,
)
from app.counseling.deep.coverage import enforce_mirror_readiness
from app.counseling.deep.notebook import NotebookService, NotebookVersionConflict
from app.counseling.deep.notebook_schema import CounselorNotebookData
from app.counseling.deep.sensitive import filter_sensitive_changes, model_sensitive_checker
from app.counseling.deep.usage import usage_callback
from app.counseling.stages import advance_discovery_stage
from app.jobs.service import BackgroundJobService
from app.inference.client import chat_completion
from app.journey import JourneyService
from app.memory.handlers import _research_delegate_allowed
from app.models import BackgroundJob, EventRecord
from scripts.counselor_eval_support import StudentSession


def _turn_job(student, db, text="A private student statement"):
    event_id, reply_id = str(uuid4()), str(uuid4())
    timestamp = student.next_timestamp()
    db.add(EventRecord(id=event_id, network_id=student.workspace_id,
                       type="workspace.message.posted", source=f"human:{student.user_id}",
                       target="channel/pai-counselor", payload={"content": text},
                       timestamp=timestamp))
    db.add(EventRecord(id=reply_id, network_id=student.workspace_id,
                       type="workspace.message.posted", source="openagents:pai",
                       target="channel/pai-counselor", payload={"content": "What happened next?"},
                       timestamp=student.next_timestamp()))
    db.commit()
    job_id = enqueue_turn_analysis(db, student.workspace_id, event_id, reply_id)
    return db.get(BackgroundJob, job_id), event_id


def _model_notebook(**updates):
    return json.dumps({"notebook": {**CounselorNotebookData().model_dump(mode="json"), **updates}})


async def _no_sensitive(_previous, candidate):
    return candidate, []


@pytest.mark.asyncio
async def test_analysis_is_idempotent_and_workspace_scoped():
    with StudentSession() as student, student.factory() as db:
        job, event_id = _turn_job(student, db)
        assert enqueue_turn_analysis(db, student.workspace_id, event_id,
                                     job.payload["assistant_event_id"]) == job.id
        model = AsyncMock(return_value=_model_notebook(person={"daily_life": "Studies at home"}))
        with patch("app.counseling.deep.analysis.chat_completion", model), \
                patch("app.counseling.deep.analysis.filter_sensitive_changes", _no_sensitive):
            first = await analyze_job(job, db)
            again = await analyze_job(job, db)
        assert first["version"] == 1
        assert again["status"] == "duplicate"
        assert model.await_count == 1
        assert NotebookService(db).get(student.workspace_id).notebook.person.daily_life == "Studies at home"
        assert "<notebook_schema>" in model.call_args.kwargs["messages"][0]["content"]
        assert "<profile>" in model.call_args.kwargs["messages"][0]["content"]
        assert "<transcript>" in model.call_args.kwargs["messages"][0]["content"]
        assert model.call_args.kwargs["system_prompt"].startswith("You are the private note-taker")


@pytest.mark.asyncio
async def test_successful_deep_turn_enqueues_one_analysis_after_reply():
    with StudentSession() as student, student.factory() as db:
        event_id = str(uuid4())
        timestamp = student.next_timestamp()
        db.add(EventRecord(id=event_id, network_id=student.workspace_id,
                           type="workspace.message.posted", source=f"human:{student.user_id}",
                           target="channel/pai-counselor", payload={"content": "I need guidance"},
                           timestamp=timestamp))
        db.commit()
        event_data = {"id": event_id, "source": f"human:{student.user_id}",
                      "target": "channel/pai-counselor", "payload": {"content": "I need guidance"},
                      "timestamp": timestamp, "metadata": {}}
        with patch.object(config, "PAI_COUNSELOR_MODE", "deep"), \
                patch.object(config, "PAI_API_KEY", "fake"), \
                patch("app.counseling.deep.turn.chat_completion",
                      new=AsyncMock(return_value=json.dumps({
                          "reply": "What matters most to you?", "action": {"type": "none"}}))):
            await runtime._run_turn(db, student.workspace_id, event_data, 0)
            await runtime._run_turn(db, student.workspace_id, event_data, 0)
        jobs = db.execute(select(BackgroundJob).where(
            BackgroundJob.workspace_id == student.workspace_id,
            BackgroundJob.job_type == "counselor.analyze",
        )).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].payload["user_event_id"] == event_id
        assert student.transcript[-1]["content"] == "What matters most to you?"


@pytest.mark.asyncio
async def test_analysis_waits_for_earlier_workspace_turn():
    with StudentSession() as student, student.factory() as db:
        first_job, _ = _turn_job(student, db, "First private event")
        second_job, _ = _turn_job(student, db, "Second private event")
        model = AsyncMock(return_value=_model_notebook(person={"daily_life": "Known"}))
        with patch("app.counseling.deep.analysis.chat_completion", model), \
                patch("app.counseling.deep.analysis.filter_sensitive_changes", _no_sensitive):
            with pytest.raises(AnalysisOrderPending):
                await analyze_job(second_job, db)
            assert model.await_count == 0
            await analyze_job(first_job, db)
            first_job.status = "succeeded"
            db.commit()
            result = await analyze_job(second_job, db)
        assert result["version"] == 2
        assert model.await_count == 2


@pytest.mark.asyncio
async def test_second_workspace_analysis_retries_immediately_while_first_is_running():
    with StudentSession() as student, student.factory() as db:
        first_job, _ = _turn_job(student, db)
        second_job, _ = _turn_job(student, db)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def paused_model(**_kwargs):
            entered.set()
            await release.wait()
            return _model_notebook()

        with patch("app.counseling.deep.analysis.chat_completion", side_effect=paused_model), \
                patch("app.counseling.deep.analysis.filter_sensitive_changes", _no_sensitive):
            first = asyncio.create_task(analyze_job(first_job, db))
            await asyncio.wait_for(entered.wait(), 1)
            try:
                with pytest.raises(AnalysisOrderPending, match="already running"):
                    await asyncio.wait_for(analyze_job(second_job, db), 0.1)
            finally:
                release.set()
                await first


@pytest.mark.asyncio
async def test_postgres_advisory_lock_is_nonblocking():
    connection = SimpleNamespace(execute=MagicMock(return_value=SimpleNamespace(
        scalar_one=lambda: False)), close=MagicMock())
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),
                             connect=lambda: connection)
    db = SimpleNamespace(bind=engine)
    with pytest.raises(AnalysisOrderPending, match="already running"):
        async with _workspace_lock(db, "test-workspace"):
            pytest.fail("unavailable lock must not enter analysis")
    assert "pg_try_advisory_lock" in str(connection.execute.call_args.args[0])
    connection.close.assert_called_once()


@pytest.mark.asyncio
async def test_no_read_transaction_during_analyst_or_sensitive_model_call():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        analyst_open = []
        sensitive_open = []

        async def analyst_response(**_kwargs):
            analyst_open.append(db.in_transaction())
            return _model_notebook(person={"daily_life": "A daily activity"})

        async def sensitive_response(**kwargs):
            sensitive_open.append(db.in_transaction())
            entries = json.loads(kwargs["messages"][0]["content"])
            return json.dumps({"decisions": [
                {"path": entry["path"], "sensitive": False} for entry in entries]})

        with patch("app.counseling.deep.analysis.chat_completion", side_effect=analyst_response), \
                patch("app.counseling.deep.sensitive.chat_completion", side_effect=sensitive_response):
            await analyze_job(job, db)
        assert analyst_open == [False]
        assert sensitive_open == [False]


@pytest.mark.asyncio
async def test_version_conflict_refetches_and_reruns_once():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        model = AsyncMock(return_value=_model_notebook(person={"daily_life": "Known"}))
        real_apply = NotebookService.apply
        calls = 0

        def conflicting_apply(service, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise NotebookVersionConflict("concurrent write")
            return real_apply(service, *args, **kwargs)

        with patch("app.counseling.deep.analysis.chat_completion", model), \
                patch("app.counseling.deep.analysis.filter_sensitive_changes", _no_sensitive), \
                patch.object(NotebookService, "apply", conflicting_apply):
            result = await analyze_job(job, db)
        assert result["model_calls"] == 2
        assert model.await_count == 2


@pytest.mark.asyncio
async def test_retry_finishes_stage_after_notebook_was_saved():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        model = AsyncMock(return_value=_model_notebook(
            coverage={"person": True, "education": True}))
        from app.counseling.deep.analysis import _advance_stage

        calls = 0

        def fail_stage_once(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("stage temporarily unavailable")
            return _advance_stage(*args)

        with patch("app.counseling.deep.analysis.chat_completion", model), \
                patch("app.counseling.deep.analysis.filter_sensitive_changes", _no_sensitive), \
                patch("app.counseling.deep.analysis._advance_stage", fail_stage_once):
            with pytest.raises(RuntimeError, match="stage temporarily unavailable"):
                await analyze_job(job, db)
            db.rollback()
            assert NotebookService(db).get(student.workspace_id).version == 1
            result = await analyze_job(job, db)
        assert result["status"] == "duplicate"
        assert JourneyService(db).ensure_counselor(student.workspace_id).current_stage == "DIRECTION"
        assert model.await_count == 1


@pytest.mark.asyncio
async def test_analyst_coverage_advances_foundation_without_starting_research():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        model = AsyncMock(return_value=_model_notebook(
            coverage={"person": True, "education": True}, mirror_ready=True))
        with patch("app.counseling.deep.analysis.chat_completion", model), \
                patch("app.counseling.deep.analysis.filter_sensitive_changes", _no_sensitive):
            await analyze_job(job, db)
        notebook = NotebookService(db).get(student.workspace_id).notebook
        journey = JourneyService(db).ensure_counselor(student.workspace_id)
        assert notebook.mirror_ready is False
        assert journey.current_stage == "DIRECTION"


def test_failed_analysis_job_uses_existing_backoff():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        job.attempts = 1
        BackgroundJobService(db).fail(job, "transient model failure")
        db.commit()
        assert job.status == "pending"
        assert job.available_at > job.created_at


@pytest.mark.asyncio
async def test_sensitive_changed_entry_is_dropped_before_storage(caplog):
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        raw = _model_notebook(claims=[{
            "id": "a", "claim": "private flagged text", "evidence_level": "claimed",
            "evidence": "private flagged text", "probed": False,
        }, {
            "id": "b", "claim": "valid student work", "evidence_level": "tried",
            "evidence": "student described the work", "probed": True,
        }])

        async def filter_with_fake(previous, candidate):
            async def checker(entries):
                return {entry["path"] for entry in entries
                        if "private flagged text" in entry["text"]}
            return await filter_sensitive_changes(previous, candidate, checker=checker)

        with patch("app.counseling.deep.analysis.chat_completion", new=AsyncMock(return_value=raw)), \
                patch("app.counseling.deep.analysis.filter_sensitive_changes", filter_with_fake), \
                caplog.at_level("INFO", logger="app.counseling.deep.sensitive"):
            result = await analyze_job(job, db)
        assert result["sensitive_removed"] == 1
        assert [claim.id for claim in NotebookService(db).get(student.workspace_id).notebook.claims] == ["b"]
        assert "claims[0]" in caplog.text
        assert "private flagged text" not in caplog.text


@pytest.mark.asyncio
async def test_sensitive_check_uses_configured_model():
    model = AsyncMock(return_value='{"decisions":[{"path":"claims[0]","sensitive":false}]}')
    with patch.object(config, "PAI_SENSITIVE_CHECK_MODEL", "configured-checker"), \
            patch.object(config, "PAI_SENSITIVE_CHECK_REASONING_EFFORT", "low"), \
            patch.object(config, "PAI_COUNSELOR_SENSITIVE_CHECK_MAX_TOKENS", 4096), \
            patch("app.counseling.deep.sensitive.chat_completion", model):
        assert await model_sensitive_checker([{"path": "claims[0]", "text": "a changed entry"}]) == set()
    assert model.call_args.kwargs["model"] == "configured-checker"
    assert model.call_args.kwargs["reasoning_effort"] == "low"
    assert model.call_args.kwargs["max_tokens"] == 4096
    assert model.await_count == 1


@pytest.mark.asyncio
async def test_one_batched_sensitive_model_call_per_analysis():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        raw = _model_notebook(person={"daily_life": "daily activity"}, claims=[{
            "id": "a", "claim": "sensitive claim", "evidence_level": "claimed",
            "evidence": "student statement", "probed": False,
        }, {
            "id": "b", "claim": "ordinary claim", "evidence_level": "tried",
            "evidence": "student activity", "probed": True,
        }])

        async def sensitive_response(**kwargs):
            entries = json.loads(kwargs["messages"][0]["content"])
            assert {entry["path"] for entry in entries} >= {
                "person.daily_life", "claims[0]", "claims[1]"}
            return json.dumps({"decisions": [
                {"path": entry["path"], "sensitive": entry["path"] == "claims[0]"}
                for entry in entries]})

        analyst = AsyncMock(return_value=raw)
        sensitive = AsyncMock(side_effect=sensitive_response)
        with patch("app.counseling.deep.analysis.chat_completion", analyst), \
                patch("app.counseling.deep.sensitive.chat_completion", sensitive):
            result = await analyze_job(job, db)
        assert analyst.await_count == 1
        assert sensitive.await_count == 1
        assert result["sensitive_removed"] == 1
        assert [claim.id for claim in NotebookService(db).get(student.workspace_id).notebook.claims] == ["b"]


@pytest.mark.asyncio
async def test_prepend_to_five_item_list_checks_only_new_entry():
    def claim(index):
        return {"id": str(index), "claim": f"Activity {index}",
                "evidence_level": "claimed", "evidence": f"Statement {index}"}

    prior = [claim(index) for index in range(5)]
    previous = CounselorNotebookData.model_validate({"claims": prior})
    candidate = CounselorNotebookData.model_validate({"claims": [claim(5), *prior]})
    checked = []

    async def fake_checker(entries):
        checked.extend(entries)
        return set()

    cleaned, removals = await filter_sensitive_changes(previous, candidate, fake_checker)
    assert checked == [{"path": "claims[0]", "text": json.dumps(
        candidate.claims[0].model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))}]
    assert len(cleaned.claims) == 6
    assert removals == []


@pytest.mark.asyncio
async def test_batched_sensitive_decisions_must_cover_exactly_the_submitted_paths():
    entries = [{"path": "person.daily_life", "text": "an entry"},
               {"path": "claims[0]", "text": "another entry"}]
    with patch("app.counseling.deep.sensitive.chat_completion", new=AsyncMock(
            return_value='{"decisions":[{"path":"person.daily_life","sensitive":false}]}')):
        with pytest.raises(ValueError, match="omitted"):
            await model_sensitive_checker(entries)


def test_token_usage_log_records_each_call_without_content(caplog):
    usage = SimpleNamespace(prompt_tokens=31, completion_tokens=12,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=7),
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=3))
    with caplog.at_level("INFO", logger="app.counseling.deep.usage"):
        usage_callback("analyst", "fake-model", "turn-id")(usage)
    assert "input=31 cached_input=7 output=12 reasoning=3" in caplog.text
    assert "turn_id=turn-id" in caplog.text


@pytest.mark.asyncio
async def test_chat_completion_invokes_per_call_usage_callback():
    usage = SimpleNamespace(prompt_tokens=31, completion_tokens=12)
    response = SimpleNamespace(usage=usage, choices=[SimpleNamespace(
        message=SimpleNamespace(content="reply"))])
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                             close=AsyncMock())
    seen = []
    with patch("app.inference.client.create_client", return_value=client), \
            patch("app.plugins._shared.budget.record_model_usage"):
        result = await chat_completion("fake-key", "fake-model", [{"role": "user", "content": "hello"}],
                                       usage_callback=seen.append)
    assert result == "reply"
    assert seen == [usage]
    client.close.assert_awaited_once()


@pytest.mark.parametrize("mode,keys", [
    ("full", ("person", "education", "claims_probed", "proven_interests", "family", "real_why", "constraints", "goal_tested")),
    ("focused", ("person", "education", "real_why", "family", "constraints", "goal_tested")),
    ("light", ("person", "education", "real_why", "constraints")),
])
def test_mirror_ready_is_forced_false_until_configured_coverage_is_complete(mode, keys):
    missing = CounselorNotebookData.model_validate({
        "depth_mode": mode, "mirror_ready": True,
        "coverage": {key: True for key in keys[:-1]},
    })
    assert enforce_mirror_readiness(missing).mirror_ready is False
    complete = CounselorNotebookData.model_validate({
        "depth_mode": mode, "mirror_ready": True,
        "coverage": {key: True for key in keys},
    })
    assert enforce_mirror_readiness(complete).mirror_ready is True


def test_deep_research_gate_and_legacy_stage_behavior():
    before = SimpleNamespace(current_stage="DIRECTION", counselor_summary_draft={})
    confirmed = SimpleNamespace(current_stage="RESEARCHING",
                                counselor_summary_draft={"status": "confirmed"})
    stale = SimpleNamespace(current_stage="PROPOSED", counselor_summary_draft={})
    assert not _research_delegate_allowed("deep", before, None)
    assert _research_delegate_allowed("deep", confirmed, None)
    assert _research_delegate_allowed("deep", stale, "refresh")
    assert _research_delegate_allowed("legacy", before, None)

    class Journeys:
        def set_counselor_stage(self, workspace_id, journey_id, stage, **kwargs):
            return SimpleNamespace(id=journey_id, current_stage=stage)

    goals = [{"details": {"stated_preference": "a", "underlying_objective": "b",
                          "constraints": []}}]
    legacy = advance_discovery_stage(Journeys(), "workspace", SimpleNamespace(
        id="journey", current_stage="DIRECTION"), identity_ready=True,
        foundation_ready=True, goal_records=goals)
    deep = advance_discovery_stage(Journeys(), "workspace", SimpleNamespace(
        id="journey", current_stage="DIRECTION"), identity_ready=True,
        foundation_ready=True, goal_records=goals, allow_auto_research=False)
    assert legacy.current_stage == "RESEARCHING"
    assert deep.current_stage == "DIRECTION"


@pytest.mark.asyncio
async def test_failed_analysis_preserves_last_good_notebook_and_reply():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        before = NotebookService(db).get(student.workspace_id)
        with patch("app.counseling.deep.analysis.chat_completion",
                   new=AsyncMock(side_effect=RuntimeError("provider unavailable"))):
            with pytest.raises(RuntimeError, match="provider unavailable"):
                await analyze_job(job, db)
        assert NotebookService(db).get(student.workspace_id) == before
        assert db.execute(select(EventRecord.id).where(
            EventRecord.id == job.payload["assistant_event_id"])).scalar_one_or_none()
