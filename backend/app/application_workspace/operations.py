"""Links application requirements to existing tasks, workflows and routines."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.models import ApplicationRequirement, ApplicationRoutine, Institution, KanbanTask, RoutineRecord, Workflow, WorkspaceMember
from .access import _auth
from .queries import _owned_plan
from .schemas import RequirementTaskInput, ReviewRoutineInput
from .serializers import _requirement

router = APIRouter()

@router.post("/applications/{plan_id}/requirements/{requirement_id}/task")
def ensure_requirement_task(plan_id: str, requirement_id: str, body: RequirementTaskInput,
                            db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                            authorization: str | None = Header(None)):
    """Create or configure the ordinary workspace task, linked atomically."""
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    workspace_id = str(workspace.id)
    plan = _owned_plan(db, workspace_id, plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    requirement = db.execute(select(ApplicationRequirement).where(
        ApplicationRequirement.id == requirement_id,
        ApplicationRequirement.application_id == plan.id,
    ).with_for_update()).scalar_one_or_none()
    if requirement is None:
        return json_response(ResponseCode.NOT_FOUND, "Requirement not found")
    if body.workflow_id and db.execute(select(Workflow.id).where(
        Workflow.id == body.workflow_id, Workflow.workspace_id == workspace_id,
    )).first() is None:
        return json_response(ResponseCode.BAD_REQUEST, "Workflow not found in workspace")
    task = db.execute(select(KanbanTask).where(
        KanbanTask.id == requirement.task_id, KanbanTask.workspace_id == workspace_id,
    )).scalar_one_or_none() if requirement.task_id else None
    if task is None:
        position = db.execute(select(func.coalesce(func.max(KanbanTask.position), -1) + 1).where(
            KanbanTask.workspace_id == workspace_id, KanbanTask.status == "backlog",
        )).scalar_one()
        institution = db.get(Institution, plan.institution_id)
        task = KanbanTask(workspace_id=workspace_id, title=requirement.label,
                          description=f"Application: {institution.name}; program: {plan.program_name or 'unspecified'}; requirement: {requirement.label}",
                          status="backlog", workflow_id=body.workflow_id,
                          file_ids=[requirement.file_id] if requirement.file_id else None,
                          created_by=f"human:{workspace.owner_user_id}", position=position)
        db.add(task)
        db.flush()
        requirement.task_id = task.id
    elif body.workflow_id is not None:
        if task.status == "in_progress":
            return json_response(ResponseCode.CONFLICT, "Cannot change a running task's workflow")
        task.workflow_id = body.workflow_id or None
    db.commit()
    return success_response(_requirement(requirement, task))


@router.post("/applications/{plan_id}/routines")
def create_application_routine(plan_id: str, body: ReviewRoutineInput,
                               db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                               authorization: str | None = Header(None)):
    """Recurring PAI review in the existing scheduler; never a submission job."""
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    plan = _owned_plan(db, str(workspace.id), plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return json_response(ResponseCode.BAD_REQUEST, "Unknown timezone")
    from app.services.pai import PAI_AGENT_NAME
    from app.routers.routines import _compute_next_fires_at, _get_or_create_routine_channel
    pai_member = db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == str(workspace.id),
        WorkspaceMember.agent_name == PAI_AGENT_NAME,
        WorkspaceMember.status != "removed",
    )).scalar_one_or_none()
    if pai_member is None:
        return json_response(ResponseCode.CONFLICT, "PAI Counselor is not available in this workspace")
    name, message = body.name.strip(), body.message.strip()
    if not name or not message:
        return json_response(ResponseCode.BAD_REQUEST, "Name and review instruction are required")
    try:
        next_fire = _compute_next_fires_at(body.hour, body.minute, body.days, None, body.timezone)
    except ValueError:
        return json_response(ResponseCode.BAD_REQUEST, "No valid occurrence for this schedule")
    channel = _get_or_create_routine_channel(db, workspace, PAI_AGENT_NAME)
    routine = RoutineRecord(workspace_id=str(workspace.id), channel_name=channel.name,
                            created_by=PAI_AGENT_NAME, name=name,
                            message=f"Application {plan.id}: {message}",
                            context=("Review the student's application plan and ask for any missing details. "
                                     "Do not submit or change an external application. "
                                     f"Application plan ID: {plan.id}."),
                            schedule_hour=body.hour, schedule_minute=body.minute,
                            schedule_days=body.days, timezone=body.timezone,
                            next_fires_at=next_fire, status="active")
    db.add(routine)
    db.flush()
    db.add(ApplicationRoutine(application_id=plan.id, routine_id=routine.id))
    db.commit()
    return success_response(dict(id=routine.id, name=routine.name, message=body.message,
                                 schedule_hour=routine.schedule_hour, schedule_minute=routine.schedule_minute,
                                 schedule_days=routine.schedule_days, timezone=routine.timezone,
                                 next_fires_at=routine.next_fires_at, status=routine.status))


@router.delete("/applications/{plan_id}/routines/{routine_id}")
def cancel_application_routine(plan_id: str, routine_id: str, network: str = Query(...),
                               db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                               authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization, write=True)
    if error:
        return error
    plan = _owned_plan(db, str(workspace.id), plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    routine = db.execute(select(RoutineRecord).join(ApplicationRoutine, ApplicationRoutine.routine_id == RoutineRecord.id)
                         .where(ApplicationRoutine.application_id == plan.id,
                                RoutineRecord.id == routine_id,
                                RoutineRecord.workspace_id == str(workspace.id))).scalar_one_or_none()
    if routine is None:
        return json_response(ResponseCode.NOT_FOUND, "Routine not found")
    routine.status = "cancelled"
    db.commit()
    return success_response({"cancelled": True})
