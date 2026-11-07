"""Page snapshots (P2 spec §4.2, P2-D11; R-29): the text a page had when it was read, with its hash, how it was read
and, for PDFs and images, the original bytes. The review queue shows them; monitoring compares them. `os_pages` stays
the cache; snapshots are the record."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert

from app.os import clock as shared_clock
from app.os import models

S, F = models.page_snapshots, models.source_files
DEFAULT_MAX_BYTES = 5_000_000


class SnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class Snapshot:
    id: int
    url: str
    sha256: str
    text: str
    content_type: str
    read_method: str
    language: str | None
    links_total: int
    links_off_list: int
    flagged: str | None
    fetched_at: datetime


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def _snap(row) -> Snapshot:
    return Snapshot(row.id, row.url, row.sha256, row.text, row.content_type, row.read_method, row.language,
                    row.links_total, row.links_off_list, row.flagged, row.fetched_at)


class SnapshotStore:
    def __init__(self, engine: Engine, tenant_id: str, max_bytes: int = DEFAULT_MAX_BYTES,
                 clock: Callable[[], datetime] = shared_clock.now) -> None:
        self.engine, self.tenant_id, self.max_bytes, self.clock = engine, tenant_id, max_bytes, clock

    def save(self, url: str, text: str, *, content_type: str = "", read_method: str = "fetch",
             language: str | None = None, links_total: int = 0, links_off_list: int = 0, flagged: str | None = None,
             fetched_at: datetime | None = None, original: bytes | None = None,
             original_type: str | None = None) -> Snapshot:
        """Stores the read. The same text read again under the same URL is one snapshot (its read time and flag
        are updated), so a page that goes A, B, A has two."""
        if original is not None:
            kind = (original_type or "").lower()
            if kind != "application/pdf" and not kind.startswith("image/"):
                raise SnapshotError("original files are kept for PDFs and images only")
            if len(original) > self.max_bytes:
                raise SnapshotError(f"original is {len(original)} bytes; the limit is {self.max_bytes}")
        values = {"tenant_id": self.tenant_id, "url": url, "sha256": text_hash(text), "text": text,
                  "content_type": content_type, "read_method": read_method, "language": language,
                  "links_total": links_total, "links_off_list": links_off_list, "flagged": flagged,
                  "fetched_at": fetched_at or self.clock()}
        with self.engine.begin() as conn:
            row = conn.execute(insert(S).values(**values).on_conflict_do_update(
                constraint="uq_os_page_snapshots_url_hash",
                set_={k: values[k] for k in ("read_method", "language", "links_total", "links_off_list", "flagged",
                                             "fetched_at")}).returning(S)).one()
            if original is not None:
                conn.execute(insert(F).values(
                    tenant_id=self.tenant_id, snapshot_id=row.id, sha256=hashlib.sha256(original).hexdigest(),
                    content_type=original_type, size_bytes=len(original), content=original)
                    .on_conflict_do_nothing(constraint="uq_os_source_files_snapshot"))
        return _snap(row)

    def latest(self, url: str, *, clean_only: bool = True) -> Snapshot | None:
        q = select(S).where(S.c.tenant_id == self.tenant_id, S.c.url == url)
        if clean_only:
            q = q.where(S.c.flagged.is_(None))
        with self.engine.connect() as conn:
            row = conn.execute(q.order_by(S.c.fetched_at.desc(), S.c.id.desc()).limit(1)).first()
        return _snap(row) if row else None

    def get(self, snapshot_id: int) -> Snapshot | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(S).where(S.c.tenant_id == self.tenant_id, S.c.id == snapshot_id)).first()
        return _snap(row) if row else None

    def original(self, snapshot_id: int) -> tuple[bytes, str] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(F.c.content, F.c.content_type).where(
                F.c.tenant_id == self.tenant_id, F.c.snapshot_id == snapshot_id)).first()
        return (bytes(row.content), row.content_type) if row else None
