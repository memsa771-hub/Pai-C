# -*- coding: utf-8 -*-
"""Consumers read the Vault view: counselor context, coverage and the extractor.

Rows are written through the real stores on an isolated SQLite student; model
calls are fakes.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.memory import extractor
from app.memory.catalog import vault_catalog
from app.memory.extraction_context import build_turn_context
from app.memory.vault import VaultService
from app.memory.vault_context import (
    context_policy, select_context_entries, sensitive_types_for, turn_words,
)
from app.memory.vault_items import VaultItemService
from app.memory.vault_view import VaultView
from app.models import ProfileIssue, VaultItem
from app.pai_c.deep.context import _profile, build_context
from app.pai_c.memory import MemoryService
from app.pai_c.understanding.data import DATA_DIR
from scripts.eval_vault import VaultSession
from tests.test_counselor_deep_pr3 import _turn

QUOTE = "Mujhe yeh bilkul pasand hai SECRET-QUOTE"


def _item(db, ws, item_type, value, *, level="stated", source_type="conversation"):
    write = VaultItemService(db).apply(
        ws, item_type, value, source_type=source_type, level=level, confidence=0.9,
        evidence={"quote": QUOTE, "source_language": "roman_ur"}, candidate_id=None)
    return write.item


def _age(db, item, days):
    item.observed_at = datetime.now(timezone.utc) - timedelta(days=days)
    item.created_at = item.observed_at
    db.flush()


def _ids(profile):
    return {e["id"] for e in profile["entries"]}


def test_context_includes_relevant_entry_beyond_thirty():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        robotics = _item(db, ws, "interest", {"text": "Robotics", "example": "Built a line follower"})
        _age(db, robotics, 300)  # the oldest entry: last by recency
        for n in range(40):
            _item(db, ws, "value", {"text": f"Value number {n} about helping people"})
        db.commit()

        view = VaultView(db).build(ws, include_sensitive=False)
        assert len([e for e in VaultView(db).build(ws)["story"] for e in e["entries"]]) == 41
        relevant = select_context_entries(view, "I keep thinking about robotics", budget_tokens=400)
        unrelated = select_context_entries(view, "Hello", budget_tokens=400)
        assert robotics.id in {e["id"] for e in relevant}
        assert robotics.id not in {e["id"] for e in unrelated}
        assert 0 < len(relevant) < 41  # the budget, not a count, stops it

        # Roman Urdu: "shauq" maps to interest; the word "robotics" still matches.
        assert {"interest", "robotic"} <= turn_words("mujhe robotics ka shauq hai")
        profile = _profile(db, ws, student_text="mujhe robotics ka shauq hai")
        assert robotics.id in _ids(profile)


def test_core_stale_and_in_question_come_first():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        VaultService(db).apply_fact(ws, "location.current_city", "Multan", "user_explicit")
        stale = _item(db, ws, "certainty", {"score": 4, "about": "Next step"})
        _age(db, stale, 200)  # certainty is fresh for 90 days
        for n in range(30):
            _item(db, ws, "value", {"text": f"Value number {n}"})
        db.commit()
        view = VaultView(db).build(ws, include_sensitive=False)
        chosen = select_context_entries(view, "Hello", budget_tokens=150)
        types = [e["type"] for e in chosen]
        assert types[:2] == ["location.current_city", "certainty"] and len(types) < 32

        disputed = _item(db, ws, "option", {"text": "Medicine", "status": "considering"})
        _age(db, disputed, 100)
        db.add(ProfileIssue(workspace_id=ws, issue_type="conflicting_value", severity="blocking",
                            affected_type="vault_item", affected_id=disputed.id, summary="x",
                            clarification_question="Still considering medicine?",
                            evidence={"item_type": "option", "current_value": disputed.value,
                                      "proposed_value": {"text": "Medicine", "status": "ruled_out"}}))
        db.commit()
        profile = _profile(db, ws, student_text="Hello")
        assert [e["id"] for e in profile["needs_recheck"]] == [stale.id]
        assert [e["id"] for e in profile["in_question"]] == [disputed.id]
        assert [i["type"] for i in profile["open_profile_issues"]] == ["option"]


@pytest.mark.asyncio
async def test_context_never_contains_restricted_or_quote():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        vault = VaultService(db)
        vault.apply_fact(ws, "contact.email", "hidden-student@example.test", "user_explicit")
        vault.apply_fact(ws, "identity.date_of_birth", "2007-03-09", "user_explicit")
        vault.apply_fact(ws, "identity.passport_number", "PASSPORT-XYZ-1", "user_explicit")
        vault.apply_fact(ws, "location.current_city", "Lahore", "user_explicit")
        father = _item(db, ws, "family_member", {"relation": "father", "occupation": "Shopkeeper"})
        worry = _item(db, ws, "pressure", {"text": "Fees are hard to pay", "kind": "money"})
        interest = _item(db, ws, "interest", {"text": "Painting"})
        db.commit()

        # A turn that names no sensitive topic: sensitive entries stay out.
        plain = await build_context(db, ws, _turn(student, "I like painting"))
        # A turn about family and money: those sensitive entries come in.
        needed = await build_context(db, ws, _turn(student, "Abbu kehte hain fees bohat zyada hai"))
        for context in (plain, needed):
            text = context.text
            assert "SECRET-QUOTE" not in text and QUOTE not in text
            assert "hidden-student@example.test" not in text
            assert "2007-03-09" not in text
            assert "PASSPORT-XYZ-1" not in text
            assert interest.id in text and "Lahore" in text
        assert father.id not in plain.text and worry.id not in plain.text
        assert father.id in needed.text and worry.id in needed.text
        assert '"needs_recheck"' in needed.text and '"in_question"' in needed.text


def test_sensitive_topics_are_data_and_never_restricted():
    catalog = vault_catalog()
    types = {t for topic in context_policy()["sensitive_topics"].values() for t in topic["types"]}
    for key in types:
        spec = catalog.type(key)
        assert spec is None or spec.sensitivity == "sensitive", key
    assert "family_member" in sensitive_types_for("Mere abbu doctor hain")
    assert "finance.budget" in sensitive_types_for("Kharcha kitna hoga?")
    assert sensitive_types_for("I like painting") == set()


def test_item_counts_toward_coverage():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        memory = MemoryService(db)
        before = memory.coverage_areas(ws)
        assert before["interests"]["item_count"] == 0 and before["sure"]["item_count"] == 0
        _item(db, ws, "interest", {"text": "Robotics"})
        _item(db, ws, "interest", {"text": "Cricket"})
        _item(db, ws, "certainty", {"score": 6})
        _item(db, ws, "family_member", {"relation": "mother", "wish": "Wants the student to teach"})
        _item(db, ws, "value", {"text": "Helping people"}, level="inferred")  # a guess is not coverage
        db.commit()
        after = memory.coverage_areas(ws)
        assert after["interests"]["covered"] and after["interests"]["item_count"] == 2
        assert after["sure"]["covered"]
        assert after["family_social"]["item_count"] == 1
        assert after["goals"]["covered"]  # a family member's wish
        assert after["values"]["item_count"] == 0
        assert after["interests"]["evidence"] == "stated"


def test_coverage_item_types_come_from_the_catalog():
    areas = json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8"))
    item_types = {t.key for t in vault_catalog().types(storage="item")}
    used = {t for spec in areas.values() for source in spec["sources"] for t in source.get("vault_items", [])}
    assert used and used <= item_types
    assert {"interest", "value", "family_member", "pressure", "option", "certainty"} <= used


@pytest.mark.asyncio
async def test_extractor_sees_existing_items_and_can_correct_one():
    with VaultSession() as student:
        with student.factory() as db:
            painting = _item(db, student.workspace_id, "interest", {"text": "Painting"})
            db.commit()
            painting_id = painting.id
        text = "Sorry, not painting, I meant sketching"
        seen = {}

        async def fake_model(**kwargs):
            prompt = kwargs["messages"][0]["content"]
            seen["prompt"] = prompt
            block = prompt.split("EXISTING VAULT ITEMS", 1)[1].split("\n", 1)[1].split("\n\n", 1)[0]
            target = next(e for e in json.loads(block) if e["display"] == "Painting")
            return json.dumps({"candidates": [{
                "candidate_type": "vault_item", "operation": "upsert", "key": "interest",
                "proposed_value": {"text": "Sketching"}, "quote": text, "confidence": 0.9,
                "entities": {"item_id": target["id"]},
                "attribution": {"correction": True, "correction_quote": "not painting, I meant sketching"}}]})

        with patch.object(extractor, "chat_completion", fake_model), \
                patch.object(extractor, "_model_config", return_value=("test", "test", None)):
            student.student_message(text)
            await student.extract_and_reconcile()
        assert painting_id in seen["prompt"] and "SECRET-QUOTE" not in seen["prompt"]
        with student.factory() as db:
            live = db.scalars(select(VaultItem).where(VaultItem.workspace_id == student.workspace_id,
                                                      VaultItem.status == "active")).all()
            assert [i.value for i in live] == [{"text": "Sketching"}]


def test_extractor_drops_an_item_id_not_in_its_context():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        painting = _item(db, ws, "interest", {"text": "Painting"})
        db.commit()
        event_id = student.student_message("I meant sketching")
        turn = build_turn_context(db, ws, event_id)
        assert {"type": "interest", "id": painting.id, "display": "Painting"} in turn.items
        assert len(turn.items) <= context_policy()["extraction_max_entries"]
        drops = []

        def propose(key, item_id):
            return extractor._validate({"candidate_type": "vault_item", "key": key,
                                        "proposed_value": {"text": "Sketching"}, "quote": "I meant sketching",
                                        "confidence": 0.9, "entities": {"item_id": item_id}}, turn, set(), drops)

        assert propose("interest", painting.id).entities == {"item_id": painting.id}
        assert drops == []
        # A wrong-type or unknown id drops only the id: the candidate goes on as a new item.
        for key, item_id in (("value", painting.id), ("interest", "someone-else")):
            kept = propose(key, item_id)
            assert kept is not None and kept.entities == {} and kept.proposed_value == {"text": "Sketching"}
        assert len(drops) == 2 and all("item reference" in d["reason"] for d in drops)


# ---- fix round 1 -------------------------------------------------------------

def test_notebook_and_vault_are_not_summed_in_coverage():
    """In an area that still reads both stores, the same thing in both is one,
    not two: the area counts the larger of the two sides."""
    from types import SimpleNamespace
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.understanding.views import coverage_areas
    from tests.truth_map_fixtures import STAMP, item
    notebook = CounselorNotebookData.model_validate({
        "source": [item(id="s1", key="value.helping", value="Helping people", evidence="I want to help people")]})
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        _item(db, ws, "value", {"text": "Helping people"})
        db.commit()
        areas = coverage_areas(notebook, SimpleNamespace(facts={}, records={}), VaultItemService(db).active(ws))
    assert areas["values"]["item_count"] == 1


# Areas with a Vault item source read the Vault alone; a notebook source stays
# only where the Vault has nothing that covers the same thing.
NOTEBOOK_SOURCES_KEPT = {
    "status": [], "history": ["world.education_story", "shown"], "interests": [], "strengths": [],
    "family_social": ["world.social"], "values": ["source"], "pressures": [], "sure": [], "goals": [],
    "options": [],
}


def test_vault_areas_drop_their_notebook_duplicates():
    from types import SimpleNamespace
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from app.pai_c.understanding.views import coverage_areas
    from tests.truth_map_fixtures import STAMP, item
    areas = json.loads((DATA_DIR / "areas.json").read_text(encoding="utf-8"))
    kept = {area: [s["path"] for s in spec["sources"] if "path" in s] for area, spec in areas.items()}
    assert kept == NOTEBOOK_SOURCES_KEPT
    notebook = CounselorNotebookData.model_validate({
        "world": {"people": [{"id": "p1", "role": "Father", "wish": "Doctor", "worry": "Fees",
                              "evidence": "my father", "first_seen": STAMP, "last_confirmed": STAMP}],
                  "daily_life": [item(id="d1", key="day.school", value="School then cricket")]},
        "self": [item(id="s1", key="interest.robotics", value="Robotics"),
                 item(id="s2", key="value.family", value="Family first")],
        "said": [item(id="o1", key="option.medicine", value="Medicine")],
        "pressures": {"items": [item(id="p2", key="pressure.fees", value="Fees")]},
        "sure": {"score": 6, "asked_at": STAMP}})
    coverage = coverage_areas(notebook, SimpleNamespace(facts={}, records={}), ())
    for area in ("status", "interests", "family_social", "values", "pressures", "sure", "goals", "options"):
        assert coverage[area]["item_count"] == 0, area


def _disputed_option(db, ws):
    disputed = _item(db, ws, "option", {"text": "Medicine", "status": "considering"})
    db.add(ProfileIssue(workspace_id=ws, issue_type="conflicting_value", severity="blocking",
                        affected_type="vault_item", affected_id=disputed.id, summary="x",
                        clarification_question="Still considering medicine?",
                        evidence={"item_type": "option", "current_value": disputed.value,
                                  "proposed_value": {"text": "Medicine", "status": "ruled_out"}}))
    return disputed


def test_core_records_are_capped_and_in_question_keeps_its_share():
    from app.memory.student_records import StudentRecordService
    from app.memory.vault_context import _json, context_entry, estimated_tokens
    from app.models import StudentGoal
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        for n in range(15):
            StudentRecordService(db).apply(
                ws, "education", {"qualification_name": f"Qualification {n} " + "x" * 400,
                                  "institution_name": f"School {n}"},
                source_type="conversation", claim_origin="student", capture_method="chat", force_new=True)
            db.add(StudentGoal(workspace_id=ws, goal_type="career", title=f"Goal number {n} " + "y" * 400,
                               source_type="conversation", claim_origin="student", capture_method="chat",
                               status="active"))
        disputed = _disputed_option(db, ws)
        db.commit()
        view = VaultView(db).build(ws, include_sensitive=False)
        budget = context_policy()["counselor_budget_tokens"]
        chosen = select_context_entries(view, "Hello", budget_tokens=budget)
        compact = [context_entry(e) for e in chosen]
        assert sum(estimated_tokens(_json(c)) for c in compact) <= budget
        assert disputed.id in {e["id"] for e in chosen}
        caps = context_policy()["core_caps"]
        assert sum(e["type"] == "education" for e in chosen) <= caps["education"]
        assert sum(e["type"] == "goal" for e in chosen) <= caps["goal"]
        assert all(len(c["display"]) <= 350 and "value" not in c for c in compact if c["kind"] == "record")


def test_identity_types_are_excluded_before_the_budget_is_counted():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        VaultService(db).apply_fact(ws, "identity.preferred_name", "Sana", "user_explicit")
        _item(db, ws, "interest", {"text": "Robotics"})
        db.commit()
        view = VaultView(db).build(ws, include_sensitive=False)
        only = select_context_entries(view, "Hello", budget_tokens=60,
                                      exclude_types={"identity.preferred_name"})
        assert [e["type"] for e in only] == ["interest"]


def test_ambiguous_relation_words_do_not_trigger_family():
    assert "family_member" not in sensitive_types_for("I built an API")
    assert "family_member" not in sensitive_types_for("Thanks bro")
    assert "family_member" in sensitive_types_for("mere abbu")


@pytest.mark.asyncio
async def test_family_follow_up_answer_brings_family_entries():
    from uuid import uuid4
    from app.models import EventRecord
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        father = _item(db, ws, "family_member", {"relation": "father", "wish": "Wants a doctor in the family"})
        db.add(EventRecord(id=str(uuid4()), network_id=ws, type="workspace.message.posted",
                           source="openagents:pai", target="channel/chat",
                           payload={"content": "Aap ke ghar wale aap ke liye kya chahte hain?"},
                           timestamp=student.next_timestamp()))
        db.commit()
        context = await build_context(db, ws, _turn(student, "haan woh chahte hain main doctor banun"))
        assert father.id in context.text
    # The planned area alone also names the topic.
    assert "family_member" in sensitive_types_for("haan", topics=["family_social"])


def test_citable_records_are_included_for_the_planner():
    from app.memory.student_records import StudentRecordService
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        skill = StudentRecordService(db).apply(
            ws, "skill", {"name": "Python"}, source_type="document", claim_origin="institution_document",
            capture_method="document_extraction", verification_status="document_supported",
            evidence={"file_id": "f1", "authority": "institution_issued", "quote": "Python"})
        for n in range(60):
            _item(db, ws, "value", {"text": f"Value number {n} about helping people"})
        db.commit()
        view = VaultView(db).build(ws, include_sensitive=False)
        chosen = select_context_entries(view, "Hello", budget_tokens=300)
        assert skill.id in {e["id"] for e in chosen}


def test_restricted_issue_never_reaches_the_counselor():
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        fact = VaultService(db).apply_fact(ws, "contact.email", "old@example.test", "user_explicit").fact
        db.add(ProfileIssue(workspace_id=ws, issue_type="conflicting_value", severity="blocking",
                            affected_type="vault_fact", affected_id=fact.id, summary="x",
                            clarification_question="Which email is right?",
                            evidence={"field_key": "contact.email", "current_fact_id": fact.id,
                                      "current_value": "old@example.test", "proposed_value": "new@example.test"}))
        db.commit()
        profile = _profile(db, ws, student_text="my email changed")
        assert profile["open_profile_issues"] == [] and profile["in_question"] == []
        assert "example.test" not in json.dumps(profile)


def _notebook_with_family_and_pressure():
    from app.pai_c.deep.notebook_schema import CounselorNotebookData
    from tests.truth_map_fixtures import STAMP, item
    return CounselorNotebookData.model_validate({
        "world": {"people": [{"id": "p1", "role": "Father", "relation": "parent", "wish": "NOTEBOOK-WISH",
                              "worry": "NOTEBOOK-WORRY", "evidence": "Student described him",
                              "first_seen": STAMP, "last_confirmed": STAMP}]},
        "pressures": {"items": [item("NOTEBOOK-PRESSURE", key="pressure.fees", id="pr1")]},
        "said": [item("Likes painting", key="interest.painting", id="s1")]})


def test_notebook_people_and_pressures_pass_the_vault_topic_gate():
    """Notebook people (with their wishes and worries) and pressures are as
    sensitive as the Vault's family and pressure entries, so they pass the same gate."""
    from app.pai_c.deep.context import _trim_notebook
    notebook = _notebook_with_family_and_pressure()
    plain = json.dumps(_trim_notebook(notebook, sensitive_types_for("I like painting")))
    assert "Likes painting" in plain
    assert not any(word in plain for word in ("NOTEBOOK-WISH", "NOTEBOOK-WORRY", "NOTEBOOK-PRESSURE"))
    family = json.dumps(_trim_notebook(notebook, sensitive_types_for("mere abbu kehte hain")))
    assert "NOTEBOOK-WISH" in family and "NOTEBOOK-WORRY" in family
    worried = json.dumps(_trim_notebook(notebook, sensitive_types_for("I am so worried")))
    assert "NOTEBOOK-PRESSURE" in worried and "NOTEBOOK-WISH" not in worried
    planned = json.dumps(_trim_notebook(notebook, sensitive_types_for("haan", topics=["family_social"])))
    assert "NOTEBOOK-WISH" in planned


@pytest.mark.asyncio
async def test_counselor_context_gates_the_notebook_by_the_turn():
    from app.models import CounselorNotebook
    with VaultSession() as student, student.factory() as db:
        ws = student.workspace_id
        db.add(CounselorNotebook(workspace_id=ws, version=1, last_event_id="seed",
                                 notebook=_notebook_with_family_and_pressure().storage_data()))
        db.commit()
        plain = await build_context(db, ws, _turn(student, "I like painting"))
        assert "NOTEBOOK-WISH" not in plain.text and "NOTEBOOK-PRESSURE" not in plain.text
        family = await build_context(db, ws, _turn(student, "Abbu kehte hain fees bohat zyada hai"))
        assert "NOTEBOOK-WISH" in family.text and "NOTEBOOK-PRESSURE" in family.text
