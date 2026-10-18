"""Student-reviewed evidence follows the canonical reconciler and tenant rules."""
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.memory.evidence import evidence_level, value_digest
from app.models import MemoryCandidate
from tests.test_student_profile_api import api, HEADERS


def seed(db, workspace, kind):
    candidate = MemoryCandidateService(db).propose(workspace,
        candidate_type="vault_fact" if kind == "vault_fact" else "student_record",
        key="location.current_city" if kind == "vault_fact" else kind,
        proposed_value="A city" if kind == "vault_fact" else {"qualification_name": "My qualification"},
        confidence=1, evidence={"quote": "My own education and city"})
    result = MemoryReconciler(db).reconcile(candidate)
    assert result.accepted
    db.commit()
    return result.result_id


@pytest.mark.parametrize("kind", ["vault_fact", "education"])
def test_confirm_edit_idempotency_and_stale_values(api, kind):
    client, db, workspace = api
    seed(db, workspace, kind)
    url = f"/v1/counselor/profile-cards?network={workspace}"
    card = next(row for row in client.get(url, headers=HEADERS).json()["data"]["cards"] if row["kind"] == kind)
    assert card["evidence_level"] == "stated" and card["source"]["quote"]
    endpoint = f"/v1/counselor/profile-cards/{kind}/{card['id']}?network={workspace}"
    body = {"submission_id": str(uuid4()), "action": "confirm", "expected_digest": card["digest"]}
    for _ in range(2):
        result = client.post(endpoint, headers=HEADERS, json=body)
        assert result.status_code == 200, result.text
    cards = client.get(url, headers=HEADERS).json()["data"]["cards"]
    confirmed = next(row for row in cards if row["kind"] == kind)
    assert confirmed["evidence_level"] == "confirmed" and confirmed["value"] == card["value"]
    changes = db.scalars(select(MemoryCandidate).where(MemoryCandidate.evidence["capture"].as_string() == "profile_review")).all()
    assert len(changes) == 1 and changes[0].status == "accepted"
    endpoint = f"/v1/counselor/profile-cards/{kind}/{confirmed['id']}?network={workspace}"
    value = "A different city" if kind == "vault_fact" else {"qualification_name": "Corrected qualification"}
    edited = client.post(endpoint, headers=HEADERS, json={"submission_id": str(uuid4()), "action": "edit", "expected_digest": confirmed["digest"], "value": value, "text": "I corrected this value"})
    assert edited.status_code == 200, edited.text
    assert client.post(endpoint, headers=HEADERS, json={**body, "submission_id": str(uuid4())}).status_code == 409
    current = next(row for row in client.get(url, headers=HEADERS).json()["data"]["cards"] if row["kind"] == kind)
    assert current["value"] == value and current["evidence_level"] == "stated"
    assert client.post(endpoint, json=body).status_code == 401


def test_model_cannot_claim_confirmed_or_shown():
    value = {"qualification_name": "A qualification"}
    row = {"source_type": "conversation", "capture_method": "profile_confirmation", "evidence": {
        "evidence_level": "confirmed", "confirmation": {"value_digest": value_digest(value), "confirmed_at": "now"}}}
    assert evidence_level(row, value) == "stated"
    row = {"source_type": "document", "evidence": {"authority": "student_authored", "file_id": "file"}}
    assert evidence_level(row, value) == "stated"
    row["evidence"]["authority"] = "institution_issued"
    assert evidence_level(row, value) == "shown"


def test_restricted_facts_not_exposed(api):
    client, db, workspace = api
    candidate = MemoryCandidateService(db).propose(workspace, "vault_fact", key="identity.passport_number",
        proposed_value="private-number", confidence=1, source_type="user_explicit", allow_user_explicit=True,
        evidence={"quote": "private-number"})
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()
    response = client.get(f"/v1/counselor/profile-cards?network={workspace}", headers=HEADERS)
    assert response.status_code == 200 and "private-number" not in response.text
