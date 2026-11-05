"""The standalone StudentFacts adapter (P1-T4): facts built from `os_profile_values`, for a PAI OS that runs without a
host adapter. A value read from a document is `confirmed`, one the student typed is `stated`. A field that names a
`fact:` key is sent under it; any other value is carried under its own `<doc_type>.<field>` key."""

from collections.abc import Mapping

from sqlalchemy import Engine

from app.os import clock
from app.os.contracts.student_facts import StudentFactsV1
from app.os.documents.store import ProfileStore
from app.os.documents.types import DocumentType


def build(engine: Engine, tenant_id: str, student_ref: str, types: Mapping[str, DocumentType]) -> StudentFactsV1:
    fact_key = {f"{t.key}.{f.name}": f.fact for t in types.values() for f in t.fields if f.fact}
    facts = []
    for v in ProfileStore(engine, tenant_id).all(student_ref):
        confirmed = v["source"] == "document"
        facts.append({"key": fact_key.get(v["key"], v["key"]), "value": v["value"],
                      "evidence": "confirmed" if confirmed else "stated", "vault_version": 0,
                      "document_ref": str(v["source_document_id"]) if v["source_document_id"] is not None else None,
                      "as_of": v["confirmed_at"]})
    return StudentFactsV1.model_validate({"schema": "pai.student_facts.v1", "student_ref": student_ref,
                                          "vault_version": 0, "built_at": clock.now(), "eligible_levels": None,
                                          "facts": facts})
