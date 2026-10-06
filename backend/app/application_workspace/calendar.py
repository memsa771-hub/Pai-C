"""Application calendar projection."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.models import ApplicationPlan, ApplicationRequirement, ApplicationRoutine, Institution, KanbanTask, RoutineRecord
from .access import _auth
from .serializers import _requirement

router = APIRouter()

@router.get("/calendar")
def application_calendar(network: str = Query(...), start: date = Query(...), end: date = Query(...),
                         db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                         authorization: str | None = Header(None)):
    """One bounded read model for plans, requirements and scheduled reviews."""
    workspace, error = _auth(db, network, x_workspace_token, authorization)
    if error:
        return error
    if end < start or (end - start).days > 62:
        return json_response(ResponseCode.BAD_REQUEST, "Calendar range must be at most 63 days")
    lower = datetime.combine(start, time.min, timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, timezone.utc)
    workspace_id = str(workspace.id)
    plans = db.execute(select(ApplicationPlan, Institution).join(
        Institution, ApplicationPlan.institution_id == Institution.id).where(
        ApplicationPlan.workspace_id == workspace_id,
        ApplicationPlan.deadline_at >= lower, ApplicationPlan.deadline_at < upper,
    )).all()
    requirements = db.execute(select(ApplicationRequirement, ApplicationPlan, Institution)
        .join(ApplicationPlan, ApplicationRequirement.application_id == ApplicationPlan.id)
        .join(Institution, ApplicationPlan.institution_id == Institution.id)
        .where(ApplicationPlan.workspace_id == workspace_id,
               ApplicationRequirement.due_at >= lower, ApplicationRequirement.due_at < upper)).all()
    task_ids = [item.task_id for item, _, _ in requirements if item.task_id]
    tasks = {task.id: task for task in db.execute(select(KanbanTask).where(
        KanbanTask.workspace_id == workspace_id, KanbanTask.id.in_(task_ids))).scalars()} if task_ids else {}
    routines = db.execute(select(RoutineRecord, ApplicationPlan, Institution)
        .join(ApplicationRoutine, ApplicationRoutine.routine_id == RoutineRecord.id)
        .join(ApplicationPlan, ApplicationRoutine.application_id == ApplicationPlan.id)
        .join(Institution, ApplicationPlan.institution_id == Institution.id)
        .where(ApplicationPlan.workspace_id == workspace_id, RoutineRecord.status == "active",
               RoutineRecord.next_fires_at >= lower - timedelta(days=1),
               RoutineRecord.next_fires_at < upper + timedelta(days=1))).all()
    routine_events = [dict(id=f"routine:{routine.id}", type="review",
                           date=routine.next_fires_at.astimezone(ZoneInfo(routine.timezone or "UTC")).date().isoformat(),
                           title=routine.name, application_id=plan.id, status=routine.status)
                      for routine, plan, _ in routines]
    events = ([dict(id=f"deadline:{plan.id}", type="deadline", date=plan.deadline_at.date().isoformat(),
                    title=f"{institution.name} application", application_id=plan.id, status=plan.status)
               for plan, institution in plans] +
              [dict(id=f"requirement:{item.id}", type="requirement", date=item.due_at.date().isoformat(),
                    title=item.label, application_id=plan.id,
                    status=_requirement(item, tasks.get(item.task_id))["status"])
               for item, plan, _ in requirements] +
              [event for event in routine_events if start.isoformat() <= event["date"] <= end.isoformat()])
    events.sort(key=lambda item: (item["date"], item["type"], item["title"]))
    return success_response({"events": events})


