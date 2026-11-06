"""The Vault's sink for fact proposals from confirmed PAI OS documents (P1-T7, R-16, D-y9, D-y10, row 6.7).

`apply(db, proposal)` takes a `fact_proposal.v1` as a plain dict (this module never imports `app.os`) and turns it
into Vault candidates: one `student_record` / `education` candidate per education family and one
`student_record` / `test_attempt` per test. The reconciler is the only writer, as for every other source: the
candidates go through `MemoryCandidateService.propose` and the existing reconcile job. Their `source_type` and
`input_channel` are `document`, and their evidence names the file and an authority, so a Counsellor file gives the
value evidence `shown`. A document that only PAI OS holds (`document_ref` = `os:<id>`) has no file and gives `stated`.

The caller commits. One `pai_document_proposals` row per key makes a repeat delivery a `duplicate` that proposes
nothing. No name, date of birth or document value is ever read here: only the fact keys the OS sent. No chat message
is queued (the reconcile job carries no `document_file_id`)."""

import logging
import re
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select

from app.pai_c.memory import reconcile_job_type

JOB_RECONCILE = reconcile_job_type()  # the durable job every Vault candidate goes through (a name the job audit reads)
log = logging.getLogger("app.pai_c.connect.document_facts")
_DATA = Path(__file__).with_name("document_facts.yaml")
_OS_ONLY = "os:"
_KEY_ID = re.compile(r"^fact_proposal:(\d+):")


@lru_cache(maxsize=1)
def _data() -> dict:
    return yaml.safe_load(_DATA.read_text(encoding="utf-8"))


def _number(value):
    """A number from a confirmed value (text or number); None when it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else number


def _set(node: dict, path: str, value) -> None:
    *parents, leaf = path.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value


def _split(facts: list[dict]) -> tuple[dict[str, dict], dict[str, object]]:
    """(education result fields by family, test scores by catalog test code) from the proposal's fact keys. A key of
    no rule, or a value that is not usable, is left out."""
    from app.pai_c.connect.vault_version import key_map

    mapping = key_map()
    fields = set(mapping["education"]["fields"]) - {"level"}
    prefix, _, suffix = mapping["tests"]["key"].partition("{type}")
    families, tests = set(mapping["education"]["families"]), {}
    education: dict[str, dict] = {}
    for fact in facts:
        key, value = str(fact.get("key") or ""), fact.get("value")
        if key.startswith("education."):
            _, _, rest = key.partition(".")
            family, _, field = rest.partition(".")
            if family not in families or field not in fields:
                continue
            value = str(value).strip() if field in _data()["text_fields"] else _number(value)
            if value in (None, ""):
                continue
            _set(education.setdefault(family, {}), field, value)
        elif key.startswith(prefix) and key.endswith(suffix) and len(key) > len(prefix) + len(suffix):
            code, score = key[len(prefix):len(key) - len(suffix)], _number(value)
            if score is not None and re.fullmatch(r"[a-z0-9_]+", code):
                tests[code] = score
    return education, tests


def _record_id(records: list[dict], family: str) -> str | None:
    """The record a family's marks are written to: the one the Vault already shows for the family (the same choice
    StudentFacts makes), else None."""
    from app.pai_c.connect.student_facts import chosen_education

    row = chosen_education(records).get(family)
    return None if row is None else row.get("id")


def apply(db, proposal: dict) -> tuple[str, list[str]]:
    """Writes the proposal's candidates and enqueues their reconciliation, in the caller's transaction (no commit).

    Returns `("written", candidate_ids)` or `("duplicate", candidate_ids)` (the key was delivered before), or
    `("refused", [code])` with code `no_workspace`, `no_mapping`, `file_not_yours` or `file_gone`. Facts the Vault
    already holds as a candidate from an earlier proposal for the same document (the student confirmed the same values
    again) are left out; if nothing is left the answer is `duplicate`."""
    from app import models
    from app.pai_c.connect.student_facts import education_records
    from app.pai_c.memory import MemoryCandidateService, MemoryService
    from app.runtime.task_runtime import enqueue

    key, ref = str(proposal.get("key") or ""), str(proposal.get("document_ref") or "")
    workspace_id = _workspace(db, str(proposal.get("student_ref") or ""))
    if workspace_id is None:
        return "refused", ["no_workspace"]
    done = db.scalar(select(models.DocumentProposal).where(models.DocumentProposal.key == key))
    if done is not None:
        return "duplicate", list(done.candidate_ids or [])
    file_id, filename = None, None
    if not ref.startswith(_OS_ONLY):
        record = db.get(models.FileRecord, ref)
        if record is None or str(record.workspace_id) != workspace_id:
            return "refused", ["file_not_yours"]
        if record.status != "active":
            return "refused", ["file_gone"]  # trashed or deleted since the student confirmed
        file_id, filename = record.id, record.filename
    doc_type = str(proposal.get("doc_type") or "")
    authority = _data()["authority"].get(doc_type)
    education, tests = _split(list(proposal.get("facts") or []))
    if authority is None or not (education or tests):
        return "refused", ["no_mapping"]

    match = _KEY_ID.match(key)
    # No file, no authority: the Vault cannot show that an issuer's paper stands behind the value, so it stays
    # `stated` (D-y13). With a Counsellor file the authority gives evidence `shown`.
    evidence = {"os_doc_type": doc_type, "os_confirmed": True, "os_proposal": key,
                **({"os_document_id": int(match.group(1))} if match else {}),
                **({"authority": authority, "file_id": file_id, "filename": filename} if file_id else {})}
    candidates, ids = MemoryCandidateService(db), []
    earlier = _earlier_values(db, workspace_id, match)

    def propose(key_, value, entities=None, correction=False):
        if (key_, _flat(value)) in earlier:  # the same confirmed values again: no second set of candidates
            return
        if correction:
            # The Vault's value came from this same document: the student is correcting their own earlier
            # confirmation. It goes through the reconciler's correction path (the student's explicit edit replaces
            # the value and keeps the old reading visible), never as a conflict between two of their confirmations.
            candidate = candidates.propose(
                workspace_id, "student_record", key=key_, proposed_value=value, entities=entities, confidence=0.95,
                source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
                evidence={**evidence, "capture": "os_document_correction"})
        else:
            candidate = candidates.propose(workspace_id, "student_record", key=key_, proposed_value=value,
                                           entities=entities, confidence=0.95, source_type="document",
                                           input_channel="document", evidence=dict(evidence))
        ids.append(candidate.id)

    def own(row) -> bool:
        """True when the record's current evidence came from this same OS document."""
        return bool(match and row and (row.get("evidence") or {}).get("os_document_id") == int(match.group(1)))

    records = education_records(db, workspace_id) if education else []
    from app.pai_c.connect.student_facts import chosen_education

    chosen = chosen_education(records)
    for family in sorted(education):
        existing = _record_id(records, family)
        if existing:
            propose("education", {"result": education[family]}, {"record_id": existing},
                    correction=own(chosen.get(family)))
        else:
            propose("education", {"qualification_name": _data()["new_record_code"][family],
                                  "result": education[family]})
    attempts = list(MemoryService(db).profile(workspace_id).records.get("test_attempt", [])) if tests else []
    for code in sorted(tests):
        mine = next((r for r in attempts if own(r) and _test_code(r.get("test_type")) == code), None)
        propose("test_attempt", {"test_type": code, "overall_score": tests[code]},
                {"record_id": mine["id"]} if mine else None, correction=mine is not None)
    db.add(models.DocumentProposal(key=key, workspace_id=workspace_id, file_id=file_id, candidate_ids=ids))
    if not ids:  # every fact was already proposed from this document
        db.flush()
        return "duplicate", []
    enqueue(db, job_type=JOB_RECONCILE, workspace_id=workspace_id, payload={"candidate_ids": ids},
            idempotency_key=f"reconcile:os_document:{key}")
    _tell_context_line(db, workspace_id, file_id, ids)
    db.flush()
    return "written", ids


def _test_code(text) -> str | None:
    from app.pai_c.memory import vault_catalog

    text = str(text or "").strip()
    return vault_catalog().choice_code("tests", text) or re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_") or None


def _earlier_values(db, workspace_id: str, match) -> list:
    """`(candidate key, proposed value)` of every candidate an earlier proposal for the same OS document made."""
    from app import models

    if match is None:
        return []
    rows = db.scalars(select(models.DocumentProposal).where(
        models.DocumentProposal.workspace_id == workspace_id,
        models.DocumentProposal.key.like(f"fact_proposal:{int(match.group(1))}:%"))).all()
    ids = [i for row in rows for i in (row.candidate_ids or [])]
    if not ids:
        return []
    found = db.scalars(select(models.MemoryCandidate).where(models.MemoryCandidate.id.in_(ids))).all()
    return [(c.key, _flat((c.proposed_value or {}).get("value"))) for c in found]


def _flat(value, path: str = "") -> tuple:
    """A value as sorted `(path, text)` pairs, so a number the Vault stored as text still equals the number sent."""
    if isinstance(value, dict):
        return tuple(sorted(p for k, v in value.items() for p in _flat(v, f"{path}.{k}")))
    return ((path, str(value)),)


def _workspace(db, student_ref: str) -> str | None:
    import uuid

    from app import models

    try:
        workspace_id = str(uuid.UUID(student_ref))
    except ValueError:
        return None
    return workspace_id if db.get(models.Workspace, workspace_id) is not None else None


def _tell_context_line(db, workspace_id: str, file_id: str | None, ids: list[str]) -> None:
    """A typed file skips the Counsellor's own reading, so its document record names no candidates and the chat's
    context line reads "nothing new for the profile". Naming these candidates lets that line report what the
    reconciler did with them. It changes no wording and queues no message."""
    if file_id is None:
        return
    from app import models

    artifact = db.scalar(select(models.DocumentArtifact).where(
        models.DocumentArtifact.file_id == file_id, models.DocumentArtifact.workspace_id == workspace_id))
    if artifact is None:
        return
    summary = dict(artifact.extraction_summary or {})
    known = list(summary.get("candidate_ids", []))
    artifact.extraction_summary = {**summary, "candidate_ids": [*known, *[i for i in ids if i not in known]]}
