"""The Counsellor side of FactConflicts v1 (P1-T8, R-21, D-w12, D-w13): the student's open Vault cards on a mark or a
test score, as a plain dict valid as `FactConflictsV1`, and the student's answer to one, written through the Vault's own
card resolution. The bridge hands both to PAI OS; this module never imports `app.os`.

Privacy allow-list: only the keys of `student_facts_keys.yaml` (education marks and level, test scores). A card on a
name, a date of birth, a guardian or a document owner gives no entry. Each differing key is one entry; the current value
is read from the record the StudentFacts stand for (`chosen_education`), so the two views agree. An answer is one of the
card's own answers: nothing here is a second way to write the Vault. The caller commits."""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import MemoryCandidate, ProfileIssue, VaultVersion
from app.pai_c.connect.student_facts import _num, chosen_education, education_records
from app.pai_c.connect.vault_version import key_map

log = logging.getLogger("app.pai_c.connect.fact_conflicts")

KINDS = ("education", "test_attempt")  # the card kinds that carry allow-listed keys
OFFERED = ("keep_current", "accept_proposed", "provide_new")  # both_true is not asked in PAI OS
ACTIONS = {"current": "keep_current", "proposed": "accept_proposed", "new": "provide_new"}
CAPTURE = "os_which_is_right"  # named on the evidence of every value an answer writes
IMPOSSIBLE = "impossible:"
_LEVELS = ("stated", "shown", "confirmed")


def _aware(value) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _level(level) -> str:
    return level if level in _LEVELS else "unknown"  # a guess (inferred) is sent as unknown


def _same(a, b) -> bool:
    return _num(a) == _num(b)


def _flat(values: dict, level: str | None) -> dict:
    """An education record's allow-listed fields (`level`, the result fields, the two parts), by the StudentFacts names."""
    out = {"level": level} if level else {}
    result = values.get("result") or {}
    for name, number in result.items():
        if name in ("part1", "part2") and isinstance(number, dict):
            out.update({f"{name}.{n}": x for n, x in number.items()})
        else:
            out[name] = number
    allowed = set(key_map()["education"]["fields"])
    return {k: v for k, v in out.items() if k in allowed and v is not None and v != ""}


def _test_code(text) -> str | None:
    from app.pai_c.connect.document_facts import _test_code as code

    return code(text)


def _family_of(row: dict) -> str | None:
    from app.pai_c.memory import vault_catalog

    catalog = vault_catalog()
    level = catalog.record_level(catalog.type("education"), row)
    return next((f for f, codes in key_map()["education"]["families"].items() if level in codes), None)


def _document_ref(source: dict | None, evidence: dict | None) -> str | None:
    file_id = ((source or {}).get("document") or {}).get("file_id")
    if file_id:
        return file_id
    os_id = (evidence or {}).get("os_document_id")
    return f"os:{os_id}" if os_id else None


def _current_side(row: dict, value) -> dict:
    level = _level(row.get("evidence_level"))
    file_id = (row.get("evidence") or {}).get("file_id")
    return {"side": "current", "value": value, "evidence": level,
            "document_ref": file_id if level in ("shown", "confirmed") else None, "as_of": _aware(row.get("updated_at"))}


def _proposed_side(card: dict, issue: ProfileIssue, value) -> dict:
    source = card.get("proposed_source") or {}
    return {"side": "proposed", "value": value, "evidence": _level(source.get("level")),
            "document_ref": _document_ref(source, (issue.evidence or {}).get("proposed_evidence")),
            "as_of": _aware(source.get("said_on"))}


def _education_entries(issue: ProfileIssue, card: dict, chosen: dict) -> list[tuple[str, dict, dict]]:
    """`(key, current side, proposed side)` for each differing field of the education record the card is about."""
    from app.pai_c.memory import vault_catalog

    evidence = issue.evidence or {}
    record_id = evidence.get("record_id") or issue.affected_id
    proposed = evidence.get("proposed")
    catalog = vault_catalog()
    spec = catalog.type("education")
    live = next((r for r in chosen.values() if r.get("id") == record_id), None)
    family = next((f for f, r in chosen.items() if r is live), None)
    if live is None or family is None or not isinstance(proposed, dict):
        return []
    now = _flat({"result": live.get("result")}, catalog.record_level(spec, live))
    new = _flat(proposed, catalog.record_level(spec, proposed) if proposed.get("qualification_name") else None)
    found = []
    for field in key_map()["education"]["fields"]:
        if field in now and field in new and not _same(now[field], new[field]):
            found.append((f"education.{family}.{field}", _current_side(live, now[field]),
                          _proposed_side(card, issue, new[field])))
    return found


def _test_entries(issue: ProfileIssue, card: dict, attempts: list[dict]) -> list[tuple[str, dict, dict]]:
    evidence = issue.evidence or {}
    record_id = evidence.get("record_id") or issue.affected_id
    proposed = evidence.get("proposed")
    live = next((r for r in attempts if r.get("id") == record_id), None)
    code = _test_code((live or {}).get("test_type"))
    if live is None or not code or not isinstance(proposed, dict):
        return []
    newest = next((r for r in attempts if _test_code(r.get("test_type")) == code), None)  # newest first
    now, new = _num(live.get("overall_score")), _num(proposed.get("overall_score"))
    if newest is not live or now is None or new is None or now == new:
        return []
    return [(key_map()["tests"]["key"].format(type=code), _current_side(live, now), _proposed_side(card, issue, new))]


def _cards(db, workspace_id: str) -> dict[str, dict]:
    from app.pai_c.memory import VaultView

    return {c["id"]: c for c in VaultView(db).build(workspace_id)["conflicts"]}


def _open_issues(db, workspace_id: str) -> list[ProfileIssue]:
    return list(db.scalars(select(ProfileIssue).where(
        ProfileIssue.workspace_id == workspace_id, ProfileIssue.status == "open",
        ProfileIssue.issue_type == "conflicting_record", ProfileIssue.affected_type.in_(KINDS))
        .order_by(ProfileIssue.created_at, ProfileIssue.id)))


def _card_entries(issue: ProfileIssue, card: dict, chosen: dict, attempts: list[dict]) -> list[tuple[str, dict, dict]]:
    """`(key, current side, proposed side)` for each key the card still differs on."""
    return (_education_entries(issue, card, chosen) if issue.affected_type == "education"
            else _test_entries(issue, card, attempts))


def _attempts(db, workspace_id: str) -> list[dict]:
    from app.pai_c.memory import MemoryService

    return list(MemoryService(db).profile(workspace_id).records.get("test_attempt", []))


def _entries(db, workspace_id: str) -> list[dict]:
    issues = _open_issues(db, workspace_id)
    if not issues:
        return []
    cards = _cards(db, workspace_id)
    chosen = chosen_education(education_records(db, workspace_id))
    attempts = _attempts(db, workspace_id)
    found: dict[str, dict] = {}
    for issue in issues:
        card = cards.get(issue.id)
        if card is None:
            continue
        answers = [a for a in card["answers"] if a in OFFERED]
        if "keep_current" not in answers:
            continue  # no current value to keep: nothing is in question for the facts
        for key, current, proposed in _card_entries(issue, card, chosen, attempts):
            found.setdefault(key, {"ref": f"profile_issue:{issue.id}", "key": key, "values": [current, proposed],
                                   "answers": answers})  # the oldest card of a key stands
    return [found[k] for k in sorted(found)]


def build(db, workspace_id: str) -> dict:
    """A `FactConflictsV1`-valid dict for the student's workspace: one entry per differing allow-listed key of an open
    conflicting-record card on an education or test record."""
    counter = db.get(VaultVersion, workspace_id)
    return {"schema": "pai.fact_conflicts.v1", "student_ref": str(workspace_id),
            "vault_version": int(counter.version) if counter else 0, "built_at": datetime.now(timezone.utc),
            "conflicts": _entries(db, workspace_id)}


# ---- the answer ----


def _typed(field: str, value):
    """The student's typed value as the Vault stores it: text for a text field, else a number. None when unusable."""
    from app.pai_c.connect.document_facts import _data, _number

    if value is None or isinstance(value, bool):
        return None
    if field in _data()["text_fields"]:
        return str(value).strip() or None
    return _number(value)


def _place(db, workspace_id: str, key: str, value) -> tuple[str, dict, str] | None:
    """`(candidate key, the record value that holds only this fact, record id)` for a fact key, or None when the key is
    not one a student can type (the level) or names no record the facts stand for."""
    from app.pai_c.memory import MemoryService

    if key.startswith("education."):
        _, _, rest = key.partition(".")
        family, _, field = rest.partition(".")
        if field not in set(key_map()["education"]["fields"]) - {"level"}:
            return None
        row = chosen_education(education_records(db, workspace_id)).get(family)
        typed = _typed(field, value)
        if row is None or typed is None:
            return None
        node: dict = {}
        *parents, leaf = field.split(".")
        cursor = node.setdefault("result", {})
        for part in parents:
            cursor = cursor.setdefault(part, {})
        cursor[leaf] = typed
        return "education", node, row["id"]
    template = key_map()["tests"]["key"]
    prefix, _, suffix = template.partition("{type}")
    if key.startswith(prefix) and key.endswith(suffix) and len(key) > len(prefix) + len(suffix):
        code, typed = key[len(prefix):len(key) - len(suffix)], _typed("overall_score", value)
        attempts = list(MemoryService(db).profile(workspace_id).records.get("test_attempt", []))
        row = next((r for r in attempts if _test_code(r.get("test_type")) == code), None)
        if row is None or typed is None or not re.fullmatch(r"[a-z0-9_]+", code):
            return None
        return "test_attempt", {"overall_score": typed}, row["id"]
    return None


def _quote(request_id) -> str:
    return "Student chose in PAI OS" + (f" (request {request_id})" if request_id is not None else "")


def _evidence(request_id, **more) -> dict:
    """What every value an answer writes names: the capture surface, the OS request, and a quote."""
    out = {"capture": CAPTURE, "quote": _quote(request_id), **more}
    if request_id is not None:
        out["os_request_id"] = request_id
    return out


def _held(db, workspace_id: str, key: str, record_id: str):
    """The record the key stands for, as it is now (or None)."""
    if key.startswith("education."):
        family = key.partition(".")[2].partition(".")[0]
        row = chosen_education(education_records(db, workspace_id)).get(family)
        return row if row is not None and row.get("id") == record_id else None
    return next((r for r in _attempts(db, workspace_id) if r.get("id") == record_id), None)


def _field_of(key: str) -> str:
    if key.startswith("education."):
        return key.partition(".")[2].partition(".")[2]
    return "overall_score"


def _raw(row: dict, field: str):
    """The stored value of an allow-listed field: the qualification name for the level, else the result field."""
    if field == "level":
        return row.get("qualification_name")
    if field == "overall_score":
        return row.get("overall_score")
    node = row.get("result") or {}
    for part in field.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _put(proposed: dict, field: str, raw) -> dict:
    """A copy of the card's proposed record whose `field` holds `raw` (so the card no longer differs on it)."""
    out = {**proposed}
    if field in ("level", "overall_score"):
        out["qualification_name" if field == "level" else field] = raw
        return out
    result = out["result"] = dict(out.get("result") or {})
    *parents, leaf = field.split(".")
    for part in parents:
        result = result[part] = dict(result.get(part) or {})
    result[leaf] = raw
    return out


def _level_place(db, workspace_id: str, key: str, proposed: dict) -> tuple[str, dict, str] | None:
    """The qualification name of the card's proposed record, as a record value (the level has no typed value)."""
    family = key.partition(".")[2].partition(".")[0]
    row = chosen_education(education_records(db, workspace_id)).get(family)
    name = proposed.get("qualification_name")
    return ("education", {"qualification_name": name}, row["id"]) if row is not None and name else None


def _write(db, workspace_id: str, issue: ProfileIssue, kind: str, record_value: dict, record_id: str, action: str,
           request_id):
    """The student's own value for one fact, through the reconciler, as the card's resolution writes it. Returns the
    reconciler's result, or None when the Vault refused the value."""
    from app.pai_c.memory import MemoryCandidateService, MemoryDataError, MemoryReconciler

    candidate = MemoryCandidateService(db).propose(
        workspace_id, "student_record", key=kind, proposed_value=record_value, entities={"record_id": record_id},
        confidence=1.0, source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
        evidence=_evidence(request_id, profile_issue_id=issue.id, resolution_action=action))
    try:
        result = MemoryReconciler(db).reconcile(candidate)
    except MemoryDataError:
        return None
    return result if result.accepted else None


def answer(db, workspace_id: str, ref: str, key: str, choice: str, value=None, request_id=None) -> dict:
    """Writes the student's answer to one question about a fact, through the Vault's own paths. No commit.

    One value at a time (owner ruling, P1-T8): an answer saves only the value of `key` and nothing else of the card.
    `proposed` writes the card's value for that key, `new` writes the typed value, `current` writes nothing; each is
    noted on the card so the key is no longer asked. The card stays open until no key of it differs; then it is closed
    (the close hook fires).

    `ref` is a card (`profile_issue:<id>`) or `impossible:<fact key>` (a value above its total: only a new value is
    taken, written as the student's own edit through the reconciler). `choice` is `current`, `proposed` or `new` (with
    `value`). `request_id` is the OS request, named on the evidence. Returns `{"status": "resolved"}` (this key is
    answered), `{"status": "gone"}` (the card is closed already: the answer was given elsewhere) or
    `{"status": "refused", "code": ...}` with code `bad_choice`, `not_offered`, `not_a_fact_question`,
    `new_value_required`, `invalid_value`, `not_typeable` or `not_saved`."""
    from app.pai_c.memory import MemoryCandidateService, MemoryDataError, MemoryReconciler, ProfileIssueService

    action = ACTIONS.get(choice)
    if action is None:
        return {"status": "refused", "code": "bad_choice"}
    if ref.startswith(IMPOSSIBLE):
        if action != "provide_new" or value is None:
            return {"status": "refused", "code": "new_value_required"}
        place = _place(db, workspace_id, key, value) if key == ref[len(IMPOSSIBLE):] else None
        if place is None:
            return {"status": "refused", "code": "not_typeable"}
        kind, record_value, record_id = place
        candidate = MemoryCandidateService(db).propose(
            workspace_id, "student_record", key=kind, proposed_value=record_value, entities={"record_id": record_id},
            confidence=1.0, source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            evidence=_evidence(request_id))
        try:
            result = MemoryReconciler(db).reconcile(candidate)
        except MemoryDataError:
            return {"status": "refused", "code": "invalid_value"}
        return {"status": "resolved"} if result.accepted else {"status": "refused", "code": "invalid_value"}

    issue_id = ref.partition(":")[2] if ref.startswith("profile_issue:") else ""
    issue = db.scalar(select(ProfileIssue).where(ProfileIssue.id == issue_id, ProfileIssue.workspace_id == workspace_id)
                      ) if issue_id else None
    if issue is None:
        return {"status": "refused", "code": "not_a_fact_question"}
    if issue.status != "open":
        return {"status": "gone"}  # answered on the Vault page or in the chat while the student was looking
    asked = next((c for c in _entries(db, workspace_id) if c["ref"] == ref and c["key"] == key), None)
    if asked is None:
        return {"status": "refused", "code": "not_a_fact_question"}  # a name card, or no longer a question about this fact
    if action not in asked["answers"]:
        return {"status": "refused", "code": "not_offered"}
    field = _field_of(key)
    place = None
    if action == "provide_new":
        place = _place(db, workspace_id, key, value) if value is not None else None
        if place is None:
            return {"status": "refused", "code": "new_value_required" if value is None else "not_typeable"}
    service = ProfileIssueService(db)
    locked = service.lock_open(workspace_id, issue_id)  # workspace before issue: the Vault's lock order
    if locked is None:
        return {"status": "gone"}  # closed by another answer between the read and the lock
    proposed = dict((locked.evidence or {}).get("proposed") or {})
    record_id = (locked.evidence or {}).get("record_id") or locked.affected_id
    if action == "accept_proposed":
        if field == "level":
            place = _level_place(db, workspace_id, key, proposed)
        else:
            theirs = next(v["value"] for v in asked["values"] if v["side"] == "proposed")
            place = _place(db, workspace_id, key, theirs)
        if place is None:
            return {"status": "refused", "code": "not_typeable"}
    if place is not None and _write(db, workspace_id, locked, *place, action, request_id) is None:
        return {"status": "refused", "code": "invalid_value"}
    # the card now agrees with the record on this key, whichever side the student chose
    row = _held(db, workspace_id, key, record_id)
    if row is None:
        return {"status": "refused", "code": "not_saved"}
    answers = {**((locked.evidence or {}).get("os_answers") or {}),
               key: {"choice": choice, **({"request_id": request_id} if request_id is not None else {})}}
    agreed = _raw(row, field)
    locked.evidence = {**(locked.evidence or {}), "proposed": _put(proposed, field, agreed), "os_answers": answers}
    original = db.get(MemoryCandidate, locked.candidate_id) if locked.candidate_id else None
    if original is not None and original.status in ("pending", "needs_review") and isinstance(
            original.proposed_value, dict):
        wrapped = set(original.proposed_value) == {"value"}  # the proposal the Vault page would apply is narrowed too
        body = original.proposed_value["value"] if wrapped else original.proposed_value
        if isinstance(body, dict):
            narrowed = _put(body, field, agreed)
            original.proposed_value = {"value": narrowed} if wrapped else narrowed
    db.flush()
    card = _cards(db, workspace_id).get(locked.id)
    left = _card_entries(locked, card, chosen_education(education_records(db, workspace_id)),
                         _attempts(db, workspace_id)) if card is not None else []
    if not left:
        service.settle(locked, note="Answered in PAI OS, one value at a time.", answers=answers)
    return {"status": "resolved"}
