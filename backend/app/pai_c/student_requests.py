"""Durable research questions for the student (PAI OS contract). The old roadmap
research runs no longer create new ones; existing rows stay readable."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import StudentRequest


class StudentRequestService:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def serialize(row: StudentRequest) -> dict:
        return {key: getattr(row, key) for key in (
            "id", "source", "execution_run_id", "item_key", "reason",
            "accepts_upload", "status") } | {
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "asked_at": row.asked_at.isoformat() if row.asked_at else None,
            "answered_at": row.answered_at.isoformat() if row.answered_at else None,
        }

    def list(self, workspace_id: str, *, status: str = "open") -> list[dict]:
        query = select(StudentRequest).where(StudentRequest.workspace_id == workspace_id)
        if status != "all":
            query = query.where(StudentRequest.status == status)
        rows = self.db.execute(query.order_by(StudentRequest.created_at,
                                              StudentRequest.id)).scalars().all()
        return [self.serialize(row) for row in rows]

    def oldest_open(self, workspace_id: str) -> StudentRequest | None:
        return self.db.execute(select(StudentRequest).where(
            StudentRequest.workspace_id == workspace_id,
            StudentRequest.status == "open",
        ).order_by(StudentRequest.created_at, StudentRequest.id).limit(1)).scalar_one_or_none()

    def mark_answered(self, workspace_id: str, run_id: str, field: str) -> None:
        row = self.db.execute(select(StudentRequest).where(
            StudentRequest.workspace_id == workspace_id,
            StudentRequest.execution_run_id == run_id,
            StudentRequest.item_key == field,
            StudentRequest.status.in_(("open", "withdrawn"))).with_for_update()).scalar_one_or_none()
        if row:
            row.status = "answered"
            row.answered_at = datetime.now(timezone.utc)

    def mark_asked(self, row: StudentRequest) -> None:
        if row.asked_at is None:
            row.asked_at = datetime.now(timezone.utc)
