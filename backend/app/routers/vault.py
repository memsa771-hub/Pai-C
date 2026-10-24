"""The student's Vault over HTTP: one view, the catalog, and the student's own edits.

Owner-only, with the same credential check as the Profile routes. Reads come
from `VaultView`, the one read model, so this router never shapes entries
itself. Every write is one candidate through `MemoryCandidateService.propose`
and `MemoryReconciler.reconcile` (VAULT_SPEC §Inputs: one door), marked as the
student's own statement from the Vault page, so an edit here carries the same
provenance and meets the same normalization, validation and conflict rules as
anything PAI extracted.
"""
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.response import ResponseCode, json_response, success_response
from app.database import get_db
from app.memory.candidates import MemoryCandidateService
from app.memory.catalog import TypeSpec, vault_catalog
from app.memory.errors import MemoryDataError
from app.memory.evidence import value_digest
from app.memory.field_definitions import VaultFieldDefinitionService
from app.memory.normalize import detect_language
from app.memory.profile_issues import ProfileIssueService
from app.memory.reconciler import MemoryReconciler
from app.memory.student_records import ENTITY_MODELS, StudentRecordService
from app.memory.student_schema import RECORD_SPECS
from app.memory.vault import VaultService, _unwrap
from app.memory.vault_items import VaultItemService
from app.memory.vault_view import VaultView, _display, _without, level_of, view_copy
from app.models import FileRecord, VaultDrop, VaultFact, VaultItem
from app.routers.network import _resolve_workspace, _verify_workspace_access
from app.security.access import is_workspace_owner

router = APIRouter(prefix="/v1/vault", tags=["Vault"])

# Entry kinds as the view names them -> the candidate type that writes them.
CANDIDATE_TYPES = {"fact": "vault_fact", "record": "student_record", "item": "vault_item"}
DROP_LIMIT = 200


class NewEntry(BaseModel):
    type: str = Field(min_length=1, max_length=200)
    value: Any
    # What the student typed, when the form had free text; it becomes the
    # quote, so the original words are kept (VAULT_SPEC §Language).
    text: Optional[str] = Field(default=None, max_length=4000)


class EntryEdit(BaseModel):
    value: Any
    text: Optional[str] = Field(default=None, max_length=4000)


class ConflictAnswer(BaseModel):
    answer: str
    value: Any = None
    note: Optional[str] = Field(default=None, max_length=1000)


def _workspace(db, network, token, authorization):
    workspace = _resolve_workspace(db, network)
    if workspace is None:
        return None, json_response(ResponseCode.NOT_FOUND, "Network not found")
    if not _verify_workspace_access(workspace, token, authorization):
        return None, json_response(ResponseCode.UNAUTHORIZED, "Invalid credentials")
    return workspace, None


def _owner_workspace(db, network, token, authorization):
    """The workspace, for a write: only the signed-in owner may change the Vault.

    The machine token reads, but a write is the student's own statement (and a
    confirm marks a value "Confirmed"), so an agent holding the token must not
    be able to make one in the student's name.
    """
    workspace, error = _workspace(db, network, token, authorization)
    if error:
        return None, error
    if not is_workspace_owner(db, workspace, authorization):
        return None, json_response(ResponseCode.FORBIDDEN, "Only the student can change their Vault")
    return workspace, None


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.isoformat() if moment else None


def _record_kinds() -> list[str]:
    """Record kinds the view shows: catalog records plus the ones vault_view.json places."""
    kinds = [spec.key for spec in vault_catalog().types(storage="record")]
    return kinds + [k for k, place in view_copy()["uncatalogued_records"].items() if not place.get("hidden")]


class _Entry:
    """The stored entry a path names, found only inside this workspace."""

    def __init__(self, kind: str, type_key: str, entry_id: str, value: Any):
        self.kind, self.type, self.id, self.value = kind, type_key, entry_id, value


def _find(db: Session, workspace_id: str, kind: str, entry_id: str, *, active: bool = True) -> Optional[_Entry]:
    if kind == "fact":
        fact = db.get(VaultFact, entry_id)
        if fact is None or str(fact.workspace_id) != workspace_id or (active and fact.status != "active"):
            return None
        return _Entry(kind, fact.field_key, fact.id, _unwrap(fact.value))
    if kind == "item":
        item = db.get(VaultItem, entry_id)
        if item is None or str(item.workspace_id) != workspace_id or (active and item.status != "active"):
            return None
        return _Entry(kind, item.item_type, item.id, item.value)
    records = StudentRecordService(db)
    for record_kind in _record_kinds():
        model = ENTITY_MODELS[record_kind]
        row = db.get(model, entry_id)
        if row is not None and str(row.workspace_id) == workspace_id and (not active or row.status == "active"):
            return _Entry(kind, record_kind, row.id, records._values(record_kind, row))
    return None


def _locate(db, workspace_id, kind, entry_id, *, active=True):
    """(entry, error response): a kind the view does not use is 400, a missing entry 404."""
    if kind not in CANDIDATE_TYPES:
        return None, json_response(ResponseCode.BAD_REQUEST, "Entry kind must be fact, record or item")
    entry = _find(db, workspace_id, kind, entry_id, active=active)
    if entry is None:
        return None, json_response(ResponseCode.NOT_FOUND, "Vault entry not found")
    return entry, None


def _write(db: Session, workspace_id: str, entry_kind: str, key: str, *, value: Any = None,
           operation: str = "upsert", entities: Optional[dict] = None, text: Optional[str] = None,
           quote_value: Any = None, extra: Optional[dict] = None):
    """One candidate, reconciled; returns the success or error response.

    The quote is what the student typed, or the JSON of the value when the form
    had no free text, so every Vault API write keeps its original input.
    """
    typed = (text or "").strip()
    quote = typed or json.dumps(value if quote_value is None else quote_value,
                                ensure_ascii=False, default=str, sort_keys=True)
    evidence = {"capture": "vault_api", "quote": quote, "source_language": detect_language(quote),
                **(extra or {})}
    try:
        candidate = MemoryCandidateService(db).propose(
            workspace_id=workspace_id, candidate_type=CANDIDATE_TYPES[entry_kind], operation=operation,
            key=key, proposed_value=value, entities=entities or {}, confidence=1.0,
            source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            evidence=evidence,
        )
        result = MemoryReconciler(db).reconcile(candidate)
    except MemoryDataError as exc:
        db.rollback()
        return json_response(ResponseCode.BAD_REQUEST, str(exc))
    db.commit()
    if result.accepted:
        return success_response({"saved": True, "kind": entry_kind, "type": key, "id": result.result_id})
    if result.outcome == "needs_review":
        # Not refused: the entry is now "In question" and a card asks the student.
        return success_response({"saved": False, "kind": entry_kind, "type": key, "in_question": True})
    return json_response(ResponseCode.BAD_REQUEST, result.reason or "Vault edit rejected")


def _editable(type_key: str) -> Optional[TypeSpec]:
    """Adding and editing go to catalog types only: their schema is the form."""
    return vault_catalog().type(type_key)


def _removable(entry: _Entry) -> bool:
    """Confirm and remove work on every record kind the view shows, except a
    file's own record, which goes when the file is deleted in Documents."""
    if entry.kind == "record":
        return not view_copy()["uncatalogued_records"].get(entry.type, {}).get("file_field")
    return _editable(entry.type) is not None


def _entities(entry: _Entry) -> dict:
    """Aim the candidate at exactly this entry."""
    if entry.kind == "item":
        return {"item_id": entry.id}
    return {"record_id": entry.id} if entry.kind == "record" else {}


# ---- reads -------------------------------------------------------------------


@router.get("")
def get_vault(
    network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """Everything the Vault holds about the student (VAULT_SPEC §Access: student sees everything)."""
    workspace, error = _workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    return success_response(VaultView(db).build(str(workspace.id), include_sensitive=True))


@router.get("/catalog")
def get_catalog(
    network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """What a form needs for each type: placement, inputs, schema and choice labels.

    Built from an explicit list, so the conflict rule, freshness window,
    version, identity, sensitivity, onboarding settings and choice synonyms
    stay server-side. A fact's schema is its active field definition and a
    record's is its record spec, since those are what validate the write.
    """
    workspace, error = _workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    catalog = vault_catalog()
    fields = VaultFieldDefinitionService(db)
    types = []
    for spec in catalog.types():
        schema = spec.schema
        if spec.storage == "fact":
            definition = fields.get(spec.key)
            schema = definition.validation_schema if definition else None
        elif spec.storage == "record" and spec.key in RECORD_SPECS:
            record = RECORD_SPECS[spec.key]
            schema = {"type": "object", "properties": record["properties"], "required": list(record["required"])}
        types.append({
            "key": spec.key, "label": spec.label, "storage": spec.storage, "shown_on": spec.shown_on,
            "section": spec.section, "inputs": list(spec.inputs), "schema": schema,
            "choices": {name: [{"code": c.code, "label": c.label} for c in catalog.choices(list_name)]
                        for name, list_name in spec.choice_fields.items()},
        })
    return success_response({"types": types})


@router.get("/entries/{kind}/{entry_id}/history")
def get_entry_history(
    kind: str, entry_id: str, network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """Every earlier value of one entry, oldest first; values only, never evidence."""
    workspace, error = _workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    workspace_id = str(workspace.id)
    entry, error = _locate(db, workspace_id, kind, entry_id, active=False)
    if error:
        return error
    spec = vault_catalog().type(entry.type)
    if kind == "fact":
        rows = reversed(VaultService(db).history(workspace_id, entry.type))
        history = [{"id": f.id, "value": _unwrap(f.value), "display": _display(spec, _unwrap(f.value)),
                    "level": level_of(f.source_type, None, f.evidence, value=_unwrap(f.value),
                                      capture_method=f.capture_method),
                    "source": f.source_type, "status": f.status,
                    "valid_from": _iso(f.valid_from), "valid_until": _iso(f.valid_until)} for f in rows]
    elif kind == "item":
        history = [{"id": i.id, "value": i.value, "display": _display(spec, i.value), "level": i.level,
                    "source": i.source_type, "status": i.status, "observed_at": _iso(i.observed_at),
                    "valid_until": _iso(i.valid_until)}
                   for i in VaultItemService(db).history(workspace_id, entry.id)]
    else:
        omit = view_copy()["uncatalogued_records"].get(entry.type, {}).get("omit_fields", ())
        history = [{"id": r.id, "before": _without(r.before, omit), "after": _without(r.after, omit),
                    "source": r.source_type, "capture_method": r.capture_method,
                    "created_at": _iso(r.created_at)}
                   for r in StudentRecordService(db).history(workspace_id, entry.type, entry.id)]
    return success_response({"kind": kind, "type": entry.type, "id": entry.id, "history": history})


@router.get("/documents/{file_id}/entries")
def get_document_entries(
    file_id: str, network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """The entries one of the student's documents backs, for the Documents view."""
    workspace, error = _workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    workspace_id = str(workspace.id)
    owned = db.execute(select(FileRecord.id).where(
        FileRecord.id == file_id, FileRecord.workspace_id == workspace_id)).scalar_one_or_none()
    if owned is None:
        return json_response(ResponseCode.NOT_FOUND, "File not found")
    return success_response({"file_id": file_id,
                             "entries": VaultView(db).entries_for_document(workspace_id, file_id)})


@router.get("/drops")
def get_drops(
    since: Optional[datetime] = Query(None), limit: int = Query(DROP_LIMIT, ge=1, le=DROP_LIMIT),
    network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """The student's own drop log, newest first (VAULT_SPEC §Measures: no silent drops).

    Only where, why and which type: never the payload's value or quote, since the
    UI never shows the student's original words (VAULT_SPEC §Language).
    """
    workspace, error = _workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    statement = select(VaultDrop).where(VaultDrop.workspace_id == str(workspace.id))
    if since is not None:
        since = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since.astimezone(timezone.utc)
        statement = statement.where(VaultDrop.created_at >= since)
    rows = db.scalars(statement.order_by(VaultDrop.created_at.desc(), VaultDrop.id).limit(limit))
    return success_response({"drops": [
        {"source": d.source, "stage": d.stage, "reason": d.reason,
         "key": d.payload.get("key") if isinstance(d.payload, dict) else None,
         "created_at": _iso(d.created_at)} for d in rows]})


# ---- writes ------------------------------------------------------------------


@router.post("/entries")
def add_entry(
    body: NewEntry, network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """A detail or story entry the student adds; the catalog's storage picks the store."""
    workspace, error = _owner_workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    spec = _editable(body.type)
    if spec is None:
        return json_response(ResponseCode.BAD_REQUEST, f"Unknown Vault type {body.type!r}")
    return _write(db, str(workspace.id), spec.storage, spec.key, value=body.value, text=body.text)


@router.patch("/entries/{kind}/{entry_id}")
def edit_entry(
    kind: str, entry_id: str, body: EntryEdit, network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """The student's correction of one entry (VAULT_SPEC §Conflicts step 2: the student wins)."""
    workspace, error = _owner_workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    workspace_id = str(workspace.id)
    entry, error = _locate(db, workspace_id, kind, entry_id)
    if error:
        return error
    spec = _editable(entry.type)
    if spec is None:
        return json_response(ResponseCode.BAD_REQUEST, "This entry cannot be edited here")
    return _write(db, workspace_id, kind, entry.type, value=body.value, entities=_entities(entry),
                  text=body.text,
                  extra={"semantic_correction": True})


@router.post("/entries/{kind}/{entry_id}/confirm")
def confirm_entry(
    kind: str, entry_id: str, network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """The student confirms the value as it stands (evidence ladder: confirmed).

    One candidate restating the current value with a confirmation digest. For
    facts and records `evidence_level` recognises it; for items the reconciler
    confirms into a new version. Either way a value that changed in the
    meantime is not confirmed by accident.
    """
    workspace, error = _owner_workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    workspace_id = str(workspace.id)
    entry, error = _locate(db, workspace_id, kind, entry_id)
    if error:
        return error
    if not _removable(entry):
        return json_response(ResponseCode.BAD_REQUEST, "This entry cannot be confirmed here")
    confirmation = {"value_digest": value_digest(entry.value),
                    "confirmed_at": datetime.now(timezone.utc).isoformat()}
    return _write(db, workspace_id, kind, entry.type, value=entry.value, entities=_entities(entry),
                  extra={"action": "confirm", "confirmation": confirmation})


@router.delete("/entries/{kind}/{entry_id}")
def remove_entry(
    kind: str, entry_id: str, network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """Retract one entry; it stays in history and returns only when the student states it again."""
    workspace, error = _owner_workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    workspace_id = str(workspace.id)
    entry, error = _locate(db, workspace_id, kind, entry_id)
    if error:
        return error
    if not _removable(entry):
        return json_response(ResponseCode.BAD_REQUEST, "This entry cannot be removed here")
    return _write(db, workspace_id, kind, entry.type, operation="retract", entities=_entities(entry),
                  quote_value=entry.value)


@router.post("/conflicts/{issue_id}/resolve")
def resolve_conflict(
    issue_id: str, body: ConflictAnswer, network: str = Query(...), db: Session = Depends(get_db),
    x_workspace_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
):
    """Answer one conflict card with one of the answers the view offered for it."""
    workspace, error = _owner_workspace(db, network, x_workspace_token, authorization)
    if error:
        return error
    workspace_id = str(workspace.id)
    card = next((c for c in VaultView(db).build(workspace_id)["conflicts"] if c["id"] == issue_id), None)
    if card is None:
        return json_response(ResponseCode.NOT_FOUND, "Conflict not found or already answered")
    if body.answer not in card["answers"]:
        return json_response(ResponseCode.BAD_REQUEST,
                             f"This question takes one of: {', '.join(card['answers'])}")
    try:
        result = ProfileIssueService(db).resolve(workspace_id, issue_id, body.answer,
                                                 value=body.value, note=body.note, capture="vault_api")
    except MemoryDataError as exc:
        db.rollback()
        return json_response(ResponseCode.BAD_REQUEST, str(exc))
    db.commit()
    if not result["resolved"]:
        return json_response(ResponseCode.BAD_REQUEST, result.get("reason") or "Answer not applied")
    return success_response(result)
