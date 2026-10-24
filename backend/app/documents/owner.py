# -*- coding: utf-8 -*-
"""Is this document the student's own? Name comparison for the owner check.

Another person's document is not applied (VAULT_SPEC §Conflicts), but a false
alarm costs the student a question about their own result card, so the
comparison forgives what romanization does to one name: "Mohammad" and
"Muhammad" are the same person, and so is a one-letter OCR slip in a long name.

Rules, decided per name pair, token by token:

- Tokens match when they are equal, are spellings in one group of
  `prompts/name_variants.json`, or are both 5+ letters and one edit apart.
- One name may be part of the other ("Ali Khan" in "Muhammad Ali Khan"), but
  only when the shorter has at least two tokens: a lone "Khan" is a family
  name half the class shares.
- A single-token name ("Ali", a preferred name) matches only the other
  name's first token: "Ali Hassan" yes, "Hassan Ali" no.
- When both sides have a full name, only full names are compared.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _variants() -> dict[str, str]:
    data = json.loads((Path(__file__).with_name("prompts") / "name_variants.json")
                      .read_text(encoding="utf-8"))
    return {spelling: group[0] for group in data["groups"] for spelling in group}


def _tokens(name) -> list[str]:
    from app.memory.catalog import norm

    return norm(name).split() if isinstance(name, str) else []


def _one_edit_apart(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def same_token(a: str, b: str) -> bool:
    if a == b:
        return True
    variants = _variants()
    if a in variants and variants.get(a) == variants.get(b):
        return True
    return len(a) >= 5 and len(b) >= 5 and _one_edit_apart(a, b)


def same_person(first, second) -> bool:
    a, b = _tokens(first), _tokens(second)
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) == 1:
        return same_token(short[0], long_[0])
    remaining = list(long_)
    for token in short:
        match = next((i for i, other in enumerate(remaining) if same_token(token, other)), None)
        if match is None:
            return False
        remaining.pop(match)
    return True


def names_disagree(document: dict, vault: dict) -> bool:
    """True when the document names someone and no name pair agrees.

    Each side is {"full": [...], "preferred": [...]}. A side with no name has
    nothing to disagree with.
    """
    if document.get("full") and vault.get("full"):
        pairs = [(d, v) for d in document["full"] for v in vault["full"]]
    else:
        doc_names = [*(document.get("full") or []), *(document.get("preferred") or [])]
        vault_names = [*(vault.get("full") or []), *(vault.get("preferred") or [])]
        pairs = [(d, v) for d in doc_names for v in vault_names]
    pairs = [(d, v) for d, v in pairs if _tokens(d) and _tokens(v)]
    if not pairs:
        return False
    return not any(same_person(d, v) for d, v in pairs)
