"""Scoring document readings against a Spike 2 answer key (Slice 3 spec §8 test 9, plan Task 10).

The key holds, per document file, its type and the true value of each field it scores (`null` where the document
shows nothing, or the value is redacted). Matching:
- names: the same tokens after normalisation (case, punctuation, word order), as the cross-checks compare them;
- dates, numbers, codes, machine-readable lines and enums: exactly (numbers by value, codes without spaces);
- other text: case and spacing ignored.
A field the key says is absent but the reader fills in is **invented** and counts as wrong. A field that is absent
in both is not scored. Only rates and counts leave this module, never a value.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.os.documents.checks import normalise_name
from app.os.documents.types import DocumentType

# Per run, for the chosen mode (spec §9). The spec's bar is 0.90. The owners set a pilot bar of 0.89 on 2026-10-21,
# after the fix rounds measured 0.905 and 0.892 with tiles on the strong tier (docs/os/slice-3-quality-report.md);
# students confirm every value before it is used. The answer key was not changed.
PASS_CORRECT = 0.89


def load_doc_key(path: Path) -> dict:
    """{verified, documents: {file: {type, person?, fields, check?, variant_of?}}, bundles?}"""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("documents"), dict):
        raise ValueError(f"{path.name}: no `documents` mapping")
    return data


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _text(v: Any) -> str:
    return " ".join(str(v).casefold().split())


def same(kind: str, key: Any, got: Any) -> bool:
    if kind == "name":
        return sorted(normalise_name(str(key))) == sorted(normalise_name(str(got)))
    if kind in ("number", "grade", "band"):
        try:
            return abs(float(key) - float(got)) < 1e-9
        except (TypeError, ValueError):
            return False
    if kind in ("code", "mrz_line"):
        return str(key).replace(" ", "") == str(got).replace(" ", "")
    if kind in ("date", "enum"):
        return str(key).strip() == str(got).strip()
    return _text(key) == _text(got)


def _letters(v: Any) -> str:
    return re.sub(r"[^0-9a-z]", "", str(v).casefold())


def _words(v: Any) -> list[str]:
    return re.findall(r"[0-9a-z]+", str(v).casefold())


def why_wrong(want: Any, have: Any) -> str:
    """Why a value read differs from the key, as a category only (never a value):
    `punctuation` (the same letters and digits), `words added` / `words missing` (one holds all the other's words,
    in order), `one character` (same length, one character different), or `other`."""
    a, b = _words(want), _words(have)
    if _letters(want) == _letters(have):
        return "punctuation"

    def holds(longer: list[str], shorter: list[str]) -> bool:
        it = iter(longer)
        return bool(shorter) and all(w in it for w in shorter)

    if len(b) > len(a) and holds(b, a):
        return "words added"
    if len(a) > len(b) and holds(a, b):
        return "words missing"
    x, y = str(want).strip(), str(have).strip()
    if len(x) == len(y) and sum(c != d for c, d in zip(x, y)) == 1:
        return "one character"
    return "other"


@dataclass
class DocScore:
    correct: int = 0
    scored: int = 0
    invented: int = 0
    per_type: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # type -> [ok, n]
    per_field: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(
        lambda: {"correct": 0, "wrong": 0, "missed": 0, "invented": 0}))  # "type.field" -> outcome counts

    why: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))  # "type.field" -> why wrong
    correct_ignoring_punctuation: int = 0  # informational only: the gate scores strictly

    @property
    def rate(self) -> float:
        return self.correct / self.scored if self.scored else 0.0

    def field_counts(self) -> dict[str, dict[str, int]]:
        """Per field name: correct, wrong (both present, different), missed (the reader gave nothing) and invented
        (the key says absent). Names and counts only."""
        return {k: dict(v) for k, v in sorted(self.per_field.items())}

    def wrong_why(self) -> dict[str, dict[str, int]]:
        """Per field name, why its wrong values were wrong (categories and counts only)."""
        return {k: dict(sorted(v.items())) for k, v in sorted(self.why.items())}

    def type_rates(self) -> dict[str, float]:
        return {t: round(ok / n, 3) if n else 0.0 for t, (ok, n) in sorted(self.per_type.items())}


def score(key_docs: dict, readings: dict[str, dict | None], types: dict[str, DocumentType]) -> DocScore:
    """`readings` maps a file name to the values read (None when the reading failed: every keyed value is wrong)."""
    s = DocScore()
    for name, entry in key_docs.items():
        if name not in readings:
            continue
        t, got = types[entry["type"]], readings[name] or {}
        for fname, want in (entry.get("fields") or {}).items():
            have = got.get(fname)
            if _empty(want) and _empty(have):
                continue  # absent in both: not scored
            ok = not _empty(want) and not _empty(have) and same(t.field(fname).type, want, have)
            outcome = ("invented" if _empty(want) else "missed" if _empty(have) else "correct" if ok else "wrong")
            s.per_field[f"{t.key}.{fname}"][outcome] += 1
            if outcome == "wrong":
                s.why[f"{t.key}.{fname}"][why_wrong(want, have)] += 1
            if outcome == "invented":
                s.invented += 1
            s.correct_ignoring_punctuation += ok or (outcome == "wrong" and why_wrong(want, have) == "punctuation")
            s.scored += 1
            s.correct += ok
            s.per_type[t.key][0] += ok
            s.per_type[t.key][1] += 1
    return s
