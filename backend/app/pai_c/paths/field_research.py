"""Shared, sourced notes on a study field (BETA_CONVERSATION_SPEC 3.1).

One bounded research run per field and country, not per student: the path
analyzer and path explain of every student read the same cached note, so the
cost is per field. Every fact carries a verbatim quote that the code finds in
the page it came from (the model's word is never enough), and a fact naming an
institution is dropped, since places come only at stage H.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.config import config
from app.inference.gateway import complete
from app.models import BackgroundJob, PaiFieldNote
from app.pai_c.deep.polish import contains_blocked_script
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.paths.fields import study_fields
from app.pai_c.policy.controller import load_data
from app.plugins._shared.budget import bounded_research, record_model_usage, spend
from app.plugins._shared.sources import public_https, read_page, search_web
from app.plugins._shared.verification import SourceVerifier

logger = logging.getLogger(__name__)
JOB_FIELD_RESEARCH = "counselor.field_research"


def policy() -> dict:
    """The analyzer's policy holds the note knobs; they are data, not code."""
    rules = load_data("path_analyzer.json")
    return {**rules["field_research"], "field_notes_per_run": rules["field_notes_per_run"],
            "field_notes_in_prompt": rules["field_notes_in_prompt"], "default_country": rules["default_country"]}


class NoteFact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(min_length=1, max_length=600)
    source_url: str
    quote: str = Field(min_length=1, max_length=1200)


class FieldNote(BaseModel):
    """A stored note. The section names are the policy's, so a new section is
    a data change."""
    model_config = ConfigDict(extra="ignore")
    field_key: str
    country: str
    sections: dict[str, list[NoteFact]]
    confidence: str
    researched_at: datetime


def country_key(country: str | None) -> str:
    return " ".join(str(country or "").split()).casefold()


def student_country(db, workspace_id: str) -> str:
    """The student's current country from the Vault, else the policy default."""
    from app.pai_c.memory import vault_value
    value = vault_value(db, workspace_id, "location.current_country")
    return value.strip() if isinstance(value, str) and value.strip() else policy()["default_country"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def fresh_note(db, field_key: str, country: str, now: datetime | None = None) -> FieldNote | None:
    """The stored note when it is younger than PAI_FIELD_NOTE_DAYS."""
    row = db.scalar(select(PaiFieldNote).where(PaiFieldNote.field_key == field_key,
                                               PaiFieldNote.country == country_key(country)))
    if row is None or _aware(row.researched_at) < (now or _now()) - timedelta(days=config.PAI_FIELD_NOTE_DAYS):
        return None
    return FieldNote(field_key=row.field_key, country=row.country, sections=row.note.get("sections") or {},
                     confidence=row.confidence, researched_at=_aware(row.researched_at))


def note_facts(note: FieldNote) -> list[dict]:
    """The note's facts in section order, each with its id `note:<field>:<n>`."""
    facts, n = [], 0
    for section in policy()["sections"]:
        for fact in note.sections.get(section, []):
            n += 1
            facts.append({"id": f"note:{note.field_key}:{n}", "section": section, "text": fact.text,
                          "source_url": fact.source_url, "quote": fact.quote})
    return facts


def _pending(db, field_key: str, country: str) -> bool:
    return db.scalar(select(BackgroundJob.id).where(
        BackgroundJob.job_type == JOB_FIELD_RESEARCH, BackgroundJob.status.in_(("pending", "running")),
        BackgroundJob.payload["field_key"].as_string() == field_key,
        BackgroundJob.payload["country"].as_string() == country_key(country)).limit(1)) is not None


def enqueue_missing(db, field_keys, country: str, limit: int | None = None) -> list[str]:
    """Queue research for fields with no fresh note and none queued, at most
    `limit` (field_notes_per_run). Idempotent per field, country and day, so a
    failed run is tried again the next day, not on every analysis. The caller
    commits."""
    from app.runtime.task_runtime import enqueue
    limit = policy()["field_notes_per_run"] if limit is None else limit
    queued, today = [], _now().date().isoformat()
    for field_key in dict.fromkeys(field_keys):
        if len(queued) >= limit:
            break
        if field_key not in study_fields() or fresh_note(db, field_key, country) or _pending(db, field_key, country):
            continue
        job = enqueue(db, JOB_FIELD_RESEARCH, {"field_key": field_key, "country": country_key(country)},
                      idempotency_key=f"field_note:{field_key}:{country_key(country)}:{today}")
        if job is not None and job.status == "pending":
            queued.append(job.id)
    return queued


def _names_institution(text: str, rules: dict) -> bool:
    padded = " " + re.sub(r"[^a-z0-9-]+", " ", text.lower()) + " "
    return (any(f" {word} " in padded for word in rules["institution_words"])
            or any(re.search(pattern, text) for pattern in rules["institution_patterns"]))


def verified_facts(raw: dict, pages: list[dict], rules: dict, checked: datetime) -> dict[str, list[dict]]:
    """Keep a fact only when its quote is verbatim on the page it cites and
    passes the policy's SourceVerifier checks, and when neither its text nor
    its quote names an institution or uses a blocked script."""
    by_url = {page["url"]: page["text"] for page in pages}
    verifier = SourceVerifier(freshness_days=config.PAI_FIELD_NOTE_DAYS)
    sections = raw.get("sections") if isinstance(raw, dict) else None
    kept: dict[str, list[dict]] = {}
    for section in rules["sections"]:
        rows = (sections or {}).get(section) or []
        for row in rows if isinstance(rows, list) else []:
            try:
                fact = NoteFact.model_validate(row)
            except ValueError:
                continue
            text = by_url.get(fact.source_url)
            if text is None or fact.quote not in text:
                continue
            words = fact.text + " " + fact.quote
            if _names_institution(words, rules) or contains_blocked_script(words, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
                continue
            claim = {"field": section, "value": fact.text, "quote": fact.quote, "source_url": fact.source_url,
                     "checked_at": checked.isoformat(), "kind": "explanation"}
            verdict = verifier.verify(claims=[claim], source_url=fact.source_url, official_domains=set(),
                                      intake=None, page_text=text, checked_at=checked, now=checked)
            if not all(verdict.checks[key]["passed"] for key in rules["required_checks"]):
                continue
            if len(kept.setdefault(section, [])) < rules["max_facts_per_section"]:
                kept[section].append(fact.model_dump())
    return {section: facts for section, facts in kept.items() if facts}


def _confidence(sections: dict[str, list[dict]], rules: dict) -> str:
    facts = [fact for rows in sections.values() for fact in rows]
    sources = {fact["source_url"] for fact in facts}
    for level in ("high", "medium"):
        need = rules["confidence"][level]
        if len(facts) >= need["min_facts"] and len(sources) >= need["min_sources"]:
            return level
    return "low"


async def research_field(field_key: str, country: str) -> dict:
    """One bounded run: search, read pages, one `researcher` call, verify.
    No database work happens here, so no transaction stays open across it."""
    rules = policy()
    field = study_fields()[field_key]
    label = country.title() if country == country_key(country) else country
    sections = {name: text.format(country=label) for name, text in rules["sections"].items()}
    pages, seen = [], set()
    # Not charged to any student: the note is shared (spec 3.1).
    with bounded_research(queries=len(rules["queries"]), fetches=rules["fetch_limit"],
                          seconds=config.PAI_RESEARCH_MAX_SECONDS, scope="field_research") as budget:
        urls = []
        for template in rules["queries"]:
            if spend("web.search"):
                break
            for hit in await search_web(template.format(field=field.title, country=label), rules["search_limit"]):
                url = hit.get("url")
                if public_https(url) and url not in seen:
                    seen.add(url)
                    urls.append(url)
        for url in urls:
            if len(pages) >= rules["fetch_limit"] or spend("web.fetch"):
                break
            page = await read_page(url, rules["page_chars"])
            if page:
                pages.append(page)
        if not pages:
            return {"status": "no_sources", "research_metrics": budget.usage()}
        if spend("model"):
            return {"status": "budget", "research_metrics": budget.usage()}
        raw = await complete(role="researcher", phase="field_research",
            system_prompt=load_prompt("field_research"),
            messages=[{"role": "user", "content": json.dumps({
                "field": field.title, "country": label, "max_facts_per_section": rules["max_facts_per_section"],
                "sections": sections, "pages": pages}, ensure_ascii=False)}],
            response_format={"type": "json_object"}, max_tokens=rules["max_tokens"],
            usage_callback=record_model_usage)
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {"status": "invalid", "research_metrics": budget.usage()}
        checked = _now()
        kept = verified_facts(parsed, pages, rules, checked)
        if not kept:
            return {"status": "no_verified_facts", "research_metrics": budget.usage()}
        used = {fact["source_url"] for rows in kept.values() for fact in rows}
        return {"status": "stored", "sections": kept, "confidence": _confidence(kept, rules), "researched_at": checked,
                "sources": [{"url": page["url"], "checked_at": checked.isoformat()} for page in pages if page["url"] in used],
                "research_metrics": budget.usage()}


async def field_research_job(job, db) -> dict:
    from app.inference import usage
    if not usage.role_allowed("researcher"):
        # Monthly model cap (research_paused): a quiet skip, logged once a day.
        return {"status": "cap_paused"}
    payload = dict(job.payload or {})
    field_key, country = payload.get("field_key"), country_key(payload.get("country") or policy()["default_country"])
    if field_key not in study_fields():
        return {"status": "unknown_field"}
    if fresh_note(db, field_key, country):
        return {"status": "fresh"}
    db.rollback()
    result = await research_field(field_key, country)
    if result["status"] != "stored":
        logger.info("field_research_%s field=%s", result["status"], field_key)
        return {key: value for key, value in result.items() if key in {"status", "research_metrics"}}
    row = db.scalar(select(PaiFieldNote).where(PaiFieldNote.field_key == field_key,
                                               PaiFieldNote.country == country).with_for_update())
    if row is None:
        row = PaiFieldNote(field_key=field_key, country=country)
        db.add(row)
    row.note = {"sections": result["sections"]}
    row.sources = result["sources"]
    row.confidence = result["confidence"]
    row.researched_at = result["researched_at"]
    db.commit()
    return {"status": "stored", "facts": sum(len(rows) for rows in result["sections"].values()),
            "confidence": result["confidence"], "research_metrics": result["research_metrics"]}


def prompt_notes(db, field_keys, country: str) -> tuple[list[dict], dict[str, dict]]:
    """The analyzer's <field_notes> block (fresh notes of at most
    field_notes_in_prompt fields, in the given order) and every shown fact by
    id, so a path citing one stores its source."""
    block, facts = [], {}
    fields = study_fields()
    for field_key in dict.fromkeys(field_keys):
        if len(block) >= policy()["field_notes_in_prompt"]:
            break
        note = fresh_note(db, field_key, country) if field_key in fields else None
        if note is None:
            continue
        shown = note_facts(note)
        facts.update({fact["id"]: fact for fact in shown})
        block.append({"field_key": field_key, "title": fields[field_key].title,
                      "facts": [{"id": fact["id"], "section": fact["section"], "text": fact["text"]} for fact in shown]})
    return block, facts
