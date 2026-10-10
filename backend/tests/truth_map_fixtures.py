"""Factories for current Truth Map fixtures and explicitly historical examples."""
from app.pai_c.deep.migrate_v1 import migrate_v1

STAMP = "2026-01-01T00:00:00+00:00"


def item(value="A student statement", *, key="claim", id="c1", evidence="Student described this", **changes):
    return {"id": id, "key": key, "value": value, "evidence": evidence, "kind": "said", "confidence": "low", "first_seen": STAMP, "last_confirmed": STAMP, **changes}


def v2_fixture(**old):
    data = migrate_v1(old, STAMP)
    data.pop("legacy_v1", None)
    # Migration deliberately clears readiness; runtime test fixtures set it explicitly.
    if "mirror_ready" in old:
        data["mirror_ready"] = old["mirror_ready"]
    if "coverage" in old and set(old["coverage"]) <= {"said", "shown", "source", "pressures", "self", "sure"}:
        data["coverage"] = old["coverage"]
    return data
