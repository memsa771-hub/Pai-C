"""Frozen, lossless v2 to v3 storage conversion for revision 107."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5


def migrate_v2(original):
    if original.get("schema_version") == 3:
        return deepcopy(original)
    if original.get("schema_version") != 2:
        raise ValueError("revision 107 requires a v2 notebook")
    data = deepcopy(original)
    people = data.setdefault("pressures", {}).pop("people", [])
    data["world"] = {"people": [], "social": [], "daily_life": [],
                     "responsibilities": [], "education_story": []}
    for index, person in enumerate(people):
        data["world"]["people"].append({
            "id": str(uuid5(NAMESPACE_URL, f"truth-map-v3:{index}:{person['role']}:{person['first_seen']}")),
            "role": person["role"], "relation": "other", "occupation": None,
            "relationship_note": "", "wish": person.get("wish", ""),
            "worry": person.get("concern", ""), "influence": "unknown",
            "supportive": None, "evidence": person["evidence"],
            "first_seen": person["first_seen"], "last_confirmed": person["last_confirmed"],
            "status": "active",
        })
    data["schema_version"] = 3
    data["legacy_v2"] = deepcopy(original)
    return data
