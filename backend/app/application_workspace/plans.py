"""Per-program application plans and sourced requirements."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.models import ApplicationPlan, ApplicationRequirement, ApplicationRoutine, Institution, KanbanTask, RoutineRecord, SavedInstitution
from .access import _auth
from .queries import _owned_plan, _visible_institution
from .schemas import PlanInput, PlanUpdate, RequirementInput, RequirementUpdate
from .serializers import _plan, _requirement

router = APIRouter()

@router.get("/applications")
def list_applications(network: str = Query(...), db: Session = Depends(get_db),
                      x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization)
    if error:
        return error
    rows = db.execute(select(ApplicationPlan, Institution).join(Institution, ApplicationPlan.institution_id == Institution.id)
                      .where(ApplicationPlan.workspace_id == str(workspace.id))
                      .order_by(ApplicationPlan.created_at.desc())).all()
    return success_response([_plan(plan, institution) for plan, institution in rows])


@router.post("/applications")
def create_application(body: PlanInput, db: Session = Depends(get_db),
                       x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    workspace_id = str(workspace.id)
    institution = _visible_institution(db, workspace_id, body.institution_id)
    if institution is None:
        return json_response(ResponseCode.NOT_FOUND, "Institution not found")
    duplicate = db.execute(select(ApplicationPlan.id).where(
        ApplicationPlan.workspace_id == workspace_id,
        ApplicationPlan.institution_id == institution.id,
        func.lower(func.coalesce(ApplicationPlan.program_name, "")) == (body.program_name or "").strip().lower(),
        func.lower(func.coalesce(ApplicationPlan.intake, "")) == (body.intake or "").strip().lower(),
    )).first()
    if duplicate:
        return json_response(ResponseCode.CONFLICT, "A plan for this college, program and intake already exists")
    plan = ApplicationPlan(workspace_id=workspace_id, institution_id=institution.id,
                           program_name=(body.program_name or "").strip() or None,
                           intake=(body.intake or "").strip() or None, route=(body.route or "").strip() or None,
                           deadline_at=body.deadline_at, application_url=str(body.application_url) if body.application_url else None,
                           notes=body.notes)
    db.add(plan)
    if db.execute(select(SavedInstitution.id).where(SavedInstitution.workspace_id == workspace_id,
                                                   SavedInstitution.institution_id == institution.id)).first() is None:
        db.add(SavedInstitution(workspace_id=workspace_id, institution_id=institution.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return json_response(ResponseCode.CONFLICT, "A plan for this college, program and intake already exists")
    return success_response(_plan(plan, institution))


@router.get("/applications/{plan_id}")
def get_application(plan_id: str, network: str = Query(...), db: Session = Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization)
    if error:
        return error
    plan = _owned_plan(db, str(workspace.id), plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    requirements = db.execute(select(ApplicationRequirement).where(ApplicationRequirement.application_id == plan.id)
                              .order_by(ApplicationRequirement.position, ApplicationRequirement.created_at)).scalars().all()
    task_ids = [row.task_id for row in requirements if row.task_id]
    tasks = {task.id: task for task in db.execute(select(KanbanTask).where(
        KanbanTask.workspace_id == str(workspace.id), KanbanTask.id.in_(task_ids))).scalars()} if task_ids else {}
    routines = db.execute(select(RoutineRecord).join(ApplicationRoutine, ApplicationRoutine.routine_id == RoutineRecord.id)
                          .where(ApplicationRoutine.application_id == plan.id,
                                 RoutineRecord.workspace_id == str(workspace.id))
                          .order_by(RoutineRecord.next_fires_at)).scalars().all()
    return success_response(_plan(plan, db.get(Institution, plan.institution_id), requirements, tasks, routines))


@router.patch("/applications/{plan_id}")
def update_application(plan_id: str, body: PlanUpdate, db: Session = Depends(get_db),
                       x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    plan = _owned_plan(db, str(workspace.id), plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    values = body.model_dump(exclude_unset=True, exclude={"network"})
    for key in ("program_name", "intake", "route"):
        if key in values:
            values[key] = (values[key] or "").strip() or None
    if "application_url" in values:
        values["application_url"] = str(values["application_url"]) if values["application_url"] else None
    if values.get("status") == "submitted" and plan.status != "submitted":
        plan.submitted_at = datetime.now(timezone.utc)
    elif values.get("status") in {"planning", "preparing", "ready", "withdrawn"}:
        plan.submitted_at = None
    for key, value in values.items():
        setattr(plan, key, value)
    if "status" in values:
        plan.status_origin = "student"
    if {"deadline_at", "status"} & values.keys():
        from app.deadlines.service import expire_deadline_notices
        expire_deadline_notices(db, str(workspace.id), "application", plan.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return json_response(ResponseCode.CONFLICT, "A plan for this college, program and intake already exists")
    return success_response(_plan(plan, db.get(Institution, plan.institution_id)))


@router.post("/applications/{plan_id}/requirements")
def add_requirement(plan_id: str, body: RequirementInput, db: Session = Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    plan = _owned_plan(db, str(workspace.id), plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    position = db.execute(select(func.coalesce(func.max(ApplicationRequirement.position), -1) + 1)
                          .where(ApplicationRequirement.application_id == plan.id)).scalar_one()
    row = ApplicationRequirement(application_id=plan.id, label=body.label.strip(), kind=body.kind.strip(),
                                 due_at=body.due_at, source_url=str(body.source_url) if body.source_url else None,
                                 notes=body.notes, position=position)
    db.add(row)
    db.commit()
    return success_response(_requirement(row))


@router.patch("/applications/{plan_id}/requirements/{requirement_id}")
def update_requirement(plan_id: str, requirement_id: str, body: RequirementUpdate,
                       db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                       authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    plan = _owned_plan(db, str(workspace.id), plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    row = db.execute(select(ApplicationRequirement).where(ApplicationRequirement.id == requirement_id,
                                                           ApplicationRequirement.application_id == plan.id)).scalar_one_or_none()
    if row is None:
        return json_response(ResponseCode.NOT_FOUND, "Requirement not found")
    values = body.model_dump(exclude_unset=True, exclude={"network"})
    if "source_url" in values:
        values["source_url"] = str(values["source_url"]) if values["source_url"] else None
    if "task_id" in values and values["task_id"] is not None:
        from app.models import KanbanTask
        if db.execute(select(KanbanTask.id).where(KanbanTask.id == values["task_id"],
                                                  KanbanTask.workspace_id == str(workspace.id))).first() is None:
            return json_response(ResponseCode.BAD_REQUEST, "Task not found in workspace")
    if "file_id" in values and values["file_id"] is not None:
        from app.models import FileRecord
        if db.execute(select(FileRecord.id).where(FileRecord.id == values["file_id"],
                                                 FileRecord.workspace_id == str(workspace.id),
                                                 FileRecord.status == "active")).first() is None:
            return json_response(ResponseCode.BAD_REQUEST, "File not found in workspace")
    for key, value in values.items():
        setattr(row, key, value)
    if {"due_at", "status", "task_id"} & values.keys():
        from app.deadlines.service import expire_deadline_notices
        expire_deadline_notices(db, str(workspace.id), "requirement", row.id)
    db.commit()
    return success_response(_requirement(row))


@router.delete("/applications/{plan_id}/requirements/{requirement_id}")
def delete_requirement(plan_id: str, requirement_id: str, network: str = Query(...),
                       db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                       authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization, write=True)
    if error:
        return error
    plan = _owned_plan(db, str(workspace.id), plan_id)
    if plan is None:
        return json_response(ResponseCode.NOT_FOUND, "Application not found")
    row = db.execute(select(ApplicationRequirement).where(ApplicationRequirement.id == requirement_id,
                                                           ApplicationRequirement.application_id == plan.id)).scalar_one_or_none()
    if row is None:
        return json_response(ResponseCode.NOT_FOUND, "Requirement not found")
    from app.deadlines.service import expire_deadline_notices
    expire_deadline_notices(db, str(workspace.id), "requirement", row.id)
    db.delete(row)
    db.commit()
    return success_response({"deleted": True})


