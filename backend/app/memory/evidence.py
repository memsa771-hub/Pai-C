"""Evidence labels derived from trusted provenance, not a model's claimed level."""
import hashlib
import json
import re
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


_PAGE_LOCATOR = re.compile(r"^p(\d+)$")


def page_of(evidence) -> int | None:
    """The page a document reading came from. Items carry `page`; document
    findings carry a parser locator, where "p3" is page 3 of a PDF or photo
    (a DOCX paragraph or table locator has no page)."""
    evidence = evidence or {}
    page = evidence.get("page")
    if isinstance(page, int) and not isinstance(page, bool):
        return page
    match = _PAGE_LOCATOR.match(str(evidence.get("locator") or "").strip().strip("[]").strip())
    return int(match.group(1)) if match else None


def agrees(reading, value) -> bool:
    """A document's reading matches the new value (a record's reading holds
    only the fields the student changed)."""
    if isinstance(reading, dict) and isinstance(value, dict):
        return all(value.get(k) == v for k, v in reading.items())
    return reading == value


MAX_DISAGREEMENTS = 10


def merge_disagreements(evidence, prior_evidence, new_value, added=()) -> dict:
    """Evidence for a new version of an entry, carrying the disagreements of
    the version it replaces. Order is oldest first: the replaced version's,
    the incoming evidence's own, then `added`. A disagreement is dropped once
    the new value matches it, repeats of one (file, page, value) keep the
    newest, and only the newest MAX_DISAGREEMENTS stay."""
    out = dict(evidence or {})
    merged = [*(prior_evidence or {}).get("disagreements", []), *out.get("disagreements", []), *added]
    kept, seen = [], set()
    for d in reversed(merged):
        if agrees(d.get("value"), new_value):
            continue
        key = (d.get("file_id"), d.get("page"), json.dumps(d.get("value"), sort_keys=True, default=str))
        if key not in seen:
            seen.add(key)
            kept.append(d)
    kept = list(reversed(kept))[-MAX_DISAGREEMENTS:]
    if kept:
        out["disagreements"] = kept
    else:
        out.pop("disagreements", None)
    return out


def with_disagreements(evidence, prior_row: dict, prior_value, reading, new_value, *, temporal=False) -> dict:
    """Evidence for a student's edit that keeps a disagreeing document visible
    (VAULT_SPEC §Evidence ladder: the student's edit wins, the document stays
    on the entry). `prior_row` is the replaced entry as {source_type,
    verification_status, capture_method, evidence}; `reading` is what the
    document said, shown on the entry. A change over time is not a
    disagreement."""
    prior = prior_row.get("evidence") or {}
    added = []
    if not temporal and evidence_level(prior_row, prior_value) == "shown" and not agrees(reading, new_value):
        added.append({"value": reading, "source_type": prior_row.get("source_type"),
                      "file_id": prior.get("file_id"), "page": page_of(prior)})
    return merge_disagreements(evidence, prior, new_value, added)
