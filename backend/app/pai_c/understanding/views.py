"""Computed evidence coverage and public projections; no persistence or model calls."""
from copy import deepcopy
from datetime import datetime, timezone
import json

from app.pai_c.understanding.data import DATA_DIR, at_path, load_policy


def _active(rows):
    return [deepcopy(row) for row in rows if row.get("status", "active") == "active"]


def _date(value):
    if not value:
        return None
    date = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return date if date.tzinfo else date.replace(tzinfo=timezone.utc)


EVIDENCE_ORDER = ("stated", "shown", "confirmed")
# Notebook item kinds map onto the same public evidence ladder as Vault facts.
_KIND_LEVEL = {"said": "stated", "shown": "shown", "document": "shown", "action": "shown"}


def _strength(row):
    """Strongest public evidence level of one row; read-only, never a score."""
    level = row.get("evidence_level")
    if level in EVIDENCE_ORDER:
        return level
    return _KIND_LEVEL.get(row.get("kind"), "stated")


def _item_row(item):
    """A Vault item as a coverage row: its English fields plus what the area
    filters read. A guess (inferred) is not evidence of coverage."""
    return {**(item.value or {}), "id": item.id, "status": item.status,
            "evidence": item.evidence if item.level != "inferred" else None,
            "evidence_level": item.level, "last_confirmed": item.confirmed_at,
            "updated_at": item.updated_at or item.observed_at}


def coverage_areas(notebook, snapshot, items=()):
    """`items` are the active Vault items; areas.json names their types."""
    data = notebook.model_dump(mode="json")
    areas = json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8"))
    result = {}
    for area, spec in areas.items():
        locations, min_items = (spec["sources"], spec.get("min_items", 1)) if isinstance(spec, dict) else (spec, 1)
        evidence, strength = {}, {}
        notebook_prefixes = tuple(location["path"] + ":" for location in locations if "path" in location)
        for location in locations:
            if "vault_fields" in location or "vault_field_prefixes" in location:
                rows = [("fact:" + key, row) for key, row in snapshot.facts.items()
                        if key in location.get("vault_fields", []) or
                        any(key.startswith(prefix) for prefix in location.get("vault_field_prefixes", []))]
            elif "vault_items" in location:
                rows = [("item:" + str(item.id), _item_row(item)) for item in items
                        if item.item_type in location["vault_items"]]
            elif "vault_records" in location:
                rows = [(kind + ":" + str(row["id"]), row) for kind in location["vault_records"] for row in snapshot.records.get(kind, [])]
            else:
                value = at_path(data, location["path"])
                entries = value if isinstance(value, list) else [value]
                rows = [(location["path"] + ":" + str(row.get("id", index)), row) for index, row in enumerate(entries)]
            for identity, row in rows:
                if row.get("status", "active") != "active":
                    continue
                # A stored shell or an unresolved candidate is not evidence of coverage.
                if "not_null" not in location and not row.get("evidence"):
                    continue
                if any(at_path(row, field) not in values for field, values in location.get("where", {}).items()):
                    continue
                if "key_prefixes" in location and not any(row.get("key", "").startswith(prefix) for prefix in location["key_prefixes"]):
                    continue
                if "nonempty" in location and not row.get(location["nonempty"]):
                    continue
                if "not_null" in location and row.get(location["not_null"]) is None:
                    continue
                stamp = row.get(location.get("timestamp", "last_confirmed")) or row.get("updated_at") or row.get("valid_from") or row.get("created_at")
                evidence[identity] = _date(stamp)
                strength[identity] = _strength(row)
        dates = [stamp for stamp in evidence.values() if stamp is not None]
        levels = [level for level in strength.values() if level]
        # Areas with a Vault equivalent read the Vault alone (areas.json). The
        # few that still read both (history, family_social, values) may hold
        # the same thing twice with no shared id, so the two sides are not
        # added: the area counts the larger side.
        notebook_side = sum(1 for identity in evidence if identity.startswith(notebook_prefixes))
        count = max(notebook_side, len(evidence) - notebook_side)
        result[area] = {"covered": count >= min_items, "item_count": count,
                        "min_items": min_items, "last_confirmed": max(dates) if dates else None,
                        "evidence": max(levels, key=EVIDENCE_ORDER.index) if levels else None}
    return result


def academic_view(notebook, snapshot):
    return {"records": {kind: _active(snapshot.records.get(kind, [])) for kind in load_policy()["academic_records"]},
            "education_story": _active(notebook.model_dump(mode="json")["world"]["education_story"])}


def personal_view(notebook):
    data = notebook.model_dump(mode="json")
    return {"world": {key: _active(rows) for key, rows in data["world"].items()},
            "self": _active([row for row in data["self"] if row.get("capability_status") is None]),
            "source": _active(data["source"]), "pressures": {"items": _active(data["pressures"]["items"])},
            "sure": deepcopy(data["sure"])}


def capability_view(notebook):
    data = notebook.model_dump(mode="json")
    policy = load_policy()
    grouped = {status: [] for status in policy["capability_statuses"]}
    for path in policy["item_paths"]:
        for row in _active(at_path(data, path)):
            status = row.get("capability_status")
            if status is not None:
                grouped[status].append(row)
    return grouped


def profile_sections(notebook):
    """Explicit public evidence selectors; private interpretation is never traversed."""
    data = notebook.model_dump(mode='json')
    selectors = json.loads((DATA_DIR / 'profile_sections.json').read_text(encoding='utf-8'))
    result = {}
    for section, sources in selectors.items():
        selected = {}
        for spec in sources:
            for row in _active(at_path(data, spec['path'])):
                if not row.get('evidence'):
                    continue
                if spec.get('prefixes') and not any(row.get('key','').startswith(prefix) for prefix in spec['prefixes']):
                    continue
                selected[row['id']] = row
        result[section] = list(selected.values())
    return result
