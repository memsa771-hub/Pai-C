# -*- coding: utf-8 -*-
"""Audit #9: a planner patch rejected after its one correction logs why (error
type and the patch's shape, never student text) and is not retried by the
worker, so one bad turn costs two model calls, not ten."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.jobs.service import BackgroundJobService
from app.pai_c.deep.analysis import AnalysisPatchRejected, analyze_job
from scripts.counselor_eval_support import StudentSession
from scripts.eval.recorded_planner import PLAN
from tests.test_counselor_deep_pr4 import _turn_job
from tests.test_counselor_planner import new_item


@pytest.mark.asyncio
async def test_9_rejection_logs_reason_and_patch_keys_without_student_text(caplog):
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        bad = {"patch": [{"op": "add", "part": "said", "item": new_item(value="private student text")},
                         {"op": "confirm", "id": "not-visible", "evidence": "private student text"}],
               "plan": PLAN}
        model = AsyncMock(return_value=json.dumps(bad))
        with patch("app.pai_c.deep.analysis.chat_completion", model):
            with pytest.raises(AnalysisPatchRejected) as raised:
                await analyze_job(job, db)
    assert model.await_count == 2  # one correction, no more
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("planner_patch_rejected")]
    assert len(lines) == 2
    assert "attempt=2" in lines[1] and "error_type=" in lines[1]
    assert "keys=patch,plan" in lines[1] and "ops=item,op,part;evidence,id,op" in lines[1]
    assert "private student text" not in caplog.text
    assert "error_type=" in str(raised.value)
    assert raised.value.retryable is False


def test_9_worker_does_not_retry_a_rejection():
    with StudentSession() as student, student.factory() as db:
        job, _ = _turn_job(student, db)
        job.attempts = 1
        exc = AnalysisPatchRejected("planner patch rejected after correction: error_type=UnknownId")
        BackgroundJobService(db).fail(job, str(exc), retry=getattr(exc, "retryable", True))
        assert job.status == "failed"
