"""Mirror contract, retries, persistence and confirmation; fake models only."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.truth_map_fixtures import item
from app.config import config
from app.pai_c.deep.actions import dispatch_action
from app.pai_c.deep.context import DeepContext
from app.pai_c.deep.mirror import (JOB_MIRROR, JOB_RESEARCH, confirmed_research_job,
                                        enqueue_mirror, mirror_job)
from app.pai_c.deep.mirror_schema import CounselorMirror
from app.pai_c.deep.notebook import NotebookService
from app.pai_c.deep.turn_input import CounselorTurnInput, shared_history
from app.pai_c.stages import require_counselor_transition
from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.models import BackgroundJob, EventRecord
from scripts.counselor_eval_support import StudentSession

FIXTURE = Path(__file__).parent / "fixtures/mirror/valid.json"


def mirror_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def prepare(student, db, *, ready=True):
    event_id = str(uuid4())
    stamp = student.next_timestamp()
    db.add(EventRecord(id=event_id, network_id=student.workspace_id,
        type="workspace.message.posted", source=f"human:{student.user_id}",
        target="channel/pai-counselor", payload={"content": "Please show how you understand me."},
        timestamp=stamp))
    db.commit()
    snapshot, _ = NotebookService(db).apply(student.workspace_id, {
        "said": [item("I study and work on practical projects.", key="daily_life")], "mirror_ready": ready,
    }, event_id, expected_version=0)
    service = JourneyService(db)
    journey = service.ensure_counselor(student.workspace_id)
    for stage in ("FOUNDATION", "DIRECTION"):
        journey = service.set_counselor_stage(student.workspace_id, journey.id, stage)
    db.commit()
    turn = CounselorTurnInput("channel/pai-counselor", student.workspace_id,
        "Please show how you understand me.", (), None, event_id, stamp, f"human:{student.user_id}")
    return turn, journey, snapshot


async def safe_model(**kwargs):
    entries = json.loads(kwargs["messages"][0]["content"])
    return json.dumps({"decisions": [{"path": item["path"], "sensitive": False} for item in entries]})


def fake_post(student):
    async def post(db, workspace_id, target, agent, content, depth, **kwargs):
        event_id = str(uuid4())
        db.add(EventRecord(id=event_id, network_id=workspace_id,
            type="workspace.message.posted", source="openagents:pai", target=target,
            timestamp=student.next_timestamp(), metadata_=kwargs.get("metadata") or {},
            payload={**kwargs.get("extra_payload", {}), "content": content,
                     "message_type": kwargs.get("message_type", "chat")}))
        db.commit()
        return event_id
    return post


def test_mirror_fixture_and_prompt_document_match():
    result = CounselorMirror.model_validate(mirror_data())
    assert result.confidence == "full"
    assert len(result.roadmap_lanes) == 4
    root = Path(__file__).resolve().parents[1]
    docs = root.parent / "docs"
    if not docs.exists():
        docs = Path("/docs")
    documented = (docs / "counselor/COUNSELOR_V3_PROMPTS.md").read_text(encoding="utf-8")
    section = documented.split("## 3.", 1)[1].split("## 4.", 1)[0]
    assert section.split("```text\n", 1)[1].split("\n```", 1)[0].rstrip() == (
        root / "app/pai_c/deep/prompts/mirror.md").read_text(encoding="utf-8").rstrip()


@pytest.mark.parametrize("change", ["evidence", "duplicate_dimension", "duplicate_lane", "few_lanes",
                                    "many_lanes", "currency", "score", "blocked", "question"])
def test_mirror_validation_rejects_broken_contract(change):
    data = mirror_data()
    if change == "evidence": data["dimensions"][0]["evidence"] = " "
    if change == "duplicate_dimension": data["dimensions"][1]["key"] = data["dimensions"][0]["key"]
    if change == "duplicate_lane": data["roadmap_lanes"][1]["lane"] = data["roadmap_lanes"][0]["lane"]
    if change == "few_lanes": data["roadmap_lanes"].pop()
    if change == "many_lanes": data["roadmap_lanes"] *= 2
    if change == "currency": data["opinion"] = "You need $1000."
    if change == "percent": data["blockers"][0] = "A threshold of 80% applies."
    if change == "score": data["opinion"] = "You need 7/9."
    if change == "blocked": data["dimensions"][0]["name"] = "\u0928\u092e"
    if change == "question": data["question"] = "Is this right? What else?"
    with pytest.raises(ValueError):
        CounselorMirror.model_validate(data)


def test_mirror_allows_explicit_unknown_and_student_numbers_in_dimensions():
    data = mirror_data()
    data["dimensions"][0].update(unknown=True, evidence="", picture="We have not explored this yet.")
    data["dimensions"][1]["picture"] = "You reported a score of 80%."
    data["blockers"][0] = "You reported a score of 80%."
    assert CounselorMirror.model_validate(data).dimensions[0].unknown


@pytest.mark.asyncio
async def test_no_job_without_readiness_and_one_job_across_versions():
    with StudentSession() as student, student.factory() as db:
        turn, journey, snapshot = prepare(student, db, ready=False)
        context = DeepContext("", {}, snapshot.notebook, journey, 0)
        assert await dispatch_action(db, turn, {"type": "mirror"}, context) == ("mirror", "ignored")
        assert db.scalar(select(BackgroundJob.id).where(BackgroundJob.job_type == JOB_MIRROR)) is None
        snapshot, _ = NotebookService(db).apply(student.workspace_id,
            snapshot.notebook.model_copy(update={"mirror_ready": True}), turn.source_event_id,
            expected_version=snapshot.version)
        context = DeepContext("", {}, snapshot.notebook, journey, 0)
        assert await dispatch_action(db, turn, {"type": "mirror"}, context) == ("mirror", "requested")
        job_id = enqueue_mirror(db, turn)
        NotebookService(db).apply(student.workspace_id, snapshot.notebook, turn.source_event_id,
                                  expected_version=snapshot.version)
        assert enqueue_mirror(db, turn) == job_id
        db.commit()
        assert len(db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_MIRROR)).all()) == 1
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(BackgroundJob(workspace_id=student.workspace_id, job_type=JOB_MIRROR,
                                 status="pending", payload={}))
            db.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_first", [False, True])
async def test_mirror_posts_once_reuses_sensitive_check_and_system_context(invalid_first):
    with StudentSession() as student, student.factory() as db:
        turn, journey, snapshot = prepare(student, db)
        data = snapshot.notebook.model_dump(mode="json")
        data["sure"]["score"] = 6
        snapshot, _ = NotebookService(db).apply(student.workspace_id, data, turn.source_event_id,
                                               expected_version=snapshot.version)
        job_id = enqueue_mirror(db, turn)
        db.commit()
        job = db.get(BackgroundJob, job_id)
        source = db.get(EventRecord, turn.source_event_id)
        source.metadata_ = {"voice_delegation_id": "offline-mirror-turn"}
        db.commit()
        replies = ["not JSON", json.dumps(mirror_data())] if invalid_first else [json.dumps(mirror_data())]

        async def model(**kwargs):
            assert not db.in_transaction()
            assert "<context>" in kwargs["system_prompt"] and "<language_policy>" in kwargs["system_prompt"]
            assert kwargs["model"] == config.PAI_MIRROR_MODEL
            return replies.pop(0)

        with patch("app.pai_c.deep.sensitive.chat_completion", AsyncMock(side_effect=safe_model)) as safety, \
             patch("app.pai_c.deep.mirror.chat_completion", AsyncMock(side_effect=model)) as call, \
             patch("app.pai_c.deep.mirror.send_to_student", AsyncMock(side_effect=fake_post(student))) as post:
            assert (await mirror_job(job, db))["status"] == "posted"
            assert (await mirror_job(job, db))["status"] == "posted"
        assert call.await_count == (2 if invalid_first else 1)
        assert safety.await_count == post.await_count == 1
        draft = JourneyService(db).get(student.workspace_id, journey.id).counselor_summary_draft
        assert draft["type"] == "mirror" and draft["notebook_version"] == snapshot.version
        assert draft["status"] == "awaiting_confirmation"
        assert draft["certainty_before"] == 6
        assert JourneyService(db).get(student.workspace_id, journey.id).current_stage == "MIRROR"
        event = db.scalar(select(EventRecord).where(EventRecord.source == "openagents:pai"))
        assert event.payload["message_type"] == "counselor_mirror"
        assert event.metadata_["voice_delegation_id"] == "offline-mirror-turn"
        assert event.payload["content"] == CounselorMirror.model_validate(mirror_data()).spoken_reply()
        assert event.payload["mirror"] == CounselorMirror.model_validate(mirror_data()).model_dump(mode="json")
        later = CounselorTurnInput(turn.channel, turn.workspace_id, "A correction", (), None, "later",
                                    student.next_timestamp(), turn.source)
        assert shared_history(db, later, student.user_id)[-1]["content"] == event.payload["content"]


@pytest.mark.asyncio
async def test_second_invalid_generation_keeps_discovery_and_logs_no_text(caplog):
    with StudentSession() as student, student.factory() as db:
        turn, journey, _ = prepare(student, db)
        job_id = enqueue_mirror(db, turn)
        db.commit()
        with patch("app.pai_c.deep.sensitive.chat_completion", AsyncMock(side_effect=safe_model)), \
             patch("app.pai_c.deep.mirror.chat_completion", AsyncMock(return_value="private broken text")) as model, \
             patch("app.pai_c.deep.mirror.send_to_student", AsyncMock()) as post:
            assert (await mirror_job(db.get(BackgroundJob, job_id), db))["status"] == "invalid"
        assert model.await_count == 2
        post.assert_not_awaited()
        assert JourneyService(db).get(student.workspace_id, journey.id).current_stage == "DIRECTION"
        assert "private broken text" not in caplog.text
        current = JourneyService(db).get(student.workspace_id, journey.id)
        assert current.counselor_summary_draft["status"] == "failed"
        from app.pai_c.deep.context import build_context
        assert '"mirror_status":"failed"' in (await build_context(db, student.workspace_id, turn)).text.replace(" ", "")
        job = db.get(BackgroundJob, job_id)
        job.status = "completed"
        db.commit()
        retry = enqueue_mirror(db, turn)
        assert retry != job_id
        db.commit()
        db.get(BackgroundJob, retry).status = "completed"
        db.commit()
        enqueue_mirror(db, turn)
        assert len(db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_MIRROR)).all()) == 2


@pytest.mark.asyncio
async def test_sensitive_removal_blocks_mirror_generation():
    with StudentSession() as student, student.factory() as db:
        turn, journey, _ = prepare(student, db)
        job_id = enqueue_mirror(db, turn)
        db.commit()
        async def sensitive(**kwargs):
            entries = json.loads(kwargs["messages"][0]["content"])
            return json.dumps({"decisions": [{"path": item["path"],
                "sensitive": item["path"] == "said[0]"} for item in entries]})
        with patch("app.pai_c.deep.sensitive.chat_completion", AsyncMock(side_effect=sensitive)) as check, \
             patch("app.pai_c.deep.mirror.chat_completion", AsyncMock()) as model:
            assert (await mirror_job(db.get(BackgroundJob, job_id), db))["status"] == "needs_discovery"
        assert check.await_count == 1
        model.assert_not_awaited()
        assert not NotebookService(db).get(student.workspace_id).notebook.mirror_ready


@pytest.mark.asyncio
async def test_stale_notebook_skips_generation_and_failed_check_never_posts():
    with StudentSession() as student, student.factory() as db:
        turn, journey, snapshot = prepare(student, db)
        job_id = enqueue_mirror(db, turn)
        db.commit()
        job = db.get(BackgroundJob, job_id)
        with patch("app.pai_c.deep.mirror.check_notebook_before_mirror",
                   AsyncMock(side_effect=RuntimeError("safety unavailable"))), \
             patch("app.pai_c.deep.mirror.chat_completion", AsyncMock()) as model, \
             patch("app.pai_c.deep.mirror.send_to_student", AsyncMock()) as post:
            with pytest.raises(RuntimeError, match="safety unavailable"):
                await mirror_job(job, db)
            model.assert_not_awaited()
            post.assert_not_awaited()
        NotebookService(db).apply(student.workspace_id, snapshot.notebook,
                                  turn.source_event_id, expected_version=snapshot.version)
        with patch("app.pai_c.deep.mirror.chat_completion", AsyncMock()) as model:
            assert (await mirror_job(job, db))["status"] == "not_ready_or_stale"
            model.assert_not_awaited()


def draft_ready(student, db):
    turn, journey, snapshot = prepare(student, db)
    result = JourneyService(db).set_counselor_summary(student.workspace_id, journey.id,
        mirror_data(), "A picture.", turn.source_event_id,
        notebook_version=snapshot.version, channel=turn.channel)
    db.commit()
    return result


def client_for(student):
    def scoped():
        with student.factory() as db:
            yield db
    app.dependency_overrides[get_db] = scoped
    return TestClient(app)


@pytest.mark.asyncio
async def test_confirm_is_versioned_scoped_and_hands_off_exactly_once():
    with StudentSession() as student, student.factory() as db:
        journey = draft_ready(student, db)
        client = client_for(student)
        url = f"/v1/counselor/summary/confirm?network={student.workspace_id}"
        headers = {"X-Workspace-Token": "synthetic-test-only"}
        try:
            assert client.post(url, json={"version": 1}).status_code == 401
            assert client.post(url, json={"version": 2}, headers=headers).status_code == 409
            for _ in range(2):
                assert client.post(url, json={"version": 1}, headers=headers).status_code == 200
            db.expire_all()
            current = JourneyService(db).get(student.workspace_id, journey.id)
            assert current.current_stage == "RESEARCHING"
            assert current.counselor_summary_draft["status"] == "confirmed"
            jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_RESEARCH)).all()
            assert len(jobs) == 1
            with patch("app.research.gateway.request_research", AsyncMock(return_value={"ok": True})) as research:
                assert (await confirmed_research_job(jobs[0], db))["status"] == "done"
                assert (await confirmed_research_job(jobs[0], db))["status"] == "duplicate"
            research.assert_awaited_once()
            assert research.call_args.args[0] == "from_mirror"
            assert research.call_args.kwargs["trigger"] == "mirror_confirmed"
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_edit_posts_normal_student_event_and_returns_to_discovery():
    with StudentSession() as student, student.factory() as db:
        journey = draft_ready(student, db)
        client = client_for(student)
        async def persist(event, context):
            context.extra["db"].add(EventRecord(id=event.id, network_id=event.network, type=event.type,
                source=event.source, target=event.target, payload=event.payload, metadata_=event.metadata,
                timestamp=event.timestamp))
            return event
        try:
            with patch("app.security.event_identity.verify_identity_claims", return_value={"session_user_id": student.user_id}), \
                 patch("app.routers.events.pipeline.process", AsyncMock(side_effect=persist)), \
                 patch("app.pai_c.orchestrator.handle_student_message", AsyncMock()) as counselor, \
                 patch("app.services.workflow.advance_workflow"), \
                 patch("app.infrastructure.cache.publish_event"), patch("app.routers.events._invalidate_poll_cache"):
                response = client.post(f"/v1/counselor/summary/edit?network={student.workspace_id}",
                    json={"version": 1, "text": "My main constraint is time, not money."},
                    headers={"X-Workspace-Token": "synthetic-test-only", "Authorization": "Bearer offline-owner-id-token"})
            assert response.status_code == 200, response.text
            counselor.assert_awaited_once()
            db.expire_all()
            current = JourneyService(db).get(student.workspace_id, journey.id)
            assert current.current_stage == "DIRECTION"
            assert current.counselor_summary_draft["status"] == "needs_changes"
            event = db.get(EventRecord, response.json()["data"]["id"])
            assert event.source == f"human:{student.user_id}"
            assert event.payload["message_type"] == "chat"
            assert event.metadata_["target_agents"] == ["pai"]
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_mirror_stage_requires_explicit_mirror_step_and_migration():
    assert require_counselor_transition("DIRECTION", "MIRROR") == "MIRROR"
    assert require_counselor_transition("MIRROR", "DIRECTION") == "DIRECTION"
    assert require_counselor_transition("MIRROR", "RESEARCHING") == "RESEARCHING"
    with pytest.raises(ValueError):
        require_counselor_transition("DIRECTION", "RESEARCHING")
    path = Path(__file__).resolve().parents[1] / "alembic/versions/098_counselor_mirror.py"
    spec = importlib.util.spec_from_file_location("mirror_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(module, "op", Mock()) as op:
        module.upgrade()
        assert "MIRROR" in op.create_check_constraint.call_args.args[2]
        assert op.create_index.call_args.args[0] == "uq_counselor_mirror_pending"
        module.downgrade()
        assert "MIRROR" not in op.create_check_constraint.call_args.args[2]

def test_v2_picture_required_evidence_unknown_and_spoken_order():
    from app.pai_c.deep.mirror_schema import SavedCounselorMirror
    data = mirror_data()
    old = {key: value for key, value in data.items() if key != "core_picture"}
    assert SavedCounselorMirror.model_validate(old).spoken_reply() == "\n\n".join(
        (old["intro"], old["opinion"], old["question"]))
    with pytest.raises(ValueError):
        CounselorMirror.model_validate(old)
    data["core_picture"]["pressure"]["evidence"] = ""
    with pytest.raises(ValueError):
        CounselorMirror.model_validate(data)
    data["core_picture"]["pressure"]["unknown"] = True
    result = CounselorMirror.model_validate(data)
    assert result.spoken_reply().split("\n\n") == [
        data["intro"], *[data["core_picture"][key]["text"] for key in
        ("you_say", "life_shows", "pressure", "you_want")], data["opinion"], data["question"]]
    data["core_picture"]["you_say"]["text"] += " Another question?"
    with pytest.raises(ValueError):
        CounselorMirror.model_validate(data)


@pytest.mark.asyncio
async def test_mirror_context_public_views_and_private_gap_allowlist():
    from app.pai_c.deep.context import build_context
    with StudentSession() as student, student.factory() as db:
        turn, _, snapshot = prepare(student, db)
        data = snapshot.notebook.model_dump(mode="json")
        data["private_notes"] = "Excluded private interpretation"
        data["tensions"] = [{"between": ["Stated ambition", "Observed practice"],
                            "evidence": "Private gap evidence", "status": "open"}]
        data["world"]["people"] = [{"id": "person1", "role": "parent", "wish": "a stable direction",
            "worry": "lost time", "evidence": "Student described the concern",
            "first_seen": "2026-01-01T00:00:00+00:00", "last_confirmed": "2026-01-01T00:00:00+00:00"}]
        NotebookService(db).apply(student.workspace_id, data, turn.source_event_id,
                                 expected_version=snapshot.version)
        context = await build_context(db, student.workspace_id, turn, mirror=True)
        assert "<personal_view>" in context.text and "<capability_view>" in context.text
        assert "<private_gap_context>" in context.text and "Private gap evidence" in context.text
        assert "a stable direction" in context.text and "lost time" in context.text
        for excluded in ("private_notes", "hypotheses", "identity_status", "decision_difficulties",
                         "legacy_v1", "legacy_v2", "Excluded private interpretation"):
            assert excluded not in context.text


@pytest.mark.asyncio
@pytest.mark.parametrize("repaired", [False, True])
async def test_private_gap_quote_rejected_once_then_repair_or_discovery(repaired):
    with StudentSession() as student, student.factory() as db:
        turn, journey, snapshot = prepare(student, db)
        gaps = [{"between": ["A private comparison", "Another private comparison"],
                 "evidence": "Private interpretation must not be copied", "status": "open"}]
        data = snapshot.notebook.model_dump(mode="json")
        data["tensions"] = gaps
        NotebookService(db).apply(student.workspace_id, data, turn.source_event_id,
                                 expected_version=snapshot.version)
        job_id = enqueue_mirror(db, turn)
        db.commit()
        broken = mirror_data()
        broken["dimensions"][0]["picture"] = gaps[0]["evidence"]
        replies = [json.dumps(broken), json.dumps(mirror_data() if repaired else broken)]
        with patch("app.pai_c.deep.sensitive.chat_completion", AsyncMock(side_effect=safe_model)), \
             patch("app.pai_c.deep.mirror.chat_completion", AsyncMock(side_effect=replies)) as model, \
             patch("app.pai_c.deep.mirror.send_to_student", AsyncMock(side_effect=fake_post(student))) as post:
            result = await mirror_job(db.get(BackgroundJob, job_id), db)
        assert model.await_count == 2
        assert result["status"] == ("posted" if repaired else "invalid")
        assert post.await_count == int(repaired)


@pytest.mark.asyncio
async def test_old_draft_publication_preserves_saved_speech_and_generation_retry_requires_v2():
    from app.pai_c.deep.mirror import _publish
    with StudentSession() as student, student.factory() as db:
        turn, journey, snapshot = prepare(student, db)
        old = mirror_data()
        old.pop("core_picture")
        old_reply = "The original spoken text."
        saved = JourneyService(db).set_counselor_summary(student.workspace_id, journey.id,
            old, old_reply, turn.source_event_id, notebook_version=snapshot.version, channel=turn.channel)
        db.commit()
        original = dict(saved.counselor_summary_draft)
        job = BackgroundJob(id=str(uuid4()), workspace_id=student.workspace_id,
                            job_type=JOB_MIRROR, payload={"source_event_id": turn.source_event_id})
        with patch("app.pai_c.deep.mirror.send_to_student", AsyncMock(side_effect=fake_post(student))) as post:
            await _publish(db, job, original)
        assert post.call_args.args[4] == old_reply
        assert "core_picture" not in original["mirror"]
        # A fresh generation following correction uses the strict v2 contract.
        JourneyService(db).request_counselor_summary_changes(student.workspace_id, journey.id, expected_version=1, actor="human:test")
        db.commit()
        next_event = str(uuid4())
        db.add(EventRecord(id=next_event, network_id=student.workspace_id,
            source=turn.source, target=turn.channel, type="workspace.message.posted",
            timestamp=student.next_timestamp(), payload={"content": "Please try the picture again."}))
        db.commit()
        fresh = BackgroundJob(id=str(uuid4()), workspace_id=student.workspace_id, job_type=JOB_MIRROR,
            payload={"source_event_id": next_event, "channel": turn.channel,
                     "journey_id": journey.id, "notebook_version": snapshot.version + 1})
        NotebookService(db).apply(student.workspace_id, snapshot.notebook, turn.source_event_id,
                                 expected_version=snapshot.version)
        db.add(fresh)
        db.commit()
        with patch("app.pai_c.deep.sensitive.chat_completion", AsyncMock(side_effect=safe_model)), \
             patch("app.pai_c.deep.mirror.chat_completion", AsyncMock(side_effect=[json.dumps(old), json.dumps(mirror_data())])) as model, \
             patch("app.pai_c.deep.mirror.send_to_student", AsyncMock(side_effect=fake_post(student))):
            assert (await mirror_job(fresh, db))["status"] == "posted"
        assert model.await_count == 2
        assert "core_picture" in JourneyService(db).get(student.workspace_id, journey.id).counselor_summary_draft["mirror"]
