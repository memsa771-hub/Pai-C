"""Confirm or correct the exact profile value the student reviewed."""
from typing import Any, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from app.api.response import success_response
from app.database import get_db
from app.routers.roadmaps import _authorized
from app.pai_c.memory import MemoryService

router = APIRouter(prefix="/v1/counselor/profile-cards", tags=["Counselor"])


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: UUID
    action: Literal["confirm", "edit"]
    expected_digest: str = Field(min_length=64, max_length=64)
    value: Any = None
    text: str = Field(default="", max_length=4000)


@router.get("")
def cards(network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return success_response({"cards": MemoryService(db).profile_cards(str(workspace.id))})


@router.post("/{kind}/{record_id}")
def review(kind: str, record_id: str, body: Review, network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    try:
        result = MemoryService(db).review_profile_card(str(workspace.id), kind, record_id, body)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    if not result["saved"]:
        raise HTTPException(409, "The profile needs clarification before saving")
    return success_response(result)
