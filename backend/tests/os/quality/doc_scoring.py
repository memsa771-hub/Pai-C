"""Scoring document readings against a Spike 2 answer key (Slice 3 spec §8 test 9, plan Task 10).

The key holds, per document file, its type and the true value of each field it scores (`null` where the document
shows nothing, or the value is redacted). Matching:
- names: the same tokens after normalisation (case, punctuation, word order), as the cross-checks compare them;
- dates, numbers, codes, machine-readable lines and enums: exactly (numbers by value, codes without spaces);
- other text: case and spacing ignored.
A field the key says is absent but the reader fills in is **invented** and counts as wrong. A field that is absent
in both is not scored. Only rates and counts leave this module, never a value.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.os.documents.checks import normalise_name
from app.os.documents.types import DocumentType

PASS_CORRECT = 0.90  # per run, for the chosen mode (spec §9)


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


@dataclass
class DocScore:
    correct: int = 0
    scored: int = 0
    invented: int = 0
    per_type: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # type -> [ok, n]

    @property
    def rate(self) -> float:
        return self.correct / self.scored if self.scored else 0.0

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
            if _empty(want) and not _empty(have):
                s.invented += 1
            s.scored += 1
            s.correct += ok
            s.per_type[t.key][0] += ok
            s.per_type[t.key][1] += 1
    return s
