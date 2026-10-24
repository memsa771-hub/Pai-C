"""Evidence labels derived from trusted provenance, not a model's claimed level."""
import hashlib
import json
from pathlib import Path


def evidence_policy():
    return json.loads(Path(__file__).with_name("evidence_policy.json").read_text(encoding="utf-8"))


def value_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str).encode()).hexdigest()


def needs_student_confirmation(evidence) -> bool:
    """A document reading that is not "shown" until the student confirms it:
    OCR can misread a digit, and a paper with no holder name may be someone
    else's (VAULT_SPEC §Conflicts)."""
    evidence = evidence or {}
    return bool(evidence.get("ocr") or evidence.get("owner_unverified"))


def evidence_level(row, value):
    policy = evidence_policy()
    evidence = row.get("evidence") or {}
    confirmation = evidence.get("confirmation") or {}
    if (row.get("source_type") == "user_explicit"
            and row.get("capture_method") == policy["confirmation_capture"]
            and confirmation.get("value_digest") == value_digest(value)
            and confirmation.get("confirmed_at")):
        return "confirmed"
    if needs_student_confirmation(evidence):
        # The student never said it and it is not yet shown: PAI's reading.
        return "inferred"
    if (row.get("verification_status") in policy["shown_verification"]
            or (row.get("source_type") == "document" and evidence.get("authority") in policy["shown_authorities"]
                and evidence.get("file_id"))):
        return "shown"
    return "stated"
