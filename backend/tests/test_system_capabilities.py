import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from app.capabilities import CapabilityContract, CapabilityRegistry, CapabilityRouter, get_capability_registry
from app.capabilities.router import CapabilityNotFound
from app.tools.builtin import capabilities

JOB_TYPES = (
    "counselor.analyze", "counselor.mirror", "counselor.mirror_research",
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
