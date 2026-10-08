"""Persist deferred questions without starting research or calling a model."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import CounselorNotedQuestion, EventRecord, Workspace


class NotedQuestionService:
    def __init__(self, db):
        self.db = db

    def record(self, workspace_id: str, source_event_id: str, question: object) -> str:
        if not isinstance(question, str) or not question.strip() or not source_event_id:
            return "ignored"
        workspace = self.db.scalar(select(Workspace).where(
            Workspace.id == workspace_id, Workspace.status == "active").with_for_update())
        if workspace is None:
            self.db.rollback()
            return "ignored"
        source = self.db.scalar(select(EventRecord.id).where(
            EventRecord.id == source_event_id, EventRecord.network_id == workspace_id,
            EventRecord.source == f"human:{workspace.owner_user_id}",
            EventRecord.type == "workspace.message.posted"))
        if source is None:
            self.db.rollback()
            return "ignored"
        existing = select(CounselorNotedQuestion.id).where(
            CounselorNotedQuestion.workspace_id == workspace_id,
            CounselorNotedQuestion.source_event_id == source_event_id)
        if self.db.scalar(existing):
            self.db.rollback()
            return "duplicate"
        self.db.add(CounselorNotedQuestion(
            workspace_id=workspace_id, source_event_id=source_event_id,
            question_to_research=question.strip(), status="open"))
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if self.db.scalar(existing):
                return "duplicate"
            raise
        return "recorded"
