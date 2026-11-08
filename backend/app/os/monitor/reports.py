"""A student reports a fact as wrong (P2 spec §4.7, P2-D22; R-28; row 6.23), with the owner ruling of 2026-11-08.

- The fact goes back to `unconfirmed` at once (marker `report`), so every screen says "not confirmed".
- Only the reporting students' steps wait (`fact_rechecking`). Other students' steps keep running, on a provisional date,
  until a reviewer agrees or `escalate_after_reporters` different students have reported the fact: the marker then
  becomes `report_escalated` and every plan's steps wait.
- A `report` item opens in the review queue, or the report joins the one open for that fact. What the student wrote goes
  only to that item. A dismissed report puts the fact back to the status it had (the queue's `resolve`).
- A student may report a few different facts a day. Counting and writing are one transaction under a per-student lock, so
  two requests at once cannot both pass the limit; a batch is checked as a whole before any of it is applied."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import Engine, func, select

from app.os import models
from app.os.knowledge.port import Fact
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


def report_facts(engine: Engine, tenant_id: str, student_ref: str, fact_ids: list[int], reason: str, text: str | None,
                 now: datetime, *, knowledge: SqlKnowledge, queue: ReviewQueue, after_change: AfterChange | None = None,
                 config: MonitorConfig | None = None) -> dict:
    """Records one report for each fact. The caller has already checked that the student's plan shows them."""
    cfg = config or load_config()
    if reason not in cfg.report_reasons:
        raise ReportError(422, "unknown_reason")
    text = (text or "").strip() or None
    if text is not None and len(text) > cfg.report_text_max_chars:
        raise ReportError(422, "text_too_long")
    ids = sorted(set(fact_ids))
    located: dict[int, tuple[str, str, str, int]] = {}
    for fid in ids:
        try:
            scope, ref, field, fact = knowledge.get(fid)
        except KeyError:
            raise ReportError(404, "fact_not_found") from None
        located[fid] = (scope, ref, field, fact.intake_year)
    changed: list[int] = []
    last_item = reports = 0
    with engine.begin() as conn:
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"os.report:{tenant_id}:{student_ref}"))))
        reported = set(conn.execute(select(REPORTS.c.fact_id).distinct().where(
            REPORTS.c.tenant_id == tenant_id, REPORTS.c.student_ref == student_ref,
            REPORTS.c.created_at >= now - timedelta(days=1))).scalars())
        if len(reported | set(ids)) > cfg.max_reported_facts_per_day:  # the whole batch, before any of it is applied
            raise ReportError(429, "too_many_reports")
        for fid in ids:
            item_id, _ = queue.open_item("report", dedupe_key=f"report:{fid}", fact_id=fid, opened_by="report",
                                         summary="A student reported this fact as wrong", conn=conn)
            report_id = conn.execute(REPORTS.insert().values(
                tenant_id=tenant_id, fact_id=fid, student_ref=student_ref, reason=reason, detail=text,
                review_item_id=item_id, created_at=now).returning(REPORTS.c.id)).scalar_one()
            queue.note_report(item_id, {"reason": reason, "text": text, "at": now.isoformat()}, conn)
            fact = knowledge.locked(conn, fid)[3]
            if fact.status != "unconfirmed":  # confirmed, verified or stale: not any more, until someone checks it again
                knowledge.revise(fid, status="unconfirmed", recheck="report", cause="report", cause_ref=str(report_id),
                                 actor="student", conflict_note="a student reported this as wrong", conn=conn)
                queue.void_verify(fid, conn)
            elif fact.recheck == "report":
                n = conn.execute(select(func.count(func.distinct(REPORTS.c.student_ref))).where(
                    REPORTS.c.tenant_id == tenant_id, REPORTS.c.fact_id == fid)).scalar_one()
                if n >= cfg.escalate_after_reporters:  # enough different students: every plan's steps wait
                    knowledge.revise(fid, recheck="report_escalated", cause="report", cause_ref=str(report_id),
                                     actor="student", conn=conn)
            if fact.recheck != "monitor":  # the reporter's own plan must now see the wait, whatever the fact's state
                changed.append(fid)
            last_item, reports = item_id, reports + 1
    if after_change is not None:
        for fid in changed:
            scope, ref, field, year = located[fid]
            after_change(scope, ref, field, fid, "unconfirmed", year)
    return {"status": "received", "item_id": last_item, "facts": reports}


def for_student(engine: Engine, tenant_id: str, student_ref: str, route_facts: Mapping[str, Fact],
                programme_facts: Mapping[tuple[str, str], Fact]) -> tuple[dict, dict]:
    """The facts as one student's plan sees them (owner ruling 2026-11-08): a fact taken back by a student report only
    holds that student's steps if they reported it themselves; once escalated it holds everyone's. Nothing else changes,
    and with no reported fact there is no query."""
    held = [f for f in [*route_facts.values(), *programme_facts.values()] if f.recheck == "report" and f.id is not None]
    if not held:
        return dict(route_facts), dict(programme_facts)
    with engine.connect() as conn:
        mine = set(conn.execute(select(REPORTS.c.fact_id).distinct().where(
            REPORTS.c.tenant_id == tenant_id, REPORTS.c.student_ref == student_ref,
            REPORTS.c.fact_id.in_([f.id for f in held]))).scalars())

    def seen(f: Fact) -> Fact:
        return replace(f, recheck=None) if f.recheck == "report" and f.id not in mine else f

    return ({k: seen(v) for k, v in route_facts.items()}, {k: seen(v) for k, v in programme_facts.items()})
