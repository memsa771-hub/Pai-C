"""A student reports a fact as wrong (P2 spec §4.7, P2-D22; R-28; row 6.23). The fact goes back to `unconfirmed` at once
(marker `report`), so the steps it dates wait (`fact_rechecking`) and the screens say "not confirmed"; a `report` item opens
in the review queue, or the report joins the one already open for that fact. What the student wrote goes only to that item,
never to another student. A student may report a few different facts a day (data)."""

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Engine, func, select

from app.os import models
from app.os.knowledge.review.queue import ReviewQueue
from app.os.knowledge.store import SqlKnowledge
from app.os.monitor.config import MonitorConfig, load_config

REPORTS = models.fact_reports
AfterChange = Callable[[str, str, str, int, str, int], None]


class ReportError(Exception):
    """A report that is refused; `status` is the HTTP code and `detail` a code (never the student's words)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def report_fact(engine: Engine, tenant_id: str, student_ref: str, fact_id: int, reason: str, text: str | None, now: datetime,
                *, knowledge: SqlKnowledge, queue: ReviewQueue, after_change: AfterChange | None = None,
                config: MonitorConfig | None = None) -> dict:
    """Records the report. The caller has already checked that the fact is one the student's plan shows."""
    cfg = config or load_config()
    if reason not in cfg.report_reasons:
        raise ReportError(422, "unknown_reason")
    text = (text or "").strip() or None
    if text is not None and len(text) > cfg.report_text_max_chars:
        raise ReportError(422, "text_too_long")
    try:
        scope, ref, field, fact = knowledge.get(fact_id)
    except KeyError:
        raise ReportError(404, "fact_not_found") from None
    since = now - timedelta(days=1)
    with engine.connect() as conn:
        reported = set(conn.execute(select(REPORTS.c.fact_id).distinct().where(
            REPORTS.c.tenant_id == tenant_id, REPORTS.c.student_ref == student_ref, REPORTS.c.created_at >= since)).scalars())
    if fact_id not in reported and len(reported) >= cfg.max_reported_facts_per_day:
        raise ReportError(429, "too_many_reports")
    item_id, _ = queue.open_item("report", dedupe_key=f"report:{fact_id}", fact_id=fact_id, opened_by="report",
                                 summary="A student reported this fact as wrong")
    with engine.begin() as conn:
        report_id = conn.execute(REPORTS.insert().values(
            tenant_id=tenant_id, fact_id=fact_id, student_ref=student_ref, reason=reason, detail=text,
            review_item_id=item_id, created_at=now).returning(REPORTS.c.id)).scalar_one()
    queue.note_report(item_id, {"reason": reason, "text": text, "at": now.isoformat()})
    if fact.status != "unconfirmed":  # confirmed, verified or stale: not any more, until someone checks it again
        knowledge.revise(fact_id, status="unconfirmed", recheck="report", cause="report", cause_ref=str(report_id),
                         actor="student", conflict_note="a student reported this as wrong")
        queue.void_verify(fact_id)
        if after_change is not None:
            after_change(scope, ref, field, fact_id, "unconfirmed", fact.intake_year)
    with engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(REPORTS).where(
            REPORTS.c.tenant_id == tenant_id, REPORTS.c.fact_id == fact_id)).scalar_one()
    return {"status": "received", "item_id": item_id, "reports_for_fact": n}
