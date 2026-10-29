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


def _readable_education(snapshot) -> bool:
    from app.pai_c.paths.fields import education_readable
    return education_readable(snapshot.records.get("education", []))


_REQUIREMENTS = {"readable_education": _readable_education}


def coverage_areas(notebook, snapshot, items=(), stale_ids=frozenset()):
    """`items` are the active Vault items; areas.json names their types.
    `stale_ids` are the Vault entries past their catalog freshness window
    (VaultView.stale_ids): an area that only they cover is `stale`, so the
    completeness meter counts it unknown and the counselor asks again."""
    data = notebook.model_dump(mode="json")
    areas = json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8"))
    result = {}
    for area, spec in areas.items():
        locations, min_items = (spec["sources"], spec.get("min_items", 1)) if isinstance(spec, dict) else (spec, 1)
        evidence, strength, sides = {}, {}, {}
        for index, location in enumerate(locations):
            # Equivalent notebook and Vault sources share a `group` (areas.json);
            # a source without one is its own group.
            group = location.get("group", f"#{index}")
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
                sides.setdefault((group, "path" in location), set()).add(identity)
        dates = [stamp for stamp in evidence.values() if stamp is not None]
        levels = [level for level in strength.values() if level]
        # The notebook and the Vault often hold the same thing twice (one father,
        # one interest) with no shared id. Within a group the larger side counts;
        # groups add up. Both stay read until a recorded eval proves extraction
        # recall (no backfill: existing students have notebooks, not items).
        groups = {group for group, _ in sides}

        def counted(skip=frozenset()):
            return sum(max(len(sides.get((group, True), set()) - skip),
                           len(sides.get((group, False), set()) - skip)) for group in groups)
        count = counted()
        # `requires` names conditions beyond a count: an education record that
        # names no group or field ("FSc" alone) leaves the education basic
        # open, so the counselor asks for the group before anything else.
        required = spec.get("requires", ()) if isinstance(spec, dict) else ()
        met = all(_REQUIREMENTS[name](snapshot) for name in required)
        covered = count >= min_items and met
        result[area] = {"covered": covered, "stale": covered and counted(stale_ids) < min_items,
                        "item_count": count,
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
