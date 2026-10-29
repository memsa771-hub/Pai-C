# -*- coding: utf-8 -*-
"""The Mirror text: 3-4 sentences written in the background when the Vault
changes (FOUR_FEATURES_SPEC 2.2).

The model sees the state card only (labels and English entry text; no chat, no
evidence quotes) and its output is checked in code before it is stored: the
sentence count, no question, every sentence in the second person, no praise
word, no university name, and no number the card does not hold. One retry,
then the job gives up and the last text stays; the card renders without it.

The reconciler calls `after_accept` (registered in capabilities/system.py,
because shared memory never imports PAI C) after every accepted Vault write.
It debounces: one pending job per workspace, and none when the stored text was
written for the current card.
"""

import json
import logging
import re
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import config
from app.inference.gateway import complete as chat_completion, resolve_model
from app.journey import JourneyService
from app.models import BackgroundJob, StudentJourney
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.mirror.engine import MirrorEngine, mirror_policy
from app.pai_c.understanding.data import load_areas
from app.runtime.task_runtime import enqueue

logger = logging.getLogger(__name__)
JOB_MIRROR_TEXT = "counselor.mirror_text"
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@lru_cache(maxsize=1)
def mirror_types() -> frozenset[str]:
    """Catalog types whose writes can change the card: every Vault field,
    record kind and item type areas.json reads."""
    return frozenset(key for spec in load_areas().values() for source in spec["sources"]
                     for name in ("vault_fields", "vault_records", "vault_items") for key in source.get(name, ()))


def _draft(db, workspace_id: str) -> dict:
    return db.scalar(select(StudentJourney.counselor_summary_draft).where(
        StudentJourney.workspace_id == workspace_id, StudentJourney.journey_type == "counselor_decision",
        StudentJourney.status == "active").limit(1)) or {}


def enqueue_mirror_text(db, workspace_id: str) -> str | None:
    pending = db.scalar(select(BackgroundJob.id).where(
        BackgroundJob.workspace_id == workspace_id, BackgroundJob.job_type == JOB_MIRROR_TEXT,
        BackgroundJob.status == "pending").limit(1))
    if pending:
        return None
    version = MirrorEngine(db).build(workspace_id)["version"]
    draft = _draft(db, workspace_id)
    if draft.get("type") == "mirror_state" and draft.get("card_version") == version:
        return None
    job = enqueue(db, JOB_MIRROR_TEXT, {"workspace_id": workspace_id, "card_version": version},
                  workspace_id=workspace_id,
                  idempotency_key=f"counselor:mirror-text:{workspace_id}:{version}:{draft.get('version') or 0}")
    return job.id


def after_accept(db, candidate) -> None:
    """Reconciler hook. The Vault write has happened; a failure to queue the
    text must not undo it, so the enqueue runs in a savepoint and a database
    error is logged, not raised."""
    if candidate.key not in mirror_types():
        return
    try:
        with db.begin_nested():
            enqueue_mirror_text(db, candidate.workspace_id)
    except SQLAlchemyError:
        logger.exception("mirror_text_enqueue_failed workspace_id=%s", candidate.workspace_id)


# ---- the model input and its checks -------------------------------------------------

def card_brief(card: dict) -> str:
    """The card as plain lines: labels and English entry text only."""
    copy = mirror_policy()["copy"]
    lines = []
    line = card["header"].get("education_line")
    if line:
        lines.append(f"Education: {line['text']}")
    for area in card["areas"]:
        if area["level"]:
            entries = "; ".join(entry["text"] for entry in area["entries"])
            bars = "; ".join(f"{bar['label']} {bar['percent']}%" for bar in area.get("bars", ()))
            lines.append(f"{area['label']} (level {area['level']} of 3): {entries}" + (f"; marks: {bars}" if bars else ""))
    notes = {mark["note_key"] for area in card["areas"] for mark in area["tension"]}
    lines += [f"Tension: {copy.get(key, key)}" for key in sorted(notes)]
    unknown = [row["label"] for row in card["unknowns"]]
    if unknown:
        lines.append("Still unknown: " + ", ".join(unknown))
    return "\n".join(lines)


def _has(words: list[str], text: str) -> list[str]:
    padded = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    return [word for word in words if f" {word} " in padded]


def valid_sentences(sentences, brief: str) -> bool:
    rules = mirror_policy()["text"]
    if (not isinstance(sentences, list) or not rules["min_sentences"] <= len(sentences) <= rules["max_sentences"]
            or not all(isinstance(s, str) and s.strip() for s in sentences)):
        return False
    text = " ".join(sentences)
    if "?" in text or _has(rules["praise_words"], text):
        return False
    if [word for word in _has(rules["university_words"], text) if word not in _has(rules["university_words"], brief)]:
        return False
    if not all(_has(rules["second_person"], sentence) for sentence in sentences):
        return False
    return set(_NUMBER.findall(text)) <= set(_NUMBER.findall(brief))


async def mirror_text_job(job, db) -> dict:
    workspace_id = job.workspace_id or (job.payload or {}).get("workspace_id")
    if not workspace_id:
        raise ValueError("Mirror text job requires a workspace")
    card = MirrorEngine(db).build(workspace_id)
    draft = _draft(db, workspace_id)
    if draft.get("type") == "mirror_state" and draft.get("card_version") == card["version"]:
        return {"status": "same_version"}
    if JourneyService.keeps_old_draft(draft):  # checked again on write; this saves the model call
        logger.info("mirror_text_skipped_old_mirror workspace_id=%s", workspace_id)
        return {"status": "old_mirror_waiting"}
    if not any(area["level"] for area in card["areas"]):
        return {"status": "empty"}
    brief = card_brief(card)
    prompt = load_prompt("mirror_text")
    messages = [{"role": "user", "content": f"<card>\n{brief}\n</card>"}]
    db.rollback()  # no transaction held open across the model call
    attempts = mirror_policy()["text"]["attempts"]
    for attempt in range(attempts):
        raw = await chat_completion(role="mirror", api_key=config.PAI_API_KEY, model=resolve_model("mirror"),
                                    system_prompt=prompt, messages=messages,
                                    response_format={"type": "json_object"},
                                    reasoning_effort=config.PAI_COUNSELOR_REASONING_EFFORT,
                                    base_url=config.PAI_BASE_URL)
        try:
            sentences = [s.strip() for s in json.loads(raw).get("sentences")]
        except (TypeError, ValueError, AttributeError):
            sentences = None
        if valid_sentences(sentences, brief):
            break
        logger.warning("mirror_text_invalid workspace_id=%s attempt=%d", workspace_id, attempt + 1)
        prompt += ("\nYour last answer broke a rule. Return 3 or 4 sentences in the second person, no question, "
                   "no praise, no university, and only numbers that are on the card.")
    else:
        return {"status": "invalid", "model_calls": attempts}
    JourneyService(db).ensure_counselor(workspace_id)
    written = JourneyService(db).set_mirror_text(workspace_id, " ".join(sentences), card["version"])
    if written is None:
        db.rollback()
        return {"status": "old_mirror_waiting"}
    db.commit()
    return {"status": "written", "card_version": card["version"]}
