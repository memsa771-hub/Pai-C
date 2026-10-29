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


def enqueue_monthly_rules_refresh(db, *, now: datetime | None = None):
    """One rules and calendar refresh per UTC month (BETA_CONVERSATION_SPEC
    3.3): the worker's research sweep calls this, so its first sweep in a
    month queues the job and later sweeps find the same key. The caller commits."""
    from app.research.rules_refresh import JOB_RULES_REFRESH
    from app.runtime.task_runtime import enqueue
    now = now or datetime.now(timezone.utc)
    return enqueue(db, job_type=JOB_RULES_REFRESH, payload={}, idempotency_key=f"rules_refresh:{now:%Y-%m}")
