"""The student's side of a document (Slice 3 spec S3-D9, S3-D10): confirming every field, resolving a finding, and
deleting a document. Only these set profile values (invariant 4), and each value names its source document
(invariant 3).

Profile keys: the cross-check keys (`full_name`, `father_name`, `date_of_birth`) as they are, held back while an
open finding covers them, and every other confirmed field as `<doc_type>.<field>`. An empty value is not set.
"""

import logging
from collections.abc import Mapping

from sqlalchemy import Engine, delete

from app.os import models
from app.os.documents.checks import cross_values
from app.os.documents.run import compare_documents, forget_document
from app.os.documents.store import Document, DocumentStore, FindingStore, ProfileStore
from app.os.documents.types import DocumentType

log = logging.getLogger("app.os.documents.confirm")

CONFIRMABLE = ("read", "needs_student", "confirmed")


class NotConfirmable(ValueError):
    """The document is not read yet (or failed, or is deleted)."""


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def confirm_document(engine: Engine, tenant_id: str, types: Mapping[str, DocumentType], variants: list[set[str]],
                     doc: Document, values: dict) -> str | None:
    """Every field of the type, no more and no fewer (`ValueError` otherwise). Then the findings are checked again
    with the confirmed values, and the profile values are set. With the host part on (or a document linked to a host
    file) the type's `fact:` fields are also offered to the Counsellor's Vault as one fact proposal (P1-T7); the
    return value is that proposal's outbox key, or None. The caller nudges the host with `fact_proposals.notify(key)`
    after its response is built."""
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
    held = {f.field for f in open_findings} | _resolved_with(engine, tenant_id, doc)  # keep the student's choice
    profile = ProfileStore(engine, tenant_id)
    for key, v in cross_values(t, values).items():
        if key not in held:
            profile.set(doc.student_ref, key, v, doc.id)
    for name, v in values.items():
        if not _empty(v):
            profile.set(doc.student_ref, f"{doc.doc_type}.{name}", v, doc.id)
    return _propose_facts(engine, tenant_id, types, doc, values)


def _propose_facts(engine: Engine, tenant_id: str, types: Mapping[str, DocumentType], doc: Document,
                   values: dict) -> str | None:
    """The fact proposal row for a document the student just confirmed. The confirmation is already stored, so a
    failure here is logged by class name and never fails it: the sweep's backfill writes the row later."""
    from app.os.ports import document_files, fact_proposals  # late: the ports import the stores

    # The worker never configures `enabled()`, so the gate is also "linked to a host file" (a link exists only while
    # the part was on). Off and unlinked, nothing is written.
    if not (document_files.enabled() or doc.file_ref is not None):
        return None
    try:
        facts = fact_proposals.facts_of(doc, types, values)
        if not facts:
            return None
        stored = DocumentStore(engine, tenant_id).get(doc.id)  # the stored confirmation time makes the key
        with engine.begin() as conn:
            return fact_proposals.emit(conn, tenant_id, stored, facts)
    except Exception as e:  # class name only: no ids, no values
        log.error("fact proposal could not be written (%s)", type(e).__name__)
        return None


def _resolved_with(engine: Engine, tenant_id: str, doc: Document) -> set[str]:
    """The cross-check keys the student already settled by resolving a finding that names this document."""
    return {f["field"] for f in FindingStore(engine, tenant_id).list_resolved(doc.student_ref)
            if any(i[0] == doc.id for i in f["items"])}


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
                    doc: Document, *, client, notify_host: bool = True) -> None:
    """The file and fields go, and so do the profile values taken from them and the document's DBOS workflows
    (their step outputs hold the values read); the row stays as `deleted`. The student's findings are checked
    again without it. A document linked to a host file (P1-T7) also tells the host, last: the host purges the file.
    The host's answer never undoes the delete (a failed purge is retried by the student); `notify_host=False` is for
    a delete that came from the host."""
    DocumentStore(engine, tenant_id).delete(doc.id)
    forget_document(client, tenant_id, doc.id)
    from app.os.packs.store import PackFileStore  # imported here: packs read documents, not the other way round

    PackFileStore(engine, tenant_id).delete_for_student(doc.student_ref)  # rendered copies go too; rebuilt on demand
    P = models.profile_values
    with engine.begin() as conn:
        conn.execute(delete(P).where(P.c.tenant_id == tenant_id, P.c.source_document_id == doc.id))
    compare_documents(engine, tenant_id, doc.student_ref, types, variants)
    if notify_host and doc.file_ref is not None:
        from app.os.ports import document_files  # late: that module imports this one

        try:
            document_files.on_deleted(doc.student_ref, doc.file_ref)
        except Exception as e:  # class name only: no ids, no values
            log.error("document file purge failed (%s)", type(e).__name__)
