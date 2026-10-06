"""Response projections; these do not mutate Vault or application records."""
from app.models import ApplicationPlan, ApplicationRequirement, Institution, KanbanTask

def _institution(row: Institution, saved=False):
    return dict(id=row.id, name=row.name, country_code=row.country_code,
                city=row.city, website_url=row.website_url, source=row.source,
                provider=row.provider, saved=saved)


def _requirement(row: ApplicationRequirement, task: KanbanTask | None = None):
    effective_status = "done" if task and task.status == "done" else row.status
    return dict(id=row.id, label=row.label, kind=row.kind, status=effective_status,
                due_at=row.due_at, source_url=row.source_url, notes=row.notes,
                source_type=row.source_type, source_checked_at=row.source_checked_at,
                task_id=row.task_id, task_status=task.status if task else None,
                workflow_id=task.workflow_id if task else None,
                file_id=row.file_id, position=row.position)


def _plan(row: ApplicationPlan, institution: Institution, requirements=None, tasks=None, routines=None):
    return dict(id=row.id, institution=_institution(institution), program_name=row.program_name,
                intake=row.intake, route=row.route, status=row.status, status_origin=row.status_origin,
                deadline_at=row.deadline_at, application_url=row.application_url,
                notes=row.notes, submitted_at=row.submitted_at,
                submission_reference=row.submission_reference,
                requirements=[_requirement(r, (tasks or {}).get(r.task_id)) for r in requirements] if requirements is not None else None,
                routines=[dict(id=r.id, name=r.name, message=r.message, schedule_hour=r.schedule_hour,
                               schedule_minute=r.schedule_minute, schedule_days=r.schedule_days,
                               timezone=r.timezone, next_fires_at=r.next_fires_at,
                               status=r.status) for r in routines] if routines is not None else None,
                created_at=row.created_at, updated_at=row.updated_at)


