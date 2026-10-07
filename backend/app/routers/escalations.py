"""Internal intake for a future OS task that returns a route to Counselor."""

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.response import success_response
from app.config import config
from app.database import get_db
from app.journey import JourneyService
from app.models import StudentJourney

router = APIRouter(prefix="/v1/escalations", tags=["Counselor hand-off"])


class EscalationInput(BaseModel):
    workspace_id: str
    journey_id: str
    reason_type: Literal["route_not_possible", "all_rejected", "blocking_gap"]
    details: str = Field(min_length=3, max_length=2000)


@router.post("")
def escalate(body: EscalationInput, db=Depends(get_db),
             x_pai_service_token: str | None = Header(None)):
    if not config.PAI_OS_SERVICE_TOKEN:
        raise HTTPException(status_code=503, detail="OS hand-off is not configured")
    if not x_pai_service_token or not secrets.compare_digest(
            x_pai_service_token, config.PAI_OS_SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid service credentials")
    journey = db.execute(select(StudentJourney).where(
        StudentJourney.id == body.journey_id,
        StudentJourney.workspace_id == body.workspace_id,
        StudentJourney.journey_type == "counselor_decision",
        StudentJourney.status == "active",
    ).with_for_update()).scalar_one_or_none()
    if journey is None:
        raise HTTPException(status_code=404, detail="Counselor journey not found")
    if journey.current_stage not in {"PROPOSED", "CHOSEN"}:
        raise HTTPException(status_code=409, detail="Journey is not at a route decision")
    previous = journey.current_stage
    JourneyService(db).set_counselor_stage(
        body.workspace_id, journey.id, "DIRECTION", actor="system:os_escalation",
        replan_escalation=True)
    decisions = list(journey.decisions or [])
    decisions.append({"kind": "route_escalation", "reason_type": body.reason_type,
                      "details": body.details, "previous_stage": previous,
                      "at": datetime.now(timezone.utc).isoformat()})
    journey.decisions = decisions
    journey.next_recommended_action = {"type": "replan_discussion"}
    db.commit()
    return success_response({"journey_id": journey.id, "stage": "DIRECTION"})
