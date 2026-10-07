"""Structured summary of only the student's known direction answers."""

from .slots import SlotState


SUMMARY_KEYS = (
    "stated_goal", "goal_reason", "subject_likes", "field_interest", "envisioned_outcome",
    "budget", "timing", "family_wish", "location_limits", "study_mode",
)


def _value(key: str, value):
    if key == "stated_goal" and isinstance(value, dict):
        return value.get("title")
    return value


def summary_payload(states: dict[str, SlotState], extraction=None) -> dict:
    """Preserve provenance/status without inventing missing details."""
    payload = {key: {"value": _value(key, states[key].value), "status": states[key].status}
            for key in SUMMARY_KEYS if key in states and states[key].answered}
    if "budget" in payload and states["budget"].quote:
        payload["budget"]["student_words"] = states["budget"].quote
    if extraction is not None:
        for claim in extraction.claims:
            if claim.key in SUMMARY_KEYS:
                payload[claim.key] = {"value": _value(claim.key, claim.value), "status": "pending"}
                if claim.key == "budget":
                    payload[claim.key]["student_words"] = claim.quote
    return payload


def is_explicit_confirmation(extraction, draft: dict | None) -> bool:
    if not draft or draft.get("status") != "awaiting_confirmation" or extraction is None:
        return False
    return extraction.summary_response == "confirmed" or any(
        claim.key == "goal_summary_confirmed" and claim.value == "confirmed"
        for claim in extraction.claims)


def has_correction(extraction, draft: dict | None) -> bool:
    if not draft or extraction is None:
        return False
    if extraction.summary_response != "corrected":
        return False
    old = draft.get("summary") or {}
    for claim in extraction.claims:
        if claim.key in SUMMARY_KEYS and (
                claim.key not in old or old[claim.key].get("value") != _value(claim.key, claim.value)):
            return True
    return False
