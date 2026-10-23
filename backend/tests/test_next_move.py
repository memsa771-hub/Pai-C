"""Catalog-only facts, evidence and policy priority, without providers."""
import json
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from app.models import MemoryCandidate
from app.pai_c import fact_cards
from app.pai_c.policy.controller import decide, Decision
from app.pai_c.deep.turn import run_deep_turn
from tests.test_policy_guided import state
from tests.test_student_profile_api import api, HEADERS
from tests.test_counselor_deep_pr3 import _turn
from scripts.counselor_eval_support import StudentSession


def test_thread_request_safety_order_and_question_cap():
    sample = state(opened_thread="interests", coverage={}, first_picture_due=True)
    assert decide(sample).action == "follow_thread"
    sample["questions_in_last_two"] = True
    assert not decide(sample).question_allowed
    sample["request"] = {"needs_context": False}
    assert decide(sample).action == "answer_request"
    sample["safety"] = {"level": "urgent"}
    assert decide(sample).action == "care"


def test_choices_are_catalog_only_with_other(monkeypatch):
    data = fact_cards.load_data("fact_cards.json")
    data["catalogs"]["levels"] = [{"value": "Catalog level", "label": "Catalog level"}]
    monkeypatch.setattr(fact_cards, "load_data", lambda _: data)
    cards = fact_cards.available_cards(SimpleNamespace(facts={}, records={}))
    level = next(card for card in cards if card["key"] == "qualification")
    assert level["choices"] == data["catalogs"]["levels"] and level["other"]["editable"]
    assert next(card for card in cards if card["key"] == "city")["kind"] == "text"
    assert fact_cards.validated_card({"type": "collect_fact", "card_key": "qualification", "choices": ["invented"]}, cards, "") is None


def test_prefill_is_quoted_and_unconfirmed():
    cards = fact_cards.available_cards(SimpleNamespace(facts={}, records={}))
    action = {"type": "collect_fact", "card_key": "city", "value": "My city", "quote": "My city is home"}
    assert fact_cards.validated_card(action, cards, action["quote"])["prefill"]["requires_confirmation"]
    assert "prefill" not in fact_cards.validated_card(action, cards, "Different text")


def test_card_interactions_obey_two_question_cap():
    from app.pai_c.policy.state import derive_state
    from app.pai_c.policy.classifier import fallback_signals
    sample = derive_state(fallback_signals(), coverage={}, mirror_ready=False, plan=None,
        student_count=3, prior_decisions=[], replies=["A card.", "Another card."],
        reply_requested_input=[True, True], student_ordinals={}, current_event_id="third")
    assert sample["questions_in_last_two"]
    assert not decide(sample).question_allowed


def test_other_reconciles_with_stated_review_evidence_once(api):
    client, db, workspace = api
    answer = {"submission_id": str(uuid4()), "value": "My qualification", "other": True, "confirmed": True}
    url = f"/v1/counselor/fact-cards/qualification?network={workspace}"
    for _ in range(2):
        response = client.post(url, headers=HEADERS, json=answer)
        assert response.status_code == 200, response.text
    rows = db.scalars(select(MemoryCandidate)).all()
    assert len(rows) == 1 and rows[0].status == "accepted"
    assert rows[0].evidence["evidence_level"] == "stated"
    assert rows[0].evidence["catalog_review"]["student_text"] == answer["value"]
    assert client.post(url, headers=HEADERS, json={**answer, "value": "Reused id"}).status_code == 422
    assert client.post(url, json=answer).status_code == 401
    assert client.post(url, headers=HEADERS, json={**answer, "confirmed": False}).status_code == 422


@pytest.mark.asyncio
async def test_card_replaces_spoken_question_without_writing():
    with StudentSession() as student, student.factory() as db:
        model = AsyncMock(return_value=json.dumps({"reply": "Let's capture that. What qualification?", "action": {"type": "collect_fact", "card_key": "qualification"}}))
        with patch("app.pai_c.deep.turn.chat_completion", model):
            result = await run_deep_turn(db, _turn(student), history=[], decision=Decision("explore_area", "explore_area", "status", True, False, False))
        assert result.reply == "Let's capture that." and model.await_count == 1
        assert "card_question_removed" in result.guard_violations
        assert not db.scalars(select(MemoryCandidate)).all()


def test_inline_presentation_obeys_policy_and_care_priority():
    from app.pai_c.fact_cards import presentation_card
    decision=SimpleNamespace(action='explore_area',topic='sure',question_allowed=True)
    assert presentation_card(decision)=={'kind':'rating','min':0,'max':10}
    assert presentation_card(decision,safety_flagged=True) is None
    decision.question_allowed=False
    assert presentation_card(decision) is None
    decision.action='first_picture'
    assert presentation_card(decision)=={'kind':'first_picture'}
