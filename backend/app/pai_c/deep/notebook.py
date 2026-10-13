"""Private, workspace-scoped Counselor Notebook persistence.

Callers must supply the source student event. A stale writer receives a
NotebookVersionConflict and must fetch the latest version before retrying.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.deep.notebook_sanitize import SanitizationIssue, sanitize_notebook
from app.models import CounselorNotebook, CounselorNotebookHistory, CounselorNotedQuestion, EventRecord, Workspace


class NotebookVersionConflict(Exception):
    """The caller must refetch and recompute against a newer notebook."""


class NotebookWorkspaceNotFound(Exception):
    """The workspace does not exist or has been deleted."""


@dataclass(frozen=True)
class NotebookSnapshot:
    notebook: CounselorNotebookData
    version: int
    last_event_id: str | None


class NotebookService:
    def __init__(self, db: Session):
        self.db = db

    def _require_workspace(self, workspace_id: str) -> None:
        workspace = self.db.execute(
            select(Workspace.id).where(Workspace.id == workspace_id, Workspace.status == "active")
        ).scalar_one_or_none()
        if workspace is None:
            raise NotebookWorkspaceNotFound(workspace_id)

    def get(self, workspace_id: str) -> NotebookSnapshot:
        self._require_workspace(workspace_id)
        row = self.db.execute(
            select(CounselorNotebook).where(CounselorNotebook.workspace_id == workspace_id)
        ).scalar_one_or_none()
        if row is None:
            return NotebookSnapshot(CounselorNotebookData(), 0, None)
        return NotebookSnapshot(CounselorNotebookData.model_validate(row.notebook), row.version, row.last_event_id)

    def apply(
        self, workspace_id: str, new_notebook: CounselorNotebookData | dict,
        source_event_id: str, *, expected_version: int | None = None,
    ) -> tuple[NotebookSnapshot, list[SanitizationIssue]]:
        """Validate, sanitize and atomically write one complete snapshot.

        expected_version is optional for first-party callers that load and
        apply in one operation. Long-lived callers should pass the version
        returned by get, so stale writes never silently replace newer notes.
        """
        # Serialize notebook writes with workspace soft deletion. The delete
        # route takes the same workspace row lock before purging private data.
        workspace = self.db.execute(
            select(Workspace.id).where(
                Workspace.id == workspace_id, Workspace.status == "active"
            ).with_for_update()
        ).scalar_one_or_none()
        if workspace is None:
            raise NotebookWorkspaceNotFound(workspace_id)
        if not source_event_id or not self.db.execute(
            select(EventRecord.id).where(
                EventRecord.id == source_event_id,
                EventRecord.network_id == workspace_id,
                EventRecord.source.like("human:%"),
            )
        ).scalar_one_or_none():
            raise ValueError("source_event_id must be a student event in this workspace")

        raw = new_notebook.model_dump(mode="json") if isinstance(new_notebook, CounselorNotebookData) else new_notebook
        if not isinstance(raw, dict):
            raise ValueError("notebook must be an object")
        if "legacy_v1" in raw:
            raise ValueError("legacy_v1 is read-only")
        clean, changes = sanitize_notebook(raw)
        current = self.get(workspace_id)
        empty = CounselorNotebookData().model_dump(mode="json")
        payload = clean.model_dump(mode="json")
        if current.notebook.model_dump(mode="json") != empty and payload == empty:
            raise ValueError("sanitization would erase the existing notebook")
        if expected_version is not None and current.version != expected_version:
            raise NotebookVersionConflict(f"expected {expected_version}, found {current.version}")
        # Historical evidence is immutable and is never supplied by a model.
        clean = clean.model_copy(update={"legacy_v1": current.notebook.legacy_v1})
        # Retain all earlier certainty ratings, even when the Analyst omits them.
        old_rating = current.notebook.sure
        history = list(old_rating.history)
        if old_rating.score is not None and (old_rating.score, old_rating.reason, old_rating.asked_at) != (clean.sure.score, clean.sure.reason, clean.sure.asked_at):
            from app.pai_c.deep.notebook_schema import Rating
            history.append(Rating(score=old_rating.score, reason=old_rating.reason, asked_at=old_rating.asked_at))
        for rating in clean.sure.history:
            if rating not in history:
                history.append(rating)
        clean = clean.model_copy(update={"sure": clean.sure.model_copy(update={"history": history})})
        payload = clean.storage_data()
        version = current.version + 1
        now = datetime.now(timezone.utc)
        if current.version:
            result = self.db.execute(
                update(CounselorNotebook).where(
                    CounselorNotebook.workspace_id == workspace_id,
                    CounselorNotebook.version == current.version,
                ).values(notebook=payload, version=version, updated_at=now, last_event_id=source_event_id)
            )
            if result.rowcount != 1:
                self.db.rollback()
                raise NotebookVersionConflict("notebook changed during apply")
        else:
            try:
                with self.db.begin_nested():
                    self.db.add(CounselorNotebook(
                        workspace_id=workspace_id, notebook=payload, version=version,
                        updated_at=now, last_event_id=source_event_id,
                    ))
                    self.db.flush()
            except IntegrityError as exc:
                self.db.rollback()
                raise NotebookVersionConflict("notebook created during apply") from exc
        self.db.add(CounselorNotebookHistory(
            workspace_id=workspace_id, notebook=payload, version=version,
            source_event_id=source_event_id, created_at=now,
        ))
        self.db.commit()
        return NotebookSnapshot(clean, version, source_event_id), changes

    def delete_for_workspace(self, workspace_id: str) -> None:
        """Purge private notes within the caller's workspace-delete transaction."""
        self.db.execute(delete(CounselorNotedQuestion).where(CounselorNotedQuestion.workspace_id == workspace_id))
        self.db.execute(delete(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == workspace_id))
        self.db.execute(delete(CounselorNotebook).where(CounselorNotebook.workspace_id == workspace_id))
