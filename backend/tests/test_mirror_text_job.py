# -*- coding: utf-8 -*-
"""The Mirror text: a background job that writes 3-4 sentences from the state
card. Model calls are mocked; nothing here reaches a live API."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.journey import JourneyService
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import BackgroundJob, StudentJourney
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.mirror import MirrorEngine
from app.pai_c.mirror.text_job import JOB_MIRROR_TEXT, enqueue_mirror_text, mirror_text_job
from scripts.counselor_eval_support import StudentSession
from tests.test_mirror_engine import QUOTE, _education, _item

MODEL = "app.pai_c.mirror.text_job.chat_completion"
GOOD = ["You are in FSc Pre-Engineering with 82% marks.", "You like robotics and you show it.",
        "Your goals and your options are still open."]


def _reply(sentences):
    return json.dumps({"sentences": sentences})


def _job(db, ws):
    """The pending text job: the reconciler queued one when the seed rows were accepted."""
    job_id = enqueue_mirror_text(db, ws) or db.scalar(select(BackgroundJob.id).where(
        BackgroundJob.workspace_id == ws, BackgroundJob.job_type == JOB_MIRROR_TEXT,
        BackgroundJob.status == "pending"))
    db.commit()
    assert job_id
    return db.get(BackgroundJob, job_id)


def _draft(db, ws):
    db.expire_all()
    return db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == ws)).counselor_summary_draft


def _seed(db, ws):
    _education(db, ws)
    _item(db, ws, "interest", {"text": "Robotics"}, level="shown")
    _item(db, ws, "interest", {"text": "Circuits"}, level="shown")
    JourneyService(db).ensure_counselor(ws)
    db.commit()


@pytest.mark.asyncio
async def test_text_job_writes_draft_shape():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        job = _job(db, ws)
        model = AsyncMock(return_value=_reply(GOOD))
        with patch(MODEL, model):
            result = await mirror_text_job(job, db)
        assert result["status"] == "written"
        kwargs = model.await_args.kwargs
        assert kwargs["role"] == "mirror"
        sent = kwargs["system_prompt"] + json.dumps(kwargs["messages"])
        assert QUOTE not in sent
        assert "Robotics" in sent and load_prompt("mirror_text") in kwargs["system_prompt"]
        draft = _draft(db, ws)
        card = MirrorEngine(db).build(ws)
    assert set(draft) == {"type", "version", "text", "written_at", "card_version"}
    assert draft["type"] == "mirror_state" and draft["version"] == 1
    assert draft["card_version"] == card["version"] and draft["text"] == " ".join(GOOD)
    assert 3 <= len(card["text"]["sentences"]) <= 4 and "?" not in draft["text"]
    assert card["text"] == {"sentences": GOOD, "version": 1, "written_at": draft["written_at"]}


@pytest.mark.asyncio
async def test_text_job_skips_same_version():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        version = MirrorEngine(db).build(ws)["version"]
        JourneyService(db).set_mirror_text(ws, " ".join(GOOD), version)
        db.commit()
        assert enqueue_mirror_text(db, ws) is None  # the reconciler's check
        job = BackgroundJob(workspace_id=ws, job_type=JOB_MIRROR_TEXT, status="pending",
                            payload={"workspace_id": ws, "card_version": version})
        db.add(job)
        db.commit()
        model = AsyncMock(side_effect=AssertionError("no model call for an unchanged card"))
        with patch(MODEL, model):
            result = await mirror_text_job(job, db)
        assert result["status"] == "same_version" and model.await_count == 0
        assert _draft(db, ws)["version"] == 1


@pytest.mark.asyncio
async def test_text_job_retries_once_then_drops_invalid_text():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        job = _job(db, ws)
        bad_number = [*GOOD[:2], "You need 95% for the next step."]
        question = [*GOOD[:2], "What do you want to study?"]
        model = AsyncMock(side_effect=[_reply(bad_number), _reply(question)])
        with patch(MODEL, model):
            result = await mirror_text_job(job, db)
        assert result["status"] == "invalid" and model.await_count == 2
        assert _draft(db, ws) is None
        for wrong in (["You are amazing at physics.", *GOOD[1:]], GOOD[:2], ["You could try NUST.", *GOOD[1:]],
                      ["The student likes robotics.", *GOOD[1:]]):
            model = AsyncMock(side_effect=[_reply(wrong), _reply(GOOD)])
            with patch(MODEL, model):
                assert (await mirror_text_job(job, db))["status"] == "written", wrong
            # Clear the text so the next round writes again.
            db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == ws)).counselor_summary_draft = None
            db.commit()


@pytest.mark.asyncio
async def test_text_job_leaves_old_mirror_awaiting_confirmation():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        row = db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == ws))
        old = {"type": "mirror", "status": "awaiting_confirmation", "version": 3, "mirror": {}}
        row.counselor_summary_draft = old
        db.commit()
        job = _job(db, ws)
        model = AsyncMock(side_effect=AssertionError("no model call while an old Mirror waits"))
        with patch(MODEL, model):
            assert (await mirror_text_job(job, db))["status"] == "old_mirror_waiting"
        assert _draft(db, ws) == old
        assert JourneyService(db).set_mirror_text(ws, " ".join(GOOD), "v1") is None
        row = db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == ws))
        row.counselor_summary_draft = {**old, "status": "confirmed"}
        db.commit()
        with patch(MODEL, AsyncMock(return_value=_reply(GOOD))):
            assert (await mirror_text_job(job, db))["status"] == "written"
        draft = _draft(db, ws)
    assert draft["type"] == "mirror_state" and draft["version"] == 4


def test_reconciler_enqueues_mirror_text_after_a_mirror_relevant_write():
    def accept(db, ws, kind, key, value):
        candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type=kind, key=key,
            proposed_value=value, confidence=0.9, source_type="user_explicit",
            evidence={"quote": QUOTE}, allow_user_explicit=True)
        assert MemoryReconciler(db).reconcile(candidate).accepted
        db.commit()

    def jobs(db, ws):
        return db.scalars(select(BackgroundJob).where(BackgroundJob.workspace_id == ws,
                                                      BackgroundJob.job_type == JOB_MIRROR_TEXT)).all()

    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        accept(db, ws, "vault_fact", "preferences.target_countries", ["Pakistan"])
        assert jobs(db, ws) == []  # not a Mirror type
        accept(db, ws, "vault_item", "interest", {"text": "Robotics"})
        first = jobs(db, ws)
        assert len(first) == 1 and first[0].payload["workspace_id"] == ws
        assert first[0].payload["card_version"] == MirrorEngine(db).build(ws)["version"]
        accept(db, ws, "vault_item", "interest", {"text": "Circuits"})
        assert len(jobs(db, ws)) == 1  # debounced: one pending job per workspace


def test_mirror_text_prompt_is_documented_verbatim():
    from pathlib import Path
    docs = Path(__file__).resolve().parents[2] / "docs/counselor/COUNSELOR_V3_PROMPTS.md"
    if not docs.exists():
        pytest.skip("docs are not mounted")
    section = docs.read_text(encoding="utf-8").split("## Mirror text (background)", 1)[1].split("\n## ", 1)[0]
    assert section.split("```text\n", 1)[1].split("\n```", 1)[0].rstrip() == load_prompt("mirror_text").rstrip()


def test_hook_failure_never_undoes_the_vault_write():
    from app.memory.vault_items import VaultItemService

    def accept(student, db):
        candidate = MemoryCandidateService(db).propose(workspace_id=student.workspace_id,
            candidate_type="vault_item", key="interest", proposed_value={"text": "Robotics"}, confidence=0.9,
            source_type="user_explicit", evidence={"quote": QUOTE}, allow_user_explicit=True)
        result = MemoryReconciler(db).reconcile(candidate)
        db.commit()
        return result

    with StudentSession() as student, student.factory() as db:
        expected = accept(student, db)
    with StudentSession() as student, student.factory() as db:
        with patch("app.pai_c.mirror.text_job.MirrorEngine.build", side_effect=KeyError("light")):
            result = accept(student, db)
        db.expire_all()
        items = VaultItemService(db).active(student.workspace_id)
    assert (result.accepted, result.outcome, result.reason) == (expected.accepted, expected.outcome, expected.reason)
    assert result.accepted and [item.value for item in items] == [{"text": "Robotics"}]


def test_sentence_count_reads_the_sentences_not_the_list():
    from app.pai_c.mirror.text_job import valid_sentences
    brief = "Education: FSc Pre-Engineering, 82%"
    two_in_one = "You study FSc with 82% marks. You like robotics."
    assert valid_sentences([two_in_one, "You weigh your options."], brief)  # 3 sentences
    assert not valid_sentences([two_in_one, "You lean toward fields.", "Your family agrees.",
                                "You weigh your options."], brief)  # 5 sentences
    # Scaffolding numbers on the brief (level N of 3) are not card numbers.
    card_brief = brief + "\nInterests (level 3 of 3): Robotics; Circuits"
    assert not valid_sentences(["You have 3 options.", "You like robotics.", "You study FSc."], card_brief)


@pytest.mark.asyncio
async def test_failed_text_keeps_the_last_text():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _seed(db, ws)
        with patch(MODEL, AsyncMock(return_value=_reply(GOOD))):
            assert (await mirror_text_job(_job(db, ws), db))["status"] == "written"
        before = _draft(db, ws)
        _item(db, ws, "value", {"text": "Helping people"})
        job = _job(db, ws)
        with patch(MODEL, AsyncMock(return_value=_reply(GOOD[:1]))):
            assert (await mirror_text_job(job, db))["status"] == "invalid"
        assert _draft(db, ws) == before
