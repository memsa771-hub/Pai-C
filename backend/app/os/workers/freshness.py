"""The freshness sweeper `os.freshness`, daily (Slice 2 spec §4.7, S1-D1, R2-P2).

A confirmed fact goes `stale` when it is older than the TTL, and a deadline fact also on its 30- and 7-day
re-check marks (end of day in the deadline's timezone). That is the whole re-check: the compiler treats a
stale fact as provisional and asks for a confirm_fact task again (the kernel re-adds a finished one), so
research runs again. There is no second research trigger.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, insert, select

from app.os import models
from app.os.compiler.compile import date_of
from app.os.knowledge.changes import after_fact_change

F = models.knowledge_facts
RECHECK_DAYS = (30, 7)


def _deadline_tz(service, field: str) -> str:
    """The timezone of a deadline that names none: the default of the playbook that anchors on it."""
    for book in service.playbooks.values():
        if any(t.anchor and t.anchor.fact == field for t in book.tasks):
            return book.default_timezone
    return "UTC"


def _recheck_reason(service, row, now: datetime) -> str | None:
    """'recheck_30d' / 'recheck_7d' when a deadline's mark has passed since the fact was last checked."""
    try:
        deadline, tz = date_of(row.value, row.field)
    except Exception:  # noqa: BLE001  (not a date: the compiler reports it; nothing to re-check here)
        return None
    zone = ZoneInfo(tz or _deadline_tz(service, row.field))
    for days in sorted(RECHECK_DAYS):  # the nearest mark first, so the reason names the latest one passed
        mark = datetime.combine(deadline - timedelta(days=days), datetime.min.time(), zone)
        if now >= mark and row.checked_at < mark and now.astimezone(zone).date() <= deadline:
            return f"recheck_{days}d"
    return None


def run(service, engine: Engine, now: datetime, ttl_days: int | None = None) -> int:
    """Marks the due facts stale and hands each to after_fact_change. Returns how many went stale."""
    kernel = service.kernel
    ttl = ttl_days if ttl_days is not None else service.settings.fact_ttl_days
    anchors = service.anchor_fields()
    with engine.connect() as conn:
        rows = conn.execute(select(F).where(F.c.tenant_id == kernel.tenant_id, F.c.status == "confirmed")
                            .order_by(F.c.id)).all()
    knowledge = service.knowledge
    stale = 0
    for row in rows:
        reason = "ttl" if row.checked_at < now - timedelta(days=ttl) else None
        if reason is None and row.field in anchors:
            reason = _recheck_reason(service, row, now)
        if reason is None or not knowledge.mark_stale(row.id):
            continue
        stale += 1
        with engine.begin() as conn:
            conn.execute(insert(models.events).values(tenant_id=kernel.tenant_id, type="fact_changed", payload={
                "scope": row.scope, "ref": row.ref, "field": row.field, "intake_year": row.intake_year,
                "fact_id": row.id, "reason": reason,
                "old": {"value": row.value, "status": "confirmed"}, "new": {"value": row.value, "status": "stale"}}))
        after_fact_change(service, kernel, row.scope, row.ref, row.field, row.id, "stale", row.intake_year,
                          complete=False)
    return stale
