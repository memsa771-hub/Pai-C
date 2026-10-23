from app.tools.policy import ToolRisk
from app.tools.registry import AUDIENCE_COUNSELOR, AUDIENCE_OPERATOR, ToolDefinition
from . import capabilities, operator, web

# Shorthand for the audience combinations builtin tools actually use.
BOTH = frozenset({AUDIENCE_COUNSELOR, AUDIENCE_OPERATOR})
OPERATOR_ONLY = frozenset({AUDIENCE_OPERATOR})
COUNSELOR_ONLY = frozenset({AUDIENCE_COUNSELOR})


def obj(properties, required=()):
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return schema


def register_builtin_tools(registry):
    definitions = [
        # ---- Web research: called by capability workflows (through their
        # tool broker) and by the myth check. ----
        ToolDefinition("web.search", "Search the public web using the configured provider.", obj({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]), "web", ToolRisk.READ, web.search, audiences=BOTH),
        ToolDefinition("web.fetch", "Read a public URL through the workspace fetch and safety pipeline.", obj({"url": {"type": "string"}, "mode": {"type": "string", "enum": ["auto", "static", "render"]}, "max_chars": {"type": "integer"}}, ["url"]), "web", ToolRisk.READ, web.fetch, audiences=BOTH),
        ToolDefinition("web.institution_registry", "Resolve an institution's official website against the public ROR registry.", obj({"url": {"type": "string"}}, ["url"]), "web", ToolRisk.READ, web.institution_registry, audiences=OPERATOR_ONLY),

        # ---- Operator runs exactly one installed capability workflow. ----
        ToolDefinition(
            "capability.invoke",
            "Invoke an installed business capability by its manifest id. The host supplies only its declared student scopes, journey fields, permissions, and tools.",
            obj({"capability_id": {"type": "string"}, "input": {"type": "object", "additionalProperties": True}}, ["capability_id", "input"]),
            "capability", ToolRisk.WRITE, capabilities.invoke, audiences=OPERATOR_ONLY,
        ),

        # ---- The Counselor -> Operator boundary: research gateway handoff. ----
        ToolDefinition(
            "operator.delegate",
            "Queue background research as one installed capability workflow. "
            "task_type must be owned by an installed capability and "
            "constraints.capability_input carries its fixed input. Returns "
            "immediately with a run_id.",
            obj({
                "objective": {"type": "string"},
                "task_type": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,63}$", "description": "Task type owned by an installed capability, such as roadmap_research."},
                "constraints": {"type": "object", "additionalProperties": True},
                "context_refs": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string"},
            }, ["objective", "task_type"]),
            "operator", ToolRisk.WRITE, operator.delegate, audiences=COUNSELOR_ONLY,
        ),
    ]
    for definition in definitions:
        registry.register(definition)
