"""A document's fields compared with the Vault's values (P1-T7, D-y11, R-16). Pure: no database, no clock, no storage.

The comparison is live. The OS keeps no Vault value (R-01): the caller passes the facts it just asked the host for.
Only fields whose type names a StudentFacts key (`fact:`) are compared; the others are `not_compared`."""

import math
import re
from collections.abc import Mapping
from typing import Any

from app.os.contracts.student_facts import StudentFactsV1
from app.os.documents.types import DocumentType

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
TOLERANCE = 1e-9


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and _NUMBER.match(v.strip()):
        return float(v.strip())
    return None


def _text(v: Any) -> str:
    return " ".join(str(v).split()).casefold()


def _same(mine: Any, vault: Any) -> bool:
    a, b = _number(mine), _number(vault)
    if a is not None and b is not None:
        return math.isclose(a, b, rel_tol=0.0, abs_tol=TOLERANCE)
    return _text(mine) == _text(vault)


def compare(doc_type: DocumentType, values: Mapping[str, Any], facts: StudentFactsV1) -> list[dict]:
    """One `{"field", "outcome"}` per field of the type, in the type's order. `values` holds the confirmed value of each
    field, else the value as read. Outcomes: `same`, `differs`, `new` (the Vault has no value for it), `not_compared`
    (the field has no Vault key, or the document has no value)."""
    held = {f.key: f.value for f in facts.facts if f.evidence != "unknown" and not _empty(f.value)}
    out = []
    for spec in doc_type.fields:
        mine = values.get(spec.name)
        if spec.fact is None or _empty(mine):
            outcome = "not_compared"
        elif spec.fact not in held:
            outcome = "new"
        else:
            outcome = "same" if _same(mine, held[spec.fact]) else "differs"
        out.append({"field": spec.name, "outcome": outcome})
    return out
