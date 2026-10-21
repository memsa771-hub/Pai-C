"""The student's side of a document (Slice 3 spec S3-D9, S3-D10): confirming every field, resolving a finding, and
deleting a document. Only these set profile values (invariant 4), and each value names its source document
(invariant 3).

Profile keys: the cross-check keys (`full_name`, `father_name`, `date_of_birth`) as they are, held back while an
open finding covers them, and every other confirmed field as `<doc_type>.<field>`. An empty value is not set.
"""

from collections.abc import Mapping

from sqlalchemy import Engine, delete

from app.os import models
from app.os.documents.checks import cross_values
from app.os.documents.run import compare_documents
from app.os.documents.store import Document, DocumentStore, FindingStore, ProfileStore
from app.os.documents.types import DocumentType

CONFIRMABLE = ("read", "needs_student", "confirmed")


class NotConfirmable(ValueError):
    """The document is not read yet (or failed, or is deleted)."""


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def confirm_document(engine: Engine, tenant_id: str, types: Mapping[str, DocumentType], variants: list[set[str]],
                     doc: Document, values: dict) -> None:
    """Every field of the type, no more and no fewer (`ValueError` otherwise). Then the findings are checked again
    with the confirmed values, and the profile values are set."""
    if doc.status not in CONFIRMABLE:
        raise NotConfirmable(f"this document is {doc.status}; it can be confirmed once it is read")
    t = types[doc.doc_type]
    names = {f.name for f in t.fields}
    missing, extra = sorted(names - set(values)), sorted(set(values) - names)
    if missing or extra:
        raise ValueError("every field must be confirmed, and only the document's fields"
                         + (f"; missing: {', '.join(missing)}" if missing else "")
                         + (f"; unknown: {', '.join(extra)}" if extra else ""))
    DocumentStore(engine, tenant_id).confirm(doc.id, values)
    open_findings = compare_documents(engine, tenant_id, doc.student_ref, types, variants)
    held = {f.field for f in open_findings}
    profile = ProfileStore(engine, tenant_id)
    for key, v in cross_values(t, values).items():
        if key not in held:
            profile.set(doc.student_ref, key, v, doc.id)
    for name, v in values.items():
        if not _empty(v):
            profile.set(doc.student_ref, f"{doc.doc_type}.{name}", v, doc.id)


def resolve_finding(engine: Engine, tenant_id: str, finding: dict, value) -> dict:
    """The student picks one of the finding's values; it becomes the profile value, with the document it came
    from as its source. Any other value is refused (`ValueError`)."""
    source = next((doc_id for doc_id, v in finding["items"] if v == value), None)
    if source is None:
        raise ValueError("choose one of the values found in your documents")
    resolved = FindingStore(engine, tenant_id).resolve(finding["id"], value)
    ProfileStore(engine, tenant_id).set(finding["student_ref"], finding["field"], value, source)
    return resolved


def delete_document(engine: Engine, tenant_id: str, types: Mapping[str, DocumentType], variants: list[set[str]],
                    doc: Document) -> None:
    """The file and fields go, and so do the profile values taken from them; the row stays as `deleted`. The
    student's findings are checked again without it."""
    DocumentStore(engine, tenant_id).delete(doc.id)
    P = models.profile_values
    with engine.begin() as conn:
        conn.execute(delete(P).where(P.c.tenant_id == tenant_id, P.c.source_document_id == doc.id))
    compare_documents(engine, tenant_id, doc.student_ref, types, variants)
