"""The import log (`os_imports`, P2 spec §4.6 step 5): who imported which file, in which mode, with what result."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import IntegrityError

from app.os import models

T = models.imports


class AlreadyImported(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportRecord:
    id: int
    file_name: str
    sha256: str
    mode: str
    decision_ref: str | None
    batch_ref: str
    actor: str
    note_actor: str | None
    status: str
    counts: dict
    programmes_created: list
    report_path: str | None
    report_csv: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    undone_at: datetime | None
    undone_by: str | None


def _rec(r) -> ImportRecord:
    return ImportRecord(r.id, r.file_name, r.sha256, r.mode, r.decision_ref, r.batch_ref, r.actor, r.note_actor,
                        r.status, r.counts, r.programmes_created, r.report_path, r.report_csv, r.error, r.started_at, r.finished_at, r.undone_at,
                        r.undone_by)


def cause_ref(import_id: int) -> str:
    """The cause_ref on every revision an import writes; undo finds them by it."""
    return f"import-{import_id}"


class ImportLog:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def start(self, *, file_name: str, sha256: str, mode: str, decision_ref: str | None, batch_ref: str,
              actor: str, note_actor: str | None = None) -> int:
        try:
            with self.engine.begin() as conn:
                return conn.execute(T.insert().values(
                    tenant_id=self.tenant_id, file_name=file_name, sha256=sha256, mode=mode, decision_ref=decision_ref,
                    batch_ref=batch_ref, actor=actor, note_actor=note_actor).returning(T.c.id)).scalar_one()
        except IntegrityError as e:
            if "uq_os_imports_live" in str(e.orig):
                raise AlreadyImported(f"{file_name} (sha256 {sha256[:12]}) is already imported; undo it first") from e
            raise

    def finish(self, import_id: int, *, status: str, counts: dict[str, Any] | None = None,
               programmes_created: list[str] | None = None, report_path: str | None = None,
               report_csv: str | None = None, error: str | None = None) -> None:
        values: dict[str, Any] = {"status": status, "finished_at": func.now(), "error": error}
        if counts is not None:
            values["counts"] = counts
        if programmes_created is not None:
            values["programmes_created"] = programmes_created
        if report_path is not None:
            values["report_path"] = report_path
        if report_csv is not None:
            values["report_csv"] = report_csv
        with self.engine.begin() as conn:
            conn.execute(update(T).where(T.c.id == import_id, T.c.tenant_id == self.tenant_id).values(**values))

    def mark_undone(self, import_id: int, by: str, conn=None) -> None:
        """Inside the undo's own transaction when `conn` is given, so the log never disagrees with the data."""
        if conn is None:
            with self.engine.begin() as own:
                return self.mark_undone(import_id, by, own)
        conn.execute(update(T).where(T.c.id == import_id, T.c.tenant_id == self.tenant_id).values(
            status="undone", undone_at=func.now(), undone_by=by))

    def get(self, import_id: int) -> ImportRecord | None:
        with self.engine.connect() as conn:
            r = conn.execute(select(T).where(T.c.id == import_id, T.c.tenant_id == self.tenant_id)).first()
        return _rec(r) if r else None

    def list(self, limit: int = 100) -> list[ImportRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(T).where(T.c.tenant_id == self.tenant_id).order_by(T.c.id.desc())
                                .limit(limit)).all()
        return [_rec(r) for r in rows]
