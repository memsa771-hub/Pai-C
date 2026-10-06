"""Bounded current application context for a scheduled review."""
from sqlalchemy import select

from app.models import ApplicationPlan, ApplicationRequirement, Institution, KanbanTask


def build_review_context(db, workspace_id: str, application_id: str) -> str:
    row = db.execute(select(ApplicationPlan, Institution).join(
        Institution, ApplicationPlan.institution_id == Institution.id).where(
        ApplicationPlan.id == application_id, ApplicationPlan.workspace_id == workspace_id,
    )).first()
    if row is None:
        return "This application plan is no longer available. Do not invent its details."
    plan, institution = row
    requirements = db.execute(select(ApplicationRequirement).where(
        ApplicationRequirement.application_id == plan.id,
    ).order_by(ApplicationRequirement.position).limit(20)).scalars().all()
    task_ids = [item.task_id for item in requirements if item.task_id]
    tasks = {task.id: task for task in db.execute(select(KanbanTask).where(
        KanbanTask.workspace_id == workspace_id, KanbanTask.id.in_(task_ids))).scalars()} if task_ids else {}
    lines = ["Current student-managed application plan (not institution-verified):",
             f"Institution: {institution.name} ({institution.country_code})",
             f"Program: {plan.program_name or 'not entered'}",
             f"Intake: {plan.intake or 'not entered'}",
             f"Status: {plan.status} (origin: {plan.status_origin})",
             f"Deadline: {plan.deadline_at.date().isoformat() if plan.deadline_at else 'not entered'}",
             "Requirements:"]
    if requirements:
        for item in requirements:
            task = tasks.get(item.task_id)
            status = "done" if task and task.status == "done" else item.status
            lines.append(f"- {item.label[:160]}: {status}; due {item.due_at.date().isoformat() if item.due_at else 'not entered'}")
    else:
        lines.append("- None recorded; ask the student to verify official requirements.")
    lines.append("Discuss progress and missing information. Never claim an external submission occurred without a verified receipt.")
    return "\n".join(lines)[:3500]
