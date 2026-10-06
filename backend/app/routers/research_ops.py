"""Restricted evidence review endpoint for Placement AI operators."""

import os
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.research.requirements import RequirementStore, ResearchEvidenceError

router = APIRouter(prefix="/v1/ops/research", tags=["Research operations"])


class ReviewRequest(BaseModel):
    workspace_id: str
    decision: Literal["verified", "expired"]


@router.post("/requirements/{requirement_id}/review")
def review_requirement(requirement_id: str, body: ReviewRequest,
                       x_pai_ops_token: str | None = Header(None), db=Depends(get_db)):
    expected = os.environ.get("PAI_OPS_REVIEW_TOKEN", "")
    if not expected or not x_pai_ops_token or not secrets.compare_digest(expected, x_pai_ops_token):
        raise HTTPException(status_code=403, detail="Operations review credential required")
    try:
        row = RequirementStore(db).review(body.workspace_id, requirement_id,
                                          reviewer="ops", decision=body.decision)
    except ResearchEvidenceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"id": row.id, "status": row.status, "reviewed_at": row.reviewed_at.isoformat()}
