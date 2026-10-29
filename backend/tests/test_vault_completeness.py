# -*- coding: utf-8 -*-
"""Vault completeness: one list of what PAI knows and what it asks next.

Rows are written through the real stores on an isolated SQLite student; no
model calls.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.memory.candidates import MemoryCandidateService
from app.pai_c.completeness import VaultCompleteness, completeness_from, unknown_areas
from app.memory.reconciler import MemoryReconciler
from app.memory.vault_items import VaultItemService
from app.pai_c.memory import MemoryService
from app.pai_c.policy import classifier, controller
from app.pai_c.policy.state import derive_state
from scripts.counselor_eval_support import StudentSession
from tests.http_student import api, HEADERS  # noqa: F401  (fixture)

POLICY = controller.load_data("areas_policy.json")
PRIORITY = POLICY["priority"]


def _education(db, ws):
    """What onboarding leaves: the finished school record and the current one."""
    service = MemoryCandidateService(db)
    for value in ({"qualification_name": "Matric", "field_of_study": "Science", "academic_status": "completed"},
                  {"qualification_name": "FSc", "field_of_study": "Pre-Engineering", "academic_status": "current"}):
        candidate = service.propose(workspace_id=ws, candidate_type="student_record", key="education",
            proposed_value=value, confidence=0.95, source_type="user_explicit",
            evidence={"quote": "Onboarding answer"}, allow_user_explicit=True)
        assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()


def _item(db, ws, item_type, value, *, level="stated", age_days=0):
    item = VaultItemService(db).apply(ws, item_type, value, source_type="conversation", level=level,
        confidence=0.9, evidence={"quote": "Said in chat"}, candidate_id=None).item
    if age_days:
        item.observed_at = item.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    db.commit()
    return item


def test_completeness_onboarding_only():
    with StudentSession() as student, student.factory() as db:
        _education(db, student.workspace_id)
        result = VaultCompleteness(db).build(student.workspace_id)
    assert (result["known"], result["total"]) == (2, 10)
    known = {row["key"] for row in result["areas"] if row["covered"] and not row["stale"]}
    assert known == {"status", "history"}
    first = next(area for area in PRIORITY if area not in known)
    assert result["unknowns"][0] == {"area": first, "label": POLICY["labels"][first],
                                     "question_key": POLICY["questions"][first],
                                     "priority": PRIORITY.index(first) + 1}
    history = next(row for row in result["areas"] if row["key"] == "history")
    assert history["label"] == POLICY["labels"]["history"]
    assert history["question_key"] == POLICY["questions"]["history"]
    assert history["evidence"] == "stated" and history["item_count"] >= history["min_items"]


def test_stale_area_is_unknown():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "interest", {"text": "Robotics"}, age_days=400)
        _item(db, ws, "interest", {"text": "Physics"}, age_days=400)
        stale = VaultCompleteness(db).build(ws)
        row = next(row for row in stale["areas"] if row["key"] == "interests")
        assert row["covered"] and row["stale"]
        assert "interests" in [u["area"] for u in stale["unknowns"]]
        _item(db, ws, "interest", {"text": "Electronics"})
        _item(db, ws, "interest", {"text": "Drawing"})
        fresh = VaultCompleteness(db).build(ws)
    row = next(row for row in fresh["areas"] if row["key"] == "interests")
    assert row["covered"] and not row["stale"]
    assert "interests" not in [u["area"] for u in fresh["unknowns"]]
    assert fresh["known"] == stale["known"] + 1


def test_unknowns_follow_priority():
    assert set(POLICY["labels"]) == set(PRIORITY) == set(POLICY["questions"])
    coverage = {area: {"covered": False, "stale": False} for area in PRIORITY}
    coverage["goals"] = {"covered": True, "stale": False}
    coverage["sure"] = {"covered": True, "stale": True}
    result = completeness_from(coverage)
    areas = [u["area"] for u in result["unknowns"]]
    assert areas == [area for area in PRIORITY if area != "goals"]
    assert [u["priority"] for u in result["unknowns"]] == sorted(u["priority"] for u in result["unknowns"])
    assert unknown_areas(coverage) == areas
    assert result["known"] == 1


def test_vault_response_has_completeness(api):
    client, db, workspace_id = api
    response = client.get(f"/v1/vault?network={workspace_id}", headers=HEADERS)
    assert response.status_code == 200, response.text
    completeness = response.json()["data"]["completeness"]
    assert (completeness["known"], completeness["total"]) == (0, 10)
    assert [u["area"] for u in completeness["unknowns"]] == PRIORITY

    from app.models import Workspace
    from app.routers.counselor_workspace import counselor_workspace
    with StudentSession() as student, student.factory() as session:
        _education(session, student.workspace_id)
        workspace = session.get(Workspace, student.workspace_id)
        with patch("app.routers.counselor_workspace._authorized", return_value=workspace):
            data = counselor_workspace(student.workspace_id, session, None, None)["data"]
    assert data["completeness"]["known"] == 2 and "coverage" in data


def _state(coverage, **changes):
    signals = classifier.fallback_signals()
    state = derive_state(signals, coverage=coverage, mirror_ready=False, plan=None, student_count=10,
                         prior_decisions=[], replies=[], student_ordinals={}, current_event_id="e10")
    state.update(mirror_due=False, first_picture_due=False,
                 discover_available=False, possibility_id=None, relevant_myth=None,
                 open_requests=[], question_needed=True, **changes)
    return state


def test_next_question_is_first_unknown():
    with StudentSession() as student, student.factory() as db:
        _education(db, student.workspace_id)
        completeness = VaultCompleteness(db).build(student.workspace_id)
        coverage = MemoryService(db).coverage_areas(student.workspace_id)
    decision = controller.decide(_state(coverage))
    assert decision.action == "explore_area"
    assert decision.topic == completeness["unknowns"][0]["area"]

    # A covered but stale area is asked again, in its priority place.
    everything = {area: {"covered": True, "stale": False} for area in PRIORITY}
    everything["interests"] = {"covered": True, "stale": True}
    assert controller.decide(_state(everything)).topic == "interests"
    # Sensitivity still applies: a sensitive area is held back early on.
    early = {**everything, "interests": {"covered": True, "stale": False},
             "pressures": {"covered": True, "stale": True}}
    assert controller.askable_areas(_state(early, student_count=1)) == []


def test_items_in_profile_cards():
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.paths.analyzer import _evidence_index
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        interest = _item(db, ws, "interest", {"text": "Robotics"})
        guess = _item(db, ws, "value", {"text": "Helping people"}, level="inferred")
        cards = MemoryService(db).profile_cards(ws)
        index = _evidence_index(db, ws, CounselorNotebookData())
    card = next(card for card in cards if card["id"] == "item:" + interest.id)
    assert {key: card[key] for key in ("kind", "key", "value", "evidence_level")} == {
        "kind": "item", "key": "interest", "value": {"text": "Robotics"}, "evidence_level": "stated"}
    assert "item:" + guess.id not in {card["id"] for card in cards}  # a guess is not evidence
    assert "Robotics" in index["item:" + interest.id]


def test_item_evidence_renders_labels_not_codes():
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.paths.analyzer import _evidence_index
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        option = _item(db, ws, "option", {"text": "Medicine", "status": "ruled_out"})
        pressure = _item(db, ws, "pressure", {"text": "Fees are high", "kind": "money"})
        cards = {card["id"]: card for card in MemoryService(db).profile_cards(ws)}
        index = _evidence_index(db, ws, CounselorNotebookData())
    assert cards["item:" + option.id]["value"] == {"text": "Medicine", "status": "Ruled out"}
    assert index["item:" + option.id] == "Medicine, Ruled out"
    assert index["item:" + pressure.id] == "Fees are high, Money"
    text = str(cards) + str(index)
    assert "ruled_out" not in text and "'money'" not in text


def test_only_spec_item_types_are_cited():
    from app.pai_c.paths.analyzer import policy as analyzer_policy
    allowed = analyzer_policy()["evidence_item_types"]
    assert set(allowed) == {"interest", "strength", "value", "pressure", "option", "certainty",
                            "family_member", "domicile", "daily_life"}
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        quota = _item(db, ws, "quota", {"kind": "hafiz_e_quran"}).id
        myth = _item(db, ws, "myth", {"text": "Only doctors earn well"}).id
        kept = _item(db, ws, "interest", {"text": "Robotics"}).id
        ids = {card["id"] for card in MemoryService(db).profile_cards(ws)}
    assert "item:" + kept in ids
    assert not {"item:" + quota, "item:" + myth} & ids


def test_fresh_and_stale_mix_below_min_is_unknown():
    """Ruling (a): stale entries do not count toward min_items."""
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "interest", {"text": "Robotics"})
        _item(db, ws, "interest", {"text": "Physics"}, age_days=400)
        result = VaultCompleteness(db).build(ws)
    row = next(row for row in result["areas"] if row["key"] == "interests")
    assert row["covered"] and row["stale"] and row["min_items"] == 2
    assert "interests" in [u["area"] for u in result["unknowns"]]


def test_notebook_source_follows_its_vault_type_freshness():
    """Ruling (b): a notebook row in a group with a Vault type ages like that type;
    a notebook source with no Vault counterpart never goes stale."""
    from types import SimpleNamespace
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.understanding.views import coverage_areas
    from tests.truth_map_fixtures import item
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    notebook = CounselorNotebookData.model_validate({
        "self": [item(id="i1", key="interest.a", evidence="I like A", last_confirmed=old),
                 item(id="i2", key="interest.b", evidence="I like B", last_confirmed=old)],
        "world": {"social": [item(id="s1", key="social.a", evidence="My friends", last_confirmed=old),
                             item(id="s2", key="social.b", evidence="My cousins", last_confirmed=old)]}})
    result = coverage_areas(notebook, SimpleNamespace(facts={}, records={}))
    assert result["interests"]["covered"] and result["interests"]["stale"]
    assert result["family_social"]["covered"] and not result["family_social"]["stale"]
