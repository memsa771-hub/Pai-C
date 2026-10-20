"""Documents, their files and fields, cross-check findings, and the student's confirmed profile values
(Slice 3 spec §3). Every query is filtered by tenant. File bytes are never logged."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.os import models

D, F, B = models.documents, models.document_fields, models.document_files
FI, P = models.document_findings, models.profile_values


class DuplicateDocument(ValueError):
    """The student already has this exact file (same SHA-256), not deleted."""


@dataclass(frozen=True)
class Document:
    id: int
    student_ref: str
    doc_type: str
    type_version: int
    filename: str
    content_type: str
    size: int
    sha256: str
    pages: int | None
    status: str
    detected_type: str | None
    error: str | None
    created_at: datetime
    read_at: datetime | None
    confirmed_at: datetime | None
    deleted_at: datetime | None


def _doc(row) -> Document:
    return Document(**{k: getattr(row, k) for k in Document.__dataclass_fields__})


def _field(row) -> dict:
    return {"field": row.field, "value_read": row.value_read, "check": row.check_result, "reasons": row.reasons,
            "value_confirmed": row.value_confirmed, "confirmed_by": row.confirmed_by,
            "confirmed_at": row.confirmed_at}


class DocumentStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def _mine(self, doc_id: int):
        return (D.c.id == doc_id) & (D.c.tenant_id == self.tenant_id)

    def create(self, student_ref: str, doc_type: str, type_version: int, filename: str, content_type: str,
               data: bytes) -> int:
        sha = hashlib.sha256(data).hexdigest()
        try:
            with self.engine.begin() as conn:
                doc_id = conn.execute(insert(D).values(
                    tenant_id=self.tenant_id, student_ref=student_ref, doc_type=doc_type, type_version=type_version,
                    filename=filename, content_type=content_type, size=len(data), sha256=sha,
                ).returning(D.c.id)).scalar_one()
                conn.execute(insert(B).values(document_id=doc_id, tenant_id=self.tenant_id, data=data))
        except IntegrityError as e:
            if "uq_os_documents_sha" in str(e.orig):
                raise DuplicateDocument("this file is already uploaded") from None
            raise
        return doc_id

    def get(self, doc_id: int) -> Document | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(D).where(self._mine(doc_id))).first()
        return None if row is None else _doc(row)

    def list_for(self, student_ref: str) -> list[Document]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(D).where(
                D.c.tenant_id == self.tenant_id, D.c.student_ref == student_ref, D.c.status != "deleted",
            ).order_by(D.c.created_at, D.c.id)).all()
        return [_doc(r) for r in rows]

    def file_bytes(self, doc_id: int) -> bytes:
        with self.engine.connect() as conn:
            data = conn.execute(select(B.c.data).where(B.c.document_id == doc_id, B.c.tenant_id == self.tenant_id)
                                ).scalar()
        if data is None:
            raise KeyError(doc_id)
        return bytes(data)

    def set_status(self, doc_id: int, status: str, *, error: str | None = None, detected_type: str | None = None,
                   pages: int | None = None) -> None:
        values: dict = {"status": status, "error": error}
        if detected_type is not None:
            values["detected_type"] = detected_type
        if pages is not None:
            values["pages"] = pages
        if status in ("read", "needs_student"):
            values["read_at"] = func.now()
        with self.engine.begin() as conn:
            conn.execute(update(D).where(self._mine(doc_id)).values(**values))

    def save_fields(self, doc_id: int, values: dict, checks: dict[str, tuple[str, list[str]]]) -> None:
        """Upserts each field's value as read and its check result; a confirmed value is never touched."""
        with self.engine.begin() as conn:
            for name in sorted(set(values) | set(checks)):
                check, reasons = checks.get(name, ("ok", []))
                row = {"value_read": values.get(name), "check_result": check, "reasons": list(reasons)}
                conn.execute(pg_insert(F).values(tenant_id=self.tenant_id, document_id=doc_id, field=name, **row)
                             .on_conflict_do_update(constraint="uq_os_document_fields", set_=row))

    def fields(self, doc_id: int) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(F).where(F.c.document_id == doc_id, F.c.tenant_id == self.tenant_id)
                                .order_by(F.c.id)).all()
        return [_field(r) for r in rows]

    def confirm(self, doc_id: int, values: dict) -> None:
        """The student confirms or corrects every field (spec S3-D9). A missing field is refused."""
        names = {f["field"] for f in self.fields(doc_id)}
        missing = sorted(names - set(values))
        if missing:
            raise ValueError(f"every field must be confirmed; missing: {', '.join(missing)}")
        with self.engine.begin() as conn:
            for name in names:
                conn.execute(update(F).where(F.c.document_id == doc_id, F.c.tenant_id == self.tenant_id,
                                             F.c.field == name)
                             .values(value_confirmed=values[name], confirmed_by="student", confirmed_at=func.now()))
            conn.execute(update(D).where(self._mine(doc_id)).values(status="confirmed", confirmed_at=func.now()))

    def delete(self, doc_id: int) -> None:
        """Removes the file and its fields; the row stays as `deleted` (an audit record without content)."""
        with self.engine.begin() as conn:
            conn.execute(delete(B).where(B.c.document_id == doc_id, B.c.tenant_id == self.tenant_id))
            conn.execute(delete(F).where(F.c.document_id == doc_id, F.c.tenant_id == self.tenant_id))
            conn.execute(update(D).where(self._mine(doc_id)).values(status="deleted", deleted_at=func.now()))


def _finding(row) -> dict:
    return {"id": row.id, "student_ref": row.student_ref, "kind": row.kind, "field": row.field, "items": row.items,
            "status": row.status, "resolution": row.resolution, "created_at": row.created_at,
            "resolved_at": row.resolved_at}


class FindingStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def replace_open(self, student_ref: str, findings: list[dict]) -> None:
        """The student's open findings become `findings` (each {kind, field, items}); resolved ones stay."""
        with self.engine.begin() as conn:
            conn.execute(delete(FI).where(FI.c.tenant_id == self.tenant_id, FI.c.student_ref == student_ref,
                                          FI.c.status == "open"))
            for f in findings:
                conn.execute(insert(FI).values(tenant_id=self.tenant_id, student_ref=student_ref, kind=f["kind"],
                                               field=f["field"], items=[list(i) for i in f["items"]]))

    def list_open(self, student_ref: str) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(FI).where(FI.c.tenant_id == self.tenant_id, FI.c.student_ref == student_ref,
                                                 FI.c.status == "open").order_by(FI.c.id)).all()
        return [_finding(r) for r in rows]

    def get(self, finding_id: int) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(FI).where(FI.c.id == finding_id, FI.c.tenant_id == self.tenant_id)).first()
        return None if row is None else _finding(row)

    def resolve(self, finding_id: int, value) -> dict:
        with self.engine.begin() as conn:
            row = conn.execute(update(FI).where(FI.c.id == finding_id, FI.c.tenant_id == self.tenant_id)
                               .values(status="resolved", resolution=value, resolved_at=func.now())
                               .returning(*FI.c)).first()
        if row is None:
            raise KeyError(finding_id)
        return _finding(row)


class ProfileStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def set(self, student_ref: str, key: str, value, source_document_id: int | None) -> None:
        row = {"value": value, "source_document_id": source_document_id, "confirmed_at": func.now()}
        with self.engine.begin() as conn:
            conn.execute(pg_insert(P).values(tenant_id=self.tenant_id, student_ref=student_ref, key=key, **row)
                         .on_conflict_do_update(constraint="uq_os_profile_values_key", set_=row))

    def all(self, student_ref: str) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(P).where(P.c.tenant_id == self.tenant_id, P.c.student_ref == student_ref)
                                .order_by(P.c.key)).all()
        return [{"key": r.key, "value": r.value, "source_document_id": r.source_document_id,
                 "confirmed_at": r.confirmed_at} for r in rows]
