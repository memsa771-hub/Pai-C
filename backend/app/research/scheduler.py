"""Sweep verified source rows so expired evidence cannot remain a verdict."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.config import config
from app.runtime.task_runtime import enqueue
from app.research.jobs import JOB_REFRESH_RESEARCH
from app.models import Opportunity, RequirementSet
from app.pai_c.roadmaps.service import RoadmapService


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
    for row, opportunity in pairs:
        window = urgent if _near_deadline(row, now.date()) else normal
        if row.checked_at >= now - timedelta(days=window):
            continue
        row.status = "unconfirmed"
        row.verified_at = None
        checks = dict(row.verification_checks or {})
        checks["freshness"] = {"passed": False, "reason": "Source check is too old for the deadline"}
        row.verification_checks = checks
        RoadmapService(db).mark_stale(
            opportunity.workspace_id, "Source verification has expired; this route is being refreshed",
            source_url=row.source_url)
        enqueue(db,
            job_type=JOB_REFRESH_RESEARCH, workspace_id=opportunity.workspace_id,
            payload={"requirement_id": row.id},
            idempotency_key=f"research-verify:{row.id}:{now.date()}")
        count += 1
    return count
