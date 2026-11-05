"""The Counsellor side of StudentFacts v1 (P1-T4, R-13, R-14, P1-D13): a plain dict, valid as `StudentFactsV1`,
built from the student's Vault. The bridge hands it to PAI OS; this module never imports `app.os`.

Privacy allow-list: education level and marks, test scores, excluded fields, field order, the budget band (never the
amount), the domicile province, the place preference and `eligible_levels`. Never a date of birth, name, guardian
e-mail or document value. A Vault `inferred` value is sent as evidence `unknown` with no value. Key words live in
`student_facts_keys.yaml`; the qualification-to-levels map lives in `eligible_levels.yaml`."""

import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from app.pai_c.connect.vault_version import key_map as _key_map

_ELIGIBLE = Path(__file__).with_name("eligible_levels.yaml")
_ORDER = {"unknown": 0, "inferred": 0, "stated": 1, "shown": 2, "confirmed": 3}


@lru_cache(maxsize=1)
def _eligible_map() -> dict[str, list[str]]:
    return yaml.safe_load(_ELIGIBLE.read_text(encoding="utf-8")) or {}


def _aware(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        number = float(str(value).strip())
    except ValueError:
        return str(value).strip() or None
    return int(number) if number.is_integer() else number


def _education_records(db, workspace_id: str) -> list[dict]:
    from app.pai_c.memory import MemoryService

    return list(MemoryService(db).profile(workspace_id).records.get("education", []))


def eligible_levels(records: list[dict]) -> list[str] | None:
    """The levels the student's current education opens (the record they are finishing, else the highest completed);
    None when there is no non-inferred education or its level is unknown."""
    from app.pai_c.paths.fields import current_education, read_education

    # An inferred record (PAI's reading, not yet the student's) opens nothing.
    current = current_education([r for r in records if r.get("evidence_level") != "inferred"])
    if current is None:
        return None
    code = read_education(current)[0]
    levels = _eligible_map().get(code or "")
    return list(levels) if levels else None


def student_eligible_levels(db, workspace_id: str) -> list[str] | None:
    return eligible_levels(_education_records(db, workspace_id))


class _Facts:
    def __init__(self, key_versions: dict, top: int):
        self.key_versions, self.top, self.items = key_versions or {}, top, {}

    def add(self, key, value, level, as_of, document_ref=None):
        """`level` is the Vault evidence level; an inferred one is sent as unknown with no value."""
        if value is None or value == "":
            return
        known = level in ("stated", "shown", "confirmed")
        self.items[key] = {
            "key": key, "value": value if known else None, "evidence": level if known else "unknown",
            "vault_version": min(int(self.key_versions.get(key, 0)), self.top),
            "document_ref": document_ref if known and level in ("shown", "confirmed") else None,
            "as_of": _aware(as_of)}


def _record_facts(out: _Facts, records: list[dict]) -> None:
    from app.pai_c.memory import vault_catalog

    catalog, mapping = vault_catalog(), _key_map()["education"]
    spec = catalog.type("education")
    chosen: dict[str, dict] = {}
    for row in records:  # newest first; a current record beats an older one of the same family
        family = next((f for f, codes in mapping["families"].items() if catalog.record_level(spec, row) in codes), None)
        if family and (family not in chosen or (row.get("academic_status") == "current"
                                                and chosen[family].get("academic_status") != "current")):
            chosen[family] = row
    for family, row in chosen.items():
        result, evidence = row.get("result") or {}, row.get("evidence") or {}
        values = {"level": catalog.record_level(spec, row), **result}
        for part in ("part1", "part2"):
            for name, number in (result.get(part) or {}).items():
                values[f"{part}.{name}"] = number
        for field in mapping["fields"]:
            out.add(f"education.{family}.{field}", values.get(field), row["evidence_level"],
                    row.get("updated_at"), evidence.get("file_id"))


def _test_facts(out: _Facts, records: list[dict]) -> None:
    from app.pai_c.memory import vault_catalog

    template, seen = _key_map()["tests"]["key"], set()
    for row in records:  # newest first: the latest attempt of a test stands
        text = str(row.get("test_type") or "").strip()
        code = vault_catalog().choice_code("tests", text) or re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")
        if not code or code in seen:
            continue
        seen.add(code)
        evidence = row.get("evidence") or {}
        out.add(template.format(type=code), _num(row.get("overall_score")), row["evidence_level"],
                row.get("updated_at"), evidence.get("file_id"))


def _item_facts(out: _Facts, db, workspace_id: str) -> None:
    from app.pai_c.memory import MemoryService, vault_catalog
    from app.pai_c.paths.exclusions import excluded_fields

    mapping = _key_map()["items"]
    catalog = vault_catalog()
    latest = {}
    for row in MemoryService(db).vault_items(workspace_id, ["field_order", "place_preference", "domicile"]):
        latest[row.item_type] = row  # oldest first: the newest active row wins
    for item_type, row in latest.items():
        key, value = mapping[item_type][0], row.value or {}
        evidence = row.evidence or {}
        when = row.updated_at or row.observed_at
        if item_type == "domicile":
            province = value.get("province")
            shaped = catalog.choice_code("provinces", province) if isinstance(province, str) else None  # unmapped: dropped
        elif item_type == "field_order":
            codes = [catalog.choice_code("study_fields", n) for n in value.get("fields") or []]
            shaped = [c for c in codes if c] or None
        else:
            shaped = {k: value[k] for k in ("scope", "fallback", "regions") if value.get(k) is not None} or None
        out.add(key, shaped, row.level, when, evidence.get("file_id"))
    excluded = excluded_fields(db, workspace_id)
    if excluded:
        by_id = {r.id: r for r in MemoryService(db).vault_items(workspace_id, ["option"])}
        rows = [by_id.get(option["item_id"]) for option in excluded.values()]
        weakest = min((o["level"] for o in excluded.values()), key=lambda lvl: _ORDER.get(lvl, 0))
        stamps = [_aware(r.updated_at or r.observed_at) for r in rows if r is not None]
        out.add(mapping["option"][0], sorted(excluded), weakest, max((s for s in stamps if s), default=None))


def build(db, workspace_id: str) -> dict:
    """A `StudentFactsV1`-valid dict for the student's workspace."""
    from app.models import VaultVersion
    from app.pai_c.memory import MemoryService

    counter = db.get(VaultVersion, workspace_id)
    top = int(counter.version) if counter else 0
    out = _Facts(counter.key_versions if counter else {}, top)
    snapshot = MemoryService(db).profile(workspace_id)
    records = list(snapshot.records.get("education", []))
    _record_facts(out, records)
    _test_facts(out, list(snapshot.records.get("test_attempt", [])))
    budget = snapshot.facts.get("finance.budget")
    if budget and isinstance(budget["value"], dict):  # the band only, never the amount
        for key in _key_map()["facts"]["finance.budget"]:
            out.add(key, budget["value"].get("band"), budget["evidence_level"], budget.get("valid_from"),
                    (budget.get("evidence") or {}).get("file_id"))
    _item_facts(out, db, workspace_id)
    return {"schema": "pai.student_facts.v1", "student_ref": str(workspace_id), "vault_version": top,
            "built_at": datetime.now(timezone.utc), "eligible_levels": eligible_levels(records),
            "facts": list(out.items.values())}
