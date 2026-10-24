"""Resolve profile conflicts through the canonical reconciliation path."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models import MemoryCandidate, ProfileIssue, VaultItem
from .candidates import MemoryCandidateService
from .errors import MemoryDataError
from .reconciler import MemoryReconciler
from .vault_intake import VaultAssertionService


# both_true: the new value holds now and the old one held before; the old
# value is kept as past (VAULT_SPEC §Conflicts, the four card answers).
ISSUE_ACTIONS = frozenset({"keep_current", "accept_proposed", "both_true", "provide_new"})


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"value"}:
        return value["value"]
    return value


class ProfileIssueService:
    def __init__(self, db):
        self.db = db
        self.candidates = MemoryCandidateService(db)
        self.reconciler = MemoryReconciler(db)

    def resolve(
        self, workspace_id: str, issue_id: str, action: str, *,
        value: Any = None, note: str | None = None, capture: str | None = None,
    ) -> dict:
        """`capture` names the surface that took the answer (e.g. "vault_api") on its evidence."""
        if action not in ISSUE_ACTIONS:
            raise MemoryDataError("Unsupported issue resolution action")
        issue = self.db.execute(
            select(ProfileIssue).where(
                ProfileIssue.id == issue_id,
                ProfileIssue.workspace_id == workspace_id,
                ProfileIssue.status == "open",
            ).with_for_update()
        ).scalar_one_or_none()
        if issue is None:
            raise MemoryDataError("Profile issue not found or already resolved")
        if issue.issue_type == "document_owner":
            return self._resolve_document_owner(workspace_id, issue, action, value, note)

        original = None
        if issue.candidate_id:
            original = self.db.execute(select(MemoryCandidate).where(
                MemoryCandidate.id == issue.candidate_id,
                MemoryCandidate.workspace_id == workspace_id,
            )).scalar_one_or_none()

        if action == "keep_current":
            if original is not None and original.status in ("pending", "needs_review"):
                self.candidates.mark_rejected(original, "Student kept the current canonical value")
                VaultAssertionService(self.db).refresh_decision(original)
            if issue.affected_type == "vault_item" and issue.affected_id:
                # The question is settled: the entry is no longer "In question".
                item = self.db.get(VaultItem, issue.affected_id)
                if item is not None and item.status == "active":
                    item.conflict_state = "none"
            self._close(issue, action, note, None)
            self._replay_waiting_courses(issue, self._kept_education_id(issue))
            return {"resolved": True, "action": action, "id": None}

        if action == "provide_new" and value is None:
            raise MemoryDataError("A new value is required")

        spec = self._candidate_spec(issue, original)
        if issue.affected_type == "vault_item" and issue.affected_id:
            # Answer about the entry the card names, never a loose look-alike.
            spec["entities"] = {**(spec["entities"] or {}), "item_id": issue.affected_id}
        proposed_value = value if action == "provide_new" else spec["proposed_value"]
        candidate = self.candidates.propose(
            workspace_id=workspace_id,
            candidate_type=spec["candidate_type"],
            operation="upsert",
            key=spec["key"],
            proposed_value=proposed_value,
            entities=spec["entities"],
            confidence=1.0,
            source_type="user_explicit",
            allow_user_explicit=True,
            input_channel="profile",
            source_event_ids=original.source_event_ids if original else None,
            evidence={
                "quote": note or "Student resolved a profile conflict.",
                "profile_issue_id": issue.id,
                "resolution_action": action,
                "original_candidate_id": original.id if original else None,
                **({"semantic_temporal_change": True} if action == "both_true" else {}),
                **({"capture": capture} if capture else {}),
            },
            subject_user_id=issue.subject_user_id,
        )
        result = self.reconciler.reconcile(candidate)
        if not result.accepted:
            return {"resolved": False, "action": action, "reason": result.reason}

        if original is not None and original.status in ("pending", "needs_review"):
            original.status = "superseded"
            original.rejection_reason = f"Replaced by confirmed candidate {candidate.id}"
            original.reconciled_at = datetime.now(timezone.utc)
            VaultAssertionService(self.db).refresh_decision(original)
        self._close(issue, action, note, candidate.id)
        self._replay_waiting_courses(issue, result.result_id if spec["key"] == "education" else None)
        return {"resolved": True, "action": action, "id": result.result_id}

    def _resolve_document_owner(self, workspace_id: str, issue: ProfileIssue, action: str,
                                value: Any, note: str | None) -> dict:
        """"Is this your document?" Yes re-reads it with the owner check
        skipped for that one file; no closes the card and applies nothing."""
        file_id = (issue.evidence or {}).get("file_id")
        if action == "both_true":
            raise MemoryDataError("This answer does not apply to a document owner question")
        if action == "provide_new":
            from app.documents.owner import same_person

            # A typed answer counts as "it's mine" only when it names the
            # document's holder ("It's my brother Ali's" does not).
            names = (issue.evidence or {}).get("document_names") or []
            if not (isinstance(value, str) and any(same_person(value, name) for name in names)):
                self._close(issue, "keep_current",
                            note or "The typed name does not match the name on the document.", None)
                return {"resolved": True, "action": "keep_current", "id": None}
        if action in ("accept_proposed", "provide_new"):
            if not file_id:
                raise MemoryDataError("This document owner question names no file")
            from app.runtime.task_runtime import enqueue

            enqueue(self.db, job_type="document.extract", workspace_id=workspace_id,
                    payload={"file_id": file_id, "owner_confirmed": True, "owner_issue_id": issue.id},
                    idempotency_key=f"document.extract:owner_confirmed:{issue.id}")
        self._close(issue, action, note, None)
        return {"resolved": True, "action": action, "id": None}

    def _kept_education_id(self, issue: ProfileIssue) -> str | None:
        """The education record a "keep current" answer left in place."""
        if issue.affected_type != "education":
            return None
        from .student_records import StudentRecordService

        record_id = issue.affected_id or (issue.evidence or {}).get("record_id")
        if record_id and StudentRecordService(self.db).get(issue.workspace_id, "education", record_id):
            return record_id
        return None

    def _replay_waiting_courses(self, issue: ProfileIssue, education_id: str | None) -> None:
        """Courses that waited on this qualification card join the education
        record that is active now; with none, they are refused and logged."""
        from .reconciler import drop_course

        for candidate_id in (issue.evidence or {}).get("pending_course_candidate_ids") or []:
            course = self.candidates.get(issue.workspace_id, candidate_id)
            if course is None or course.status != "pending":
                continue
            if education_id is None:
                drop_course(self.db, course, "course_education_not_saved")
                self.candidates.mark_rejected(course, "course_education_not_saved")
                VaultAssertionService(self.db).refresh_decision(course)
                continue
            values = _unwrap(course.proposed_value)
            course.proposed_value = {"value": {**values, "education_id": education_id}}
            course.entities = {k: v for k, v in (course.entities or {}).items()
                               if k != "education_candidate_id"} or None
            self.db.flush()
            self.reconciler.reconcile(course)

    @staticmethod
    def _candidate_spec(issue: ProfileIssue, original: MemoryCandidate | None) -> dict:
        evidence = issue.evidence or {}
        if original is not None:
            entities = dict(original.entities or {})
            if evidence.get("record_id") and not entities.get("record_id"):
                entities["record_id"] = evidence["record_id"]
            if evidence.get("force_new_on_accept"):
                entities["force_new"] = True
            return {
                "candidate_type": original.candidate_type,
                "key": original.key,
                "proposed_value": _unwrap(original.proposed_value),
                "entities": entities,
            }
        if evidence.get("item_type"):
            return {
                "candidate_type": "vault_item",
                "key": evidence["item_type"],
                "proposed_value": evidence.get("proposed_value"),
                "entities": {},
            }
        if evidence.get("field_key"):
            return {
                "candidate_type": "vault_fact",
                "key": evidence["field_key"],
                "proposed_value": evidence.get("proposed_value"),
                "entities": {},
            }
        if evidence.get("record_type"):
            entities = {}
            if evidence.get("record_id"):
                entities["record_id"] = evidence["record_id"]
            if evidence.get("force_new_on_accept"):
                entities["force_new"] = True
            return {
                "candidate_type": "student_record",
                "key": evidence["record_type"],
                "proposed_value": evidence.get("proposed"),
                "entities": entities,
            }
        raise MemoryDataError("This legacy issue has no resolvable candidate data")

    @staticmethod
    def _close(issue: ProfileIssue, action: str, note: str | None, candidate_id: str | None) -> None:
        issue.status = "resolved"
        issue.resolution = {
            "action": action,
            "note": note,
            "resolved_by": "student",
            "candidate_id": candidate_id,
        }
        issue.resolved_at = datetime.now(timezone.utc)
