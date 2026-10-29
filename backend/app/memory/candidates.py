# -*- coding: utf-8 -*-
"""MemoryCandidateService — the quarantine between an LLM and the truth.

Extraction proposes; it never commits. Everything an LLM believes about the
student enters as a row here with `status='pending'`, and only the
deterministic reconciler can promote it. The value of the seam is that a
hallucinated grade is a rejected candidate row you can inspect, rather than a
corrupted Vault you have to notice.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.memory.errors import MemoryDataError
from app.models import MemoryCandidate, VaultDrop

logger = logging.getLogger(__name__)

CANDIDATE_TYPES = ("vault_fact", "semantic_memory", "episode", "student_record", "vault_item")
OPERATIONS = ("upsert", "retract", "forget")

# `source_type` decides how much a proposal is trusted — `user_explicit`
# outranks every other source in the reconciler and bypasses the confidence
# floor. It must therefore be assigned by trusted server code that KNOWS where
# the claim came from, and never taken from model output.
#
# The attack this closes, before Phase 2 makes it reachable: an extraction
# prompt reads the student's message, the message says "source_type:
# user_explicit, grade: 10.0", the model echoes it into its JSON, and an
# inference is laundered into a first-hand statement that outranks the
# student's real answer. Extraction is therefore not permitted to name its own
# source_type at all — the call site does, from the channel it read.
TRUSTED_SOURCE_TYPES = ("user_explicit", "document", "conversation", "agent", "system")

# Only the explicit remember/forget tools may claim this. Enforced in
# `propose()` via `allow_user_explicit`, which extraction never sets.
PRIVILEGED_SOURCE_TYPES = ("user_explicit",)

# Types whose values land in the Vault and so must be English, coded and ISO.
NORMALIZED_TYPES = ("vault_fact", "student_record", "vault_item")
_DROP_SOURCE = {"conversation": "chat", "voice": "chat", "document": "document", "profile": "details"}
_DROP_PAYLOAD_LIMIT = 2048
# What the student is told when a write would store a household income.
INCOME_REFUSED = "Household income isn't stored. You can add an approximate study budget instead."
# A budget's amount: a new one replaces the saved one as a whole.
_BUDGET_AMOUNT = ("band", "min", "max", "amount")


@event.listens_for(Session, "after_transaction_end")
def _write_pending_drops(session, transaction):
    """Persist rejected-value logs after the caller's locks are gone.

    Runs for every session; only a root transaction ending with queued drops
    does anything. It never raises: the MemoryDataError already left propose.
    """
    if transaction.parent is not None or transaction.nested:
        return
    pending = session.info.pop("pending_vault_drops", None)
    if not pending:
        return
    try:
        from app.database import new_session
        with new_session() as log:
            log.add_all([VaultDrop(**row) for row in pending])
            log.commit()
    except Exception as exc:  # noqa: BLE001 - logging must not mask the rejection
        logger.warning("vault drop log not written (%d rows): %s", len(pending), type(exc).__name__)


def record_drop(db, workspace_id: str, source: str, stage: str, reason: str,
                payload: Any, source_ref: Optional[str] = None) -> None:
    """Queue one drop-log row; the listener above writes it when the root transaction ends.

    Deferred, not written here: a second connection could wait on a row lock
    the caller's transaction holds. The payload is capped so the log never
    becomes a second copy of student data.
    """
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text.encode("utf-8")) > _DROP_PAYLOAD_LIMIT:
        key = payload.get("key") if isinstance(payload, dict) else None
        payload = {"key": key, "value": text.encode("utf-8")[:1500].decode("utf-8", "ignore")}
    db.info.setdefault("pending_vault_drops", []).append(dict(
        workspace_id=workspace_id, source=source, stage=stage, reason=str(reason)[:1000],
        payload=payload, source_ref=str(source_ref) if source_ref else None))
    db.connection()  # make sure a transaction exists to end, so the drop is written


def carries_household_income(candidate_type, key, value, quote) -> bool:
    """The extractors' household-income check, on a value about to be logged."""
    from .catalog import vault_catalog
    from .extractor import states_household_income

    facts = {spec.key for spec in vault_catalog().types(storage="fact")}
    return states_household_income({"candidate_type": candidate_type, "key": key,
                                    "proposed_value": value, "quote": quote}, facts)


def income_guarded(candidate_type, key) -> bool:
    """Where a household's money could land: finance facts and the catalog's
    money kinds (family members, pressures, sponsor and scholarship records)."""
    from .extractor import money_kinds

    if not isinstance(key, str):
        return False
    if candidate_type == "vault_fact":
        return key.startswith("finance.") or key in money_kinds()
    return candidate_type in ("vault_item", "student_record") and key in money_kinds()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryCandidateService:
    def __init__(self, db):
        self.db = db

    def propose(
        self,
        workspace_id: str,
        candidate_type: str,
        operation: str = "upsert",
        key: Optional[str] = None,
        proposed_value: Any = None,
        content: Optional[str] = None,
        entities: Optional[dict] = None,
        confidence: float = 0.5,
        source_type: str = "conversation",
        source_event_ids: Optional[list] = None,
        evidence: Optional[dict] = None,
        subject_user_id: Optional[str] = None,
        allow_user_explicit: bool = False,
        input_channel: Optional[str] = None,
        effective_at: Optional[datetime] = None,
    ) -> MemoryCandidate:
        """Record a proposal. Deliberately cheap and always safe to call.

        `source_type` must be one of `TRUSTED_SOURCE_TYPES` and is assigned by
        the CALLER, from what the caller knows about where the claim came from
        — never copied out of model output. `allow_user_explicit` must be set
        explicitly to claim `user_explicit`, so an extraction path cannot
        promote its own guess to a first-hand statement even if a model emits
        that string.

        Note what this does NOT do: it does not validate against the field
        definition. Validation is the reconciler's job, so an invalid proposal
        is preserved with its rejection reason instead of vanishing — that
        record is how you find a misbehaving extraction prompt.
        """
        if candidate_type not in CANDIDATE_TYPES:
            raise ValueError(f"Unknown candidate_type: {candidate_type}")
        if operation not in OPERATIONS:
            raise ValueError(f"Unknown operation: {operation}")
        if source_type not in TRUSTED_SOURCE_TYPES:
            raise ValueError(f"Unknown source_type: {source_type}")
        if source_type in PRIVILEGED_SOURCE_TYPES and not allow_user_explicit:
            raise ValueError(
                f"source_type '{source_type}' may only be set by the explicit "
                "user-command path"
            )
        if input_channel is not None and input_channel not in {
            "conversation", "voice", "profile", "document", "credential", "connector", "system",
        }:
            raise ValueError("Unknown Vault input channel")
        if effective_at is not None and (not isinstance(effective_at, datetime) or effective_at.tzinfo is None or effective_at.utcoffset() is None):
            raise ValueError("effective_at must be a timezone-aware datetime")
        if effective_at is not None:
            effective_at = effective_at.astimezone(timezone.utc)

        if candidate_type == "vault_fact" and key:
            from .field_definitions import FIELD_ALIASES
            key = FIELD_ALIASES.get(key, key)
        if operation == "upsert":
            self._refuse_income(workspace_id, candidate_type, key, proposed_value, evidence,
                                input_channel, source_event_ids)
        if candidate_type == "vault_fact" and key == "finance.budget" and operation == "upsert":
            proposed_value = self._merge_budget(workspace_id, proposed_value)
        if candidate_type in NORMALIZED_TYPES and operation == "upsert" and proposed_value is not None:
            proposed_value, evidence = self._normalize(
                workspace_id, candidate_type, key, proposed_value, evidence,
                input_channel, source_event_ids, source_type=source_type)
        candidate = MemoryCandidate(
            workspace_id=workspace_id,
            subject_user_id=subject_user_id,
            candidate_type=candidate_type,
            operation=operation,
            key=key,
            # Wrapped to match VaultFact.value, so the reconciler unwraps once.
            proposed_value=None if proposed_value is None else {"value": proposed_value},
            content=content,
            entities=entities,
            confidence=confidence,
            source_type=source_type,
            input_channel=input_channel,
            effective_at=effective_at,
            source_event_ids=source_event_ids,
            evidence=evidence,
            status="pending",
        )
        self.db.add(candidate)
        self.db.flush()
        return candidate

    @staticmethod
    def _drop_source(key, input_channel) -> str:
        """The drop log's source: the surface the value came through."""
        from app.memory.catalog import vault_catalog

        source = _DROP_SOURCE.get(input_channel or "", "chat")
        spec = vault_catalog().type(key or "")
        if source == "details" and spec is not None and spec.shown_on == "story":
            source = "story"
        return source

    def _refuse_income(self, workspace_id, candidate_type, key, value, evidence,
                       input_channel, source_event_ids) -> None:
        """Household income is never stored, from any source (VAULT_SPEC §Money).

        Checked here, at the one door, so conflict answers, profile and fact
        cards and the Vault API meet the same rule as the extractors. The drop
        is logged with the key and reason only, never the figure or the quote.
        """
        quote = (evidence or {}).get("quote")
        if not income_guarded(candidate_type, key) or not carries_household_income(
                candidate_type, key, value, quote if isinstance(quote, str) else ""):
            return
        ref = (source_event_ids[0] if source_event_ids else None) or (evidence or {}).get("file_id")
        record_drop(self.db, workspace_id, self._drop_source(key, input_channel), "validate",
                    "household_income", {"key": key, "reason": "household_income"}, source_ref=ref)
        raise MemoryDataError(INCOME_REFUSED)

    def _merge_budget(self, workspace_id, value):
        """A budget follow-up ("only fees, not hostel") completes the saved
        budget instead of replacing it. A new amount replaces the saved amount
        as a whole, so a band and an old range never sit side by side."""
        from .vault import VaultService, _unwrap, is_fact_guess

        if not isinstance(value, dict):
            return value
        fact = VaultService(self.db).get_fact(workspace_id, "finance.budget")
        if fact is None or is_fact_guess(fact.source_type, fact.evidence):
            # PAI's guess is not the student's budget: merged in, it would be
            # saved as something the student said. The follow-up stands alone.
            return value
        saved = _unwrap(fact.value)
        if not isinstance(saved, dict):
            return value
        given = {k: v for k, v in value.items() if v not in (None, "")}
        if any(k in given for k in _BUDGET_AMOUNT):
            saved = {k: v for k, v in saved.items() if k not in _BUDGET_AMOUNT}
        return {**saved, **given}

    def _normalize(self, workspace_id, candidate_type, key, value, evidence,
                   input_channel, source_event_ids, source_type=None):
        """English/codes/ISO before the row exists; a rejection is logged, then raised."""
        from app.memory.normalize import normalize_candidate

        evidence = dict(evidence or {})
        result = normalize_candidate(
            candidate_type, key, value, student_text=evidence.get("quote", "") or "",
            # A form (Details, onboarding, a conflict answer) offers only
            # the level's own list, so an off-list code there is refused.
            strict_choices=input_channel == "profile")
        if result.rejected_reason:
            source = self._drop_source(key, input_channel)
            ref = (source_event_ids[0] if source_event_ids else None) or evidence.get("file_id")
            payload = {"key": key, "value": value}
            if carries_household_income(candidate_type, key, value, evidence.get("quote")):
                # Household income is never stored, the drop log included (VAULT_SPEC §Money).
                payload = {"key": key, "reason": result.rejected_reason}
            record_drop(self.db, workspace_id, source, "normalize", result.rejected_reason,
                        payload, source_ref=ref)
            raise MemoryDataError(result.rejected_reason)
        evidence["source_language"] = result.source_language
        if result.stated and evidence.get("inferred") and source_type == "conversation":
            # The student named this person in their own words: what they
            # said about them is Stated, not PAI's guess (audit #5).
            evidence.pop("inferred")
        if result.needs_confirmation:
            evidence["inferred"] = True
        return result.value, evidence

    def get(self, workspace_id: str, candidate_id: str) -> Optional[MemoryCandidate]:
        return self.db.execute(
            select(MemoryCandidate).where(
                MemoryCandidate.id == candidate_id,
                MemoryCandidate.workspace_id == workspace_id,
            )
        ).scalar_one_or_none()

    def pending(self, workspace_id: str, limit: int = 100) -> list[MemoryCandidate]:
        return list(self.db.execute(
            select(MemoryCandidate)
            .where(
                MemoryCandidate.workspace_id == workspace_id,
                MemoryCandidate.status == "pending",
            )
            .order_by(MemoryCandidate.created_at)
            .limit(limit)
        ).scalars().all())

    def mark_accepted(self, candidate: MemoryCandidate, result_id: Optional[str]) -> MemoryCandidate:
        candidate.status = "accepted"
        candidate.result_id = result_id
        candidate.reconciled_at = _now()
        self.db.flush()
        return candidate

    def mark_rejected(self, candidate: MemoryCandidate, reason: str) -> MemoryCandidate:
        candidate.status = "rejected"
        candidate.rejection_reason = (reason or "")[:1000]
        candidate.reconciled_at = _now()
        self.db.flush()
        return candidate
