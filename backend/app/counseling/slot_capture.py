"""Persist extracted slot answers and propose canonical changes safely."""

import logging
import re
from typing import Any, Sequence

from sqlalchemy import select

from app.memory.candidates import MemoryCandidateService
from app.memory.education_journey import canonical_education_level
from app.memory.reconciler import MemoryReconciler
from app.memory.student_snapshot import StudentSnapshot
from app.models import CounselorSlotAnswer, ProfileFieldResponse, ProfileRequirement
from .extraction import SlotClaim, TurnExtraction
from .slots import short_key


logger = logging.getLogger(__name__)


def _value(claims: dict[str, SlotClaim], key: str) -> Any:
    claim = claims.get(key)
    return None if claim is None else claim.value


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _numbers_supported(value: dict, quote: str) -> bool:
    observed = {float(number) for number in re.findall(r"\d+(?:\.\d+)?", quote)}
    return all(float(item) in observed for item in value.values()
               if isinstance(item, (int, float)) and not isinstance(item, bool))


def _matching_record(snapshot: StudentSnapshot, kind: str, key: str,
                     value: str | None) -> dict | None:
    rows = snapshot.records.get(kind, ())
    if value:
        return next((row for row in rows if str(row.get(key) or "").strip().casefold()
                     == value.strip().casefold()), None)
    return rows[0] if len(rows) == 1 else None


def _record_proposals(claims: dict[str, SlotClaim], snapshot: StudentSnapshot) -> list[tuple[str, dict, list[str], str | None]]:
    proposals = []
    education_keys = ("recent_qualification", "qualification_group", "academic_result", "academic_status")
    if any(key in claims for key in education_keys):
        used = []
        raw = _value(claims, "recent_qualification")
        values: dict[str, Any] = {}
        if isinstance(raw, dict):
            values.update({key: raw[key] for key in ("qualification_name", "canonical_level")
                           if isinstance(raw.get(key), str) and raw[key].strip()})
            if values:
                used.append("recent_qualification")
            year = raw.get("graduation_year")
            if (isinstance(year, int) and not isinstance(year, bool)
                    and 1900 <= year <= 2200 and str(year) in claims["recent_qualification"].quote):
                values["graduation_year"] = year
        elif _text(raw):
            values["qualification_name"] = raw.strip()
            used.append("recent_qualification")
        group = _text(_value(claims, "qualification_group"))
        if group:
            values["field_of_study"] = group
            used.append("qualification_group")
        result = _value(claims, "academic_result")
        if (isinstance(result, dict) and result
                and _numbers_supported(result, claims["academic_result"].quote)):
            values["result"] = result
            used.append("academic_result")
        elif _text(result):
            values["result"] = {"grade": result.strip()}
            used.append("academic_result")
        status = _text(_value(claims, "academic_status"))
        if status in {"current", "completed", "incomplete", "planned"}:
            values["academic_status"] = status
            used.append("academic_status")
        existing = _matching_record(snapshot, "education", "qualification_name",
                                    values.get("qualification_name"))
        qualification = values.get("qualification_name") or (existing or {}).get("qualification_name")
        inferred_level = canonical_education_level(None, qualification) if qualification else None
        if inferred_level and values.get("canonical_level") not in {None, inferred_level}:
            values.pop("canonical_level")
        if qualification and used and "canonical_level" not in values and inferred_level:
            values["canonical_level"] = inferred_level
        if qualification and values and used:
            proposals.append(("education", values, used, existing.get("id") if existing else None))

    goal_keys = ("stated_goal", "goal_reason", "envisioned_outcome", "timing")
    if any(key in claims for key in goal_keys):
        used = []
        raw = _value(claims, "stated_goal")
        values: dict[str, Any] = {}
        if isinstance(raw, dict):
            values.update({key: raw[key] for key in ("title", "goal_type")
                           if isinstance(raw.get(key), str) and raw[key].strip()})
            if values:
                used.append("stated_goal")
        details = {}
        if motivation := _text(_value(claims, "goal_reason")):
            details["motivation"] = motivation
            used.append("goal_reason")
        if objective := _text(_value(claims, "envisioned_outcome")):
            details["underlying_objective"] = objective
            used.append("envisioned_outcome")
        if intake := _text(_value(claims, "timing")):
            details["target_intake"] = intake
            used.append("timing")
        if details:
            values["details"] = details
        existing = _matching_record(snapshot, "goal", "title", values.get("title"))
        if ((values.get("title") and values.get("goal_type")) or existing) and values:
            proposals.append(("goal", values, used, existing.get("id") if existing else None))

    family = _value(claims, "family_wish")
    if isinstance(family, dict) and all(_text(family.get(key)) for key in
                                       ("influencer_type", "source_label", "suggested_direction", "influence_type")):
        proposals.append(("external_influence", family, ["family_wish"], None))
    likes = _value(claims, "subject_likes")
    if _text(likes):
        proposals.append(("student_voice_statement", {"voice_type": "interest", "statement": likes},
                          ["subject_likes"], None))
    return proposals


def _vault_proposals(claims: dict[str, SlotClaim]) -> list[tuple[str, Any, list[str]]]:
    proposals = []
    mappings = {
        "field_interest": "career.primary_interest",
        "budget": "finance.budget",
        "study_mode": "preferences.study_load",
        "location_limits": "preferences.location_limits",
    }
    for key, field in mappings.items():
        if key not in claims:
            continue
        value = claims[key].value
        if key in {"field_interest", "study_mode"} and not _text(value):
            continue
        if key == "budget" and not isinstance(value, dict):
            continue
        if key == "location_limits" and _text(value):
            value = [value.strip()]
        if key == "location_limits" and not isinstance(value, list):
            continue
        proposals.append((field, value, [key]))
    return proposals


def capture_turn_slots(db, workspace_id: str, source_event_id: str,
                       extraction: TurnExtraction,
                       requirements: Sequence[ProfileRequirement],
                       snapshot: StudentSnapshot,
                       *, channel: str = "conversation") -> list[str]:
    """Make pending answers visible now; propose facts through reconciliation.

    A retry of the same event is idempotent. A failed transaction rolls back
    both pending state and candidates, so a retry can safely start over.
    """
    if channel not in {"conversation", "voice"}:
        raise ValueError("Unsupported Counselor input channel")
    allowed = {short_key(row): row for row in requirements}
    claims = {item.key: item for item in extraction.claims if item.key in allowed}
    existing = {row.slot_key for row in db.execute(select(CounselorSlotAnswer).where(
        CounselorSlotAnswer.workspace_id == workspace_id,
        CounselorSlotAnswer.source_event_id == source_event_id,
    )).scalars()}
    if existing:
        return []
    for claim in claims.values():
        db.add(CounselorSlotAnswer(workspace_id=workspace_id, source_event_id=source_event_id,
                                   slot_key=claim.key, value=claim.value, confidence=claim.confidence,
                                   quote=claim.quote, status="pending"))
    for key in extraction.unknown_or_declined:
        requirement = allowed.get(key)
        if requirement is None or not requirement.accepts_unknown or key in claims:
            continue
        status = dict(extraction.response_statuses).get(key, "valid_unknown")
        if status not in {"valid_unknown", "declined"}:
            status = "valid_unknown"
        db.add(CounselorSlotAnswer(workspace_id=workspace_id, source_event_id=source_event_id,
                                   slot_key=key, status=status))
        response = db.execute(select(ProfileFieldResponse).where(
            ProfileFieldResponse.workspace_id == workspace_id,
            ProfileFieldResponse.requirement_key == requirement.key,
        )).scalar_one_or_none()
        if response is None:
            db.add(ProfileFieldResponse(workspace_id=workspace_id,
                                        requirement_key=requirement.key,
                                        status=status, source_event_id=source_event_id))
        else:
            response.status = status
            response.source_event_id = source_event_id
    db.flush()

    candidates = MemoryCandidateService(db)
    reconciler = MemoryReconciler(db)
    candidate_ids = []
    proposed_keys: set[str] = set()
    for kind, values, keys, record_id in _record_proposals(claims, snapshot):
        anchor = claims[keys[0]]
        candidate = candidates.propose(
            workspace_id=workspace_id, candidate_type="student_record", key=kind,
            proposed_value=values, confidence=min(claims[key].confidence for key in keys),
            source_type="conversation", input_channel=channel,
            source_event_ids=[source_event_id],
            entities={"record_id": record_id} if record_id else {},
            evidence={"quote": anchor.quote, "slot_quotes": {key: claims[key].quote for key in keys}},
        )
        reconciler.reconcile(candidate)
        candidate_ids.append(candidate.id)
        proposed_keys.update(keys)
    for field, value, keys in _vault_proposals(claims):
        anchor = claims[keys[0]]
        candidate = candidates.propose(
            workspace_id=workspace_id, candidate_type="vault_fact", key=field,
            proposed_value=value, confidence=anchor.confidence,
            source_type="conversation", input_channel=channel,
            source_event_ids=[source_event_id], evidence={"quote": anchor.quote,
                                                          "slot_key": keys[0]},
        )
        reconciler.reconcile(candidate)
        candidate_ids.append(candidate.id)
        proposed_keys.update(keys)
    # Preserve a clearly quoted statement even if it lacks the fields a
    # structured record requires. It is still a candidate, never a direct
    # Vault write, and cannot masquerade as an accepted structured slot.
    for key, claim in claims.items():
        if key in proposed_keys or key == "goal_summary_confirmed":
            continue
        candidate = candidates.propose(
            workspace_id=workspace_id, candidate_type="semantic_memory",
            content=claim.quote, confidence=claim.confidence,
            source_type="conversation", input_channel=channel,
            source_event_ids=[source_event_id],
            entities={"memory_type": "context", "slot_key": key},
            evidence={"quote": claim.quote, "slot_key": key},
        )
        reconciler.reconcile(candidate)
        candidate_ids.append(candidate.id)
    return candidate_ids
