"""The Counsellor's decision export for PAI OS: `pai.decision_record.v2` (P1 spec §3.9). Codes and IDs only, never
the Truth Map or free text. The shape follows app.os.contracts.decision_record_v2; it is validated in the bridge, so
this module does not import app.os."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import RouteDecision, StudentJourney

SCHEMA = "pai.decision_record.v2"


def _utc(at: datetime) -> str:
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _journey_id(db, workspace_id: str) -> str | None:
    """The student's active `counselor_decision` journey (rule D-d)."""
    return db.scalar(select(StudentJourney.id).where(
        StudentJourney.workspace_id == workspace_id, StudentJourney.journey_type == "counselor_decision",
        StudentJourney.status == "active").order_by(StudentJourney.created_at).limit(1))


def decision_record_v2(db, row: RouteDecision) -> dict | None:
    """The export of one decision version, or None when the student has no journey."""
    journey_id = _journey_id(db, row.workspace_id)
    if journey_id is None:
        return None
    return {
        "schema": SCHEMA, "decision_id": row.id, "journey_id": journey_id, "student_ref": row.workspace_id,
        "decision_version": row.decision_version, "status": row.status, "chosen_at": _utc(row.chosen_at),
        "authorized_at": _utc(row.authorized_at) if row.authorized_at else None,
        "guardian_required": bool(row.guardian_required),
        "guardian_authorized_at": _utc(row.guardian_authorized_at) if row.guardian_authorized_at else None,
        "origin_country": row.origin_country, "destination_country": row.destination_country, "level": row.level,
        "path_ref": row.path_ref, "os_supported": bool(row.os_supported),
        "target_intake": dict(row.intake) if row.intake else None,
        "programmes": [{"programme_ref": place["programme_ref"], "rank": place["rank"]}
                       for place in row.places or []],
    }
