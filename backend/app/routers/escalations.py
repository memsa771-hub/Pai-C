"""Internal intake for a future OS task that returns a route to Counselor."""

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select

from app.api.response import success_response
from app.config import config
from app.database import get_db
from app.journey import JourneyService
from app.models import StudentJourney
from app.pai_c.connect.flags import part_on

router = APIRouter(prefix="/v1/escalations", tags=["Counselor hand-off"])


_LEGACY = ("route_not_possible", "all_rejected", "blocking_gap")
_EXPECTED = "'route_not_possible', 'all_rejected' or 'blocking_gap'"


class EscalationInput(BaseModel):
    workspace_id: str
    journey_id: str
    # The legacy three, plus the three codes PAI OS sends when CONNECT_HANDOFF is on (R-11). With the part off the
    # validator refuses any other value with today's literal_error, so the 422 is the one it always was.
    reason_type: Literal["route_not_possible", "all_rejected", "blocking_gap", "not_eligible", "deadline_passed",
                         "other"]
    details: str = Field(min_length=3, max_length=2000)
    decision_version: int | None = Field(None, ge=1)

    @field_validator("reason_type", mode="before")
    @classmethod
    def _legacy_while_off(cls, value):
        if value not in _LEGACY and not part_on("CONNECT_HANDOFF"):
            raise PydanticCustomError("literal_error", "Input should be {expected}", {"expected": _EXPECTED})
        return value

    @field_validator("decision_version", mode="before")
    @classmethod
    def _version_only_when_on(cls, value):
        """With the part off the field is an extra one, ignored and never validated, as before."""
        return value if part_on("CONNECT_HANDOFF") else None


@router.post("")
def escalate(body: EscalationInput, db=Depends(get_db),
             x_pai_service_token: str | None = Header(None)):
    handoff = part_on("CONNECT_HANDOFF")
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
    if handoff:
        return _escalate_v2(body, db, journey)
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


def _escalate_v2(body: EscalationInput, db, journey: StudentJourney):
    """CONNECT_HANDOFF is on (D-x9): works whenever the student has an active decision. A chosen route goes back to
    proposed (the student chooses again); any other stage stays as it is. The decision is not withdrawn."""
    from app.pai_c.roadmap.decisions import RouteDecisionService

    active = RouteDecisionService(db).active(body.workspace_id)
    if active is None:
        raise HTTPException(status_code=409, detail="The student has no active route decision")
    version = body.decision_version
    if version is not None and not _same_choice(db, body.workspace_id, active, version):
        raise HTTPException(status_code=409, detail="The escalation is for a choice the student has since changed")
    previous = journey.current_stage
    if previous == "CHOSEN":
        JourneyService(db).set_counselor_stage(body.workspace_id, journey.id, "PROPOSED",
                                               actor="system:os_escalation")
    decisions = list(journey.decisions or [])
    decisions.append({"kind": "route_escalation", "reason_type": body.reason_type,
                      "details": body.details, "previous_stage": previous,
                      "decision_version": version or active.decision_version,
                      "at": datetime.now(timezone.utc).isoformat()})
    journey.decisions = decisions
    journey.next_recommended_action = {"type": "replan_discussion"}
    db.commit()
    return success_response({"journey_id": journey.id, "stage": journey.current_stage})


def _same_choice(db, workspace_id: str, active, version: int) -> bool:
    """The escalation belongs to a decision version whose choice is still the active one (a stale escalation about a
    choice the student already changed must not send them back to choosing)."""
    from app.models import RouteDecision
    from app.pai_c.roadmap.decisions import choice_of

    if version > active.decision_version:
        return False
    if version == active.decision_version:
        return True
    row = db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == workspace_id,
                                                RouteDecision.decision_version == version))
    return row is not None and choice_of(row) == choice_of(active)
