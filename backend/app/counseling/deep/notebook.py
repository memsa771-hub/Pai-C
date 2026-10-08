"""Private, workspace-scoped Counselor Notebook persistence.

Callers must supply the source student event. A stale writer receives a
NotebookVersionConflict and must fetch the latest version before retrying.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.counseling.deep.notebook_schema import CounselorNotebookData
from app.models import CounselorNotebook, CounselorNotebookHistory, EventRecord, Workspace


# Conservative whole-word filters for protected beliefs/affiliations and
# diagnostic labels. The notebook stores observed behavior instead.
BANNED_TERMS = (
    "adhd", "ocd", "ptsd", "autism", "autistic", "depression",
    "depressed", "anxiety", "anxious", "bipolar", "schizophrenia",
    "dyslexia", "diagnosis", "diagnosed", "disorder",
    "religion", "religious", "muslim", "hindu", "christian", "sikh",
    "buddhist", "atheist", "islam", "hinduism", "christianity",
    "catholic", "jewish", "jain", "jainism",
    "sect", "sunni", "shia", "shiite", "ahmadi", "barelvi", "deobandi",
    "caste", "brahmin", "dalit", "rajput",
    "politics", "political", "party affiliation", "democrat", "republican",
    "pti", "pml-n", "pmln", "ppp", "bjp",
)
_BANNED = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(term) for term in sorted(BANNED_TERMS, key=len, reverse=True)) + r")(?!\w)", re.IGNORECASE)


def _strip_banned(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s{2,}", " ", _BANNED.sub("", value)).strip()
    if isinstance(value, list):
        return [_strip_banned(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_banned(item) for key, item in value.items()}
    return value


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
    ) -> NotebookSnapshot:
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
        # Validate both sides of sanitization: malformed input is never
        # normalized into validity, and stripping cannot remove evidence.
        parsed = CounselorNotebookData.model_validate(raw)
        clean = CounselorNotebookData.model_validate(_strip_banned(parsed.model_dump(mode="json")))
        payload = clean.model_dump(mode="json")
        current = self.get(workspace_id)
        if expected_version is not None and current.version != expected_version:
            raise NotebookVersionConflict(f"expected {expected_version}, found {current.version}")
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
        return NotebookSnapshot(clean, version, source_event_id)

    def delete_for_workspace(self, workspace_id: str) -> None:
        """Purge private notes within the caller's workspace-delete transaction."""
        self.db.execute(delete(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == workspace_id))
        self.db.execute(delete(CounselorNotebook).where(CounselorNotebook.workspace_id == workspace_id))
