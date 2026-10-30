"""Cross-checks across one student's documents (spec S3-D7).

The full name, the father's name and the date of birth must agree across documents. Names are compared as token
multisets, so order and punctuation do not matter ("KHAN, SARA AHMED" equals "Sara Ahmed Khan"). Spellings in one
group of `name_variants.yaml` make a "variant" finding the student confirms; anything else is a "mismatch".
"""

import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Literal

import yaml

from app.os.documents.types import DocumentType

NAME_VARIANTS = Path(__file__).parent / "name_variants.yaml"
Compare = Literal["equal", "variant", "different"]
CROSS_FIELDS = ("full_name", "father_name", "date_of_birth")

_PUNCT = re.compile(r"[^\w\s,]")


@dataclass(frozen=True)
class Finding:
    kind: Literal["variant", "mismatch"]
    field: str
    items: list[tuple[int, str]]  # (document id, value as read), in the order the documents were given


def load_name_variants(path: Path = NAME_VARIANTS) -> list[set[str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [{str(n).casefold() for n in group} for group in raw.get("groups", [])]


def normalise_name(s: str) -> list[str]:
    """Lower-case tokens. Text before a comma is the surname and goes last (passport style "SURNAME, GIVEN")."""
    s = _PUNCT.sub(" ", s.casefold().replace("_", " "))
    if "," in s:
        surname, _, given = s.partition(",")
        s = f"{given.replace(',', ' ')} {surname}"
    return s.split()


def _same_or_variant(a: str, b: str, variants: list[set[str]]) -> bool:
    return a == b or any(a in g and b in g for g in variants)


def _pairs_by_variant(a: list[str], b: list[str], variants: list[set[str]]) -> bool:
    """Every leftover token of `a` pairs with one of `b` in the same variant group."""
    if len(a) != len(b):
        return False
    rest = list(b)
    for t in a:
        match = next((u for u in rest if _same_or_variant(t, u, variants)), None)
        if match is None:
            return False
        rest.remove(match)
    return True


def compare_names(a: str, b: str, variants: list[set[str]]) -> Compare:
    ta, tb = normalise_name(a), normalise_name(b)
    if sorted(ta) == sorted(tb):
        return "equal"
    if _pairs_by_variant(ta, tb, variants):
        return "variant"
    if ta and "".join(ta) == "".join(tb):  # "Abdul Rehman" written as one word
        return "variant"
    return "different"


def _cross_value(t: DocumentType, values: dict, field: str) -> str | None:
    if field == "full_name" and t.full_name_from:
        parts = [str(values[p]).strip() for p in t.full_name_from if values.get(p) not in (None, "")]
        return " ".join(parts) or None
    spec = next((f for f in t.fields if f.cross_check == field), None)
    v = values.get(spec.name) if spec else None
    return str(v).strip() or None if v is not None else None


def cross_values(t: DocumentType, values: dict) -> dict[str, str]:
    """The document's values for the cross-check keys (full name built from its parts), where it has them."""
    return {field: v for field in CROSS_FIELDS if (v := _cross_value(t, values, field))}


def cross_check(docs: list[tuple[int, DocumentType, dict]], variants: list[set[str]]) -> list[Finding]:
    findings = []
    for field in CROSS_FIELDS:
        items = [(doc_id, v) for doc_id, t, values in docs if (v := _cross_value(t, values, field))]
        if len(items) < 2:
            continue
        if field == "date_of_birth":
            outcomes = {"equal" if a == b else "different" for (_, a), (_, b) in combinations(items, 2)}
        else:
            outcomes = {compare_names(a, b, variants) for (_, a), (_, b) in combinations(items, 2)}
        if "different" in outcomes:
            findings.append(Finding("mismatch", field, items))
        elif "variant" in outcomes:
            findings.append(Finding("variant", field, items))
    return findings
