# -*- coding: utf-8 -*-
"""LLM extraction of memory candidates from one conversational turn.

Produces *proposals* and nothing else. It cannot write canonical state, cannot
choose how far it is trusted, and cannot name its own `source_type` — the
caller sets that. Everything it emits still goes through the deterministic
reconciler.

Two failure modes are handled differently on purpose:

    malformed output      -> ExtractionError, the job fails and retries. We do
                             not half-parse a broken response into candidates.
    one bad candidate     -> dropped with a logged reason; its valid siblings
                             survive. One hallucinated field must not discard a
                             correctly extracted CGPA from the same turn.
"""

import json
import logging
import re
import math
from dataclasses import dataclass
from typing import Any, Optional

from app.config import config
from app.inference.gateway import complete as chat_completion, resolve_model

logger = logging.getLogger(__name__)

CANDIDATE_TYPES = ("vault_fact", "student_record")
OPERATIONS = ("upsert",)          # extraction may only ADD proposals
MEMORY_TYPES = ("preference", "goal", "constraint", "interest", "context")
MAX_CANDIDATES = 16                # allow a useful multi-fact introduction


class ExtractionError(RuntimeError):
    """The model's output could not be trusted. Retryable."""


@dataclass(frozen=True)
class ExtractedCandidate:
    """One validated proposal. Note the absence of `source_type` — the server
    assigns it, so there is no field here for a model to populate."""

    candidate_type: str
    operation: str
    key: Optional[str]
    proposed_value: Any
    content: Optional[str]
    entities: dict
    confidence: float
    evidence: dict


SYSTEM_PROMPT = """You extract durable objective student facts from one counseling turn.
The student's message is the only evidence. The assistant and earlier context only resolve references. Return JSON {"candidates": [...]} and no prose.
Use the supplied Vault fields and record schemas. Preserve original qualification wording and reuse exact existing record ids for corrections. Propose only stated fields; never infer dates, scores, currency, institutions or commitment. Every candidate needs a quote copied from the student's message and confidence 0-1.
Candidates: vault_fact with key/proposed_value; student_record with key/proposed_value. All use candidate_type, operation upsert, quote, confidence and optional entities. Existing record patches use entities.record_id; goal replacement uses entities.supersedes_record_id. Course references need an existing education_id.
Goals record only the student's expressed objective target: stated_preference, target_countries, degree_level, field_of_study, target_intake. Preserve exploratory/considering commitment when stated; never upgrade it. Use attribution.claim_owner student/external/mixed/uncertain; mixed goals need attribution.student_clause_quote. Outside suggestions never become student goals.
Do not propose student_voice_statement, external_influence, career.primary_interest, or interpretive goal details. Motivations, drivers, underlying objectives, limits and career interpretations belong to the separate Truth Map, not the Vault. Do not invent personality or affiliations. Greetings and transient logistics produce no candidates.
For explicit corrections include attribution.correction and correction_quote; for explicit changes over time include attribution.temporal_change and change_quote. Copy their evidence, never infer change from a contradiction. Dates may retain year/month precision; do not invent a date. Nothing already recorded is reproposed unless corrected. No evidence means no candidate.
"""

_STOPPED_RECORD_KINDS = frozenset({"student_voice_statement", "external_influence"})
_GOAL_TARGET_DETAILS = frozenset({"stated_preference", "target_countries", "degree_level", "field_of_study", "target_intake"})


def _extractor_specs():
    from copy import deepcopy
    from .student_schema import extraction_specs
    specs = deepcopy(extraction_specs())
    for kind in _STOPPED_RECORD_KINDS:
        specs.pop(kind, None)
    details = specs.get("goal", {}).get("properties", {}).get("details", {})
    if "properties" in details:
        details["properties"] = {k: v for k, v in details["properties"].items() if k in _GOAL_TARGET_DETAILS}
    return specs



def _model_config() -> tuple[str, str, Optional[str]]:
    """Return ``(api_key, model, base_url)`` for extraction.

    Falls back to PAI Counselor's own configuration so this works out of the
    box, while `MEMORY_EXTRACTOR_*` lets extraction move to a cheaper/faster
    model later without touching Counselor.
    """
    api_key = getattr(config, "MEMORY_EXTRACTOR_API_KEY", "") or config.PAI_API_KEY
    model = resolve_model("extractor")
    base_url = (
        getattr(config, "MEMORY_EXTRACTOR_BASE_URL", "")
        or config.PAI_BASE_URL
        or None
    )
    return api_key, model, base_url


def _render_field_specs(field_specs) -> str:
    """Render the Vault fields the model is allowed to propose.

    Without this the model is asked for "<one of the allowed vault field keys>"
    and never told what they are, so it guesses (`cgpa`, `ielts`) and every
    proposal is dropped by `_validate` as an unknown key — the Vault then never
    populates from conversation at all. The key must be exact, so it has to be
    listed; the type has to come with it, because a key the model gets right
    with a value of the wrong shape is rejected one layer later instead.
    """
    lines = []
    for spec in field_specs:
        key = spec.get("key")
        if not key or key == "career.primary_interest":
            continue
        bits = [f"- {key}"]
        if spec.get("data_type"):
            bits.append(f"({spec['data_type']})")
        if spec.get("description"):
            bits.append(f"— {spec['description']}")
        schema = spec.get("validation_schema") or {}
        # Objects/arrays are the ones a model reliably gets wrong; a bare
        # "(object)" does not say which properties are required.
        if spec.get("data_type") in ("object", "array") and schema:
            bits.append(f"shape: {json.dumps(schema, sort_keys=True)}")
        lines.append(" ".join(bits))
    if not lines:
        return ""
    return (
        "VAULT FIELDS YOU MAY PROPOSE (`key` must match one of these EXACTLY; "
        "if nothing fits, propose nothing):\n" + "\n".join(lines)
    )


def build_user_prompt(turn, field_specs=None) -> str:
    """Render a TurnContext into the extractor's user message."""
    parts: list[str] = []

    if field_specs:
        parts.append(_render_field_specs(field_specs))
    from .student_schema import extraction_specs
    parts.append("RECORD SCHEMAS (new records require their required fields; existing record patches may be partial):\n"
                 + json.dumps(_extractor_specs(), ensure_ascii=False))
    if getattr(turn, "records", None):
        parts.append("EXISTING RECORDS (reuse the exact id when updating; do not duplicate):\n"
                     + json.dumps(turn.records, ensure_ascii=False))

    if turn.vault:
        parts.append(
            "EXISTING PROFILE (do not re-propose these unless corrected):\n"
            + json.dumps(turn.vault, ensure_ascii=False, sort_keys=True)
        )
    if turn.existing_memories:
        parts.append(
            "EXISTING MEMORIES (do not repeat these):\n"
            + "\n".join(f"- {m}" for m in turn.existing_memories)
        )
    if turn.recent:
        parts.append(
            "EARLIER IN THIS CONVERSATION (context only, not evidence):\n"
            + "\n".join(f"{m['role']}: {m['text']}" for m in turn.recent)
        )

    parts.append(f"STUDENT MESSAGE (the only evidence):\n{turn.user_text}")
    if turn.assistant_text:
        parts.append(
            "ASSISTANT REPLY (for reference resolution only — never evidence):\n"
            + turn.assistant_text
        )
    parts.append("Extract now. Return only the JSON object.")
    return "\n\n".join(parts)


def _parse_response(raw: str) -> list[dict]:
    """Parse the model's JSON. Raises ExtractionError on anything unusable."""
    if not (raw or "").strip():
        raise ExtractionError("empty extraction response")

    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ExtractionError(f"extraction output was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ExtractionError("extraction output was not a JSON object")
    candidates = parsed.get("candidates")
    if candidates is None:
        raise ExtractionError("extraction output has no 'candidates' key")
    if not isinstance(candidates, list):
        raise ExtractionError("'candidates' was not a list")
    return candidates


# Fillers models emit for a field they were asked to omit. Storing one would
# put the string "Unknown" into a canonical student record.
_PLACEHOLDERS = frozenset({
    "", "-", "--", "n/a", "na", "none", "null", "nil", "unknown", "unspecified",
    "not specified", "not stated", "not mentioned", "not provided", "not applicable",
    "tbd", "to be determined", "unsure", "undecided",
})


def _coerce_proposal(raw: dict) -> dict:
    """Repair the two transport shapes models reliably get wrong.

    The RECORD SCHEMAS block lists record kinds ("education", "visa", ...) as
    top-level JSON keys, which pulls models into naming the kind as
    `candidate_type` and nesting `quote`/`confidence` inside `proposed_value`.
    Both shapes carry correctly extracted data, so normalize them rather than
    discard a good record. Nothing here relaxes a check: the repaired quote is
    still verified against the student's message, and the key is still matched
    against ENTITY_MODELS by the caller.
    """
    from .student_records import ENTITY_MODELS

    kind = raw.get("candidate_type")
    if isinstance(kind, str) and kind not in CANDIDATE_TYPES and kind in ENTITY_MODELS:
        raw = {**raw, "candidate_type": "student_record", "key": raw.get("key") or kind}

    value = raw.get("proposed_value")
    if isinstance(value, dict) and ("quote" in value or "confidence" in value):
        repaired = dict(raw)
        for field in ("quote", "confidence"):
            # A value already stated at the top level wins over the nested copy.
            if field in value and repaired.get(field) is None:
                repaired[field] = value[field]
        repaired["proposed_value"] = {
            k: v for k, v in value.items() if k not in ("quote", "confidence")
        }
        raw = repaired
    return raw


def _strip_placeholders(value):
    """Drop filler values recursively. None means "nothing worth storing"."""
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            child = _strip_placeholders(child)
            if child is not None:
                cleaned[key] = child
        return cleaned or None
    if isinstance(value, list):
        items = [item for item in (_strip_placeholders(v) for v in value) if item is not None]
        return items or None
    if isinstance(value, str) and value.strip().casefold() in _PLACEHOLDERS:
        return None
    return value


# Schema fields that assert a point in time. A model that is told "final year"
# will happily compute a graduation year; a counselor that believes the student
# already graduated gives wrong advice for the rest of the relationship.
_YEAR_FIELDS = ("graduation_year",)
_DATE_FIELDS = ("start_date", "end_date", "test_date", "expiry_date", "issued_on",
                "expires_on", "issued_at", "valid_from", "valid_until",
                "deadline", "target_date", "achieved_on")


def _drop_unevidenced_dates(value: dict, user_text: str) -> dict:
    """Remove a year the student never actually said.

    The module already refuses a quote that is not in the student's message;
    this applies the same evidence rule to the one field type models infer
    most confidently. Omitting a date is recoverable — PAI can ask. A wrong
    one silently poisons every later recommendation.
    """
    stated = set(re.findall(r"(?:19|20)\d{2}", user_text or ""))
    cleaned = dict(value)
    for field in _YEAR_FIELDS + _DATE_FIELDS:
        if field not in cleaned:
            continue
        if str(cleaned[field])[:4] not in stated:
            logger.info("memory: dropped inferred %s from a %s proposal", field, "record")
            cleaned.pop(field)
    return cleaned


# A budget is only comparable if its currency is written one way. Models echo
# whatever the student typed ("EUR", "eur", "€"), and "€" != "EUR" defeats every
# later comparison, conversion and affordability check. Only unambiguous symbols
# are mapped; an ambiguous one is left untouched rather than guessed wrong.
_CURRENCY_SYMBOLS = {
    "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "₨": "PKR", "₩": "KRW",
    "₪": "ILS", "₺": "TRY", "₽": "RUB", "₴": "UAH", "₫": "VND", "฿": "THB",
    # An unqualified "$" is ambiguous across countries; leave it as written.
    "US$": "USD", "usd": "USD", "eur": "EUR",
    "gbp": "GBP", "pkr": "PKR", "inr": "INR",
}


def _normalize_currencies(value):
    """Rewrite any `currency` field to an ISO-4217-style code, recursively."""
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if key == "currency" and isinstance(child, str):
                text = child.strip()
                mapped = _CURRENCY_SYMBOLS.get(text) or _CURRENCY_SYMBOLS.get(text.casefold())
                if mapped is None and len(text) == 3 and text.isalpha():
                    mapped = text.upper()
                out[key] = mapped or text
            else:
                out[key] = _normalize_currencies(child)
        return out
    if isinstance(value, list):
        return [_normalize_currencies(item) for item in value]
    return value


_MONEY_FIELDS = ("amount", "value", "tuition", "cost")


def _stated_amounts(text: str) -> set:
    """Every figure the student actually wrote, with k/thousand expanded.

    "About EUR 12k per year" yields {12, 12000}, so a proposal of 12000 is
    evidenced and a proposal of 15000 is not.
    """
    found = set()
    for raw, suffix in re.findall(r"(\d[\d,.\s]*)\s*(k|m|thousand|million|lakh|crore)?",
                                  (text or ""), flags=re.IGNORECASE):
        digits = re.sub(r"[,\s]", "", raw).rstrip(".")
        if not digits:
            continue
        try:
            number = float(digits)
        except ValueError:
            continue
        found.add(number)
        multiplier = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6,
                      "lakh": 1e5, "crore": 1e7}.get((suffix or "").lower())
        if multiplier:
            found.add(number * multiplier)
        # "12,000" also reads as a bare 12 followed by 000 in sloppy output.
        if "." not in digits:
            found.add(number * 1000)
    return found


def _money_is_evidenced(figure, text: str) -> bool:
    """True when this exact figure appears in the student's own words."""
    if isinstance(figure, bool) or not isinstance(figure, (int, float)):
        return True  # not a number we can check; other rules apply
    return any(abs(figure - candidate) < 0.01 for candidate in _stated_amounts(text))


def _validate(raw: dict, turn, allowed_vault_keys: set[str]) -> Optional[ExtractedCandidate]:
    """Validate one proposal. None (with a reason logged) if unusable.

    Dropping the individual candidate rather than raising is what lets a good
    CGPA survive a bad sibling from the same turn.
    """
    def drop(reason: str) -> None:
        logger.info("memory: dropped candidate — %s", reason)
        return None

    if not isinstance(raw, dict):
        return drop("not an object")

    raw = _coerce_proposal(raw)

    candidate_type = raw.get("candidate_type")
    if raw.get("key") in _STOPPED_RECORD_KINDS or raw.get("key") == "career.primary_interest":
        return drop("interpretation belongs to the Truth Map")
    if candidate_type not in CANDIDATE_TYPES:
        return drop(f"unknown candidate_type {candidate_type!r}")

    operation = raw.get("operation", "upsert")
    if operation not in OPERATIONS:
        return drop(f"extraction may not propose operation {operation!r}")

    # The evidence rule, enforced rather than requested: the quote must
    # actually appear in the student's message. This is what stops the
    # assistant's own words becoming student truth (requirement 7).
    if not isinstance(raw.get("quote"), str):
        return drop("quote not a string")
    quote = raw["quote"].strip()
    if not quote:
        return drop("no quote")
    if _normalize(quote) not in _normalize(turn.user_text):
        return drop("quote not found in the student's message")

    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        return drop("confidence not a number")
    if not math.isfinite(confidence):
        return drop("confidence not finite")
    confidence = max(0.0, min(1.0, confidence))

    entities = raw.get("entities")
    if not isinstance(entities, dict):
        entities = {}

    evidence = {"quote": quote[:500], "user_event_id": turn.user_event_id}
    from .voice_attribution import contained, validated_attribution
    attribution = raw.get("attribution")
    if (isinstance(attribution, dict) and attribution.get("correction") is True
            and contained(attribution.get("correction_quote"), quote)):
        evidence["semantic_correction"] = True
    if (isinstance(attribution, dict) and attribution.get("temporal_change") is True
            and contained(attribution.get("change_quote"), quote)):
        evidence["semantic_temporal_change"] = True

    if candidate_type == "vault_fact":
        key = raw.get("key")
        if not key or key not in allowed_vault_keys:
            return drop(f"unknown vault key {key!r}")
        if "proposed_value" not in raw:
            return drop("vault_fact without proposed_value")
        proposed = _strip_placeholders(raw["proposed_value"])
        if proposed is None:
            return drop(f"vault_fact {key!r} stated no actual value")
        proposed = _normalize_currencies(proposed)
        # A money field of 0 is a model filling in a blank, not a figure the
        # student gave ("Cost is important" became {"amount": 0} in testing).
        # Storing it as canonical makes every affordability check wrong; no
        # budget at all is recoverable, because PAI can simply ask.
        if isinstance(proposed, dict):
            for money in ("amount", "value", "tuition", "cost"):
                figure = proposed.get(money)
                if isinstance(figure, bool) or figure is None:
                    continue
                if isinstance(figure, (int, float)) and figure <= 0:
                    return drop(f"vault_fact {key!r} proposed a non-positive {money}")
                # A figure the student never said is invented, and a wrong
                # budget is more damaging than a missing one: it looks
                # legitimate and silently misprices every recommendation.
                if not _money_is_evidenced(figure, turn.user_text):
                    return drop(f"vault_fact {key!r} {money}={figure!r} is not in the student's words")
        return ExtractedCandidate(
            candidate_type="vault_fact", operation="upsert", key=key,
            proposed_value=proposed, content=None,
            entities=entities, confidence=confidence, evidence=evidence,
        )

    if candidate_type == "student_record":
        from .student_records import ENTITY_MODELS
        from .student_schema import validate_record
        from .errors import MemoryDataError
        kind = raw.get("key")
        value = raw.get("proposed_value")
        if not isinstance(kind, str) or kind not in ENTITY_MODELS or kind == "document" or not isinstance(value, dict):
            return drop("invalid student record proposal")
        record_ids = {row["id"] for row in (getattr(turn, "records", {}) or {}).get(kind, [])}
        clean_entities = {}
        for reference in ("record_id", "supersedes_record_id"):
            if reference in entities:
                if not isinstance(entities[reference], str) or entities[reference] not in record_ids:
                    return drop("record reference was not in this student's context")
                clean_entities[reference] = entities[reference]
        if "supersedes_record_id" in clean_entities and kind != "goal":
            return drop("only goals may supersede another goal")
        if kind == "course" and "education_id" in value:
            education_ids = {row["id"] for row in (getattr(turn, "records", {}) or {}).get("education", [])}
            if value["education_id"] not in education_ids:
                return drop("course education_id was not in this student's context")
        value = _strip_placeholders(value)
        if not isinstance(value, dict) or not value:
            return drop(f"{kind} record stated no actual values")
        if kind == "goal" and isinstance(value.get("details"), dict):
            value = {**value, "details": {key: child for key, child in value["details"].items() if key in _GOAL_TARGET_DETAILS}}
        value = _drop_unevidenced_dates(value, turn.user_text)
        value = _normalize_currencies(value)
        if not value:
            return drop(f"{kind} record stated no actual values")
        if kind in {"goal", "student_voice_statement", "external_influence"}:
            owner = validated_attribution(attribution, kind=kind, quote=quote,
                message=turn.user_text, voice_type=value.get("voice_type"))
            if owner is None:
                return drop(f"{kind} lacks valid claim ownership")
            evidence["attribution"] = owner
        try:
            value = validate_record(kind, value, partial="record_id" in clean_entities)
        except MemoryDataError as exc:
            return drop(str(exc))
        return ExtractedCandidate(
            candidate_type="student_record", operation="upsert", key=kind,
            proposed_value=value, content=None, entities=clean_entities,
            confidence=confidence, evidence=evidence,
        )

    if not isinstance(raw.get("content"), str):
        return drop("content not a string")
    content = raw["content"].strip()
    if not content:
        return drop(f"{candidate_type} without content")

    if candidate_type == "semantic_memory":
        memory_type = raw.get("memory_type", "context")
        if memory_type not in MEMORY_TYPES:
            memory_type = "context"
        entities = {**entities, "memory_type": memory_type}
    else:
        event_type = raw.get("event_type") or "decision_made"
        entities = {**entities, "event_type": str(event_type)[:80]}

    return ExtractedCandidate(
        candidate_type=candidate_type, operation="upsert", key=None,
        proposed_value=None, content=content[:2000],
        entities=entities, confidence=confidence, evidence=evidence,
    )


def _normalize(text: str) -> str:
    """Casefold + collapse whitespace, for quote matching."""
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


async def extract_candidates(
    turn, allowed_vault_keys: set[str], field_specs=None,
) -> list[ExtractedCandidate]:
    """Run extraction for one turn. Raises ExtractionError on bad output.

    `allowed_vault_keys` is the authorization boundary — `_validate` drops
    anything outside it regardless of what the model returns. `field_specs`
    (key/type/description) is the same set rendered INTO the prompt so the
    model can hit those keys exactly; callers that pass only keys still get
    them listed, just without type hints.
    """
    if turn.is_empty():
        return []

    api_key, model, base_url = _model_config()
    if not api_key:
        raise ExtractionError("no extraction API key configured")

    specs = field_specs or [{"key": key} for key in sorted(allowed_vault_keys)]
    raw = await chat_completion(role="extractor",
        api_key=api_key, model=model,
        messages=[{"role": "user", "content": build_user_prompt(turn, specs)}],
        system_prompt=SYSTEM_PROMPT, max_tokens=4000, base_url=base_url,
    )

    proposals = _parse_response(raw)
    if len(proposals) > MAX_CANDIDATES:
        logger.warning(
            "memory: extraction returned %d candidates, truncating to %d",
            len(proposals), MAX_CANDIDATES,
        )
        proposals = proposals[:MAX_CANDIDATES]

    validated = [
        candidate for candidate in (
            _validate(p, turn, allowed_vault_keys) for p in proposals
        ) if candidate is not None
    ]
    return validated
