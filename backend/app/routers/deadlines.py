"""Central student deadline read model and personal date management."""
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.deadlines.service import deadline_settings, expire_deadline_notices, list_deadlines
from app.models import DeadlineSettings, StudentDeadline
from app.application_workspace.access import _auth

router = APIRouter(prefix="/v1/deadlines", tags=["Student Deadlines"])


class PersonalDeadlineInput(BaseModel):
    network: str
    title: str = Field(min_length=1, max_length=240)
    due_on: date
    category: str = Field(default="other", min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    source_url: AnyHttpUrl | None = None


class PersonalDeadlineUpdate(BaseModel):
    network: str
    title: str | None = Field(default=None, min_length=1, max_length=240)
    due_on: date | None = None
    category: str | None = Field(default=None, min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    source_url: AnyHttpUrl | None = None
    status: Literal["open", "done"] | None = None


class SettingsUpdate(BaseModel):
    network: str
    timezone: str = Field(min_length=1, max_length=100)
    reminder_days: list[int] = Field(max_length=12)


def _personal(row: StudentDeadline):
    return dict(id=f"personal:{row.id}", source="personal", source_id=row.id,
                application_id=None, title=row.title, date=row.due_on.isoformat(),
                status=row.status, category=row.category, source_url=row.source_url,
                notes=row.notes, institution=None)


@router.get("")
def get_deadlines(network: str = Query(...), start: date = Query(...), end: date = Query(...),
                  db: Session = Depends(get_db), x_workspace_token: str | None = Header(None),
                  authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization)
    if error:
        return error
    if end < start or (end - start).days > 366:
        return json_response(ResponseCode.BAD_REQUEST, "Choose a range of at most one year")
    return success_response({"deadlines": list_deadlines(db, str(workspace.id), start, end),
                             "settings": deadline_settings(db, str(workspace.id))})


@router.post("")
def create_deadline(body: PersonalDeadlineInput, db: Session = Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    if not body.title.strip() or not body.category.strip():
        return json_response(ResponseCode.BAD_REQUEST, "Title and category are required")
    row = StudentDeadline(workspace_id=str(workspace.id), title=body.title.strip(),
                          due_on=body.due_on, category=body.category.strip(), notes=body.notes,
                          source_url=str(body.source_url) if body.source_url else None)
    db.add(row)
    db.commit()
    return success_response(_personal(row))


@router.patch("/{deadline_id}")
def update_deadline(deadline_id: str, body: PersonalDeadlineUpdate, db: Session = Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    row = db.execute(select(StudentDeadline).where(StudentDeadline.id == deadline_id,
                                                   StudentDeadline.workspace_id == str(workspace.id))).scalar_one_or_none()
    if row is None:
        return json_response(ResponseCode.NOT_FOUND, "Deadline not found")
    values = body.model_dump(exclude_unset=True, exclude={"network"})
    if "title" in values:
        if not values["title"] or not values["title"].strip():
            return json_response(ResponseCode.BAD_REQUEST, "Title is required")
        values["title"] = values["title"].strip()
    if "category" in values:
        if not values["category"] or not values["category"].strip():
            return json_response(ResponseCode.BAD_REQUEST, "Category is required")
        values["category"] = values["category"].strip()
    if "due_on" in values and values["due_on"] is None:
        return json_response(ResponseCode.BAD_REQUEST, "Due date is required")
    if "source_url" in values:
        values["source_url"] = str(values["source_url"]) if values["source_url"] else None
    for key, value in values.items():
        setattr(row, key, value)
    expire_deadline_notices(db, str(workspace.id), "personal", row.id)
    db.commit()
    return success_response(_personal(row))


@router.delete("/{deadline_id}")
def delete_deadline(deadline_id: str, network: str = Query(...), db: Session = Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, network, x_workspace_token, authorization, write=True)
    if error:
        return error
    row = db.execute(select(StudentDeadline).where(StudentDeadline.id == deadline_id,
                                                   StudentDeadline.workspace_id == str(workspace.id))).scalar_one_or_none()
    if row is None:
        return json_response(ResponseCode.NOT_FOUND, "Deadline not found")
    expire_deadline_notices(db, str(workspace.id), "personal", row.id)
    db.delete(row)
    db.commit()
    return success_response({"deleted": True})


@router.put("/settings/reminders")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace, error = _auth(db, body.network, x_workspace_token, authorization, write=True)
    if error:
        return error
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return json_response(ResponseCode.BAD_REQUEST, "Unknown timezone")
    if any(day < -30 or day > 365 for day in body.reminder_days):
        return json_response(ResponseCode.BAD_REQUEST, "Reminder days must be between -30 and 365")
    row = db.get(DeadlineSettings, str(workspace.id))
    if row is None:
        row = DeadlineSettings(workspace_id=str(workspace.id))
        db.add(row)
    row.timezone = body.timezone
    row.reminder_days = sorted(set(body.reminder_days), reverse=True)
    db.commit()
    return success_response(deadline_settings(db, str(workspace.id)))
