import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import app.capabilities as capability_module
from app.capabilities import CapabilityRegistry, CapabilityContract
from app.capabilities.permissions import OPERATOR_PLATFORM_PERMISSIONS
from app.models import ExecutionRun
from app.services import operator
from app.tools import ToolContext
from scripts.counselor_eval_support import StudentSession


def owner(handler, **changes):
    fields = dict(id="example.workflow", version="1.0.0", name="Workflow", description="Test workflow",
                  input_schema={"type": "object"}, output_schema={"type": "object"},
                  handler=handler, owns_task_types={"workflow_task"})
    fields.update(changes)
    return CapabilityContract(**fields)


def create_run(student, task_type="workflow_task", capability_input=None):
    with student.factory() as db:
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                           objective="Do the fixed work", task_type=task_type,
                           constraints={"capability_input": capability_input if capability_input is not None else {"item": "value"}},
                           context_refs=[], channel_target="channel/pai-counselor")
        db.add(run); db.commit()
        return run.id


@pytest.mark.asyncio
async def test_workflow_checked_invocation_zero_operator_calls_same_run_and_result():
    seen = []
    async def handler(context, payload):
        seen.append((context, payload))
        return {"summary": "Done", "artifacts": [{"id": "artifact"}], "pending_action": None}
    hook = Mock()
    registry = workflow_registry(); registry.register(owner(handler, run_status_hook=hook))
    with StudentSession() as student:
        run_id = create_run(student)
        with patch.object(capability_module, "_registry", registry), \
             patch.object(operator, "chat_completion", AsyncMock(side_effect=AssertionError("model called"))) as plain, \
             patch.object(operator, "chat_completion_tools", AsyncMock(side_effect=AssertionError("model called"))) as tools, \
             patch.object(operator, "_resolve_memory_context", side_effect=AssertionError("generic context read")), \
             patch.object(operator, "_post_result", AsyncMock()) as post, \
             patch.object(operator, "_publish_run_updated"):
            await operator._execute(run_id, student.workspace_id, object(), "Do the fixed work", {}, [], None)
        plain.assert_not_awaited(); tools.assert_not_awaited()
        assert len(seen) == 1 and seen[0][1] == {"item": "value"}
        assert seen[0][0].workspace_id == student.workspace_id
        assert seen[0][0].permissions == OPERATOR_PLATFORM_PERMISSIONS
        assert seen[0][0].tools is not None
        assert hook.call_count == 2
        with student.factory() as db:
            run = db.get(ExecutionRun, run_id)
            assert run.status == "completed" and run.completed_at
            assert run.result["summary"] == "Done"
            assert run.result["capability_result"]["artifacts"] == [{"id": "artifact"}]
            assert set(run.result) == {"summary", "final_message", "plan", "tool_calls", "observations", "artifact_id", "capability_result"}
            assert run.tool_calls[0]["tool"] == "capability.invoke"
            assert run.completed_steps == ["Do the fixed work"]
        assert post.await_args.args[3:5] == (run_id, "completed")


@pytest.mark.asyncio
async def test_workflow_approval_resume_uses_same_row_and_permission_path():
    handler = AsyncMock(return_value={"summary": "Approved work done"})
    registry = workflow_registry(); registry.register(owner(handler, approval="always"))
    with StudentSession() as student:
        run_id = create_run(student)
        with patch.object(capability_module, "_registry", registry), \
             patch.object(operator, "chat_completion", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "chat_completion_tools", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "_post_result", AsyncMock()), \
             patch.object(operator, "_publish_run_updated"):
            await operator._execute(run_id, student.workspace_id, object(), "Work", {}, [], None)
            handler.assert_not_awaited()
            with student.factory() as db:
                run = db.get(ExecutionRun, run_id)
                assert run.status == "needs_user_action" and run.completed_at is None
                assert run.pending_action["purpose"] == "capability_invoke"
                assert run.pending_action["capability_id"] == "example.workflow"
            resumed = await operator.resume(ToolContext(student.workspace_id, "pai", object()), run_id, {"approved": True})
            assert resumed["data"]["run_id"] == run_id and resumed["data"]["resumed"] is True
            await dispatch_queued(student)
            handler.assert_awaited_once()
            with student.factory() as db:
                run = db.get(ExecutionRun, run_id)
                assert run.status == "completed" and run.pending_action is None
                assert run.resume_input["response"]["approved"] is True
                assert len(run.tool_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", [
    {"kind": "text", "title": "Detail", "prompt": "Provide detail", "required": True},
    {"type": "need_from_student", "items": [{"field": "education.level", "reason": "Need level"}]},
])
async def test_workflow_capability_pending_action_pauses_without_model(pending):
    registry = workflow_registry(); registry.register(owner(AsyncMock(return_value={"pending_action": pending})))
    with StudentSession() as student:
        run_id = create_run(student)
        with patch.object(capability_module, "_registry", registry), \
             patch.object(operator, "chat_completion", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "chat_completion_tools", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "_post_result", AsyncMock()), patch.object(operator, "_publish_run_updated"):
            await operator._execute(run_id, student.workspace_id, object(), "Work", {}, [], None)
        with student.factory() as db:
            run = db.get(ExecutionRun, run_id)
            assert run.status == "needs_user_action" and run.completed_at is None
            if pending.get("type") == "need_from_student":
                assert run.pending_action["kind"] == "fact"
                assert run.pending_action["items"] == pending["items"]
            else:
                assert run.pending_action == pending


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{}, {"permissions": {"unknown.permission"}}, {"input_schema": {"type": "object", "required": ["missing"]}}])
async def test_workflow_error_is_failed_no_generic_fallback(changes):
    handler = AsyncMock(side_effect=ValueError("capability error"))
    registry = workflow_registry(); registry.register(owner(handler, **changes))
    with StudentSession() as student:
        run_id = create_run(student)
        with patch.object(capability_module, "_registry", registry), \
             patch.object(operator, "chat_completion", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "chat_completion_tools", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "_post_result", AsyncMock()) as post, patch.object(operator, "_publish_run_updated"):
            await operator._execute(run_id, student.workspace_id, object(), "Work", {}, [], None)
        with student.factory() as db:
            run = db.get(ExecutionRun, run_id)
            assert run.status == "failed" and run.error and run.completed_at
            assert run.tool_calls[0]["ok"] is False
            assert run.pending_action is None
        assert post.await_args.args[4] == "failed"


@pytest.mark.asyncio
async def test_operator_run_dispatch_calls_policy_selected_execution_and_checks_workspace():
    from app.runtime.task_runtime import run as dispatch
    from app.capabilities import get_capability_registry
    with StudentSession() as student, student.factory() as db:
        run_id = create_run(student, task_type="unowned_task")
        job = SimpleNamespace(job_type="operator.run", workspace_id=student.workspace_id, payload={"run_id": run_id})
        with patch.object(operator, "_execute", AsyncMock()) as loop:
            await dispatch(job, db)
            assert "_agent_only" not in loop.await_args.kwargs
            assert loop.await_args.args[0] == run_id
        job.workspace_id = "other-workspace"
        with pytest.raises(LookupError):
            await dispatch(job, db)
        assert get_capability_registry().get("operator.run").kind == "system"


@pytest.mark.asyncio
async def test_roadmap_research_installed_owner_uses_workflow_without_operator_phases():
    from app.capabilities import get_capability_registry
    from app.journey import JourneyService
    installed = get_capability_registry()
    contract = installed.owner_for_task_type("roadmap_research")
    handler = AsyncMock(return_value={"roadmaps": [], "unconfirmed": ["Undecisive fact"],
                                     "pending_action": None, "mirror_version": 1})
    registry = workflow_registry()
    registry.register(replace(contract, handler=handler))
    with StudentSession() as student:
        with student.factory() as db:
            journeys = JourneyService(db)
            journey = journeys.ensure_counselor(student.workspace_id)
            for stage in ("FOUNDATION", "DIRECTION", "MIRROR", "RESEARCHING"):
                journeys.set_counselor_stage(student.workspace_id, journey.id, stage, actor="test")
            db.commit()
        run_id = create_run(student, task_type="roadmap_research", capability_input={"brief": {"mirror_version": 1}})
        with patch.object(capability_module, "_registry", registry), \
             patch.object(operator, "chat_completion", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "chat_completion_tools", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "_post_result", AsyncMock()), patch.object(operator, "_publish_run_updated"):
            await operator._execute(run_id, student.workspace_id, object(), "Work", {}, [], None)
        handler.assert_awaited_once()
        assert handler.await_args.args[1] == {"brief": {"mirror_version": 1}}
        with student.factory() as db:
            assert db.get(ExecutionRun, run_id).status == "completed"
            assert JourneyService(db).get(student.workspace_id, journey.id).current_stage == "ASSESSING"


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [False, True])
async def test_no_owner_or_no_fixed_input_keeps_existing_model_phases(owned):
    registry = workflow_registry()
    handler = AsyncMock()
    if owned:
        registry.register(owner(handler))
    with StudentSession() as student:
        run_id = create_run(student, task_type="workflow_task" if owned else "unowned_task")
        with student.factory() as db:
            run = db.get(ExecutionRun, run_id)
            run.constraints = {}; db.commit()
        phases = AsyncMock(side_effect=["Understood", '[{"id":"work","title":"Work"}]',
                           '{"status":"completed","summary":"Done","completed_step_ids":["work"]}'])
        execute = AsyncMock(side_effect=[
            {"role": "assistant", "tool_calls": [{"id": "call", "type": "function", "function": {
                "name": "capability__invoke" if owned else "web__search",
                "arguments": '{"capability_id":"example.workflow","input":{}}' if owned else '{"query":"example"}'}}]},
            {"role": "assistant", "content": "Done"},
        ])
        with patch.object(capability_module, "_registry", registry), \
             patch.object(operator, "chat_completion", phases), \
             patch.object(operator, "chat_completion_tools", execute), \
             patch.object(operator, "_resolve_memory_context", return_value=""), \
             patch("app.services.pai.workspace_state_summary", AsyncMock(return_value="")), \
             patch("app.tools.get_tool_executor", return_value=SimpleNamespace(execute=AsyncMock(return_value={"ok": True, "data": {"result": {}}}))), \
             patch.object(operator, "_post_result", AsyncMock()), patch.object(operator, "_publish_run_updated"):
            await operator._execute(run_id, student.workspace_id, object(), "Work", {}, [], None)
        assert phases.await_count == 3 and execute.await_count == 2
        handler.assert_not_awaited()
        with student.factory() as db:
            assert db.get(ExecutionRun, run_id).status == "completed"


@pytest.mark.asyncio
async def test_workflow_text_pending_resume_keeps_same_input_and_row():
    handler = AsyncMock(side_effect=[
        {"pending_action": {"kind": "text", "title": "Detail", "prompt": "Provide detail", "required": True}},
        {"summary": "Finished"},
    ])
    registry = workflow_registry(); registry.register(owner(handler))
    with StudentSession() as student:
        run_id = create_run(student)
        with patch.object(capability_module, "_registry", registry), \
             patch.object(operator, "chat_completion", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "chat_completion_tools", AsyncMock(side_effect=AssertionError("model called"))), \
             patch.object(operator, "_post_result", AsyncMock()), patch.object(operator, "_publish_run_updated"):
            await operator._execute(run_id, student.workspace_id, object(), "Work", {}, [], None)
            result = await operator.resume(ToolContext(student.workspace_id, "pai", object()), run_id, {"text": "Detail"})
            assert result["data"]["resumed"]
            await dispatch_queued(student)
        assert handler.await_count == 2
        assert handler.await_args_list[0].args[1] == handler.await_args_list[1].args[1]
        with student.factory() as db:
            run = db.get(ExecutionRun, run_id)
            assert run.status == "completed" and run.resume_input["response"] == {"text": "Detail"}


async def dispatch_queued(student):
    from sqlalchemy import select
    from app.models import BackgroundJob
    from app.runtime.task_runtime import run
    with student.factory() as db:
        jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "operator.run",
                         BackgroundJob.status == "pending")).all()
        for job in jobs:
            await run(job, db)
            job.status = "succeeded"; db.commit()


def workflow_registry():
    from app.capabilities import get_capability_registry
    registry = CapabilityRegistry()
    registry.register(get_capability_registry().get("operator.run"))
    return registry
