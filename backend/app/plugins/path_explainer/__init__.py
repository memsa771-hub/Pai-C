"""Stage G workflow owner; no generic agent fallback."""
from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy


async def explain(context, payload):
    from app.pai_c.paths.explain import explain as run
    return await run(context, payload)


def get_capabilities():
    return [CapabilityContract(id="path.explain", version="1.0.0", name="Path explanation",
        description="Explain a selected direction before considering institutions",
        input_schema={"type": "object", "properties": {"brief": {"type": "object"}}, "required": ["brief"]},
        output_schema={"type": "object", "properties": {"path": {"type": "object"}, "facts": {"type": "array"}}, "required": ["path", "facts"]},
        handler=explain, owns_task_types=frozenset({"path_explain"}),
        fallback_policy=FallbackPolicy.FORBIDDEN, risk=CapabilityRisk.READ,
        required_tools=frozenset({"web.search", "web.fetch"}), permissions=frozenset({"web.read"}),
        timeout_seconds=300)]
