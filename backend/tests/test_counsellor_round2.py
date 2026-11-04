# -*- coding: utf-8 -*-
"""P0 round 2 fixes after the live run of 2026-11-04 (R-47, design 5.5)."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.planner.patch import apply_patch, PatchRejected
from scripts.counselor_eval_support import StudentSession
from scripts.eval.recorded_planner import PLAN
from tests.test_counselor_deep_pr4 import _turn_job
from tests.test_counselor_planner import new_item


# R2-3: a rejected patch says why, as a fixed reason code, never student text.

@pytest.mark.req("R-47")
def test_r2_3_rejection_names_reason_code_op_index_and_part():
    before = CounselorNotebookData()
    ops = [{"op": "add", "part": "source", "item": new_item(value="private student text", category="self")},
           {"op": "add", "part": "said", "item": new_item(value="private student text")},
           {"op": "set_coverage", "part": "shown", "value": True}]
    with pytest.raises(PatchRejected) as raised:
        apply_patch(before, ops, frozenset(), "")
    message = str(raised.value)
    assert "op_index=2" in message
    assert "reason=coverage_without_evidence" in message
    assert "part=shown" in message
    assert "private student text" not in message
    assert raised.value.reason == "coverage_without_evidence"


@pytest.mark.req("R-47")
@pytest.mark.parametrize("op, reason", [
    ({"op": "confirm", "id": "unknown", "evidence": "private student text"}, "id_not_visible"),
    ({"op": "set_sure", "score": 7, "reason": "r", "would_raise": "w", "evidence": "e"}, "rating_not_in_student_text"),
    ({"op": "add", "part": "said", "item": new_item(category="self")}, "category_source_only"),
    ({"op": "add", "part": "said", "item": new_item(kind="shown")}, "evidence_needs_profile_ref"),
    ({"op": "add", "part": "said", "item": new_item(value="private student text", id="x")}, "invalid_operation"),
    ({"op": "unknown"}, "invalid_operation"),
])
def test_r2_3_each_rejection_has_a_fixed_reason(op, reason):
    with pytest.raises(PatchRejected) as raised:
        apply_patch(CounselorNotebookData(), [op], frozenset(), "")
    assert f"reason={reason}" in str(raised.value)
    assert "private student text" not in str(raised.value)


@pytest.mark.req("R-47")
def test_r2_3_non_list_patch_has_reason():
    with pytest.raises(PatchRejected) as raised:
        apply_patch(CounselorNotebookData(), {"op": "x"}, frozenset(), "")
    assert "reason=patch_not_a_list" in str(raised.value)


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_r2_3_retry_feedback_to_the_analyst_carries_the_reason(caplog):
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        bad = {"patch": [{"op": "add", "part": "source", "item": new_item(value="private student text", category="self")},
                         {"op": "set_coverage", "part": "said", "value": True}],
               "plan": PLAN}
        good = {"patch": [{"op": "add", "part": "said", "item": new_item(value="Corrected")},
                          {"op": "set_coverage", "part": "said", "value": True}],
                "plan": PLAN}
        model = AsyncMock(side_effect=[json.dumps(bad), json.dumps(good)])
        from app.pai_c.deep.analysis import analyze_job
        with patch("app.pai_c.deep.analysis.chat_completion", model):
            await analyze_job(job, db)
    feedback = model.await_args_list[1].kwargs["system_prompt"]
    assert "op_index=1" in feedback
    assert "reason=coverage_without_evidence" in feedback and "part=said" in feedback
    assert "private student text" not in feedback
    assert "private student text" not in caplog.text


# R2-2: Voice's note_question ("I'll check") always leaves an open research question.

def _signals_with_request(kind, needs_research):
    from tests.test_adaptive_counseling import QUESTION, signals
    return signals(intent="asking_info", request={"text": QUESTION, "kind": kind,
        "needs_context": False, "needs_research": needs_research})


@pytest.mark.req("R-47")
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["information", "task"])
@pytest.mark.parametrize("decision", ["answer_request", "counsel"])
async def test_r2_2_voice_note_question_starts_research_even_when_classifier_said_no(monkeypatch, kind, decision):
    from app.config import config
    from app.models import CounselorNotedQuestion
    from sqlalchemy import select
    from tests.test_adaptive_counseling import QUESTION, _ask, _claim_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    with StudentSession() as student:
        await _ask(student, _signals_with_request(kind, False), decision=decision,
                   voice_action={"type": "note_question", "question_to_research": QUESTION})
        with student.factory() as db:
            [noted] = db.scalars(select(CounselorNotedQuestion)).all()
            assert (noted.kind, noted.needs_research, noted.status) == ("information", True, "open")
            assert noted.answered_event_id is None
            jobs = _claim_jobs(db)
            assert len(jobs) == 1
            assert jobs[0].idempotency_key == f"information:{student.workspace_id}:{noted.id}"


@pytest.mark.req("R-47")
@pytest.mark.asyncio
@pytest.mark.parametrize("voice_flags, starts", [
    ({"kind": "task"}, True),                             # Voice's own default: research
    ({"kind": "task", "needs_research": True}, True),
    ({"kind": "task", "needs_research": False}, False),   # answered on the spot: no promise
])
async def test_r2_2_voice_note_without_classifier_request_follows_voices_research_flag(monkeypatch, voice_flags, starts):
    from app.config import config
    from app.models import CounselorNotedQuestion
    from app.pai_c.policy.classifier import fallback_signals
    from sqlalchemy import select
    from tests.test_adaptive_counseling import QUESTION, _ask, _claim_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    with StudentSession() as student:
        await _ask(student, fallback_signals(), voice_action={"type": "note_question",
                   "question_to_research": QUESTION, **voice_flags})
        with student.factory() as db:
            noted = db.scalar(select(CounselorNotedQuestion))
            assert len(_claim_jobs(db)) == (1 if starts else 0)
            assert noted.status == ("open" if starts else "answered_now")


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_r2_2_answered_request_without_note_question_stays_answered_now(monkeypatch):
    from app.config import config
    from app.models import CounselorNotedQuestion
    from sqlalchemy import select
    from tests.test_adaptive_counseling import _ask, _claim_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    with StudentSession() as student:
        await _ask(student, _signals_with_request("information", False), decision="answer_request")
        with student.factory() as db:
            assert db.scalar(select(CounselorNotedQuestion)).status == "answered_now"
            assert _claim_jobs(db) == []


@pytest.mark.req("R-47")
@pytest.mark.asyncio
async def test_r2_2_sweep_tells_the_student_when_the_start_failed(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.config import config
    from app.models import CounselorNotedQuestion
    from app.pai_c import myths
    from sqlalchemy import select
    from tests.test_adaptive_counseling import QUESTION, _ask, _claim_jobs, _notice_jobs
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    research = AsyncMock(side_effect=RuntimeError("database went away"))
    now = datetime.now(timezone.utc)
    with StudentSession() as student:
        await _ask(student, _signals_with_request("information", False), decision="answer_request",
                   voice_action={"type": "note_question", "question_to_research": QUESTION}, research=research)
        assert research.await_count == 2
        with student.factory() as db:
            assert _claim_jobs(db) == []
            row = db.scalar(select(CounselorNotedQuestion))
            row.created_at = now - timedelta(minutes=31)
            db.commit()
            assert myths.sweep_unstarted_information(db, now=now) == 1
            [notice] = _notice_jobs(db)
            assert notice.idempotency_key == f"information-unanswered:{student.workspace_id}:{row.id}"
