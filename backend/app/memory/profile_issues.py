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
        value: Any = None, note: str | None = None,
    ) -> dict:
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
        return {"resolved": True, "action": action, "id": result.result_id}

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
