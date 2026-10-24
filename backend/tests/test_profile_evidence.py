"""Evidence levels follow the canonical rules, and the student's evidence cards keep restricted facts out."""
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.memory.evidence import evidence_level, value_digest
from app.pai_c.memory import MemoryService
from tests.http_student import api


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


def test_model_cannot_claim_confirmed_or_shown():
    value = {"qualification_name": "A qualification"}
    row = {"source_type": "conversation", "capture_method": "profile_confirmation", "evidence": {
        "evidence_level": "confirmed", "confirmation": {"value_digest": value_digest(value), "confirmed_at": "now"}}}
    assert evidence_level(row, value) == "stated"
    row = {"source_type": "document", "evidence": {"authority": "student_authored", "file_id": "file"}}
    assert evidence_level(row, value) == "stated"
    row["evidence"]["authority"] = "institution_issued"
    assert evidence_level(row, value) == "shown"


def test_profile_cards_keep_restricted_facts_out(api):
    """The cards feed the data export and the path analyzer: no passport number in either."""
    _, db, workspace = api
    seed(db, workspace, "education")
    candidate = MemoryCandidateService(db).propose(workspace, "vault_fact", key="identity.passport_number",
        proposed_value="private-number", confidence=1, source_type="user_explicit", allow_user_explicit=True,
        evidence={"quote": "private-number"})
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()
    cards = MemoryService(db).profile_cards(workspace)
    assert [card["kind"] for card in cards] == ["education"]
    assert "private-number" not in str(cards)
    assert cards[0]["evidence_level"] == "stated" and cards[0]["source"]["quote"]
