# -*- coding: utf-8 -*-
"""Which Vault entries a model sees for one turn, read from the Vault view.

Why a selector and not "the first N facts": the counselor and the extractor
each get a small slice of a Vault that keeps growing, and the slice must hold
what this turn is about. Order (VAULT_SPEC §Access, §Freshness, §Conflicts):

1. core details (who and where the student is), always;
2. entries in question or due for re-confirmation, so they get checked;
3. entries sharing words with the student's turn (Roman Urdu words mapped to
   English through the catalog's choice synonyms and a small word list);
4. the newest of the rest, until the token budget is spent.

Access: the counselor's view is built without sensitive types; a sensitive
type comes in only when the turn names its topic (family, money, ...), and a
restricted type never does. Entries carry the English value and badge, never
evidence, so the student's original words cannot reach a prompt from here.
No model calls, no embeddings.
"""

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from .catalog import norm, vault_catalog


@lru_cache(maxsize=1)
def context_policy() -> dict:
    return json.loads(Path(__file__).with_name("vault_context.json").read_text(encoding="utf-8"))


def estimated_tokens(value: str) -> int:
    """Conservative transport-independent estimate; no tokenizer/model call."""
    return math.ceil(len(value.encode("utf-8")) / 4)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text: str) -> set[str]:
    stop = set(context_policy()["stopwords"])
    return {_stem(w) for w in norm(text).split() if len(w) > 2 and w not in stop}


def turn_words(student_text: str) -> set[str]:
    """The turn's words in English: catalog choice wordings ("abbu", "inter")
    add their label and code, and the Roman Urdu word list adds its English word."""
    catalog = vault_catalog()
    raw = norm(student_text).split()
    phrases = raw + [" ".join(pair) for pair in zip(raw, raw[1:])]
    words = _words(student_text)
    extra = context_policy()["roman_urdu_words"]
    for phrase in phrases:
        if phrase in extra:
            words |= _words(extra[phrase])
        for name in catalog.choice_names():
            code = catalog.choice_code(name, phrase)
            if code is not None:
                words |= _words(catalog.label(name, code) + " " + code.replace("_", " "))
    return words


def sensitive_types_for(student_text: str) -> set[str]:
    """Sensitive types this turn needs: the turn names a topic by one of its
    words or by a wording from one of its choice lists (a relation, a band)."""
    catalog = vault_catalog()
    raw = norm(student_text).split()
    phrases = set(raw) | {_stem(w) for w in raw} | {" ".join(p) for p in zip(raw, raw[1:])}
    found: set[str] = set()
    for topic in context_policy()["sensitive_topics"].values():
        named = phrases & {norm(w) for w in topic["words"]} or any(
            catalog.choice_code(name, phrase) for name in topic["choices"] for phrase in phrases)
        if named:
            found |= set(topic["types"])
    return found


def counselor_view(db, workspace_id: str, student_text: str) -> dict:
    """The counselor's Vault view: normal types, plus the sensitive types this turn needs."""
    from .vault_view import VaultView
    return VaultView(db).build(workspace_id, include_sensitive=False,
                               sensitive_types=sensitive_types_for(student_text))


def view_entries(view: dict) -> list[dict]:
    """Every entry in a Vault view, once."""
    seen, entries = set(), []
    for entry in [*(e for s in view["details"].values() for e in s["entries"]),
                  *(e for card in view["story"] for e in card["entries"])]:
        if (entry["kind"], entry["id"]) not in seen:
            seen.add((entry["kind"], entry["id"]))
            entries.append(entry)
    return entries


def context_entry(entry: dict) -> dict:
    """The compact form a prompt gets: English value, label and badge, never evidence.
    A structured value keeps its field names, which the display text drops."""
    compact = {"id": entry["id"], "kind": entry["kind"], "type": entry["type"],
               "label": entry["label"], "display": entry["display"], "badge": entry["badge"]}
    if isinstance(entry["value"], dict):
        compact["value"] = entry["value"]
    return compact


def select_context_entries(view: dict, student_text: str, *, budget_tokens: int,
                           kinds: Optional[Iterable[str]] = None,
                           limit: Optional[int] = None) -> list[dict]:
    """The entries a model should see for this turn, most important first.
    Core details are always kept; the rest stop at the budget (counted on the
    compact form with the counselor's estimator) or at `limit`."""
    kinds = set(kinds) if kinds is not None else None
    core = set(context_policy()["core_types"])
    asked = turn_words(student_text)
    entries = [e for e in view_entries(view) if kinds is None or e["kind"] in kinds]
    # Newest first inside every tier.
    entries.sort(key=lambda e: e.get("observed_at") or "", reverse=True)

    def tier(entry: dict) -> tuple:
        if entry["type"] in core:
            return (0, 0)
        if entry["in_question"] or entry["stale"]:
            return (1, 0)
        overlap = len(asked & _words(f"{entry['label']} {entry['display']}"))
        return (2, -overlap) if overlap else (3, 0)

    chosen, used = [], 0
    for entry in sorted(entries, key=tier):  # stable: newest first within a tier
        if limit is not None and len(chosen) >= limit:
            break
        cost = estimated_tokens(_json(context_entry(entry)))
        if entry["type"] not in core and used + cost > budget_tokens:
            continue
        chosen.append(entry)
        used += cost
    return chosen
