import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.capabilities as capability_module
from app.capabilities import CapabilityContract, CapabilityRegistry, CapabilityRouter, FallbackPolicy
from app.capabilities.context import CapabilityExecutionContext
from app.capabilities.execution_policy import resolve_run_policy
from app.capabilities.manifest import CapabilitySchemaError
from app.capabilities.permissions import OPERATOR_PLATFORM_PERMISSIONS
from app.capabilities.tool_broker import CapabilityToolBroker, CapabilityToolUnavailable
from app.models import ExecutionRun
from app.services import operator
from app.tools import AUDIENCE_OPERATOR, ToolContext, ToolDefinition, ToolExecutor, ToolRegistry, ToolRisk
from scripts.counselor_eval_support import StudentSession


async def _handler(context, payload):
    return {"result": payload}


def contract(*, capability_id="example.owner", task_type="owned_task",
             fallback=FallbackPolicy.FORBIDDEN, handler=_handler, **changes):
    values = dict(
        id=capability_id, version="1.0.0", name="Owner", description="Owns a test task.",
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        handler=handler, owns_task_types=frozenset({task_type}), fallback_policy=fallback,
    )
    values.update(changes)
    return CapabilityContract(**values)


def test_task_owner_resolution_duplicate_rejection_and_per_run_surface():
    registry = CapabilityRegistry()
    owner = registry.register(contract())
    assert registry.owner_for_task_type("owned_task") is owner
    assert CapabilityRouter(registry).resolve_task("owned_task") is owner
    with pytest.raises(ValueError, match="Duplicate task ownership"):
        registry.register(contract(capability_id="example.other"))

    available = frozenset({"capability.invoke", "web.search", "web.fetch"})
    owned = resolve_run_policy(registry, "owned_task")
    assert owned.allowed_tools(available) == frozenset({"capability.invoke"})
    assert resolve_run_policy(registry, "unowned_task").allowed_tools(available) == available


@pytest.mark.asyncio
async def test_task_type_is_persisted_by_delegation():
    from app.capabilities import get_capability_registry
    registry = CapabilityRegistry()
    registry.register(get_capability_registry().get("operator.run"))
    registry.register(contract())
    with StudentSession() as student:
        ctx = ToolContext(student.workspace_id, "pai", object(), conversation="pai-counselor")
        with patch.object(capability_module, "_registry", registry), \
                patch.object(operator, "is_available", return_value=True), \
                patch.object(operator, "_execute", AsyncMock()):
            result = await operator.delegate(
                ctx, "Do the owned work", {"capability_input": {}}, None, "discovery", "owned_task",
            )
            await asyncio.sleep(0)
        with student.factory() as db:
            run = db.get(ExecutionRun, result["data"]["run_id"])
            assert run.task_type == "owned_task"
            assert operator.serialize_run(run)["task_type"] == "owned_task"


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type,constraints", [
    ("unowned_task", {"capability_input": {}}), ("owned_task", {}),
])
async def test_delegation_refuses_work_no_capability_owns(task_type, constraints):
    registry = CapabilityRegistry()
    registry.register(contract())
    with StudentSession() as student:
        ctx = ToolContext(student.workspace_id, "pai", object(), conversation="pai-counselor")
        with patch.object(capability_module, "_registry", registry), \
                patch.object(operator, "is_available", return_value=True):
            result = await operator.delegate(ctx, "Work", constraints, None, None, task_type)
        assert result["ok"] is False and result["error"]["code"] == "unsupported_task"
        with student.factory() as db:
            assert db.query(ExecutionRun).count() == 0


@pytest.mark.asyncio
async def test_tool_broker_allows_declared_tool_blocks_undeclared_and_uses_policy():
    calls = []

    async def search(ctx, args):
        calls.append(args)
        return {"items": [args["query"]]}

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        "web.search", "Search", {"type": "object", "properties": {"query": {"type": "string"}},
                                  "required": ["query"], "additionalProperties": False},
        "web", ToolRisk.READ, search, audiences=frozenset({AUDIENCE_OPERATOR}),
    ))
    registry.register(ToolDefinition(
        "danger.act", "Sensitive", {"type": "object", "properties": {}, "additionalProperties": False},
        "danger", ToolRisk.SENSITIVE, search, audiences=frozenset({AUDIENCE_OPERATOR}),
    ))
    host = ToolContext("w", "pai-operator", object(), audience=AUDIENCE_OPERATOR,
                       allowed_tools=frozenset({"web.search", "danger.act"}), granted_capabilities=frozenset())
    declared = contract(required_tools=frozenset({"web.search"}), permissions=frozenset({"web.read"}))
    broker = CapabilityToolBroker(
        contract=declared, registry=registry, executor=ToolExecutor(registry),
        host_context=host, platform_permissions=OPERATOR_PLATFORM_PERMISSIONS,
    )
    assert (await broker.invoke("web.search", {"query": "AI"}))["ok"]
    assert calls == [{"query": "AI"}]
    with pytest.raises(CapabilityToolUnavailable, match="undeclared"):
        await broker.invoke("danger.act", {})

    sensitive = contract(required_tools=frozenset({"danger.act"}), permissions=frozenset({"danger.act"}))
    sensitive_broker = CapabilityToolBroker(
        contract=sensitive, registry=registry, executor=ToolExecutor(registry),
        host_context=host, platform_permissions=frozenset({"danger.act"}),
    )
    denied = await sensitive_broker.invoke("danger.act", {})
    assert denied["error"]["code"] == "tool_not_allowed"

    # Even a guessed raw call is denied by the same ToolPolicy when an owned
    # run's host-selected surface excludes it.
    locked_context = ToolContext(
        "w", "pai-operator", object(), audience=AUDIENCE_OPERATOR,
        allowed_tools=frozenset({"capability.invoke"}), granted_capabilities=frozenset(),
    )
    bypass = await ToolExecutor(registry).execute("web.search", {"query": "bypass"}, locked_context)
    assert bypass["error"]["code"] == "tool_not_allowed"
    assert calls == [{"query": "AI"}]


@pytest.mark.asyncio
async def test_discovery_and_recursive_input_output_validation():
    nested_input = {
        "type": "object", "additionalProperties": False, "required": ["student"],
        "properties": {"student": {"type": "object", "required": ["scores"],
            "additionalProperties": False, "properties": {"scores": {"type": "array", "minItems": 1,
                "items": {"type": "integer", "minimum": 0, "maximum": 10}}}}},
    }
    nested_output = {"type": "object", "required": ["result"], "additionalProperties": False,
                     "properties": {"result": {"type": "object", "required": ["ok"],
                         "properties": {"ok": {"type": "boolean"}}, "additionalProperties": False}}}

    async def bad_output(context, payload):
        return {"result": {"ok": "yes"}}

    registry = CapabilityRegistry()
    item = registry.register(contract(input_schema=nested_input, output_schema=nested_output,
                                      handler=bad_output, permissions=frozenset()))
    context = CapabilityExecutionContext("w", {}, {}, frozenset(), frozenset())
    with pytest.raises(CapabilitySchemaError):
        await CapabilityRouter(registry).execute(item.id, {"student": {"scores": [11]}}, context)
    with pytest.raises(CapabilitySchemaError):
        await CapabilityRouter(registry).execute(item.id, {"student": {"scores": [8]}}, context)



async def _run_owned(student, fallback, capability_result):
    registry = CapabilityRegistry()
    registry.register(contract(fallback=fallback))
    with student.factory() as db:
        run = ExecutionRun(workspace_id=student.workspace_id, requested_by="openagents:pai",
                           objective="Owned objective", task_type="owned_task",
                           constraints={"capability_input": {}}, context_refs=[])
        db.add(run)
        db.commit()
        run_id = run.id
    executor = SimpleNamespace(execute=AsyncMock(return_value=capability_result))
    with patch.object(capability_module, "_registry", registry), \
            patch("app.tools.get_tool_executor", return_value=executor), \
            patch.object(operator, "_publish_run_updated"), \
            patch.object(operator, "_post_result", AsyncMock()):
        await operator._execute(run_id, student.workspace_id, None, "Owned objective", {}, [], None)
    with student.factory() as db:
        return db.get(ExecutionRun, run_id), executor


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", list(FallbackPolicy))
async def test_owned_failure_is_failed_whatever_the_fallback_policy(fallback):
    failure = {"ok": False, "error": {"code": "capability_failed", "message": "provider down"}}
    with StudentSession() as student:
        run, executor = await _run_owned(student, fallback, failure)
        assert run.status == "failed"
        assert executor.execute.await_count == 1
        assert executor.execute.await_args.args[0] == "capability.invoke"


@pytest.mark.asyncio
async def test_capability_approval_signal_immediately_pauses_same_run():
    signal = {"ok": False, "error": {"code": "approval_required", "message": "approve",
              "pending_action": {"kind": "approval", "title": "Approve", "prompt": "Approve?",
                                 "reason": "Sensitive", "options": ["approve", "decline"],
                                 "required": True, "purpose": "capability_invoke",
                                 "capability_id": "example.owner"}}}
    with StudentSession() as student:
        paused, executor = await _run_owned(student, FallbackPolicy.FORBIDDEN, signal)
        assert paused.status == "needs_user_action"
        assert paused.completed_at is None
        assert paused.pending_action["purpose"] == "capability_invoke"
        assert len(paused.tool_calls) == 1
        assert executor.execute.await_count == 1
