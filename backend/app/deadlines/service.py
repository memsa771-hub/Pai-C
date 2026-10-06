"""Read application and personal dates without copying them into a second planner."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import (ApplicationPlan, ApplicationRequirement, DeadlineSettings,
                        Institution, KanbanTask, NotificationRecord, StudentDeadline)
from app.services.notify import notify

logger = logging.getLogger(__name__)

DEFAULT_REMINDER_DAYS = [7, 1, 0, -1]


def deadline_settings(db, workspace_id: str) -> dict:
    row = db.get(DeadlineSettings, workspace_id)
    return {"timezone": row.timezone if row else "UTC",
            "reminder_days": row.reminder_days if row else DEFAULT_REMINDER_DAYS}


def list_deadlines(db, workspace_id: str, start: date, end: date) -> list[dict]:
    lower = datetime.combine(start, time.min, timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, timezone.utc)
    result = []
    manual = db.execute(select(StudentDeadline).where(
        StudentDeadline.workspace_id == workspace_id,
        StudentDeadline.due_on >= start, StudentDeadline.due_on <= end,
    )).scalars().all()
    for row in manual:
        result.append(dict(id=f"personal:{row.id}", source="personal", source_id=row.id,
                           application_id=None, title=row.title, date=row.due_on.isoformat(),
                           status=row.status, category=row.category, source_url=row.source_url,
                           notes=row.notes, institution=None))

    plans = db.execute(select(ApplicationPlan, Institution).join(
        Institution, ApplicationPlan.institution_id == Institution.id).where(
        ApplicationPlan.workspace_id == workspace_id,
        ApplicationPlan.deadline_at >= lower, ApplicationPlan.deadline_at < upper,
    )).all()
    for plan, institution in plans:
        result.append(dict(id=f"application:{plan.id}", source="application", source_id=plan.id,
                           application_id=plan.id,
                           title=f"{institution.name} application" + (f" · {plan.program_name}" if plan.program_name else ""),
                           date=plan.deadline_at.date().isoformat(),
                           status="done" if plan.status in {"submitted", "decision", "withdrawn"} else "open",
                           category="application", source_url=plan.application_url,
                           notes=plan.notes, institution=institution.name))

    requirements = db.execute(select(ApplicationRequirement, ApplicationPlan, Institution)
        .join(ApplicationPlan, ApplicationRequirement.application_id == ApplicationPlan.id)
        .join(Institution, ApplicationPlan.institution_id == Institution.id)
        .where(ApplicationPlan.workspace_id == workspace_id,
               ApplicationRequirement.due_at >= lower, ApplicationRequirement.due_at < upper)).all()
    task_ids = [row.task_id for row, _, _ in requirements if row.task_id]
    tasks = {task.id: task for task in db.execute(select(KanbanTask).where(
        KanbanTask.workspace_id == workspace_id, KanbanTask.id.in_(task_ids))).scalars()} if task_ids else {}
    for row, plan, institution in requirements:
        task = tasks.get(row.task_id)
        completed = row.status in {"done", "not_applicable"} or (task and task.status == "done")
        result.append(dict(id=f"requirement:{row.id}", source="requirement", source_id=row.id,
                           application_id=plan.id, title=row.label, date=row.due_at.date().isoformat(),
                           status="done" if completed else "open", category=row.kind,
                           source_url=row.source_url, notes=row.notes, institution=institution.name))
    return sorted(result, key=lambda item: (item["date"], item["title"], item["id"]))


def expire_deadline_notices(db, workspace_id: str, source: str, source_id: str) -> None:
    db.execute(update(NotificationRecord).where(
        NotificationRecord.workspace_id == workspace_id,
        NotificationRecord.created_by == "system:deadline",
        NotificationRecord.status == "active",
        NotificationRecord.dedupe_key.like(f"deadline:{source}:{source_id}:%"),
    ).values(status="expired"))


def generate_due_notices(db, workspace_id: str, *, now: datetime | None = None) -> int:
    """Idempotent per workspace across scheduler replicas; in-app only."""
    settings = deadline_settings(db, workspace_id)
    try:
        today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings["timezone"])).date()
    except ZoneInfoNotFoundError:
        today = (now or datetime.now(timezone.utc)).date()
    offsets = settings["reminder_days"]
    active_notices = db.execute(select(NotificationRecord).where(
        NotificationRecord.workspace_id == workspace_id,
        NotificationRecord.created_by == "system:deadline",
        NotificationRecord.status == "active",
    )).scalars().all()
    if not offsets:
        for notice in active_notices:
            notice.status = "expired"
        return 0
    start, end = today + timedelta(days=min(offsets)), today + timedelta(days=max(offsets))
    notice_dates = []
    for notice in active_notices:
        parts = (notice.dedupe_key or "").split(":")
        if len(parts) == 5:
            try:
                notice_dates.append(date.fromisoformat(parts[3]))
            except ValueError:
                notice.status = "expired"
    if notice_dates:
        start, end = min(start, *notice_dates), max(end, *notice_dates)
    current_items = list_deadlines(db, workspace_id, start, end)
    current = {(item["source"], item["source_id"], item["date"]): item
               for item in current_items}
    for notice in active_notices:
        parts = (notice.dedupe_key or "").split(":")
        if len(parts) != 5 or current.get((parts[1], parts[2], parts[3]), {}).get("status") != "open":
            notice.status = "expired"
    created = 0
    for item in current_items:
        if item["status"] != "open":
            expire_deadline_notices(db, workspace_id, item["source"], item["source_id"])
            continue
        distance = (date.fromisoformat(item["date"]) - today).days
        if distance not in offsets:
            continue
        key = f"deadline:{item['source']}:{item['source_id']}:{item['date']}:{distance}"
        if distance < 0:
            message = f"This date passed {abs(distance)} day(s) ago. Check the official source before taking action."
        elif distance == 0:
            message = "Due today. Check the official source and complete any remaining steps."
        else:
            message = f"Due in {distance} day(s). Check your application work and the official source."
        try:
            with db.begin_nested():
                notify(db, workspace_id, source="system:deadline",
                       title=item["title"][:240], message=message,
                       priority="high" if distance <= 0 else "normal", dedupe_key=key)
            created += 1
        except IntegrityError:
            pass
    return created


def sweep_due_notices() -> None:
    """Page workspaces with dated work; each workspace owns a short transaction."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        # Settings allow -30..365 days; one extra day covers the edge of any
        # IANA timezone relative to UTC without scanning unrelated years.
        utc_today = datetime.now(timezone.utc).date()
        first = utc_today - timedelta(days=31)
        last = utc_today + timedelta(days=366)
        lower = datetime.combine(first, time.min, timezone.utc)
        upper = datetime.combine(last + timedelta(days=1), time.min, timezone.utc)
        sources = (select(StudentDeadline.workspace_id.label("workspace_id")).where(
                StudentDeadline.due_on >= first, StudentDeadline.due_on <= last)
            .union(select(ApplicationPlan.workspace_id).where(
                       ApplicationPlan.deadline_at >= lower, ApplicationPlan.deadline_at < upper),
                   select(ApplicationPlan.workspace_id).join(
                       ApplicationRequirement,
                       ApplicationRequirement.application_id == ApplicationPlan.id,
                   ).where(ApplicationRequirement.due_at >= lower,
                           ApplicationRequirement.due_at < upper))).subquery()
        cursor = None
        while True:
            query = select(sources.c.workspace_id).order_by(sources.c.workspace_id).limit(200)
            if cursor is not None:
                query = query.where(sources.c.workspace_id > cursor)
            workspace_ids = db.execute(query).scalars().all()
            if not workspace_ids:
                break
            for workspace_id in workspace_ids:
                try:
                    generate_due_notices(db, str(workspace_id))
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Deadline notice sweep failed for workspace %s", workspace_id)
            cursor = workspace_ids[-1]
    finally:
        db.close()
