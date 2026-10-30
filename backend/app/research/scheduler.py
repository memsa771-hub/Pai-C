"""Sweep verified source rows so expired evidence cannot remain a verdict."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.config import config
from app.models import Opportunity, RequirementSet


def _near_deadline(row: RequirementSet, today: date) -> bool:
    for fact in (row.deadlines or {}).values():
        try:
            day = date.fromisoformat(fact["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= (day - today).days <= 60:
            return True
    return False


def enqueue_due_verification(db, *, now: datetime | None = None, limit: int = 50) -> int:
    now = now or datetime.now(timezone.utc)
    normal = max(1, config.PAI_RESEARCH_FRESHNESS_DAYS)
    urgent = max(1, config.PAI_RESEARCH_DEADLINE_FRESHNESS_DAYS)
    pairs = db.execute(select(RequirementSet, Opportunity).join(Opportunity).where(
        RequirementSet.status == "verified",
        RequirementSet.checked_at < now - timedelta(days=min(normal, urgent)),
    ).order_by(RequirementSet.checked_at).limit(limit).with_for_update(skip_locked=True)).all()
    count = 0
    for row, _ in pairs:
        window = urgent if _near_deadline(row, now.date()) else normal
        if row.checked_at >= now - timedelta(days=window):
            continue
        row.status = "unconfirmed"
        row.verified_at = None
        checks = dict(row.verification_checks or {})
        checks["freshness"] = {"passed": False, "reason": "Source check is too old for the deadline"}
        row.verification_checks = checks
        count += 1
    db.flush()
    return count


_STARTED_AT = datetime.now(timezone.utc)


def last_rules_refresh(db) -> datetime | None:
    """When the last refresh happened: the newest refresh job in the queue or
    the newest proposal file's date, whichever is later; None when neither."""
    from app.models import BackgroundJob
    from app.research.rules_refresh import JOB_RULES_REFRESH, proposals_dir
    times = []
    created = db.scalar(select(BackgroundJob.created_at).where(BackgroundJob.job_type == JOB_RULES_REFRESH)
                        .order_by(BackgroundJob.created_at.desc()).limit(1))
    if created is not None:
        times.append(created if created.tzinfo else created.replace(tzinfo=timezone.utc))
    folder = proposals_dir()
    for path in folder.glob("*.json") if folder.is_dir() else ():
        try:
            day = date.fromisoformat(path.stem[:10])
        except ValueError:
            continue
        times.append(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))
    return max(times, default=None)


def enqueue_monthly_rules_refresh(db, *, now: datetime | None = None, started_at: datetime | None = None):
    """The rules and calendar refresh (BETA_CONVERSATION_SPEC 3.3), queued by
    the worker's research sweep only when the last refresh is at least
    PAI_RULES_REFRESH_INTERVAL_DAYS old and the worker (`started_at`, default
    this process's start) has been up PAI_RULES_REFRESH_MIN_UPTIME_MIN
    minutes, so a fresh stack's first boot never runs it. One job per UTC
    month by its key. Returns the job, or None when not due. The caller commits."""
    from app.research.rules_refresh import JOB_RULES_REFRESH
    from app.runtime.task_runtime import enqueue
    now = now or datetime.now(timezone.utc)
    if now - (started_at or _STARTED_AT) < timedelta(minutes=max(0, config.PAI_RULES_REFRESH_MIN_UPTIME_MIN)):
        return None
    last = last_rules_refresh(db)
    if last is not None and now - last < timedelta(days=max(1, config.PAI_RULES_REFRESH_INTERVAL_DAYS)):
        return None
    return enqueue(db, job_type=JOB_RULES_REFRESH, payload={}, idempotency_key=f"rules_refresh:{now:%Y-%m}")
