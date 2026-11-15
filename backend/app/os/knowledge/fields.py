"""Excluded study fields on the OS side (master R-15, P2-T24).

The student's excluded fields are the Vault's: the OS reads them through the StudentFacts port each time it needs them
(`constraint.excluded_fields`, the Counsellor's study-field codes) and never stores them (master §4). A programme is
in an excluded field when its registry `field`, read through `field_codes.yaml`, is one of those codes. A programme
with an empty `field` is never in one: hiding a place whose tag is missing would be silent (rule 8 of the consistency
job opens a case for it instead)."""

import re
from collections.abc import Iterable
from functools import cache
from pathlib import Path

import yaml
from sqlalchemy import Engine, select

from app.os import models

EXCLUDED_KEY = "constraint.excluded_fields"
FIELD_CODES_FILE = Path(__file__).with_name("field_codes.yaml")
_CODE = re.compile(r"^[a-z0-9_]+$")


@cache
def _aliases(path: Path = FIELD_CODES_FILE) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    aliases = data.get("aliases") or {}
    for raw, code in aliases.items():
        if not isinstance(code, str) or not _CODE.match(code):
            raise ValueError(f"field code for '{raw}' must be a study-field code like 'pharm_d'")
    return {str(k).strip(): v for k, v in aliases.items()}


def field_code(field: str | None) -> str | None:
    """The Counsellor study-field code a programme's `field` means; None for an empty field."""
    raw = (field or "").strip()
    if not raw:
        return None
    return _aliases().get(raw, raw)


def excluded_of(facts) -> frozenset[str]:
    """The excluded field codes in a `StudentFactsV1` (empty when the Vault holds none or does not know)."""
    for f in facts.facts:
        if f.key == EXCLUDED_KEY:
            if f.evidence == "unknown" or not isinstance(f.value, list):
                return frozenset()
            return frozenset(v for v in f.value if isinstance(v, str) and v)
    return frozenset()


def excluded_for(student_ref: str, *, engine: Engine, tenant_id: str) -> frozenset[str]:
    """The student's excluded field codes, read now through the StudentFacts port (never copied)."""
    from app.os.ports import student_facts  # late: the port imports the eligibility code, which imports knowledge

    return excluded_of(student_facts.get(student_ref, engine=engine, tenant_id=tenant_id))


def is_excluded(field: str | None, excluded: Iterable[str]) -> bool:
    code = field_code(field)
    return code is not None and code in set(excluded)


def excluded_refs(engine: Engine, tenant_id: str, refs: Iterable[str], excluded: Iterable[str]) -> set[str]:
    """Of `refs`, the programmes whose field is excluded."""
    refs, excluded = list(refs), frozenset(excluded)
    if not refs or not excluded:
        return set()
    P = models.programmes
    with engine.connect() as conn:
        rows = conn.execute(select(P.c.ref, P.c.field).where(P.c.tenant_id == tenant_id, P.c.ref.in_(refs))).all()
    return {r.ref for r in rows if is_excluded(r.field, excluded)}
