import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from app.capabilities import CapabilityContract, CapabilityRegistry, CapabilityRouter, get_capability_registry
from app.capabilities.router import CapabilityNotFound
from app.tools.builtin import capabilities

JOB_TYPES = (
    "counselor.analyze", "counselor.mirror", "counselor.mirror_research", "roadmaps.mark_stale",
    "memory.extract", "memory.reconcile", "memory.embed", "memory.unindex",
    "memory.reindex", "memory.resume_research", "research.refresh_stale",
    "document.parse", "document.extract", "document.index", "document.unindex", "document.notify",
)

@pytest.mark.parametrize("job_type", JOB_TYPES)
def test_existing_job_is_a_system_capability(job_type):
    contract = get_capability_registry().get(job_type)
    assert contract.kind == "system"
    assert contract.input_schema["type"] == "object"
    assert not contract.owns_task_types
    assert contract not in get_capability_registry().all()
    with pytest.raises(CapabilityNotFound):
        CapabilityRouter(get_capability_registry()).resolve(job_type)

@pytest.mark.asyncio
async def test_systems_hidden_from_agent_list_describe_and_invoke():
    result = await capabilities.list_capabilities(None, {})
    assert all(item["id"] not in JOB_TYPES for item in result["data"]["capabilities"])
    for job_type in JOB_TYPES:
        assert (await capabilities.describe(None, {"capability_id": job_type}))["ok"] is False
        assert (await capabilities.invoke(SimpleNamespace(), {"capability_id": job_type, "input": {}}))["error"]["code"] == "capability_not_found"

@pytest.mark.parametrize("changes", [{"kind": "other"}, {"kind": "system", "owns_task_types": {"test_task"}}])
def test_invalid_system_contract_rejected(changes):
    with pytest.raises(ValueError):
        CapabilityRegistry().register(CapabilityContract(
            id="test.job", version="1.0.0", name="Job", description="Test",
            input_schema={"type": "object"}, output_schema={"type": "object"},
            handler=AsyncMock(), **changes,
        ))

@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", JOB_TYPES)
async def test_task_runtime_dispatches_existing_handler_signature(job_type):
    from dataclasses import replace
    from app.runtime.task_runtime import run
    original = get_capability_registry().get(job_type)
    handler = AsyncMock(return_value={"done": True})
    registry = CapabilityRegistry()
    registry.register(replace(original, handler=handler))
    payload = {"workspace_id": "workspace", "reason": "Profile changed"} if job_type == "roadmaps.mark_stale" else {}
    job, db = SimpleNamespace(job_type=job_type, payload=payload), object()
    assert await run(job, db, registry=registry) == {"done": True}
    handler.assert_awaited_once_with(job, db)

@pytest.mark.asyncio
async def test_task_runtime_rejects_invalid_payload_before_handler():
    from dataclasses import replace
    from app.runtime.task_runtime import run
    original = get_capability_registry().get("memory.embed")
    handler = AsyncMock()
    registry = CapabilityRegistry()
    registry.register(replace(original, handler=handler))
    with pytest.raises(ValueError):
        await run(SimpleNamespace(job_type="memory.embed", payload={"memory_ids": "bad"}), object(), registry=registry)
    handler.assert_not_awaited()

@pytest.mark.asyncio
async def test_job_registry_is_only_a_compatibility_facade():
    from app.jobs.service import JobHandlerRegistry, run_job
    registry = CapabilityRegistry()
    compat = JobHandlerRegistry(registry)
    handler = AsyncMock(return_value={"done": True})
    assert compat.register("example.job", handler) is handler
    assert registry.get("example.job").kind == "system"
    assert compat.registered() == ("example.job",)
    assert compat.handler_for("example.job") is handler
    job, db = SimpleNamespace(job_type="example.job", payload={}), object()
    assert await run_job(job, db, compat) == {"done": True}
    handler.assert_awaited_once_with(job, db)
    with pytest.raises(ValueError):
        compat.register("example.job", handler)


def test_task_runtime_enqueue_preserves_queue_idempotency_and_options():
    from app.runtime.task_runtime import enqueue
    from scripts.counselor_eval_support import StudentSession
    with StudentSession() as student, student.factory() as db:
        first = enqueue(db, "memory.embed", {"memory_ids": [], "episode_ids": None},
                        workspace_id=student.workspace_id, idempotency_key="runtime-test", priority=7, max_attempts=3)
        second = enqueue(db, "memory.embed", {}, workspace_id=student.workspace_id, idempotency_key="runtime-test")
        assert first.id == second.id
        assert first.priority == 7 and first.max_attempts == 3
        assert first.payload["episode_ids"] is None
        with pytest.raises(LookupError):
            enqueue(db, "missing.job", {})


def test_no_background_registrations_or_enqueue_outside_runtime():
    import ast
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app"
    for path in app.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "register" and isinstance(node.func.value, ast.Name):
                assert node.func.value.id != "job_handlers", str(path)
            if node.func.attr == "enqueue":
                assert path.relative_to(app).as_posix() == "runtime/task_runtime.py", str(path)


def test_every_enqueued_job_type_has_system_contract():
    import ast
    import importlib
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app"
    seen = set()
    for path in app.rglob("*.py"):
        if path.name == "task_runtime.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_name = "app." + ".".join(path.relative_to(app).with_suffix("").parts)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "enqueue":
                continue
            argument = next((item.value for item in node.keywords if item.arg == "job_type"), None)
            if argument is None:
                argument = node.args[1]
            if isinstance(argument, ast.Name):
                argument = getattr(importlib.import_module(module_name), argument.id, None)
                if argument is None:
                    # Function-local imported job constants retain their existing owner.
                    symbol = next(item.value for item in node.keywords if item.arg == "job_type").id
                    source = next(item for item in ast.walk(tree) if isinstance(item, ast.ImportFrom)
                                  and any(alias.name == symbol for alias in item.names))
                    argument = getattr(importlib.import_module(source.module), symbol)
            elif isinstance(argument, ast.Constant):
                argument = argument.value
            else:
                raise AssertionError(f"Unreviewed enqueue type in {path}")
            assert get_capability_registry().get(argument).kind == "system", str(path)
            seen.add(argument)
    assert seen == set(JOB_TYPES) | {"operator.run", "session.sweep", "session.summarize"}
