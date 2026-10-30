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
                             correctly extracted grade from the same turn.
"""

import json
import logging
import re
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.workspace_language import workspace_language_block
from app.config import config
from app.inference.gateway import complete as chat_completion, resolve_model

logger = logging.getLogger(__name__)

CANDIDATE_TYPES = ("vault_fact", "student_record", "vault_item")
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


@dataclass(frozen=True)
class ExtractionOutput:
    """What one turn produced: the valid proposals, and every proposal dropped
    with its reason. The caller persists the drops (zero silent drops)."""

    candidates: list
    drops: list


def render_item(spec) -> str:
    """One item type as a prompt line: fields, required marks, codes, ranges.
    Shared with the document extractor so both read the catalog the same way."""
    from app.memory.catalog import vault_catalog
    catalog = vault_catalog()
    required = set(spec.schema.get("required", []))
    fields = []
    for name, prop in spec.schema["properties"].items():
        bit = name + ("*" if name in required else "")
        if name in spec.choice_fields:
            bit += " (" + "|".join(c.code for c in catalog.choices(spec.choice_fields[name])) + ")"
        elif "enum" in prop:
            bit += " (" + "|".join(prop["enum"]) + ")"
        elif prop.get("type") == "number":
            bit += f" (number {prop.get('minimum', '')}-{prop.get('maximum', '')})"
        fields.append(bit)
    return f"- {spec.key}: " + ", ".join(fields)


def _render_catalog() -> str:
    """Item types and record kinds, read from the catalog so a new catalog
    entry reaches the model without a prompt edit."""
    from app.memory.catalog import vault_catalog
    catalog = vault_catalog()
    lines = ["VAULT ITEMS (candidate_type vault_item, key = the item type; * = required):"]
    lines += [render_item(spec) for spec in catalog.types(storage="item")]
    kinds = ", ".join(spec.key for spec in catalog.types(storage="record"))
    lines.append(f"RECORD KINDS (candidate_type student_record): {kinds}")
    return "\n".join(lines)


def _render_codes(text: str) -> str:
    """Fill <enum type.field/> with that field's codes, <choices list/> with a
    catalog choice list's codes and <code type.field c/> with c, failing at import if the catalog no longer has it, so the prose
    can never name a code the validator would reject."""
    from app.memory.catalog import vault_catalog

    def enum(type_field: str) -> list[str]:
        type_key, field_name = type_field.rsplit(".", 1)
        return list(vault_catalog().type(type_key).schema["properties"][field_name]["enum"])

    def code(match) -> str:
        if match.group(2) not in enum(match.group(1)):
            raise ValueError(f"extractor prompt names unknown code {match.group(2)!r} for {match.group(1)}")
        return match.group(2)

    def choices(name: str) -> str:
        codes = [c.code for c in vault_catalog().choices(name)]
        if not codes:
            raise ValueError(f"extractor prompt names unknown choice list {name!r}")
        return "|".join(codes)

    text = re.sub(r"<choices (\w+)/>", lambda m: choices(m.group(1)), text)
    text = re.sub(r"<enum ([\w.]+)/>", lambda m: "|".join(enum(m.group(1))), text)
    return re.sub(r"<code ([\w.]+) (\w+)/>", code, text)


# Loaded once; the catalog block is filled in here so the eval fingerprint
# (scripts/eval_vault.py) changes whenever the catalog does.
SYSTEM_PROMPT = _render_codes((Path(__file__).with_name("prompts") / "extractor.md").read_text(
    encoding="utf-8")).replace("<vault_catalog/>", _render_catalog())

_GOAL_TARGET_DETAILS = frozenset({"stated_preference", "target_countries", "degree_level", "field_of_study", "target_intake"})


def _chat_proposable(raw: dict) -> bool:
    """Whether chat may propose this key, from data: a catalog type needs
    "chat" in its inputs (career.primary_interest is the Story card's own);
    an uncatalogued record kind is stopped by `chat_input: false` in
    vault_view.json (voice statements and outside influences: a family's wish
    is a family_member item now)."""
    from .catalog import vault_catalog
    from .vault_view import view_copy
    key = raw.get("key")
    if not isinstance(key, str):
        return True
    spec = vault_catalog().type(key)
    if spec is not None:
        return "chat" in spec.inputs
    return view_copy()["uncatalogued_records"].get(key, {}).get("chat_input", True)


def _extractor_specs():
    from copy import deepcopy
    from .student_schema import extraction_specs
    specs = {kind: spec for kind, spec in deepcopy(extraction_specs()).items()
             if _chat_proposable({"key": kind})}
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
    and never told what they are, so it guesses (unsupported field names) and every
    proposal is dropped by `_validate` as an unknown key — the Vault then never
    populates from conversation at all. The key must be exact, so it has to be
    listed; the type has to come with it, because a key the model gets right
    with a value of the wrong shape is rejected one layer later instead.
    """
    lines = []
    for spec in field_specs:
        key = spec.get("key")
        if not key or not _chat_proposable({"key": key}):
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

    if getattr(turn, "items", None):
        parts.append("EXISTING VAULT ITEMS (to correct one, name its exact id in entities.item_id):\n"
                     + json.dumps(turn.items, ensure_ascii=False))
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
    from .catalog import vault_catalog
    from .student_records import ENTITY_MODELS

    kind = raw.get("candidate_type")
    if isinstance(kind, str) and kind not in CANDIDATE_TYPES and kind in ENTITY_MODELS:
        raw = {**raw, "candidate_type": "student_record", "key": raw.get("key") or kind}
    elif isinstance(kind, str) and kind not in CANDIDATE_TYPES:
        spec = vault_catalog().type(kind)
        if spec is not None and spec.storage == "item":
            raw = {**raw, "candidate_type": "vault_item", "key": raw.get("key") or kind}

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


def _normalize_currencies(value):
    """Uppercase three-letter currency values; preserve other trimmed text."""
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if key == "currency" and isinstance(child, str):
                text = child.strip()
                out[key] = text.upper() if len(text) == 3 and text.isalpha() else text
            else:
                out[key] = _normalize_currencies(child)
        return out
    if isinstance(value, list):
        return [_normalize_currencies(item) for item in value]
    return value


_MONEY_FIELDS = ("amount", "value", "tuition", "cost", "min", "max")
def _income_rules():
    """Compile prompts/income_words.json (a data file: no language lists in code)."""
    data = json.loads((Path(__file__).with_name("prompts") / "income_words.json").read_text(encoding="utf-8"))

    def words(items):
        return re.compile(r"\b(?:" + "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in items) + r")\b",
                          re.IGNORECASE)

    income = re.compile("|".join([words(data["words"]).pattern, *data["patterns"]]), re.IGNORECASE)
    return income, words(data["never"]), words(data["amount_cues"])


_INCOME, _NOT_INCOME, _AMOUNT_CUE = _income_rules()


def money_kinds() -> set[str]:
    """Types and record kinds that can carry a household's money, from data:
    the catalog's `money` flag and vault_view.json's uncatalogued records. The
    student's own records (their pay at a job, "low-income families" in an
    activity) are not marked, so they are not household income."""
    from .catalog import vault_catalog
    from .vault_view import view_copy
    return ({spec.key for spec in vault_catalog().types() if spec.money}
            | {kind for kind, place in view_copy()["uncatalogued_records"].items() if place.get("money")})


def _text_of(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _states_income(value) -> bool:
    """An income word and a figure together: a household income was stated.
    The spec never stores one, whatever the student volunteered."""
    text = _NOT_INCOME.sub(" ", _text_of(value))
    return bool(_INCOME.search(text)) and bool(re.search(r"\d", text))


def states_household_income(raw: dict, allowed_vault_keys) -> bool:
    """True when a proposal would carry a household income into memory.

    Checked before every other rule, by both extractors: a proposal dropped
    for a bad quote or locator still reaches the drop log, and the log must
    not hold the figure either. Guarded targets are where a household's money
    could land (finance facts, family and pressure items, free-text memories)
    and any key or type we do not know, such as an invented `household_income`.
    """
    from .catalog import vault_catalog
    from .student_records import ENTITY_MODELS

    candidate_type, key = raw.get("candidate_type"), raw.get("key")
    known = isinstance(key, str)
    money = money_kinds()
    if candidate_type == "vault_fact":
        guarded = not known or key not in allowed_vault_keys or key in money
    elif candidate_type == "vault_item":
        guarded = not known or vault_catalog().type(key) is None or key in money
    elif candidate_type == "student_record":
        guarded = not known or key not in ENTITY_MODELS or key in money
    else:
        guarded = True
    if not guarded:
        return False
    quote = raw.get("quote") if isinstance(raw.get("quote"), str) else ""
    return any(_states_income(text) for text in (quote, raw.get("proposed_value"), raw.get("content") or ""))


def drop_household_income(proposals: list, allowed_vault_keys, drops: list, coerce=None) -> list:
    """The proposals with every household income removed, each logged redacted.

    Run before the candidate limit: an income proposal must not be cut into
    the over-limit log with its value, nor take a slot from a real one.
    """
    kept = []
    for raw in proposals:
        shaped = coerce(raw) if coerce and isinstance(raw, dict) else raw
        if isinstance(shaped, dict) and states_household_income(shaped, allowed_vault_keys):
            logger.info("memory: dropped candidate — household_income")
            drops.append({"reason": "household_income", "payload": {
                "candidate_type": shaped.get("candidate_type"), "key": shaped.get("key"),
                "reason": "household_income"}})
            continue
        kept.append(raw)
    return kept


def _carries_money_figure(text: str) -> bool:
    """A free-text field with a figure and a money cue ("about 50,000 a month")."""
    return _states_income(text) or (bool(re.search(r"\d", text)) and bool(_AMOUNT_CUE.search(text)))


_MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "lakh": 1e5, "crore": 1e7}


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
        multiplier = _MULTIPLIERS.get((suffix or "").lower())
        if multiplier:
            found.add(number * multiplier)
        # "12,000" also reads as a bare 12 followed by 000 in sloppy output.
        if "." not in digits:
            found.add(number * 1000)
    # "2 se 3 lakh" / "2-3 lakh": the unit after a range covers its low end too.
    for low, unit in re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:-|–|to|se|sy|or|ya)\s*\d+(?:\.\d+)?\s*(k|m|thousand|million|lakh|crore)\b",
            text or "", flags=re.IGNORECASE):
        found.add(float(low) * _MULTIPLIERS[unit.lower()])
    return found


def _money_is_evidenced(figure, text: str) -> bool:
    """True when this exact figure appears in the student's own words."""
    if isinstance(figure, bool) or not isinstance(figure, (int, float)):
        return True  # not a number we can check; other rules apply
    return any(abs(figure - candidate) < 0.01 for candidate in _stated_amounts(text))


def _validate(raw: dict, turn, allowed_vault_keys: set[str],
              drops: Optional[list] = None) -> Optional[ExtractedCandidate]:
    """Validate one proposal. None (with a reason logged) if unusable.

    Dropping the individual candidate rather than raising is what lets a good
    grade survive a bad sibling from the same turn. Each drop is also appended
    to `drops` so the caller can write it to the Vault drop log.
    """
    original = raw

    def drop(reason: str, redact: bool = False) -> None:
        logger.info("memory: dropped candidate — %s", reason)
        if drops is not None:
            if redact:
                # The drop log must never hold the figure either: no value, no quote.
                payload = {"candidate_type": raw.get("candidate_type"), "key": raw.get("key"), "reason": reason}
            elif isinstance(original, dict):
                payload = {k: original.get(k) for k in ("candidate_type", "key", "proposed_value")}
            else:
                payload = {"raw": original}
            drops.append({"reason": reason, "payload": payload})
        return None

    if not isinstance(raw, dict):
        return drop("not an object")

    raw = _coerce_proposal(raw)
    # The quote is checked too: a budget of {"amount": 80000} is only numbers,
    # but "Abbu ki tankhwah 80 hazar hai" says whose money it is.
    if states_household_income(raw, allowed_vault_keys):
        return drop("household_income", redact=True)

    candidate_type = raw.get("candidate_type")
    if not _chat_proposable(raw):
        return drop("not a chat input for this type")
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
    if raw.get("inferred") is True:
        evidence["inferred"] = True
    key = raw.get("key")
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
            # A figure already saved for this field is the student's own earlier
            # answer, repeated as context; only a changed figure needs their words.
            # A saved guess is not their answer, so its figures still need them.
            saved = (getattr(turn, "vault", None) or {}).get(key)
            guessed = key in (getattr(turn, "vault_guesses", None) or ())
            saved = saved if isinstance(saved, dict) and not guessed else {}
            for money in _MONEY_FIELDS:
                figure = proposed.get(money)
                if isinstance(figure, bool) or figure is None or figure == saved.get(money):
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

    if candidate_type == "vault_item":
        from app.memory.catalog import vault_catalog
        from app.tools.schema import SchemaValidationError, validate_schema_instance
        key = raw.get("key")
        spec = vault_catalog().type(key) if isinstance(key, str) else None
        if spec is None or spec.storage != "item" or "chat" not in spec.inputs:
            return drop(f"unknown item type {key!r}")
        value = _strip_placeholders(raw.get("proposed_value"))
        if not isinstance(value, dict):
            return drop(f"{key} item stated no actual values")
        if key == "family_member":
            # A parent's pay in a free-text field ("Shopkeeper, about 50,000 a
            # month") loses that field; the rest of the person is kept.
            kept = {f: v for f, v in value.items() if not (isinstance(v, str) and _carries_money_figure(v))}
            if kept != value:
                drop("household_income", redact=True)
                value = kept
        try:
            validate_schema_instance(spec.schema, value)
        except SchemaValidationError as exc:
            return drop(f"{key} item invalid: {exc}")
        if (evidence.get("inferred") and key == "family_member" and value.get("wish")
                and isinstance(attribution, dict) and attribution.get("stated_field") == "wish"):
            # The extractor says the student stated this person's wish; it is
            # Stated only when the quote says a wish ("abbu chahte hain"),
            # never because the quote merely names the person (audit #5).
            from app.memory.normalize import says_a_wish
            if says_a_wish(quote):
                evidence.pop("inferred")
        # An id is passed on only when it names one of this student's items of
        # this type that the turn context showed. Any other id is dropped on
        # its own (and logged): the value is still the student's words, so it
        # goes on as a new item rather than being lost.
        clean_entities = {}
        if "item_id" in entities:
            known = {row["id"] for row in (getattr(turn, "items", None) or []) if row.get("type") == key}
            if isinstance(entities["item_id"], str) and entities["item_id"] in known:
                clean_entities["item_id"] = entities["item_id"]
            else:
                drop("item reference was not in this student's context; kept as a new item")
        return ExtractedCandidate(
            candidate_type="vault_item", operation="upsert", key=key,
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
) -> ExtractionOutput:
    """Run extraction for one turn. Raises ExtractionError on bad output.

    `allowed_vault_keys` is the authorization boundary — `_validate` drops
    anything outside it regardless of what the model returns. `field_specs`
    (key/type/description) is the same set rendered INTO the prompt so the
    model can hit those keys exactly; callers that pass only keys still get
    them listed, just without type hints. Every dropped proposal comes back in
    `drops` for the caller to log.
    """
    if turn.is_empty():
        return ExtractionOutput([], [])
    from app.inference import usage
    if not usage.role_allowed("extractor"):
        # Monthly model cap reached: extraction stops until next month.
        return ExtractionOutput([], [])

    api_key, model, base_url = _model_config()
    if not api_key:
        raise ExtractionError("no extraction API key configured")

    specs = field_specs or [{"key": key} for key in sorted(allowed_vault_keys)]
    raw = await chat_completion(role="extractor",
        api_key=api_key, model=model,
        messages=[{"role": "user", "content": build_user_prompt(turn, specs) + "\n" + workspace_language_block()}],
        system_prompt=SYSTEM_PROMPT, base_url=base_url,  # output cap: model_roles.json
    )

    drops: list[dict] = []
    # Income first, so it neither reaches the over-limit log nor uses a slot.
    proposals = drop_household_income(_parse_response(raw), allowed_vault_keys, drops,
                                      coerce=_coerce_proposal)
    if len(proposals) > MAX_CANDIDATES:
        logger.warning(
            "memory: extraction returned %d candidates, truncating to %d",
            len(proposals), MAX_CANDIDATES,
        )
        # Unvalidated, so only what names the proposal is kept.
        for extra in proposals[MAX_CANDIDATES:]:
            payload = ({k: extra.get(k) for k in ("candidate_type", "key")}
                       if isinstance(extra, dict) else {})
            drops.append({"reason": "over_candidate_limit", "payload": payload})
        proposals = proposals[:MAX_CANDIDATES]

    validated = [
        candidate for candidate in (
            _validate(p, turn, allowed_vault_keys, drops) for p in proposals
        ) if candidate is not None
    ]
    return ExtractionOutput(validated, drops)
