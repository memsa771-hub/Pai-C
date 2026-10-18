"""Optional authoritative season bounds supplement the existing freshness TTL."""
import json
from datetime import date
from pathlib import Path


def policy():
    return json.loads(Path(__file__).with_name("season_policy.json").read_text(encoding="utf-8"))


def season_current(label, *, today=None):
    today = today or date.today()
    entries = [row for row in policy()["seasons"] if row.get("key") == label]
    if not entries:
        # A missing authoritative calendar never invents a season. Existing TTL
        # still applies; merit calculations separately require reviewed rules.
        return True
    try:
        return any(date.fromisoformat(row["starts_on"]) <= today <= date.fromisoformat(row["ends_on"]) for row in entries)
    except (KeyError, TypeError, ValueError):
        return False


def verified_rules(program_id, season):
    from app.plugins._shared.sources import public_https
    if not season or not season_current(season):
        return []
    result = []
    for row in policy()["rules"]:
        if row.get("program_id") != program_id or row.get("season") != season or row.get("verification_status") != "verified":
            continue
        if not public_https(row.get("source_url")) or not row.get("checked_at"):
            continue
        result.append(dict(row))
    return result
