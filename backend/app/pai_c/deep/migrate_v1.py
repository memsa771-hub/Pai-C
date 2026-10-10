"""Frozen, lossless v1-to-v2 converter used by migration 101."""
from copy import deepcopy
from datetime import datetime

MISSING_EVIDENCE = "migrated from v1 notebook (no evidence recorded)"
SOURCE_CATEGORIES = {"reels": "media", "friend": "peers", "relative": "family", "family": "family", "need": "need", "own_experience": "self", "unknown": "unknown"}


def migrate_v1(original, created_at, updated_at=None):
    if original.get("schema_version") == 2:
        return deepcopy(original)
    first = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
    last_date = updated_at or created_at
    last = last_date.isoformat() if isinstance(last_date, datetime) else str(last_date)
    result = {"schema_version": 2, "said": [], "shown": [], "source": [],
              "pressures": {"items": [], "people": []}, "self": [],
              "sure": {"score": None, "reason": "", "would_raise": "", "asked_at": None, "history": []},
              "private_notes": original.get("emotional_notes", ""), "legacy_v1": deepcopy(original)}

    def item(part, key, value, entry=None, **extra):
        entry = entry or {}
        evidence = entry.get("evidence") or MISSING_EVIDENCE
        missing = evidence == MISSING_EVIDENCE
        record = {"id": entry.get("id") or f"v1:{part}:{len(result[part] if part != 'pressures' else result[part]['items'])}",
                  "key": key, "value": deepcopy(value), "evidence": evidence,
                  "kind": "said" if missing or part != "shown" else "shown",
                  "confidence": "low" if missing else entry.get("confidence", "low"),
                  "level": entry.get("evidence_level"), "first_seen": first, "last_confirmed": last,
                  "status": "active", "vault_fact_ref": None, **extra}
        (result[part] if part != "pressures" else result[part]["items"]).append(record)

    goal = original.get("stated_goal") or {}
    if goal.get("text"):
        item("said", "stated_goal", goal["text"], goal)
        item("source", "source_of_goal", goal["text"], goal, category=SOURCE_CATEGORIES.get(goal.get("source_of_goal"), "unknown"))
    for claim in original.get("claims", []):
        value = {"text": claim["claim"], "probed": claim.get("probed", False)}
        item("said", "claim", value, claim)
        if claim.get("evidence_level") in {"sustained", "proven"}:
            item("shown", "claim", value, claim)
        item("source", "claim_source", claim["claim"], claim, category=SOURCE_CATEGORIES.get(claim.get("interest_source"), "unknown"))
    for key in ("current_situation", "location_context", "daily_life"):
        value = (original.get("person") or {}).get(key)
        if value:
            item("said", key, value)
    for old, key, text_key in (("strengths", "strength", "trait"), ("growth_areas", "growth_area", "trait"), ("drivers", "driver", "driver")):
        for entry in original.get(old, []):
            value = {"text": entry[text_key], "weight": entry.get("weight")} if old == "drivers" else entry[text_key]
            item("self", key, value, entry)
    for value in original.get("values", []):
        item("self", "value", value)
    for old, key in (("learning_style", "learning_style"), ("work_preferences", "work_preference")):
        if original.get(old):
            item("self", key, original[old])
    for entry in original.get("constraints", []):
        item("self", "limit", {"type": entry["type"], "detail": entry["detail"], "hard": entry["hard"]}, entry)
    family = original.get("family") or {}
    for key, role in (("father", "father"), ("mother", "mother"), ("others", "other")):
        entry = family.get(key)
        if not entry or isinstance(entry, dict) and not any(entry.values()):
            continue
        data = entry if isinstance(entry, dict) else {"wish": entry}
        result["pressures"]["people"].append({"role": role, "wish": data.get("wish", ""),
            "concern": data.get("underlying_concern", ""), "evidence": data.get("evidence") or MISSING_EVIDENCE,
            "first_seen": first, "last_confirmed": last})
    if family.get("pressure_level"):
        item("pressures", "family_pressure", family["pressure_level"])
    for key in ("hypotheses", "open_questions", "mirror_ready", "mirror_blockers", "depth_mode", "engagement_style", "chapter", "goal_history"):
        if key in original:
            result[key] = deepcopy(original[key])
    result["coverage"] = {part: bool(result[part]) for part in ("said", "shown", "source", "self")}
    result["coverage"].update(pressures=bool(result["pressures"]["items"] or result["pressures"]["people"]), sure=False)
    # V1 never asked a certainty rating. It cannot satisfy any v2 mirror gate.
    result["mirror_ready"] = False
    return result
