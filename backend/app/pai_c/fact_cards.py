"""Catalog-owned choices and quoted prefills; only confirmed input is stored."""
from copy import deepcopy
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.pai_c.memory import MemoryService
from app.pai_c.policy.controller import load_data
from app.pai_c.understanding.data import at_path, set_path


class CardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["collect_fact"]
    card_key: str
    value: str | None = Field(default=None, max_length=1000)
    quote: str | None = Field(default=None, max_length=1000)


class CardAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: UUID
    value: str = Field(min_length=1, max_length=1000)
    other: bool = False
    confirmed: Literal[True]
    record_id: str | None = None
    education_id: str | None = None


def choices_for(spec, data, record=None):
    return [deepcopy(row) for row in data["catalogs"].get(spec["catalog"], [])
            if not row.get("levels") or (record or {}).get("canonical_level") in row["levels"]]


def available_cards(snapshot, area=None):
    data = load_data("fact_cards.json")
    cards = []
    for key, spec in data["cards"].items():
        if area is not None and area != spec["area"]:
            continue
        rows = snapshot.records.get(spec.get("parent_type") or spec.get("record_type"), [])
        record = next((row for row in rows if row.get("academic_status") == "current"), next(iter(rows), None))
        if spec.get("requires_record") and (record is None or at_path(record, spec["field"])):
            continue
        if spec.get("parent_type") and record is None:
            continue
        if spec.get("field_key") in snapshot.facts:
            continue
        if not spec.get("requires_record") and not spec.get("parent_type") and rows:
            continue
        choices = choices_for(spec, data, record)
        cards.append({"key": key, "area": spec["area"], "label": spec["label"],
            "kind": "choice" if choices else "text", "choices": choices,
            "other": {"label": data["copy"]["other"], "editable": True},
            "upload_invite": data["copy"]["upload"] if spec["upload"] else None,
            "confirm_label": data["copy"]["confirm"], "text_label": data["copy"]["text"],
            "record_id": record["id"] if spec.get("requires_record") else None,
            "education_id": record["id"] if spec.get("parent_type") else None})
    return cards


def validated_card(action, cards, student_text):
    try:
        request = CardRequest.model_validate(action)
    except ValueError:
        return None
    card = next((deepcopy(row) for row in cards if row["key"] == request.card_key), None)
    if card is not None and request.value and request.quote and request.quote in student_text and request.value in request.quote:
        card["prefill"] = {"value": request.value, "quote": request.quote, "requires_confirmation": True}
    return card


def submit_answer(db, workspace_id, key, answer):
    data = load_data("fact_cards.json")
    if key not in data["cards"]:
        raise ValueError("Unknown fact card")
    spec = data["cards"][key]
    memory = MemoryService(db)
    snapshot = memory.profile(workspace_id)
    record = None
    if spec.get("requires_record") or spec.get("parent_type"):
        record_id = answer.education_id if spec.get("parent_type") else answer.record_id
        record = next((row for row in snapshot.records.get(spec.get("parent_type") or spec["record_type"], []) if row["id"] == record_id), None)
        if record is None:
            raise ValueError("Record is not available in this workspace")
    elif answer.record_id is not None or answer.education_id is not None:
        raise ValueError("This card does not edit an existing record")
    value = answer.value.strip()
    if not value:
        raise ValueError("An answer is required")
    choices = choices_for(spec, data, record)
    known = value in {row["value"] for row in choices}
    if choices and not known and not answer.other:
        raise ValueError("Select a catalog choice or use Other")
    proposed = value
    if spec.get("record_type"):
        proposed = {}
        set_path(proposed, spec["field"], value)
        if spec.get("parent_type"):
            proposed["education_id"] = answer.education_id
    evidence = {"quote": value, "capture": "fact_card", "evidence_level": "stated",
        "card_key": key, "submission_id": str(answer.submission_id)}
    if not known:
        evidence["catalog_review"] = {"catalog": spec["catalog"], "status": "pending", "student_text": value}
    return memory.save_fact_card(workspace_id, spec, proposed, evidence, answer.record_id)


def presentation_card(decision, *, safety_flagged=False):
    """Presentation follows the policy decision; it never selects a next move."""
    if decision is None or safety_flagged:
        return None
    data = load_data('inline_cards.json')
    if decision.action == data['picture_action']:
        return {'kind': 'first_picture'}
    if decision.question_allowed and decision.topic == data['rating_topic'] and decision.action in data['rating_actions']:
        return {'kind': 'rating', 'min': data['rating_min'], 'max': data['rating_max']}
    return None
