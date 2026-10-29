"""Internal job contracts; handlers and queue semantics stay with their owners."""
from .contract import CapabilityContract


def load_system_capabilities(registry):
    from app.pai_c.deep import analysis
    from app.pai_c.paths import analyzer as paths
    from app.pai_c import sessions, opening, myths, checkins, reliability
    from app.memory import handlers as memory
    from app.research import jobs as research
    from app.research import rules_refresh
    from app.pai_c.paths import field_research
    from app.documents import handlers as documents
    from app.services.operator import run_operator_job
    from app.pai_c.mirror import text_job as mirror_text
    from app.memory.reconciler import register_accept_hook

    # After Mirror-relevant Vault writes the reconciler moves the journey to
    # MIRROR when the card is ready and queues the Mirror text.
    register_accept_hook(mirror_text.after_accept)
    # A path-relevant Vault write queues the Path engine (reason vault).
    register_accept_hook(paths.after_accept)

    string = {"type": "string"}
    array = {"type": "array"}
    entries = (
        (reliability.JOB_HEALTH_ALERT, reliability.alert_job, {"summary": {"type": "object"}}),
        (checkins.JOB_CHECKIN, checkins.checkin_job, {"kind": string, "reference_id": string}),
        (myths.JOB_CHECK, myths.check_job, {"fingerprint": string, "source_event_id": string}),
        (opening.JOB_OPENING, opening.opening_job, {}),
        (sessions.JOB_SWEEP, sessions.sweep_job, {}),
        (sessions.JOB_SUMMARIZE, sessions.summarize_job, {"workspace_id": string, "first_event_id": string, "last_event_id": string}),
        (analysis.JOB_ANALYZE, analysis.analyze_job, {"user_event_id": string, "assistant_event_id": string, "source_timestamp": {"type": "number"}}),
        (mirror_text.JOB_MIRROR_TEXT, mirror_text.mirror_text_job, {"workspace_id": string, "card_version": string}),
        (field_research.JOB_FIELD_RESEARCH, field_research.field_research_job, {"field_key": string, "country": string}),
        (rules_refresh.JOB_RULES_REFRESH, rules_refresh.rules_refresh_job, {}),
        (paths.JOB_ANALYZE_PATHS, paths.path_analysis_job, {"notebook_version": {"type": "integer"}, "source_event_id": string, "channel": string, "reason": string}),
        (memory.JOB_EXTRACT, memory.extract_memory, {"source_type": string, "channel": string, "user_event_id": string, "assistant_event_id": string, "agent_name": string, "candidates": array}),
        (memory.JOB_RECONCILE, memory.reconcile_memory, {"candidate_ids": array}),
        (memory.JOB_EMBED, memory.embed_memory, {"memory_ids": array, "episode_ids": array, "fact_ids": array, "record_refs": array}),
        (memory.JOB_UNINDEX, memory.unindex_memory, {"ids": array}),
        (memory.JOB_REINDEX, memory.reindex_workspace, {"purge_first": {"type": "boolean"}, "batch_size": {"type": "integer"}}),
        (research.JOB_RESUME_RESEARCH, research.resume_research, {"candidate_id": string}),
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
    for job_type, handler, properties in entries:
        registry.register(CapabilityContract(
            id=job_type, version="1.0.0", name=job_type,
            description=f"Internal durable job: {job_type}", kind="system",
            input_schema={"type": "object", "properties": properties,
                          **({"required": ["workspace_id", "first_event_id", "last_event_id"]}
                             if job_type == sessions.JOB_SUMMARIZE else {})},
            output_schema={"type": "object"}, handler=handler,
        ))
