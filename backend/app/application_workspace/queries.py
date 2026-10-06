"""Scoped lookups shared by catalog, plans and operations."""
from sqlalchemy import or_, select

from app.models import ApplicationPlan, Institution


def _visible_institution(db, workspace_id, institution_id):
    return db.execute(select(Institution).where(
        Institution.id == institution_id,
        or_(Institution.owner_workspace_id.is_(None), Institution.owner_workspace_id == workspace_id),
    )).scalar_one_or_none()


def _owned_plan(db, workspace_id, plan_id):
    return db.execute(select(ApplicationPlan).where(
        ApplicationPlan.id == plan_id,
        ApplicationPlan.workspace_id == workspace_id,
    )).scalar_one_or_none()
