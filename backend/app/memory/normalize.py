# -*- coding: utf-8 -*-
"""Normalize — the one step that turns any Vault candidate into English values,
catalog codes, ASCII digits and ISO dates, and says why when it cannot.

Every source (chat, documents, details page, story cards) goes through here so
the Vault never holds the student's original wording; that stays only in the
evidence quote. A value that cannot be made English is rejected, never guessed.
"""

import re
from dataclasses import dataclass
from typing import Any, Optional

from app.memory.catalog import norm, vault_catalog

# Words that only occur in untranslated Roman Urdu; English values never hold them.
ROMAN_URDU = frozenset({
    "hai", "hain", "nahi", "nahin", "kiya", "tha", "thi", "hoon", "mera", "meri",
    "mujhe", "bohat", "bahut", "raha", "rahi", "abbu", "ammi", "acha", "achi",
    "karna", "karni", "wala", "wali", "lekin", "kyunke", "sakta", "sakti",
})
# Function words plus a few common ones: enough to tell "Roman Urdu with some
# English mixed in" from pure Roman Urdu. Deliberately excludes proper nouns
# students use inside Urdu sentences (board, college names).
_ENGLISH = frozenset({
    "i", "im", "my", "the", "and", "from", "is", "are", "was", "with", "for", "a", "an", "bro", "next", "month", "result", "but", "have", "got",
    "did", "just", "now", "on", "at", "be", "it", "me", "want", "like", "this", "around", "thousand", "sorry", "teacher", "housewife", "fees",
})
ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

NAME_PATHS = {"identity.full_name", "identity.preferred_name"}
_RUPEE_WORDS = {"rupees", "rupee", "rs", "pkr", "روپے", "روپیہ"}
_DATE_NAMES = {"start_date", "end_date", "started_at", "completed_at", "target_date"}
_MONTH_NAMES = [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
                ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
                ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
                ("dec", "december")]
_MONTHS = {name: i for i, names in enumerate(_MONTH_NAMES, 1) for name in names}


def detect_language(text: str) -> str:
    """en | ur | roman_ur | mixed, from script and a small Roman-Urdu lexicon."""
    text = text or ""
    if ARABIC_SCRIPT.search(text):
        return "mixed" if _LATIN.search(text) else "ur"
    words = norm(text).split()
    if sum(w in ROMAN_URDU for w in words) >= 2:
        return "mixed" if sum(w in _ENGLISH for w in words) >= 2 else "roman_ur"
    return "en"


def ascii_digits(text: str) -> str:
    return (text or "").translate(_DIGITS)


def iso_date(text: str) -> Optional[str]:
    """Day-first (Pakistani) dates to ISO; month-year to YYYY-MM; else None."""
    s = ascii_digits(str(text or "")).strip().lower().replace(",", " ")
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", s)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) or re.fullmatch(r"\d{4}-\d{2}", s):
        return s
    m = re.fullmatch(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())
        return _fmt(y, mo, d)
    m = re.fullmatch(r"(\d{1,2})\s*[/.\-]\s*(\d{4})", s)
    if m:
        mo, y = map(int, m.groups())
        return _fmt(y, mo)
    m = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", s)
    if m and m.group(2) in _MONTHS:
        return _fmt(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    m = re.fullmatch(r"([a-z]+)\s+(\d{4})", s)
    if m and m.group(1) in _MONTHS:
        return _fmt(int(m.group(2)), _MONTHS[m.group(1)])
    return None


def _fmt(y: int, mo: int, d: Optional[int] = None) -> Optional[str]:
    if not 1 <= mo <= 12 or (d is not None and not 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}" + ("" if d is None else f"-{d:02d}")


@dataclass
class NormalizeResult:
    value: Any
    source_language: str
    needs_confirmation: bool = False
    rejected_reason: Optional[str] = None


def _is_date_field(candidate_type: str, key: str, name: str) -> bool:
    if candidate_type == "vault_fact":
        return key == "identity.date_of_birth" and name == ""
    return name.endswith("_date") or name.endswith("_on") or name in _DATE_NAMES


def _is_name_field(candidate_type: str, key: str, path: str) -> bool:
    if candidate_type == "vault_fact":
        return key in NAME_PATHS and path == ""
    return candidate_type == "vault_item" and key == "family_member" and path == "name"


def normalize_candidate(candidate_type: str, key: Optional[str], value: Any, *,
                        student_text: str = "") -> NormalizeResult:
    language = detect_language(student_text)
    catalog = vault_catalog()
    spec = catalog.type(key or "")
    choice_fields = spec.choice_fields if spec else {}
    state = {"confirm": False, "reject": None}

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {k: walk(v, f"{path}.{k}" if path else k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, path) for v in node]
        if not isinstance(node, str):
            return node
        text = ascii_digits(node)
        name = path.rsplit(".", 1)[-1]
        if name == "currency" and norm(text) in _RUPEE_WORDS:
            return "PKR"
        if ARABIC_SCRIPT.search(text):
            if _is_name_field(candidate_type, key, path):
                state["confirm"] = True
            elif state["reject"] is None:
                state["reject"] = f"not_english: {path or 'value'}"
            return text
        if path in choice_fields:
            code = catalog.choice_code(choice_fields[path], text)
            return code if code is not None else text
        if _is_date_field(candidate_type, key, name if path else ""):
            return iso_date(text) or text
        return text

    if key == "finance.budget" and isinstance(value, dict) and not any(
            value.get(k) not in (None, "") for k in ("band", "min", "max", "amount")):
        return NormalizeResult(value, language, False, "empty_budget")

    out = walk(value, "")
    return NormalizeResult(out, language, state["confirm"], state["reject"])
