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


def coverage_areas(notebook, snapshot):
    data = notebook.model_dump(mode="json")
    areas = json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8"))
    result = {}
    for area, spec in areas.items():
        locations, min_items = (spec["sources"], spec.get("min_items", 1)) if isinstance(spec, dict) else (spec, 1)
        evidence = {}
        for location in locations:
            if "vault_fields" in location or "vault_field_prefixes" in location:
                rows = [("fact:" + key, row) for key, row in snapshot.facts.items()
                        if key in location.get("vault_fields", []) or
                        any(key.startswith(prefix) for prefix in location.get("vault_field_prefixes", []))]
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
        dates = [stamp for stamp in evidence.values() if stamp is not None]
        result[area] = {"covered": len(evidence) >= min_items, "item_count": len(evidence),
                        "min_items": min_items, "last_confirmed": max(dates) if dates else None}
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
