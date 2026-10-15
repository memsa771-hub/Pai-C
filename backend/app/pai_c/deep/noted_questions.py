"""Persist student requests without starting research or calling a model."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import CounselorNotedQuestion, EventRecord, Workspace


def request_policy():
    return json.loads(Path(__file__).with_name("request_policy.json").read_text(encoding="utf-8"))


_UNSET = object()


class NotedQuestionService:
    def __init__(self, db):
        self.db = db

    def open_requests(self, workspace_id: str) -> list[dict]:
        policy = request_policy()
        rows = self.db.scalars(select(CounselorNotedQuestion).where(
            CounselorNotedQuestion.workspace_id == workspace_id,
            CounselorNotedQuestion.status == policy["context_status"],
        ).order_by(CounselorNotedQuestion.created_at.desc(), CounselorNotedQuestion.id.desc())
          .limit(policy["context_limit"])).all()
        return [{"text": row.question_to_research, "kind": row.kind} for row in rows]

    def record(self, workspace_id: str, source_event_id: str, question: object, *,
               kind: object = _UNSET, needs_research: object = _UNSET,
               answered_event_id: str | None = None, pending: bool = False) -> str:
        if not isinstance(question, str) or not question.strip() or not source_event_id:
            return "ignored"
        policy = request_policy()
        kind = policy["default_kind"] if kind is _UNSET else kind
        needs_research = policy["default_needs_research"] if needs_research is _UNSET else needs_research
        if kind not in policy["kinds"] or type(needs_research) is not bool:
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
        if not needs_research and not pending:
            reply = self.db.scalar(select(EventRecord.id).where(
                EventRecord.id == answered_event_id, EventRecord.network_id == workspace_id,
                EventRecord.source == "openagents:pai", EventRecord.type == "workspace.message.posted"))
            if reply is None:
                self.db.rollback()
                return "ignored"
        self.db.add(CounselorNotedQuestion(
            workspace_id=workspace_id, source_event_id=source_event_id,
            question_to_research=question.strip(), kind=kind, needs_research=needs_research,
            status=policy["pending_status"] if needs_research or pending else policy["immediate_status"],
            answered_event_id=None if needs_research else answered_event_id))
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if self.db.scalar(existing):
                return "duplicate"
            raise
        return "recorded"

    def mark_answered_now(self, workspace_id, source_event_id, answered_event_id):
        policy = request_policy()
        row = self.db.scalar(select(CounselorNotedQuestion).where(
            CounselorNotedQuestion.workspace_id == workspace_id,
            CounselorNotedQuestion.source_event_id == source_event_id).with_for_update())
        reply = self.db.scalar(select(EventRecord.id).where(
            EventRecord.id == answered_event_id, EventRecord.network_id == workspace_id,
            EventRecord.source == "openagents:pai", EventRecord.type == "workspace.message.posted"))
        if row is None or reply is None or row.needs_research or row.status != policy["pending_status"]:
            self.db.rollback()
            return False
        row.status = policy["immediate_status"]
        row.answered_event_id = answered_event_id
        self.db.commit()
        return True
