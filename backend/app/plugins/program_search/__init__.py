"""Explicit path-scoped program research workflow."""
from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy


async def search(context, payload):
    from app.pai_c.paths.programs import search as run
    return await run(context, payload)


def get_capabilities():
    return [CapabilityContract(id='program.search', version='1.0.0', name='Where to study',
        description='Research programs only after explicit path exploration',
        input_schema={'type':'object','properties':{'brief':{'type':'object'}},'required':['brief']},
        output_schema={'type':'object','properties':{'programs':{'type':'array'},'missing':{'type':'array'}},'required':['programs','missing']},
        handler=search, owns_task_types=frozenset({'program_search'}),
        uses_capabilities=frozenset({'program.discover','program.research'}),
        fallback_policy=FallbackPolicy.FORBIDDEN, risk=CapabilityRisk.READ,
        permissions=frozenset({'web.read'}), required_tools=frozenset(), timeout_seconds=300)]
