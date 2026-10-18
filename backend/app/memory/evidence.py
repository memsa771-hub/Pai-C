"""Evidence labels derived from trusted provenance, not a model's claimed level."""
import hashlib
import json
from pathlib import Path


def evidence_policy():
    return json.loads(Path(__file__).with_name("evidence_policy.json").read_text(encoding="utf-8"))


def value_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str).encode()).hexdigest()


def evidence_level(row, value):
    policy = evidence_policy()
    evidence = row.get("evidence") or {}
    confirmation = evidence.get("confirmation") or {}
    if (row.get("source_type") == "user_explicit"
            and row.get("capture_method") == policy["confirmation_capture"]
            and confirmation.get("value_digest") == value_digest(value)
            and confirmation.get("confirmed_at")):
        return "confirmed"
    if (row.get("verification_status") in policy["shown_verification"]
            or (row.get("source_type") == "document" and evidence.get("authority") in policy["shown_authorities"]
                and evidence.get("file_id"))):
        return "shown"
    return "stated"
