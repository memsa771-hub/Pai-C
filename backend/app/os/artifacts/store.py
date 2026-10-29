"""Artifacts: the student's co-written texts, as immutable versions with hash-bound approvals (Slice 5 S5-D7, S5-D8).

A version is never changed: an edit is a new version. An approval stores the SHA-256 of one version's UTF-8 text
(invariant 5); a newer version clears it, so the approved text is always exactly what the student approved. Slice 6
reuses these tables for the application pack. Every query is filtered by tenant.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models

A, V, AP = models.artifacts, models.artifact_versions, models.approvals
BASE = ""  # programme_ref of a student's base artifact (not tied to a programme)
STATEMENT_KINDS = ("sop", "cv")  # the student's statements; the pack and the visa file share the table (Slices 6a, 6b)


@dataclass(frozen=True)
class Artifact:
    id: int
    student_ref: str
    kind: str
    programme_ref: str | None
    status: str
    current_version: int | None


@dataclass(frozen=True)
class Version:
    number: int
    text: str
    sha256: str
    author: str
    words: int
    critic: dict | None
    flags: list
    limit_words: int | None
    created_at: datetime


@dataclass(frozen=True)
class Approval:
    version: int
    sha256: str
    approved_at: datetime


def _artifact(r) -> Artifact:
    return Artifact(r.id, r.student_ref, r.kind, r.programme_ref or None, r.status, r.current_version)


def _version(r) -> Version:
    return Version(r.number, r.text, r.sha256, r.author, r.words, r.critic, list(r.flags or []), r.limit_words,
                   r.created_at)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def _own(self, conn, artifact_id: int, lock: bool = False):
        q = select(A).where(A.c.id == artifact_id, A.c.tenant_id == self.tenant_id)
        row = conn.execute(q.with_for_update() if lock else q).first()
        if row is None:
            raise KeyError(f"artifact {artifact_id}")
        return row

    def get_or_create(self, student_ref: str, kind: str, programme_ref: str | None) -> Artifact:
        key = {"tenant_id": self.tenant_id, "student_ref": student_ref, "kind": kind,
               "programme_ref": programme_ref or BASE}
        with self.engine.begin() as conn:
            conn.execute(pg_insert(A).values(**key).on_conflict_do_nothing(constraint="uq_os_artifacts_key"))
            row = conn.execute(select(A).where(*[A.c[k] == v for k, v in key.items()])).one()
        return _artifact(row)

    def get(self, artifact_id: int) -> Artifact | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(A).where(A.c.id == artifact_id, A.c.tenant_id == self.tenant_id)).first()
        return None if row is None else _artifact(row)

    def list_for(self, student_ref: str, kinds: tuple[str, ...] | None = None) -> list[Artifact]:
        """The student's artifacts, or only those of `kinds` (e.g. STATEMENT_KINDS)."""
        q = select(A).where(A.c.tenant_id == self.tenant_id, A.c.student_ref == student_ref)
        if kinds is not None:
            q = q.where(A.c.kind.in_(kinds))
        with self.engine.connect() as conn:
            rows = conn.execute(q.order_by(A.c.kind, A.c.programme_ref)).all()
        return [_artifact(r) for r in rows]

    def add_version(self, artifact_id: int, text: str, author: str, *, critic: dict | None = None,
                    flags: list | None = None, limit_words: int | None = None) -> Version:
        with self.engine.begin() as conn:
            art = self._own(conn, artifact_id, lock=True)
            number = (art.current_version or 0) + 1
            row = conn.execute(insert(V).values(
                tenant_id=self.tenant_id, artifact_id=artifact_id, number=number, text=text, sha256=sha256(text),
                author=author, words=len(text.split()), critic=critic, flags=flags or [], limit_words=limit_words,
            ).returning(V)).one()
            conn.execute(delete(AP).where(AP.c.artifact_id == artifact_id))  # a newer text is not the approved one
            conn.execute(update(A).where(A.c.id == artifact_id).values(current_version=number, status="draft",
                                                                       updated_at=func.now()))
        return _version(row)

    def versions(self, artifact_id: int) -> list[Version]:
        with self.engine.connect() as conn:
            self._own(conn, artifact_id)
            rows = conn.execute(select(V).where(V.c.artifact_id == artifact_id).order_by(V.c.number)).all()
        return [_version(r) for r in rows]

    def version(self, artifact_id: int, number: int) -> Version:
        found = next((v for v in self.versions(artifact_id) if v.number == number), None)
        if found is None:
            raise KeyError(f"artifact {artifact_id} version {number}")
        return found

    def approve(self, artifact_id: int, number: int) -> Approval:
        with self.engine.begin() as conn:
            self._own(conn, artifact_id, lock=True)
            v = conn.execute(select(V).where(V.c.artifact_id == artifact_id, V.c.number == number)).first()
            if v is None:
                raise KeyError(f"artifact {artifact_id} version {number}")
            values = {"version": number, "sha256": v.sha256, "approved_at": func.now()}
            row = conn.execute(pg_insert(AP).values(tenant_id=self.tenant_id, artifact_id=artifact_id, **values)
                               .on_conflict_do_update(constraint="uq_os_approvals_artifact", set_=values)
                               .returning(AP)).one()
            conn.execute(update(A).where(A.c.id == artifact_id).values(status="approved", updated_at=func.now()))
        return Approval(row.version, row.sha256, row.approved_at)

    def approval(self, artifact_id: int) -> Approval | None:
        with self.engine.connect() as conn:
            self._own(conn, artifact_id)
            row = conn.execute(select(AP).where(AP.c.artifact_id == artifact_id)).first()
        return None if row is None else Approval(row.version, row.sha256, row.approved_at)

    def set_status(self, artifact_id: int, status: str) -> None:
        with self.engine.begin() as conn:
            self._own(conn, artifact_id)
            conn.execute(update(A).where(A.c.id == artifact_id).values(status=status, updated_at=func.now()))

    def delete_for(self, student_ref: str) -> None:
        with self.engine.begin() as conn:  # versions and approvals go with their artifact (ON DELETE CASCADE)
            conn.execute(delete(A).where(A.c.tenant_id == self.tenant_id, A.c.student_ref == student_ref))
