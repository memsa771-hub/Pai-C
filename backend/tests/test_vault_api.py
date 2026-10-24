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

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.memory.field_definitions import VaultFieldDefinitionService
from app.memory.vault_items import VaultItemService
from app.models import FileRecord, MemoryCandidate, ProfileIssue, VaultDrop, Workspace
from scripts.eval_vault import VaultSession

TOKEN = "synthetic-test-only"  # StudentSession's workspace password_hash
HEADERS = {"X-Workspace-Token": TOKEN}
MIGRATION_116 = Path(__file__).resolve().parents[1] / "alembic/versions/116_vault_items.py"


def _budget_schema() -> dict:
    """Migration 116's ranged budget definition, which production runs on."""
    spec = importlib.util.spec_from_file_location("vault_items_116_api", MIGRATION_116)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BUDGET_SCHEMA


@pytest.fixture
def api():
    with VaultSession() as student, student.factory() as db:
        VaultFieldDefinitionService(db).upsert_definition({
            "key": "finance.budget", "category": "finance", "data_type": "object",
            "validation_schema": _budget_schema(), "sensitivity": "sensitive"})
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            yield TestClient(app), db, student.workspace_id
        finally:
            app.dependency_overrides.pop(get_db, None)


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


def test_cross_workspace_access_denied(api):
    client, db, ws = api
    saved = _ok(client.post(_url(ws, "/entries"), headers=HEADERS,
                            json={"type": "interest", "value": {"text": "Robotics"}}))
    other = Workspace(name="Someone else", owner_user_id=None, password_hash="other-token")
    db.add(other)
    db.commit()
    stranger = {"X-Workspace-Token": "other-token"}

    entry = f"/entries/item/{saved['id']}"
    calls = [
        ("get", ""), ("get", "/catalog"), ("get", "/drops"), ("get", f"{entry}/history"),
        ("get", "/documents/some-file/entries"),
        ("post", "/entries"), ("patch", entry), ("post", f"{entry}/confirm"), ("delete", entry),
        ("post", "/conflicts/some-issue/resolve"),
    ]
    body = {"type": "interest", "value": {"text": "x"}, "answer": "keep_current"}
    for method, path in calls:
        kwargs = {"json": body} if method in ("post", "patch") else {}
        # The other student's token on this student's Vault: same refusal as the Profile routes.
        assert getattr(client, method)(_url(ws, path), headers=stranger, **kwargs).status_code == 401, path
        assert getattr(client, method)(_url(ws, path), **kwargs).status_code == 401, path

    # With their own credentials, this student's entry does not exist for them.
    mine = str(other.id)
    assert client.get(_url(mine, f"{entry}/history"), headers=stranger).status_code == 404
    assert client.patch(_url(mine, entry), headers=stranger, json={"value": {"text": "x"}}).status_code == 404
    assert client.delete(_url(mine, entry), headers=stranger).status_code == 404
    assert client.post(_url(mine, f"{entry}/confirm"), headers=stranger).status_code == 404
    assert VaultItemService(db).active(ws)[0].value == {"text": "Robotics"}


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
