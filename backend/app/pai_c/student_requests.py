"""Durable research questions across chat, voice, uploads and roadmap cards."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import ExecutionRun, StudentRequest


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

    def sync_research_run(self, run: ExecutionRun) -> None:
        if run.task_type != "roadmap_research":
            return
        if run.status in {"completed", "failed"}:
            for row in self.db.execute(select(StudentRequest).where(
                StudentRequest.execution_run_id == run.id,
                StudentRequest.status == "open")).scalars():
                row.status = "withdrawn"
            self.db.flush()
            return
        pending = run.pending_action or {}
        if run.status != "needs_user_action" or pending.get("type") != "need_from_student":
            return
        for item in pending.get("items") or []:
            if not isinstance(item, dict) or not item.get("field"):
                continue
            key = str(item["field"])
            existing = self.db.execute(select(StudentRequest).where(
                StudentRequest.execution_run_id == run.id,
                StudentRequest.item_key == key)).scalar_one_or_none()
            if existing is None:
                row = StudentRequest(
                    workspace_id=run.workspace_id, source="research",
                    execution_run_id=run.id, item_key=key,
                    reason=str(item.get("reason") or "PAI needs this to compare the route"),
                    accepts_upload=bool(item.get("accepts_upload")))
                self.db.add(row)
                self.db.flush()
                from app.services.notify import notify_once
                notify_once(self.db, run.workspace_id,
                            dedupe_key=f"research-request:{row.id}",
                            source="system:roadmaps", title="PAI needs one detail",
                            message="A research question is ready in Counselor",
                            link_url="/roadmaps")
            elif existing.status != "open":
                existing.status = "open"
                existing.reason = str(item.get("reason") or existing.reason)
                existing.accepts_upload = bool(item.get("accepts_upload"))
                existing.answered_at = None
        self.db.flush()

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
