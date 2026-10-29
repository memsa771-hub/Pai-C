"""Canonical text for derived retrieval hints; PostgreSQL remains authoritative."""
import json


def canonical_text(row, kind):
    if kind == "episode":
        return row.summary or ""
    if kind in ("semantic_memory", "document_chunk"):
        return row.content or ""
    if kind == "vault_fact":
        return row.field_key + ": " + json.dumps(row.value, ensure_ascii=False, default=str)
    if kind == "vault_item":
        # The catalog label, the stored English value and the evidence level;
        # never the evidence quote (the student's original words).
        from .catalog import vault_catalog
        spec = vault_catalog().type(row.item_type)
        label = spec.label if spec is not None else row.item_type
        return (label + ": " + json.dumps(row.value, ensure_ascii=False, default=str)
                + " (" + row.level + ")")
    # Exclude audit/provenance and ownership fields; never index private auth metadata.
    excluded = {"id", "workspace_id", "subject_user_id", "evidence", "created_at", "updated_at"}
    return json.dumps({column.key: getattr(row, column.key) for column in row.__table__.columns
                      if column.key not in excluded}, ensure_ascii=False, default=str)
