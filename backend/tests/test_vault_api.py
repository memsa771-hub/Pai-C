# -*- coding: utf-8 -*-
"""The /v1/vault HTTP contract, exercised through the real ASGI app.

The stores and the view are covered by their own tests; these cover the wire:
owner-only access, every write going through propose -> reconcile with the
Vault API's provenance, the conflict answers the view offers, and a catalog
that exposes only what a form needs.
"""

import importlib.util
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.memory.field_definitions import VaultFieldDefinitionService
from app.memory.vault_items import VaultItemService
from app.memory.student_records import StudentRecordService
from app.models import (
    BackgroundJob, FileRecord, MemoryCandidate, ProfileIssue, User, VaultDrop, VaultItem, Workspace,
)
from scripts.eval_vault import VaultSession

TOKEN = "synthetic-test-only"  # StudentSession's workspace password_hash
# The signed-in owner: the frontend sends the machine token and the bearer together.
HEADERS = {"X-Workspace-Token": TOKEN, "Authorization": "Bearer owner"}
MACHINE_ONLY = {"X-Workspace-Token": TOKEN}
MIGRATION_116 = Path(__file__).resolve().parents[1] / "alembic/versions/116_vault_items.py"


def _budget_schema() -> dict:
    """Migration 116's ranged budget definition, which production runs on."""
    spec = importlib.util.spec_from_file_location("vault_items_116_api", MIGRATION_116)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BUDGET_SCHEMA


# Bearer -> verified user id. Only "owner" is this student; the others are
# real accounts that do not own this workspace.
BEARERS = {}


def _claims(bearer):
    user_id = BEARERS.get(bearer)
    return {"session_user_id": user_id} if user_id else None


@pytest.fixture
def api():
    with VaultSession() as student, student.factory() as db,             patch("app.security.access.verify_identity_claims", side_effect=_claims):
        VaultFieldDefinitionService(db).upsert_definition({
            "key": "finance.budget", "category": "finance", "data_type": "object",
            "validation_schema": _budget_schema(), "sensitivity": "sensitive"})
        db.commit()
        BEARERS.clear()
        BEARERS.update({"owner": student.user_id, "stranger": str(uuid.uuid4())})
        app.dependency_overrides[get_db] = lambda: db
        try:
            yield TestClient(app), db, student.workspace_id
        finally:
            app.dependency_overrides.pop(get_db, None)


def _other_student(db):
    """A second student with their own account, token and bearer."""
    user = User(email="other@example.test", username="other_student")
    db.add(user)
    db.flush()
    other = Workspace(name="Someone else", owner_user_id=user.id, password_hash="other-token")
    db.add(other)
    db.commit()
    BEARERS["other"] = str(user.id)
    return str(other.id), {"X-Workspace-Token": "other-token", "Authorization": "Bearer other"}


def _url(network, path=""):
    return f"/v1/vault{path}?network={network}"


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _entries(view, type_key):
    found = [e for section in view["details"].values() for e in section["entries"] if e["type"] == type_key]
    found += [e for card in view["story"] if card["type"] == type_key for e in card["entries"]]
    return found


def test_add_story_item_then_view_shows_stated(api):
    client, db, ws = api
    saved = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                            json={"type": "interest", "value": {"text": "Robotics"}}))
    assert saved["saved"] is True and saved["kind"] == "item" and saved["id"]

    view = _ok(client.get(_url(ws), headers=HEADERS))
    [entry] = _entries(view, "interest")
    assert entry["value"] == {"text": "Robotics"}
    assert entry["level"] == "stated" and entry["badge"] == "Stated"
    assert entry["source"] == "user_explicit"

    [candidate] = db.scalars(select(MemoryCandidate).where(MemoryCandidate.workspace_id == ws)).all()
    assert candidate.input_channel == "profile" and candidate.source_type == "user_explicit"
    assert candidate.candidate_type == "vault_item" and candidate.status == "accepted"
    assert candidate.evidence["capture"] == "vault_api"
    assert json.loads(candidate.evidence["quote"]) == {"text": "Robotics"}
    assert candidate.evidence["source_language"] == "en"


CYCLES = [
    ("interest", "item", {"text": "Robotics"}, {"text": "Robotics and drones"}),
    ("location.current_city", "fact", "Lahore", "Karachi"),
    ("skill", "record", {"name": "Python"}, {"name": "Python", "proficiency": "intermediate"}),
]


@pytest.mark.parametrize("type_key,kind,first,second", CYCLES, ids=[c[1] for c in CYCLES])
def test_edit_confirm_remove_cycle(api, type_key, kind, first, second):
    client, db, ws = api
    added = _ok(client.post(_url(ws, "/entries"), headers=HEADERS, json={"type": type_key, "value": first}))
    assert added["kind"] == kind

    edited = _ok(client.patch(_url(ws, f"/entries/{kind}/{added['id']}"), headers=HEADERS,
                              json={"value": second, "text": "I changed this"}))
    [entry] = _entries(_ok(client.get(_url(ws), headers=HEADERS)), type_key)
    assert entry["value"] == second and entry["badge"] == "Stated"
    assert entry["id"] == edited["id"]

    _ok(client.post(_url(ws, f"/entries/{kind}/{entry['id']}/confirm"), headers=HEADERS))
    [entry] = _entries(_ok(client.get(_url(ws), headers=HEADERS)), type_key)
    assert entry["value"] == second
    assert entry["level"] == "confirmed" and entry["badge"] == "Confirmed"

    history = _ok(client.get(_url(ws, f"/entries/{kind}/{entry['id']}/history"), headers=HEADERS))["history"]
    assert len(history) >= 2
    assert "evidence" not in json.dumps(history) and "I changed this" not in json.dumps(history)

    _ok(client.delete(_url(ws, f"/entries/{kind}/{entry['id']}"), headers=HEADERS))
    assert _entries(_ok(client.get(_url(ws), headers=HEADERS)), type_key) == []

    candidates = db.scalars(select(MemoryCandidate).where(MemoryCandidate.workspace_id == ws)).all()
    assert all(c.input_channel == "profile" and c.source_type == "user_explicit" for c in candidates)
    assert all(c.evidence["capture"] == "vault_api" and c.evidence.get("source_language") for c in candidates)
    assert all(c.status == "accepted" for c in candidates)
    assert "retract" in {c.operation for c in candidates}


def _file(db, ws, name="card.pdf"):
    f = FileRecord(id=str(uuid.uuid4()), workspace_id=ws, filename=name, content_type="application/pdf",
                   size=10, storage_key=f"k/{name}", uploaded_by="human:user", status="active")
    db.add(f)
    db.flush()
    return f


def _owner_card(db, ws, f):
    issue = ProfileIssue(workspace_id=ws, issue_type="document_owner", severity="blocking",
                         affected_type="document", affected_id=f.id, summary="x", clarification_question="?",
                         evidence={"file_id": f.id, "document_names": ["Ali Khan"], "vault_names": ["Sara"]})
    db.add(issue)
    db.flush()
    return issue


def test_cross_workspace_access_denied(api):
    client, db, ws = api
    item = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                           json={"type": "interest", "value": {"text": "Robotics"}}))
    fact = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                           json={"type": "location.current_city", "value": "Lahore"}))
    record = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                             json={"type": "skill", "value": {"name": "Python"}}))
    f = _file(db, ws)
    issue = _owner_card(db, ws, f)
    db.add(VaultDrop(workspace_id=ws, source="details", stage="normalize", reason="empty_budget",
                     payload={"key": "finance.budget"}))
    db.commit()
    mine, theirs = _other_student(db)

    entry = f"/entries/item/{item['id']}"
    calls = [
        ("get", ""), ("get", "/catalog"), ("get", "/drops"), ("get", f"{entry}/history"),
        ("get", f"/documents/{f.id}/entries"),
        ("post", "/entries"), ("patch", entry), ("post", f"{entry}/confirm"), ("delete", entry),
        ("post", f"/conflicts/{issue.id}/resolve"),
    ]
    body = {"type": "interest", "value": {"text": "x"}, "answer": "keep_current"}
    for method, path in calls:
        kwargs = {"json": body} if method in ("post", "patch") else {}
        # The other student's credentials on this student's Vault: same refusal as the Profile routes.
        assert getattr(client, method)(_url(ws, path), headers=theirs, **kwargs).status_code == 401, path
        assert getattr(client, method)(_url(ws, path), **kwargs).status_code == 401, path

    # With their own credentials, none of this student's ids exist for them.
    for kind, entry_id in (("item", item["id"]), ("fact", fact["id"]), ("record", record["id"])):
        path = f"/entries/{kind}/{entry_id}"
        assert client.get(_url(mine, f"{path}/history"), headers=theirs).status_code == 404, kind
        assert client.patch(_url(mine, path), headers=theirs, json={"value": "x"}).status_code == 404, kind
        assert client.delete(_url(mine, path), headers=theirs).status_code == 404, kind
        assert client.post(_url(mine, f"{path}/confirm"), headers=theirs).status_code == 404, kind
    assert client.get(_url(mine, f"/documents/{f.id}/entries"), headers=theirs).status_code == 404
    assert client.post(_url(mine, f"/conflicts/{issue.id}/resolve"), headers=theirs,
                       json={"answer": "keep_current"}).status_code == 404
    assert _ok(client.get(_url(mine, "/drops"), headers=theirs))["drops"] == []
    assert _ok(client.get(_url(mine), headers=theirs))["conflicts"] == []

    assert VaultItemService(db).active(ws)[0].value == {"text": "Robotics"}
    assert db.get(ProfileIssue, issue.id).status == "open"


def _domicile_card(db, ws):
    items = VaultItemService(db)
    items.apply(ws, "domicile", {"province": "sindh"}, source_type="conversation", level="stated",
                confidence=0.9, evidence={"quote": "Sindh"}, candidate_id=None)
    return items.apply(ws, "domicile", {"province": "punjab"}, source_type="conversation", level="stated",
                       confidence=0.9, evidence={"quote": "Punjab"}, candidate_id=None)


def test_writes_need_the_owner_bearer(api):
    client, db, ws = api
    item = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                           json={"type": "interest", "value": {"text": "Robotics"}}))
    card = _domicile_card(db, ws)
    db.commit()
    entry = f"/entries/item/{item['id']}"
    writes = [("post", "/entries", {"type": "interest", "value": {"text": "Chess"}}),
              ("patch", entry, {"value": {"text": "Chess"}}),
              ("post", f"{entry}/confirm", None),
              ("delete", entry, None),
              ("post", f"/conflicts/{card.issue_id}/resolve", {"answer": "keep_current"})]
    stranger = {"X-Workspace-Token": TOKEN, "Authorization": "Bearer stranger"}
    for method, path, body in writes:
        kwargs = {"json": body} if body is not None else {}
        # The machine token alone could otherwise forge a "Confirmed" the student never gave.
        assert getattr(client, method)(_url(ws, path), headers=MACHINE_ONLY, **kwargs).status_code == 403, path
        # Another signed-in account is not the owner, even holding the token.
        assert getattr(client, method)(_url(ws, path), headers=stranger, **kwargs).status_code == 403, path
        assert getattr(client, method)(_url(ws, path), headers={"Authorization": "Bearer stranger"},
                                       **kwargs).status_code == 401, path
    # Reads keep the usual rule: the token or the owner.
    assert client.get(_url(ws), headers=MACHINE_ONLY).status_code == 200
    assert client.get(_url(ws), headers={"Authorization": "Bearer owner"}).status_code == 200

    [entry_row] = _entries(_ok(client.get(_url(ws), headers=HEADERS)), "interest")
    assert entry_row["value"] == {"text": "Robotics"} and entry_row["level"] == "stated"
    assert db.get(ProfileIssue, card.issue_id).status == "open"
    assert len(db.scalars(select(MemoryCandidate)).all()) == 1


def test_item_confirm_goes_through_a_candidate_and_keeps_history(api):
    client, db, ws = api
    added = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                            json={"type": "interest", "value": {"text": "Robotics"}}))
    confirmed = _ok(client.post(_url(ws, f"/entries/item/{added['id']}/confirm"), headers=HEADERS))
    assert confirmed["id"] != added["id"]  # a new version, not an overwrite

    candidate = db.scalars(select(MemoryCandidate).where(
        MemoryCandidate.evidence["action"].as_string() == "confirm")).one()
    assert (candidate.candidate_type, candidate.source_type, candidate.input_channel, candidate.status) == (
        "vault_item", "user_explicit", "profile", "accepted")
    assert candidate.entities == {"item_id": added["id"]} and candidate.result_id == confirmed["id"]
    assert candidate.evidence["capture"] == "vault_api" and candidate.evidence["confirmation"]["value_digest"]

    history = _ok(client.get(_url(ws, f"/entries/item/{confirmed['id']}/history"), headers=HEADERS))["history"]
    assert [(h["level"], h["status"]) for h in history] == [("stated", "superseded"), ("confirmed", "active")]
    [entry] = _entries(_ok(client.get(_url(ws), headers=HEADERS)), "interest")
    assert entry["id"] == confirmed["id"] and entry["badge"] == "Confirmed"
    # A confirm against a value that changed since is refused, not applied to the new value.
    assert client.post(_url(ws, f"/entries/item/{added['id']}/confirm"), headers=HEADERS).status_code == 404


def test_confirming_an_in_question_item_is_the_students_keep_current(api):
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler

    client, db, ws = api
    first = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                            json={"type": "domicile", "value": {"province": "sindh"}}))
    competing = MemoryCandidateService(db).propose(
        ws, "vault_item", key="domicile", proposed_value={"province": "punjab"}, confidence=0.9,
        source_type="conversation", input_channel="conversation", evidence={"quote": "Punjab"})
    assert MemoryReconciler(db).reconcile(competing).outcome == "needs_review"
    db.commit()
    [card] = _ok(client.get(_url(ws), headers=HEADERS))["conflicts"]

    _ok(client.post(_url(ws, f"/entries/item/{first['id']}/confirm"), headers=HEADERS))
    issue = db.get(ProfileIssue, card["id"])
    assert issue.status == "resolved"
    assert issue.resolution["resolved_by"] == "student" and issue.resolution["action"] == "keep_current"
    db.refresh(competing)
    assert competing.status == "rejected"
    view = _ok(client.get(_url(ws), headers=HEADERS))
    assert view["conflicts"] == []
    [entry] = _entries(view, "domicile")
    assert entry["value"] == {"province": "sindh"} and entry["badge"] == "Confirmed"


def test_every_shown_record_can_be_removed_and_confirmed(api):
    client, db, ws = api
    records = StudentRecordService(db)
    common = dict(source_type="conversation", claim_origin="student", capture_method="conversation_extraction",
                  evidence={"quote": "q"})
    visa = records.apply(ws, "visa", {"country": "Germany", "visa_type": "student"}, **common)
    application = records.apply(ws, "application", {"institution_name": "TU Munich"}, **common)
    f = _file(db, ws)
    document = records.apply(ws, "document", {"file_id": f.id, "document_type": "result_card"}, **common)
    db.commit()

    _ok(client.delete(_url(ws, f"/entries/record/{visa.id}"), headers=HEADERS))
    _ok(client.post(_url(ws, f"/entries/record/{application.id}/confirm"), headers=HEADERS))
    view = _ok(client.get(_url(ws), headers=HEADERS))
    assert _entries(view, "visa") == []
    [entry] = _entries(view, "application")
    assert entry["badge"] == "Confirmed"
    # Editing stays limited to catalog types; a file's record goes with the file.
    assert client.patch(_url(ws, f"/entries/record/{application.id}"), headers=HEADERS,
                        json={"value": {"institution_name": "LMU"}}).status_code == 400
    assert client.delete(_url(ws, f"/entries/record/{document.id}"), headers=HEADERS).status_code == 400
    assert client.post(_url(ws, f"/entries/record/{document.id}/confirm"), headers=HEADERS).status_code == 400
    kinds = {c.key: c.candidate_type for c in db.scalars(select(MemoryCandidate))}
    assert kinds == {"visa": "student_record", "application": "student_record"}


def test_document_owner_answers_over_http(api):
    client, db, ws = api
    kept, accepted = _owner_card(db, ws, _file(db, ws, "a.pdf")), _owner_card(db, ws, _file(db, ws, "b.pdf"))
    db.commit()
    assert _ok(client.post(_url(ws, f"/conflicts/{kept.id}/resolve"), headers=HEADERS,
                           json={"answer": "keep_current"}))["resolved"] is True
    assert _ok(client.post(_url(ws, f"/conflicts/{accepted.id}/resolve"), headers=HEADERS,
                           json={"answer": "accept_proposed"}))["resolved"] is True
    assert db.get(ProfileIssue, kept.id).resolution["action"] == "keep_current"
    assert db.get(ProfileIssue, accepted.id).resolution["action"] == "accept_proposed"
    [job] = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "document.extract")).all()
    assert job.payload["file_id"] == accepted.affected_id and job.payload["owner_confirmed"] is True


def test_resolve_conflict_both_true(api):
    client, db, ws = api
    items = VaultItemService(db)
    items.apply(ws, "domicile", {"province": "sindh"}, source_type="conversation", level="stated",
                confidence=0.9, evidence={"quote": "Sindh"}, candidate_id=None)
    write = items.apply(ws, "domicile", {"province": "punjab"}, source_type="conversation", level="stated",
                        confidence=0.9, evidence={"quote": "Punjab"}, candidate_id=None)
    f = FileRecord(id=str(uuid.uuid4()), workspace_id=ws, filename="card.pdf", content_type="application/pdf",
                   size=10, storage_key="k/card.pdf", uploaded_by="human:user", status="active")
    db.add(f)
    owner = ProfileIssue(workspace_id=ws, issue_type="document_owner", severity="blocking",
                         affected_type="document", affected_id=f.id, summary="x",
                         clarification_question="Is this your document?",
                         evidence={"file_id": f.id, "document_names": ["Ali Khan"], "vault_names": ["Sara"]})
    db.add(owner)
    db.commit()

    # An answer the card does not offer is refused, and the card stays open.
    refused = client.post(_url(ws, f"/conflicts/{owner.id}/resolve"), headers=HEADERS,
                          json={"answer": "both_true"})
    assert refused.status_code == 400
    assert client.post(_url(ws, f"/conflicts/{write.issue_id}/resolve"), headers=HEADERS,
                       json={"answer": "provide_new"}).status_code == 400  # value required
    assert client.post(_url(ws, "/conflicts/no-such-issue/resolve"), headers=HEADERS,
                       json={"answer": "keep_current"}).status_code == 404

    result = _ok(client.post(_url(ws, f"/conflicts/{write.issue_id}/resolve"), headers=HEADERS,
                             json={"answer": "both_true"}))
    assert result["resolved"] is True and result["action"] == "both_true"
    answer = db.scalars(select(MemoryCandidate).where(MemoryCandidate.input_channel == "profile")).one()
    assert answer.evidence["capture"] == "vault_api" and answer.evidence["resolution_action"] == "both_true"

    view = _ok(client.get(_url(ws), headers=HEADERS))
    [entry] = _entries(view, "domicile")
    assert entry["value"] == {"province": "punjab"} and entry["in_question"] is False
    assert write.issue_id not in {c["id"] for c in view["conflicts"]}
    assert owner.id in {c["id"] for c in view["conflicts"]}
    history = _ok(client.get(_url(ws, f"/entries/item/{entry['id']}/history"), headers=HEADERS))["history"]
    assert {"province": "sindh"} in [h["value"] for h in history]  # the old value is kept as past


INTERNAL = {"conflict", "freshness_days", "version", "identity", "sensitivity", "onboarding", "synonyms"}


def test_catalog_has_no_internal_fields(api):
    client, _, ws = api
    catalog = _ok(client.get(_url(ws, "/catalog"), headers=HEADERS))
    types = {t["key"]: t for t in catalog["types"]}
    assert all(set(t) == {"key", "label", "storage", "shown_on", "section", "inputs", "schema", "choices"}
               for t in types.values())

    def keys(node):
        if isinstance(node, dict):
            return set(node) | {k for v in node.values() for k in keys(v)}
        if isinstance(node, list):
            return {k for v in node for k in keys(v)}
        return set()
    # Schemas may name a property "identity"-like words; only the type level is checked for those.
    assert not INTERNAL & {k for t in types.values() for k in t}
    assert not {"synonyms"} & keys(catalog)

    budget = types["finance.budget"]
    assert budget["storage"] == "fact" and budget["section"] == "money_and_place"
    assert {"code": "3_6_lakh", "label": "3-6 lakh"} in budget["choices"]["band"]
    assert budget["schema"]["properties"]["band"]["enum"]  # the active field definition's schema
    assert types["interest"]["schema"]["properties"]["text"]
    assert types["skill"]["schema"]["required"] == ["name"]


def test_budget_band_through_api(api):
    client, db, ws = api
    saved = _ok(client.post(_url(ws, "/entries"), headers=HEADERS, json={
        "type": "finance.budget",
        "value": {"band": "3_6_lakh", "period": "per_year", "covers": "fees_only"}}))
    assert saved["kind"] == "fact"
    view = _ok(client.get(_url(ws), headers=HEADERS))
    [entry] = view["details"]["money_and_place"]["entries"]
    assert entry["type"] == "finance.budget" and entry["badge"] == "Stated"
    assert entry["value"]["band"] == "3_6_lakh"
    assert "3-6 lakh" in entry["display"] and "3_6_lakh" not in entry["display"]


def test_rejected_values_are_400_and_logged_for_the_owner(api):
    client, db, ws = api
    assert client.post(_url(ws, "/entries"), headers=HEADERS,
                       json={"type": "no.such.type", "value": "x"}).status_code == 400
    assert client.post(_url(ws, "/entries"), headers=HEADERS,
                       json={"type": "interest", "value": {"text": "x", "extra": 1}}).status_code == 400
    empty = client.post(_url(ws, "/entries"), headers=HEADERS, json={"type": "finance.budget", "value": {}})
    assert empty.status_code == 400 and "empty_budget" in empty.text
    assert client.patch(_url(ws, "/entries/planet/abc"), headers=HEADERS,
                        json={"value": "x"}).status_code == 400

    drops = _ok(client.get(_url(ws, "/drops"), headers=HEADERS))["drops"]
    assert [(d["source"], d["stage"], d["reason"]) for d in drops] == [("details", "normalize", "empty_budget")]
    assert set(drops[0]) == {"id", "source", "stage", "reason", "payload", "created_at"}
    later = _ok(client.get(_url(ws, "/drops") + "&since=2999-01-01T00:00:00Z", headers=HEADERS))["drops"]
    assert later == []
    since = _ok(client.get(_url(ws, "/drops") + "&since=2000-01-01T00:00:00Z", headers=HEADERS))["drops"]
    assert [d["reason"] for d in since] == ["empty_budget"]
    assert client.get(_url(ws, "/drops") + "&since=yesterday", headers=HEADERS).status_code == 422
    assert db.scalars(select(VaultDrop)).first() is not None


def test_document_entries(api):
    client, db, ws = api
    f = FileRecord(id=str(uuid.uuid4()), workspace_id=ws, filename="card.pdf", content_type="application/pdf",
                   size=10, storage_key="k/card.pdf", uploaded_by="human:user", status="active")
    db.add(f)
    db.flush()
    VaultItemService(db).apply(ws, "domicile", {"province": "sindh"}, source_type="document", level="shown",
                               confidence=0.9, evidence={"file_id": f.id, "quote": "SECRET", "locator": "p2"},
                               candidate_id=None)
    db.commit()
    entries = _ok(client.get(_url(ws, f"/documents/{f.id}/entries"), headers=HEADERS))["entries"]
    assert [(e["type"], e["document"]["page"]) for e in entries] == [("domicile", 2)]
    assert "SECRET" not in json.dumps(entries)
    assert client.get(_url(ws, "/documents/not-a-file/entries"), headers=HEADERS).status_code == 404


def test_income_in_a_rejected_value_is_not_logged(api):
    """The normalize-stage drop is redacted too, for any caller of propose
    (the Vault page refuses income before this, so propose is called directly)."""
    from app.memory.candidates import MemoryCandidateService
    from app.memory.errors import MemoryDataError

    client, db, ws = api
    with pytest.raises(MemoryDataError):
        MemoryCandidateService(db).propose(
            ws, "vault_fact", key="finance.budget", proposed_value={"covers": "fees_only"},
            source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            evidence={"quote": "Abba ki income 80000 hai, fees only"})
    db.rollback()
    [drop] = _ok(client.get(_url(ws, "/drops"), headers=HEADERS))["drops"]
    assert drop["reason"] == "empty_budget"
    assert drop["payload"] == {"key": "finance.budget", "reason": "empty_budget"}
    assert "80000" not in json.dumps(drop)


INCOME_REFUSED = "Household income isn't stored. You can add an approximate study budget instead."


def _income_drops(client, ws):
    return [d for d in _ok(client.get(_url(ws, "/drops"), headers=HEADERS))["drops"]
            if d["reason"] == "household_income"]


def test_household_income_is_refused_roman_urdu(api):
    client, db, ws = api
    refused = client.post(_url(ws, "/entries"), headers=HEADERS, json={
        "type": "pressure", "value": {"text": "Abba ki tankhwah 40000 hai"}})
    assert refused.status_code == 400 and refused.json()["message"] == INCOME_REFUSED
    assert VaultItemService(db).active(ws) == []
    assert db.scalars(select(MemoryCandidate)).all() == []
    [drop] = _income_drops(client, ws)
    assert drop["payload"] == {"key": "pressure", "reason": "household_income"}
    assert "40000" not in json.dumps(drop)


def test_household_income_is_refused_english_and_on_edit(api):
    client, db, ws = api
    refused = client.post(_url(ws, "/entries"), headers=HEADERS, json={
        "type": "finance.budget", "value": {"amount": 30000, "currency": "PKR", "period": "per_month"},
        "text": "My father's salary is 30000 a month"})
    assert refused.status_code == 400 and refused.json()["message"] == INCOME_REFUSED
    member = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                             json={"type": "family_member", "value": {"relation": "father"}}))
    edited = client.patch(_url(ws, f"/entries/item/{member['id']}"), headers=HEADERS, json={
        "value": {"relation": "father", "occupation": "Teacher, his income is 50000 per month"}})
    assert edited.status_code == 400 and edited.json()["message"] == INCOME_REFUSED
    [entry] = _entries(_ok(client.get(_url(ws), headers=HEADERS)), "family_member")
    assert entry["value"] == {"relation": "father"}
    assert _entries(_ok(client.get(_url(ws), headers=HEADERS)), "finance.budget") == []
    drops = _income_drops(client, ws)
    assert len(drops) == 2 and "30000" not in json.dumps(drops) and "50000" not in json.dumps(drops)


def test_a_study_budget_is_still_accepted(api):
    client, db, ws = api
    saved = _ok(client.post(_url(ws, "/entries"), headers=HEADERS, json={
        "type": "finance.budget", "value": {"band": "3_6_lakh", "period": "per_year", "covers": "fees_only"},
        "text": "We can spend about 3 to 6 lakh a year on fees"}))
    assert saved["saved"] is True
    [entry] = _entries(_ok(client.get(_url(ws), headers=HEADERS)), "finance.budget")
    assert entry["value"]["band"] == "3_6_lakh"
    assert _income_drops(client, ws) == []
