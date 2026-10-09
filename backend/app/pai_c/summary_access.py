"""Workspace-isolated access to a current Counselor Mirror draft."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models import StudentJourney


def _journey(db, workspace_id):
    row = db.scalar(select(StudentJourney).where(
        StudentJourney.workspace_id == workspace_id,
        StudentJourney.journey_type == "counselor_decision", StudentJourney.status == "active",
    ).with_for_update())
    if row is None or (row.counselor_summary_draft or {}).get("type") != "mirror":
        raise HTTPException(409, "No current Mirror")
    return row
