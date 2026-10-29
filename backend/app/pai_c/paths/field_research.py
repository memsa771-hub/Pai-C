"""Shared, sourced notes on a study field (BETA_CONVERSATION_SPEC 3.1).

One bounded research run per field and country, not per student: the path
analyzer and path explain of every student read the same cached note, so the
cost is per field. Every fact carries a real passage that the code finds on
the page it came from and that states the fact's numbers and words (the
model's word is never enough); a fact naming an institution is dropped, since
places come only at stage H; a fact from a site outside the trusted domains is
kept as uncertain and never shown to the analyzer.
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
from app.plugins._shared.sources import public_https, quote_on_page, quote_supports, read_page, search_web
from app.plugins._shared.verification import official_url

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
    # trusted: from a trusted domain; uncertain: any other site (and notes stored before this field).
    confidence: str = "uncertain"


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
                          "source_url": fact.source_url, "quote": fact.quote, "confidence": fact.confidence})
    return facts


def _pending(db, field_key: str, country: str) -> bool:
    return db.scalar(select(BackgroundJob.id).where(
        BackgroundJob.job_type == JOB_FIELD_RESEARCH, BackgroundJob.status.in_(("pending", "running")),
        BackgroundJob.payload["field_key"].as_string() == field_key,
        BackgroundJob.payload["country"].as_string() == country_key(country)).limit(1)) is not None


def enqueue_missing(db, field_keys, country: str, limit: int | None = None) -> list[str]:
    """Queue research for fields with no fresh note and none queued, at most
    `limit` (field_notes_per_run). Idempotent per field, country and ISO week,
    so a run that found nothing is tried again the next week, not on every
    analysis. The caller commits."""
    from app.runtime.task_runtime import enqueue
    limit = policy()["field_notes_per_run"] if limit is None else limit
    year, week, _ = _now().isocalendar()
    queued, period = [], f"{year}-W{week:02d}"
    for field_key in dict.fromkeys(field_keys):
        if len(queued) >= limit:
            break
        if field_key not in study_fields() or fresh_note(db, field_key, country) or _pending(db, field_key, country):
            continue
        job = enqueue(db, JOB_FIELD_RESEARCH, {"field_key": field_key, "country": country_key(country)},
                      idempotency_key=f"field_note:{field_key}:{country_key(country)}:{period}")
        if job is not None and job.status == "pending":
            queued.append(job.id)
    return queued


def institution_blocklist(db) -> set[str]:
    """Institution names to keep out of notes: the policy's words plus every
    name and domain label in the institution catalog. Without a session, the
    words alone."""
    blocked = {word.casefold() for word in policy()["institution_words"]}
    if db is None:
        return blocked
    from app.models import Institution, InstitutionDomain
    for name, normal in db.execute(select(Institution.name, Institution.normalized_name)).all():
        blocked.update(value.casefold() for value in (name, normal) if value and value.strip())
    for (domain,) in db.execute(select(InstitutionDomain.domain)).all():
        labels = [label for label in str(domain or "").casefold().split(".") if label and label != "www"]
        if labels:
            blocked.add(labels[0])
    return {" ".join(word.split()) for word in blocked if word.strip()}


def names_institution(text: str, blocked: set[str], rules: dict) -> bool:
    """A whole-word match of a blocked name in any case ("Nust", "NUST"), or
    an institution pattern. A name that is also an English word
    (english_collisions) matches only in capitals, so "FAST" is blocked but
    "work fast" is not."""
    lower = " " + re.sub(r"[^a-z0-9-]+", " ", text.lower()) + " "
    upper = " " + re.sub(r"[^A-Za-z0-9-]+", " ", text) + " "
    collisions = set(rules["english_collisions"])
    for name in blocked:
        if (f" {name.upper()} " in upper) if name in collisions else (f" {name} " in lower):
            return True
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in rules["institution_patterns"])


def trusted_domains() -> set[str]:
    """Sites whose facts count as trusted: the policy's domains, path
    research's trusted_domains, and the hosts of admission rules researched
    from an official source."""
    from urllib.parse import urlparse
    rules = load_data("admission_rules.json")
    hosts = {(urlparse(url).hostname or "").casefold().removeprefix("www.")
             for row in rules["rules"] if row.get("confidence") == "official" for url in row.get("sources", [])}
    from app.pai_c.paths.explain import policy as research_policy
    return {domain for domain in (*policy()["trusted_domains"], *research_policy()["trusted_domains"], *hosts) if domain}


def verified_facts(raw: dict, pages: list[dict], rules: dict, checked: datetime, *,
                   blocked: set[str], trusted: set[str]) -> dict[str, list[dict]]:
    """Keep a fact only when its quote is on the page it cites (line breaks
    ignored) and supports it (quote_rules: a real passage with the fact's
    numbers, negations and most of its content words), and when neither its text nor its
    quote names an institution or uses a blocked script. A fact from a
    trusted domain is "trusted", any other "uncertain"."""
    by_url = {page["url"]: page["text"] for page in pages}
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
            if text is None or not quote_on_page(fact.quote, text) or not quote_supports(fact.text, fact.quote, rules["quote_rules"]):
                continue
            words = fact.text + " " + fact.quote
            if names_institution(words, blocked, rules) or contains_blocked_script(words, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
                continue
            fact.confidence = "trusted" if official_url(fact.source_url, trusted) else "uncertain"
            if len(kept.setdefault(section, [])) < rules["max_facts_per_section"]:
                kept[section].append(fact.model_dump())
    return {section: facts for section, facts in kept.items() if facts}


def _confidence(sections: dict[str, list[dict]], rules: dict) -> str:
    """From trusted facts only; a note with none is uncertain."""
    facts = [fact for rows in sections.values() for fact in rows if fact.get("confidence") == "trusted"]
    if not facts:
        return "uncertain"
    sources = {fact["source_url"] for fact in facts}
    for level in ("high", "medium"):
        need = rules["confidence"][level]
        if len(facts) >= need["min_facts"] and len(sources) >= need["min_sources"]:
            return level
    return "low"


async def research_field(field_key: str, country: str, blocked: set[str] | None = None) -> dict:
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
        kept = verified_facts(parsed, pages, rules, checked, blocked=blocked or institution_blocklist(None),
                              trusted=trusted_domains())
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
    blocked = institution_blocklist(db)
    db.rollback()
    result = await research_field(field_key, country, blocked)
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
    id, so a path citing one stores its source. Only trusted facts are shown,
    so an uncertain one can never back a path's why."""
    block, facts = [], {}
    fields = study_fields()
    for field_key in dict.fromkeys(field_keys):
        if len(block) >= policy()["field_notes_in_prompt"]:
            break
        note = fresh_note(db, field_key, country) if field_key in fields else None
        if note is None:
            continue
        shown = [fact for fact in note_facts(note) if fact["confidence"] == "trusted"]
        if not shown:
            continue
        facts.update({fact["id"]: fact for fact in shown})
        block.append({"field_key": field_key, "title": fields[field_key].title,
                      "facts": [{"id": fact["id"], "section": fact["section"], "text": fact["text"]} for fact in shown]})
    return block, facts
