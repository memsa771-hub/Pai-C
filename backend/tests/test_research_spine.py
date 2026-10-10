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


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["mirror_confirmed", "student_route", "route_retry", "stale_refresh", "student_answer"])
async def test_each_research_trigger_uses_gateway_and_persists_attribution(trigger):
    from app.research.gateway import request_research
    from app.models import Roadmap
    from tests.test_counselor_deep_lean import research_journey
    from app.memory.permissions import capabilities_for_agent
    from app.tools import AUDIENCE_COUNSELOR
    with StudentSession() as student, student.factory() as db:
        journey = research_journey(student, db, confirmed=True)
        ctx = ToolContext(student.workspace_id, "pai", None, conversation="pai-counselor",
                          allowed_tools=frozenset({"operator.delegate"}), audience=AUDIENCE_COUNSELOR,
                          granted_capabilities=capabilities_for_agent("pai"))
        kwargs = {}
        kind = "roadmap_light"
        if trigger in {"student_route", "route_retry", "stale_refresh"}:
            route = Roadmap(workspace_id=student.workspace_id, journey_id=journey.id,
                            origin="student_added", title="Student route", generation_status="stale")
            db.add(route); db.flush()
            if trigger != "stale_refresh": kwargs["roadmap_id"] = route.id
            if trigger != "student_route": kwargs["refresh_key"] = "source-change"
            if trigger == "stale_refresh": kind = "stale_refresh"
            db.commit()
        with patch.object(operator, "is_available", return_value=True):
            result = await request_research(kind, student.workspace_id, db=db, journey=journey,
                                            tool_context=ctx, trigger=trigger, **kwargs)
            duplicate = await request_research(kind, student.workspace_id, db=db, journey=journey,
                                               tool_context=ctx, trigger=trigger, **kwargs)
        assert result["ok"] and duplicate["data"]["run_id"] == result["data"]["run_id"]
        db.expire_all()
        run = db.get(ExecutionRun, result["data"]["run_id"])
        assert run.constraints["trigger"] == trigger
        assert run.task_type == "roadmap_research"
        assert db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "operator.run")).all()[0].payload == {"run_id": run.id}
        assert len(db.scalars(select(ExecutionRun)).all()) == 1


@pytest.mark.asyncio
async def test_student_answer_gateway_resumes_same_run_records_trigger_and_queues_once():
    from app.research.gateway import request_research
    from app.models import MemoryCandidate
    now = datetime.now(timezone.utc)
    with StudentSession() as student, student.factory() as db:
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                           objective="Research", task_type="roadmap_research", created_at=now,
                           status="needs_user_action", constraints={"trigger": "mirror_confirmed"},
                           pending_action={"kind": "fact", "items": [{"field": "goal.details.route"}]})
        candidate = MemoryCandidate(workspace_id=student.workspace_id, candidate_type="student_record",
                                    operation="upsert", key="goal", status="accepted", reconciled_at=now)
        db.add_all([run, candidate]); db.commit()
        ctx = ToolContext(student.workspace_id, "pai-operator", None)
        result = await request_research("roadmap_light", student.workspace_id, db=db, journey=None,
            tool_context=ctx, trigger="student_answer", resume_run_id=run.id,
            resume_action={"candidate_id": candidate.id})
        assert result["data"]["resumed"] and result["data"]["run_id"] == run.id
        db.expire_all()
        assert db.get(ExecutionRun, run.id).constraints["trigger"] == "student_answer"
        assert db.get(ExecutionRun, run.id).resume_input["resume_count"] == 1
        assert len(db.scalars(select(BackgroundJob)).all()) == 1
        assert await request_research("roadmap_light", student.workspace_id, db=db, journey=None,
            tool_context=ctx, trigger="student_answer", resume_run_id=run.id,
            resume_action={"candidate_id": candidate.id}) is None


@pytest.mark.asyncio
async def test_student_answer_gateway_cannot_resume_another_workspace():
    from app.research.gateway import request_research
    with StudentSession() as student, student.factory() as db:
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                           objective="Research", status="needs_user_action", constraints={},
                           pending_action={"kind": "text", "prompt": "Detail"})
        db.add(run); db.commit()
        result = await request_research("roadmap_light", "other-workspace", db=db, journey=None,
            tool_context=ToolContext("other-workspace", "pai-operator", None), trigger="student_answer",
            resume_run_id=run.id, resume_action={"text": "Detail"})
        assert result is None
        db.refresh(run)
        assert run.status == "needs_user_action" and run.constraints == {}


def test_research_and_operator_architecture_boundaries():
    import ast
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app"
    research_delegate_sites = []
    for path in app.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(app).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("app.pai_c.research_gateway", "app.pai_c.light_research")), relative
                if relative.startswith("memory/"):
                    assert not node.module.startswith("app.research"), relative
            if isinstance(node, ast.Import) and relative.startswith("memory/"):
                assert not any(alias.name.startswith("app.research") for alias in node.names), relative
            if isinstance(node, ast.Call):
                if relative == "services/operator.py" and isinstance(node.func, ast.Attribute):
                    assert node.func.attr != "create_task", relative
                if isinstance(node.func, ast.Attribute) and node.func.attr == "execute" and node.args:
                    if isinstance(node.args[0], ast.Constant) and node.args[0].value == "operator.delegate":
                        research_delegate_sites.append(relative)
    assert research_delegate_sites == ["research/gateway.py"]
    assert not (app / "pai_c/research_gateway.py").exists()
    assert not (app / "pai_c/light_research.py").exists()
    from app.capabilities import get_capability_registry
    registry = get_capability_registry()
    assert registry.get("operator.run").kind == "system"
    assert registry.get("agent.run") is None
    assert registry.get("research.run") is None
    assert registry.get("memory.resume_research").handler.__module__ == "app.research.jobs"
    assert registry.get("research.refresh_stale").handler.__module__ == "app.research.jobs"
