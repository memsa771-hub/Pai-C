"""Internal job contracts; handlers and queue semantics stay with their owners."""
from .contract import CapabilityContract


def load_system_capabilities(registry):
    from app.pai_c.deep import analysis, mirror
    from app.pai_c import sessions
    from app.pai_c.roadmaps import jobs as roadmaps
    from app.memory import handlers as memory
    from app.research import jobs as research
    from app.documents import handlers as documents
    from app.services.operator import run_operator_job

    string = {"type": "string"}
    array = {"type": "array"}
    entries = (
        (sessions.JOB_SWEEP, sessions.sweep_job, {}),
        (analysis.JOB_ANALYZE, analysis.analyze_job, {"user_event_id": string, "assistant_event_id": string, "source_timestamp": {"type": "number"}}),
        (mirror.JOB_MIRROR, mirror.mirror_job, {"notebook_version": {"type": "integer"}, "journey_id": string, "source_event_id": string, "channel": string, "mirror_attempt": {"type": "integer"}}),
        (mirror.JOB_RESEARCH, mirror.confirmed_research_job, {"journey_id": string, "version": {"type": "integer"}}),
        (memory.JOB_EXTRACT, memory.extract_memory, {"source_type": string, "channel": string, "user_event_id": string, "assistant_event_id": string, "agent_name": string, "profile_captured": {"type": "boolean"}, "candidates": array}),
        (memory.JOB_RECONCILE, memory.reconcile_memory, {"candidate_ids": array}),
        (memory.JOB_EMBED, memory.embed_memory, {"memory_ids": array, "episode_ids": array}),
        (memory.JOB_UNINDEX, memory.unindex_memory, {"ids": array}),
        (memory.JOB_REINDEX, memory.reindex_workspace, {"purge_first": {"type": "boolean"}, "batch_size": {"type": "integer"}}),
        (research.JOB_RESUME_RESEARCH, research.resume_research, {"candidate_id": string}),
        (research.JOB_REFRESH_RESEARCH, research.refresh_stale_research, {"requirement_id": string}),
        (documents.JOB_DOCUMENT_PARSE, documents.parse_document_job, {"file_id": string}),
        (documents.JOB_DOCUMENT_EXTRACT, documents.extract_document_job, {"file_id": string}),
        (documents.JOB_DOCUMENT_INDEX, documents.index_document_job, {"file_id": string}),
        (documents.JOB_DOCUMENT_UNINDEX, documents.unindex_document_job, {"file_ids": array}),
        (documents.JOB_DOCUMENT_NOTIFY, documents.notify_document_job, {"file_id": string}),
    )
    registry.register(CapabilityContract(
        id="operator.run", version="1.0.0", name="Operator run",
        description="Internal durable Operator workflow or agent run", kind="system",
        input_schema={"type": "object", "properties": {"run_id": string}, "required": ["run_id"]},
        output_schema={"type": "object"}, handler=run_operator_job,
    ))
    registry.register(CapabilityContract(
        id=roadmaps.JOB_MARK_STALE, version="1.0.0", name=roadmaps.JOB_MARK_STALE,
        description="Internal durable roadmap invalidation", kind="system",
        input_schema={"type": "object", "properties": {"workspace_id": string, "reason": string},
                      "required": ["workspace_id", "reason"]},
        output_schema={"type": "object", "properties": {"marked_stale": {"type": "integer"}},
                       "required": ["marked_stale"]}, handler=roadmaps.mark_stale_job,
    ))
    for job_type, handler, properties in entries:
        registry.register(CapabilityContract(
            id=job_type, version="1.0.0", name=job_type,
            description=f"Internal durable job: {job_type}", kind="system",
            input_schema={"type": "object", "properties": properties},
            output_schema={"type": "object"}, handler=handler,
        ))
