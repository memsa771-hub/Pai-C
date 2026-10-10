"""Offline proof of shared research ownership and durable Operator execution."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.jobs.service import BackgroundJobService
from app.models import BackgroundJob, ExecutionRun
from app.runtime.task_runtime import run as dispatch
from app.services import operator
from app.tools import ToolContext
from scripts.counselor_eval_support import StudentSession


@pytest.mark.asyncio
async def test_delegate_atomically_persists_run_and_one_job_without_starting_execution():
    with StudentSession() as student:
        ctx = ToolContext(student.workspace_id, "pai", None, conversation="pai-counselor")
        with patch.object(operator, "is_available", return_value=True), patch.object(operator, "_execute", AsyncMock()) as execute:
            first = await operator.delegate(ctx, "Fixed work", {}, [], task_type="unowned_task")
            second = await operator.delegate(ctx, "Fixed work", {}, [], task_type="unowned_task")
        execute.assert_not_awaited()
        assert first["data"]["run_id"] == second["data"]["run_id"]
        with student.factory() as db:
            runs = db.scalars(select(ExecutionRun)).all()
            jobs = db.scalars(select(BackgroundJob)).all()
            assert len(runs) == len(jobs) == 1
            assert jobs[0].job_type == "operator.run"
            assert jobs[0].payload == {"run_id": runs[0].id}
            assert jobs[0].idempotency_key == f"operator:{runs[0].id}:resume:0"
            assert jobs[0].status == "pending"


@pytest.mark.asyncio
async def test_enqueue_failure_does_not_leave_an_unscheduled_run():
    with StudentSession() as student:
        ctx = ToolContext(student.workspace_id, "pai", None)
        with patch.object(operator, "is_available", return_value=True), \
             patch("app.runtime.task_runtime.enqueue", side_effect=RuntimeError("queue unavailable")):
            with pytest.raises(RuntimeError):
                await operator.delegate(ctx, "Fixed work", {}, [])
        with student.factory() as db:
            assert db.scalars(select(ExecutionRun)).all() == []
            assert db.scalars(select(BackgroundJob)).all() == []


@pytest.mark.asyncio
async def test_operator_job_survives_claiming_worker_crash_and_restart():
    from app.jobs.worker import _process_one
    with StudentSession() as student:
        with patch.object(operator, "is_available", return_value=True):
            result = await operator.delegate(ToolContext(student.workspace_id, "pai", None), "Work", {}, [])
        run_id = result["data"]["run_id"]
        with student.factory() as db:
            job = BackgroundJobService(db).claim(worker_id="crashed-worker")[0]
            job_id = job.id
            job.locked_at = datetime.now(timezone.utc) - timedelta(hours=1)
            run = db.get(ExecutionRun, run_id)
            run.status = "executing"
            db.commit()
        # Fresh session/process has only persisted rows, no in-process task state.
        with student.factory() as restarted_db:
            queue = BackgroundJobService(restarted_db)
            assert queue.reclaim_stale() == 1
            claimed = queue.claim(worker_id="restarted-worker")
            assert [job.id for job in claimed] == [job_id]
            assert claimed[0].attempts == 2
        async def complete(run_id, *args, **kwargs):
            with student.factory() as db:
                run = db.get(ExecutionRun, run_id)
                run.status = "completed"; db.commit()
        with patch.object(operator, "_execute", AsyncMock(side_effect=complete)) as execute:
            assert await _process_one(job_id, "restarted-worker")
        execute.assert_awaited_once()
        with student.factory() as db:
            assert db.get(ExecutionRun, run_id).status == "completed"
            assert db.get(BackgroundJob, job_id).status == "succeeded"


@pytest.mark.asyncio
async def test_resume_enqueues_new_generation_same_run_and_old_job_is_superseded():
    with StudentSession() as student:
        with patch.object(operator, "is_available", return_value=True):
            result = await operator.delegate(ToolContext(student.workspace_id, "pai", None), "Work", {}, [])
        run_id = result["data"]["run_id"]
        with student.factory() as db:
            run = db.get(ExecutionRun, run_id)
            run.status = "needs_user_action"
            run.pending_action = {"kind": "text", "prompt": "Detail"}
            db.commit()
        with patch.object(operator, "_execute", AsyncMock()) as execute:
            resumed = await operator.resume(ToolContext(student.workspace_id, "pai", None), run_id, {"text": "Detail"})
            assert resumed["data"]["run_id"] == run_id
            execute.assert_not_awaited()
            with student.factory() as db:
                jobs = db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at)).all()
                assert len(jobs) == 2
                old = next(job for job in jobs if job.idempotency_key.endswith(":0"))
                latest = next(job for job in jobs if job.idempotency_key.endswith(":1"))
                assert (await dispatch(old, db))["status"] == "superseded"
                execute.assert_not_awaited()
                await dispatch(latest, db)
                assert execute.await_args.kwargs["resume_payload"] == {"text": "Detail"}
        with student.factory() as db:
            assert db.get(ExecutionRun, run_id).resume_input["resume_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "needs_user_action"])
async def test_redelivered_operator_job_does_not_restart_terminal_or_paused_run(status):
    with StudentSession() as student:
        with patch.object(operator, "is_available", return_value=True):
            result = await operator.delegate(ToolContext(student.workspace_id, "pai", None), "Work", {}, [])
        with student.factory() as db:
            run = db.get(ExecutionRun, result["data"]["run_id"])
            run.status = status; db.commit()
            job = db.scalar(select(BackgroundJob))
            with patch.object(operator, "_execute", AsyncMock()) as execute:
                assert (await dispatch(job, db))["status"] == status
                execute.assert_not_awaited()
