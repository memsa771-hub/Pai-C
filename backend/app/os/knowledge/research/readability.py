"""Sources and facts that could not be read by a machine (P2 spec §4.3; R-72).

`is_not_readable(blocked)` says which page refusals mean "a person has to read this" (login-only, failed render, failed
OCR, a PDF that cannot be opened). `NotReadableStore` keeps one row for the source and one per field it should have
answered, for T5's `collect` review item. `machine_status_ceiling(read_method)` is the highest status a machine reading
may give a fact: OCR text stays `unconfirmed` until a checker compares it with the original, and a `human` reading is
never `confirmed` by a machine (it can become `verified` through two reviewers).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import clock as shared_clock
from app.os import models

N = models.not_readable
_LOGIN = ("http_401", "http_403")


def is_not_readable(blocked: str | None) -> bool:
    if not blocked:
        return False
    return blocked.startswith(("not_readable", "unsupported:image/")) or blocked in _LOGIN or blocked == "unreadable_pdf"


def machine_status_ceiling(read_method: str | None) -> str:
    """The highest status a machine reading can give. `confirmed` for fetch and render (the quote was matched on the
    text the machine itself read); `unconfirmed` for OCR (R-72) and for anything typed by a person."""
    return "confirmed" if read_method in (None, "fetch", "render", "model") else "unconfirmed"


class NotReadableStore:
    def __init__(self, engine: Engine, tenant_id: str, clock: Callable[[], datetime] = shared_clock.now) -> None:
        self.engine, self.tenant_id, self.clock = engine, tenant_id, clock

    def mark(self, url: str, reason: str, *, programme_ref: str = "", fields: Sequence[str] = (), intake_year: int = 0,
             snapshot_id: int | None = None) -> int:
        """Marks the source (field '') and each field. A repeat updates the reason and the time and reopens a row
        that was `readable`; a `collected` row stays collected. Returns the rows written."""
        now = self.clock()
        n = 0
        with self.engine.begin() as conn:
            for field in ("", *fields):
                values = {"tenant_id": self.tenant_id, "url": url, "reason": reason, "programme_ref": programme_ref,
                          "field": field, "intake_year": intake_year, "snapshot_id": snapshot_id, "last_seen": now,
                          "first_seen": now}
                upd = {"reason": reason, "last_seen": now, "snapshot_id": snapshot_id}
                stmt = insert(N).values(**values).on_conflict_do_update(constraint="uq_os_not_readable", set_=upd)
                conn.execute(stmt)
                conn.execute(update(N).where(
                    N.c.tenant_id == self.tenant_id, N.c.url == url, N.c.programme_ref == programme_ref,
                    N.c.field == field, N.c.intake_year == intake_year, N.c.state == "readable").values(state="open"))
                n += 1
        return n

    def open_rows(self, *, programme_ref: str | None = None) -> list:
        q = select(N).where(N.c.tenant_id == self.tenant_id, N.c.state == "open").order_by(N.c.id)
        if programme_ref is not None:
            q = q.where(N.c.programme_ref == programme_ref)
        with self.engine.connect() as conn:
            return list(conn.execute(q))

    def set_state(self, url: str, state: str, *, programme_ref: str | None = None, field: str | None = None) -> int:
        """Closes open rows: `collected` (T5, a human supplied the value) or `readable` (a later machine read worked).
        A row that is not open is left alone."""
        q = update(N).where(N.c.tenant_id == self.tenant_id, N.c.url == url, N.c.state == "open").values(state=state)
        if programme_ref is not None:
            q = q.where(N.c.programme_ref == programme_ref)
        if field is not None:
            q = q.where(N.c.field == field)
        with self.engine.begin() as conn:
            return conn.execute(q).rowcount


def annotate_snapshot(engine: Engine, tenant_id: str, snapshot_id: int | None, *, read_method: str,
                      language: str | None) -> None:
    """Records how a snapshot's text was read (the snapshot store itself saves 'fetch' by default)."""
    if snapshot_id is None:
        return
    S = models.page_snapshots
    with engine.begin() as conn:
        conn.execute(update(S).where(S.c.tenant_id == tenant_id, S.c.id == snapshot_id)
                     .values(read_method=read_method, language=language))
