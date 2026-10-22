"""Rendered pack files and the student's per-programme pack items (Slice 6a spec §3). Every query is filtered by
tenant and by student: a file is stored once per SHA-256 per student, and only that student can read it."""

import hashlib
from dataclasses import dataclass

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models

F, I = models.pack_files, models.pack_items


@dataclass(frozen=True)
class PackFileMeta:
    sha256: str
    programme_ref: str
    item_key: str
    filename: str
    content_type: str
    size: int
    pages: int


@dataclass(frozen=True)
class PackFile(PackFileMeta):
    data: bytes


class PackFileStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def put(self, student_ref: str, programme_ref: str, item_key: str, filename: str, content_type: str,
            data: bytes, pages: int) -> str:
        """Stores the bytes once per student (a repeat is a no-op) and returns their SHA-256."""
        sha = hashlib.sha256(data).hexdigest()
        with self.engine.begin() as conn:
            conn.execute(pg_insert(F).values(
                tenant_id=self.tenant_id, student_ref=student_ref, programme_ref=programme_ref, item_key=item_key,
                sha256=sha, filename=filename, content_type=content_type, size=len(data), pages=pages, data=data,
            ).on_conflict_do_nothing(constraint="uq_os_pack_files_sha"))
        return sha

    def _where(self, student_ref: str, sha256: str):
        return (F.c.tenant_id == self.tenant_id) & (F.c.student_ref == student_ref) & (F.c.sha256 == sha256)

    def get(self, student_ref: str, sha256: str) -> PackFile | None:
        with self.engine.connect() as conn:
            r = conn.execute(select(F).where(self._where(student_ref, sha256))).first()
        return None if r is None else PackFile(r.sha256, r.programme_ref, r.item_key, r.filename, r.content_type,
                                               r.size, r.pages, bytes(r.data))

    def meta(self, student_ref: str, sha256: str) -> PackFileMeta | None:
        cols = [F.c.sha256, F.c.programme_ref, F.c.item_key, F.c.filename, F.c.content_type, F.c.size, F.c.pages]
        with self.engine.connect() as conn:
            r = conn.execute(select(*cols).where(self._where(student_ref, sha256))).first()
        return None if r is None else PackFileMeta(*r)

    def delete_for_item(self, student_ref: str, item_key: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(F).where(F.c.tenant_id == self.tenant_id, F.c.student_ref == student_ref,
                                         F.c.item_key == item_key))

    def delete_for_student(self, student_ref: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(F).where(F.c.tenant_id == self.tenant_id, F.c.student_ref == student_ref))


class PackItemStore:
    """The student's ticks on manual items, and the items they added because the portal asks for them."""

    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def _mine(self, student_ref: str, programme_ref: str):
        return (I.c.tenant_id == self.tenant_id) & (I.c.student_ref == student_ref) & (I.c.programme_ref == programme_ref)

    def tick(self, student_ref: str, programme_ref: str, item_key: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(pg_insert(I).values(tenant_id=self.tenant_id, student_ref=student_ref,
                                             programme_ref=programme_ref, item_key=item_key, kind="ticked")
                         .on_conflict_do_nothing(constraint="uq_os_pack_items"))

    def untick(self, student_ref: str, programme_ref: str, item_key: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(I).where(self._mine(student_ref, programme_ref), I.c.item_key == item_key,
                                         I.c.kind == "ticked"))

    def add(self, student_ref: str, programme_ref: str, label: str) -> str:
        with self.engine.begin() as conn:
            n = conn.execute(select(func.count()).select_from(I).where(
                self._mine(student_ref, programme_ref), I.c.kind == "added")).scalar() + 1
            key = f"added:{n}"
            conn.execute(pg_insert(I).values(tenant_id=self.tenant_id, student_ref=student_ref,
                                             programme_ref=programme_ref, item_key=key, kind="added", label=label))
        return key

    def ticked(self, student_ref: str, programme_ref: str) -> set[str]:
        with self.engine.connect() as conn:
            return set(conn.execute(select(I.c.item_key).where(self._mine(student_ref, programme_ref),
                                                               I.c.kind == "ticked")).scalars())

    def added(self, student_ref: str, programme_ref: str) -> list[tuple[str, str]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(I.c.item_key, I.c.label).where(
                self._mine(student_ref, programme_ref), I.c.kind == "added").order_by(I.c.id)).all()
        return [(r.item_key, r.label) for r in rows]
