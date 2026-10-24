# -*- coding: utf-8 -*-
"""Which Vault entries a model sees for one turn, read from the Vault view.

Why a selector and not "the first N facts": the counselor and the extractor
each get a small slice of a Vault that keeps growing, and the slice must hold
what this turn is about. Order (VAULT_SPEC §Access, §Freshness, §Conflicts):

1. core details (who and where the student is), capped per type and never
   more than the budget minus a share kept for tier 2;
2. entries in question or due for re-confirmation, so they get checked;
3. citable evidence: shown or confirmed skills, certifications, achievements;
4. entries sharing words with the student's turn (Roman Urdu words mapped to
   English through the catalog's choice synonyms and a small word list);
5. the newest of the rest, until the token budget is spent.

Access: the counselor's view is built without sensitive types; a sensitive
type comes in only when the turn (or the counselor's question it answers, or
the area the counselor planned) names its topic (family, money, ...), and a
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


def sensitive_types_for(text: str, topics: Iterable[str] = ()) -> set[str]:
    """Sensitive types this turn needs. The text (the student's turn and the
    counselor's question before it) names a topic by one of its words or by a
    wording from one of its choice lists (a relation, a band); a wording in
    trigger_exclude ("bro", "api") is too common to count. `topics` are the
    areas the counselor planned to explore, mapped to topics in data."""
    catalog = vault_catalog()
    policy = context_policy()
    excluded = {norm(w) for w in policy["trigger_exclude"]}
    raw = norm(text).split()
    phrases = ({*raw, *(_stem(w) for w in raw), *(" ".join(p) for p in zip(raw, raw[1:]))}) - excluded
    named = {policy["area_topics"][t] for t in topics if t in policy["area_topics"]}
    found: set[str] = set()
    for name, topic in policy["sensitive_topics"].items():
        if (name in named or phrases & {norm(w) for w in topic["words"]} or any(
                catalog.choice_code(choice, phrase) for choice in topic["choices"] for phrase in phrases)):
            found |= set(topic["types"])
    return found


def counselor_view(db, workspace_id: str, student_text: str, *, trigger_text: str = "",
                   topics: Iterable[str] = ()) -> dict:
    """The counselor's Vault view: normal types, plus the sensitive types this turn needs."""
    from .vault_view import VaultView
    return VaultView(db).build(workspace_id, include_sensitive=False,
                               sensitive_types=sensitive_types_for(f"{trigger_text} {student_text}", topics))


def view_entries(view: dict) -> list[dict]:
    """Every entry in a Vault view, once."""
    seen, entries = set(), []
    for entry in [*(e for s in view["details"].values() for e in s["entries"]),
                  *(e for card in view["story"] for e in card["entries"])]:
        if (entry["kind"], entry["id"]) not in seen:
            seen.add((entry["kind"], entry["id"]))
            entries.append(entry)
    return entries


def _short(value, limit: int):
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return {key: _short(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_short(item, limit) for item in value]
    return value


def context_entry(entry: dict) -> dict:
    """The compact form a prompt gets: English value, label and badge, never evidence.
    A fact or item with a structured value keeps its field names, which the
    display drops; a record (often long) is summarized to its display. Text
    is trimmed as the counselor context always trimmed it."""
    limit = context_policy()["value_max_chars"]
    compact = {"id": entry["id"], "kind": entry["kind"], "type": entry["type"],
               "label": entry["label"], "display": entry["display"][:limit], "badge": entry["badge"]}
    if isinstance(entry["value"], dict) and entry["kind"] != "record":
        compact["value"] = _short(entry["value"], limit)
    return compact


def select_context_entries(view: dict, student_text: str, *, budget_tokens: int,
                           kinds: Optional[Iterable[str]] = None, limit: Optional[int] = None,
                           exclude_types: Iterable[str] = ()) -> list[dict]:
    """The entries a model should see for this turn, most important first.

    Tiers, each newest first: core details (capped per type, and never more
    than the budget minus the re-check share); entries in question or stale,
    which always keep that share; citable evidence (shown or confirmed
    skills, certifications, achievements) the planner can cite; entries
    sharing words with the turn; the rest. Excluded types (identity the
    caller sends on its own) are removed before anything is counted. Cost
    is the compact form under the counselor's estimator."""
    policy = context_policy()
    kinds = set(kinds) if kinds is not None else None
    excluded = set(exclude_types)
    core, caps, citable = set(policy["core_types"]), policy["core_caps"], policy["citable"]
    asked = turn_words(student_text)
    entries = [e for e in view_entries(view)
               if (kinds is None or e["kind"] in kinds) and e["type"] not in excluded]
    entries.sort(key=lambda e: e.get("observed_at") or "", reverse=True)

    tiers: list[list[dict]] = [[], [], [], [], []]
    per_type: dict[str, int] = {}
    cited = 0
    for entry in entries:
        if entry["in_question"] or entry["stale"]:
            tiers[1].append(entry)
        elif entry["type"] in core:
            # Only the newest N of a core type; older ones are history, not who the student is now.
            per_type[entry["type"]] = per_type.get(entry["type"], 0) + 1
            if per_type[entry["type"]] <= caps.get(entry["type"], 1):
                tiers[0].append(entry)
        elif (entry["type"] in citable["types"] and entry["level"] in citable["levels"]
              and cited < citable["max"]):
            cited += 1
            tiers[2].append(entry)
        elif asked & _words(f"{entry['label']} {entry['display']}"):
            tiers[3].append(entry)
        else:
            tiers[4].append(entry)
    tiers[3].sort(key=lambda e: -len(asked & _words(f"{e['label']} {e['display']}")))  # stable

    reserve = int(budget_tokens * policy["recheck_share"])
    chosen, used = [], 0
    for index, tier in enumerate(tiers):
        ceiling = budget_tokens - reserve if index == 0 else budget_tokens
        for entry in tier:
            if limit is not None and len(chosen) >= limit:
                return chosen
            cost = estimated_tokens(_json(context_entry(entry)))
            if used + cost <= ceiling:
                chosen.append(entry)
                used += cost
    return chosen
