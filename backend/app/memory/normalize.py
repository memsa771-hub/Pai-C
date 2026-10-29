# -*- coding: utf-8 -*-
"""Normalize — the one step that turns any Vault candidate into English values,
catalog codes, ASCII digits and ISO dates, and says why when it cannot.

Every source (chat, documents, details page, story cards) goes through here so
the Vault never holds the student's original wording; that stays only in the
evidence quote. A value that cannot be made English is rejected, never guessed.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.memory.catalog import norm, vault_catalog

# Language word lists live in normalize_words.json (no language lists in code),
# loaded once.
_WORDS = json.loads((Path(__file__).with_name("normalize_words.json")).read_text(encoding="utf-8"))
# Words that only occur in untranslated Roman Urdu; English values never hold them.
ROMAN_URDU = frozenset(_WORDS["roman_urdu"])
# Enough English to tell "Roman Urdu with some English mixed in" from pure Roman Urdu.
_ENGLISH = frozenset(_WORDS["english"])
ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

NAME_PATHS = {"identity.full_name", "identity.preferred_name"}
_RUPEE_WORDS = frozenset(_WORDS["rupee_words"])
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
    # The student's own words name it (a family member they mention): it is
    # Stated whatever the extractor guessed (audit #5).
    stated: bool = False


def _phrase(text: str) -> re.Pattern:
    """A whole-word, case-blind pattern; an apostrophe may be straight or curly."""
    body = re.escape(text).replace("'", "['’]")
    return re.compile(rf"(?<![\w'’]){body}(?![\w'’])", re.IGNORECASE)


_THIRD = [(_phrase(first), third) for first, third in _WORDS["third_person"]["phrases"]]


def third_person(text: str) -> str:
    """"Wants me to become an engineer" -> "Wants the student to become an
    engineer": family and values entries are about the student, never in their
    first person (audit #5). Phrases live in normalize_words.json."""
    out = text
    for pattern, third in _THIRD:
        out = pattern.sub(third, out)
    return out[:1].upper() + out[1:] if text[:1].isupper() else out


def _says(text: str, words) -> bool:
    return any(_phrase(word).search(text or "") for word in words)


def _done_not_planned(status: str, quote: str) -> str:
    """A status the student's own words put in the past ("I built", "bana
    liya") is done, never planned; a stated plan stays planned (audit #5)."""
    rule = _WORDS["tense"]
    if (status == rule["planned"] and _says(quote, rule["done_words"])
            and not _says(quote, rule["future_words"])):
        return rule["done"]
    return status


def _phrase_choice(list_name: str, *texts: str) -> Optional[str]:
    """A choice said inside a sentence ("I can't leave Lahore"): the longest
    catalog wording of two or more words found in the value or the quote."""
    catalog = vault_catalog()
    wordings = sorted(((norm(w), c.code) for c in catalog.choices(list_name)
                       for w in (c.label, *c.synonyms) if len(norm(w).split()) >= 2),
                      key=lambda pair: -len(pair[0]))
    for text in texts:
        padded = f" {norm(text)} "
        for wording, code in wordings:
            if f" {wording} " in padded:
                return code
    return None


def _named_in_quote(key: Optional[str], value: Any, quote: str) -> bool:
    rule = _WORDS["stated_types"].get(key or "")
    if not rule or not isinstance(value, dict) or not isinstance(value.get(rule["field"]), str):
        return False
    catalog = vault_catalog()
    code = catalog.choice_code(rule["list"], value[rule["field"]]) or value[rule["field"]]
    words = [w for c in catalog.choices(rule["list"]) if c.code == code for w in (c.code, c.label, *c.synonyms)]
    padded = f" {norm(quote)} "
    return any(f" {norm(w)} " in padded for w in words if norm(w))


def _is_date_field(candidate_type: str, key: str, name: str) -> bool:
    if candidate_type == "vault_fact":
        return key == "identity.date_of_birth" and name == ""
    return name.endswith("_date") or name.endswith("_on") or name in _DATE_NAMES


def _is_name_field(candidate_type: str, key: str, path: str) -> bool:
    if candidate_type == "vault_fact":
        return key in NAME_PATHS and path == ""
    return candidate_type == "vault_item" and key == "family_member" and path == "name"


def normalize_candidate(candidate_type: str, key: Optional[str], value: Any, *,
                        student_text: str = "", strict_choices: bool = False) -> NormalizeResult:
    language = detect_language(student_text)
    catalog = vault_catalog()
    spec = catalog.type(key or "")
    # Level-aware: a Bachelor's field_of_study is read against study fields.
    choice_fields = catalog.record_choice_fields(spec, value)
    state = {"confirm": False, "reject": None}
    third_fields = set(_WORDS["third_person"]["types"].get(key or "", ()))

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
            if code is None and key in _WORDS["phrase_choice_types"]:
                code = _phrase_choice(choice_fields[path], text, student_text)
            return code if code is not None else text
        if name in _WORDS["tense"]["fields"]:
            return _done_not_planned(text, student_text)
        if candidate_type == "vault_item" and path in third_fields:
            return third_person(text)
        if _is_date_field(candidate_type, key, name if path else ""):
            return iso_date(text) or text
        return text

    if key == "finance.budget" and isinstance(value, dict) and not any(
            value.get(k) not in (None, "") for k in ("band", "min", "max", "amount")):
        return NormalizeResult(value, language, False, "empty_budget")

    out = walk(value, "")
    if strict_choices and state["reject"] is None:
        state["reject"] = _off_list(catalog, spec, out)
    stated = candidate_type == "vault_item" and _named_in_quote(key, out, student_text)
    return NormalizeResult(out, language, state["confirm"], state["reject"], stated=stated)


def _off_list(catalog, spec, value) -> Optional[str]:
    """A level-aware field the student picked from a form must be a code of
    its level's list: a Bachelor's field_of_study of pre_medical is a stale
    choice from another level, refused with words the student can act on.
    Chat and documents are not held to this; they keep the student's words."""
    if spec is None or not spec.choice_by_level or not isinstance(value, dict):
        return None
    level = catalog.record_level(spec, value)
    for path, by_level in spec.choice_by_level.items():
        node = value
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if (level in by_level and isinstance(node, str) and node.strip()
                and node not in {c.code for c in catalog.choices(by_level[level])}):
            level_label = catalog.label(spec.choice_fields.get("qualification_name", "levels"), level)
            return f"Choose a {path.replace('_', ' ')} from the {level_label} list"
    return None
