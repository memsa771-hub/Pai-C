"""Adapt historical full-map fake responses to the current patch contract.

Offline replay only: stored historical recordings are not runtime model outputs.
"""
from collections import defaultdict

PLAN = {"next_move": "understand", "intent": "Explore the next evidence gap", "target_gap": None,
        "give": "", "avoid_questions": [], "playbooks": []}


def recorded_patch(target, view=None):
    view = view or {}
    operations = []
    for part in ("said", "shown", "source", "self", "pressures.items"):
        rows = target.get("pressures", {}).get("items", []) if part == "pressures.items" else target.get(part, [])
        previous = view.get("pressures", {}).get("items", []) if part == "pressures.items" else view.get(part, [])
        available = defaultdict(list)
        for row in previous:
            available[row["key"]].append(row)
        for row in rows:
            matches = available[row["key"]]
            if matches:
                known = matches.pop(0)
                operations.append({"op": "update", "id": known["id"], "fields": {
                    key: row[key] for key in ("value", "evidence", "confidence", "level") if key in row}})
            else:
                fields = ("key", "value", "evidence", "kind", "confidence", "level", "vault_fact_ref")
                entry = {key: row[key] for key in fields if key in row}
                if part == "source":
                    entry["category"] = row.get("category", "unknown")
                operations.append({"op": "add", "part": part, "item": entry})
    for person in target.get("pressures", {}).get("people", []):
        operations.append({"op": "upsert_person", **{key: person[key] for key in ("role", "wish", "evidence")}, "worry": person.get("concern", "")})
    for key in ("tensions", "identity_status", "decision_difficulties", "hypotheses", "open_questions", "private_notes", "engagement_style", "depth_mode"):
        if key in target:
            operations.append({"op": "set_private", "field": key, "value": target[key]})
    for key, value in target.get("coverage", {}).items():
        operations.append({"op": "set_coverage", "part": key, "value": value})
    return {"patch": operations, "plan": dict(PLAN)}
