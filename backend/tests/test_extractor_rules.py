# -*- coding: utf-8 -*-
"""Audit #5 and #7: what chat extraction stores, through the real normalizer
and reconciler with fixed extractor output (no live calls).

#5: family and values entries in the third person; a status the student's
words put in the past is done, not planned; the student's own words about a
family member are Stated, never PAI's guess.
#7: "can't leave Lahore" / "Lahore se bahar nahi ja sakta" sets
mobility.relocation_willingness to the catalog's "no".
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.memory import extractor
from app.memory.normalize import normalize_candidate, third_person
from app.memory.student_records import StudentRecordService
from app.memory.vault import VaultService, _unwrap
from app.models import VaultItem
from scripts.eval_vault import VaultSession

DOCS = Path(__file__).resolve().parents[2] / "docs/counselor/COUNSELOR_V3_PROMPTS.md"


def _proposal(candidate_type, key, value, quote, **extra):
    return {"candidate_type": candidate_type, "operation": "upsert", "key": key,
            "proposed_value": value, "quote": quote, "confidence": 0.9, **extra}


async def _run(text, candidates):
    """One student turn through extract -> normalize -> reconcile; the state after it."""
    async def fake_model(**kwargs):
        return json.dumps({"candidates": candidates})

    with VaultSession() as student, \
            patch.object(extractor, "chat_completion", fake_model), \
            patch.object(extractor, "_model_config", return_value=("test", "test", None)):
        student.student_message(text)
        await student.extract_and_reconcile()
        with student.factory() as db:
            ws = student.workspace_id
            items = db.scalars(select(VaultItem).where(VaultItem.workspace_id == ws,
                                                       VaultItem.status == "active")).all()
            fact = VaultService(db).get_fact(ws, "mobility.relocation_willingness")
            return SimpleNamespace(
                items={i.item_type: SimpleNamespace(value=i.value, level=i.level) for i in items},
                mobility=_unwrap(fact.value) if fact is not None else None,
                records={kind: [StudentRecordService(db)._values(kind, r)
                                for r in StudentRecordService(db).list(ws, kind)]
                         for kind in ("exploration_experience",)})


def test_5_third_person_rewrites_first_person():
    assert third_person("Wants me to become an engineer") == "Wants the student to become an engineer"
    assert third_person("I want a stable income for my family") == (
        "The student wants a stable income for the student's family")
    assert third_person("Father wants him to study medicine") == "Father wants him to study medicine"


@pytest.mark.asyncio
async def test_5_family_wish_is_third_person_and_stated():
    text = "Abbu chahte hain main engineer banun, he wants me to become an engineer."
    state = await _run(text, [
        # The model wrongly marks the student's own statement as its guess and
        # writes the wish in the student's first person.
        _proposal("vault_item", "family_member",
                  {"relation": "father", "wish": "Wants me to become an engineer", "influence": "high"},
                  "Abbu chahte hain main engineer banun", inferred=True),
        _proposal("vault_item", "value", {"text": "I want a stable income"},
                  "he wants me to become an engineer"),
    ])
    father = state.items["family_member"]
    assert father.value["wish"] == "Wants the student to become an engineer"
    assert father.level == "stated"
    assert state.items["value"].value["text"] == "The student wants a stable income"


@pytest.mark.asyncio
async def test_5_a_guess_without_the_person_named_stays_a_guess():
    state = await _run("Mujhe lagta hai ghar wale khush honge.", [
        _proposal("vault_item", "family_member", {"relation": "father", "wish": "Wants the student happy"},
                  "ghar wale khush honge", inferred=True)])
    assert state.items["family_member"].level == "inferred"


def test_5_built_is_done_and_a_plan_stays_planned():
    built = normalize_candidate("student_record", "exploration_experience",
                                {"domain": "robotics", "activity_type": "project", "title": "Line-following robot",
                                 "activity_status": "planned"}, student_text="I built a line-following robot")
    assert built.value["activity_status"] == "completed"
    roman = normalize_candidate("student_record", "exploration_experience",
                                {"domain": "apps", "activity_type": "project", "title": "Quiz app",
                                 "activity_status": "planned"}, student_text="maine quiz app bana liya tha")
    assert roman.value["activity_status"] == "completed"
    plan = normalize_candidate("student_record", "exploration_experience",
                               {"domain": "games", "activity_type": "project", "title": "Game",
                                "activity_status": "planned"}, student_text="I will make a game next summer")
    assert plan.value["activity_status"] == "planned"


@pytest.mark.asyncio
async def test_5_built_project_is_saved_completed():
    text = "Last year I built a line-following robot for the science fair."
    state = await _run(text, [_proposal(
        "student_record", "exploration_experience",
        {"domain": "robotics", "activity_type": "project", "title": "Line-following robot",
         "activity_status": "planned"}, "I built a line-following robot")])
    [project] = state.records["exploration_experience"]
    assert project["activity_status"] == "completed"


def test_7_cant_leave_reads_as_the_catalog_no():
    for value, quote in (("can't leave Lahore", "I can't leave Lahore"),
                         ("Lahore se bahar nahi ja sakta", "Lahore se bahar nahi ja sakta"),
                         ("No", "No, I cannot move")):
        result = normalize_candidate("vault_fact", "mobility.relocation_willingness", value, student_text=quote)
        assert result.value == "no", (value, result.value)


@pytest.mark.asyncio
async def test_7_cant_leave_lahore_sets_relocation_willingness_even_when_the_model_only_saves_the_city():
    text = "Main Lahore se bahar nahi ja sakta, ammi akeli hain."
    state = await _run(text, [_proposal("vault_fact", "location.current_city", "Lahore",
                                        "Main Lahore se bahar nahi ja sakta")])
    assert state.mobility == "no"


@pytest.mark.asyncio
async def test_7_model_phrase_value_becomes_the_code():
    state = await _run("I can't leave Lahore.", [_proposal(
        "vault_fact", "mobility.relocation_willingness", "can't leave Lahore", "I can't leave Lahore")])
    assert state.mobility == "no"


def test_5_7_extractor_prompt_states_the_rules_and_is_documented_verbatim():
    prompt = (Path(extractor.__file__).with_name("prompts") / "extractor.md").read_text(encoding="utf-8").rstrip()
    for line in ('"Wants the student to become an engineer", never "wants me to become an engineer"',
                 '"I built a line-following robot" or "maine app banaya" is completed',
                 "always mobility.relocation_willingness with the code no",
                 "so it never carries \"inferred\""):
        assert line in prompt
    if not DOCS.exists():
        pytest.skip("docs are not mounted")
    section = DOCS.read_text(encoding="utf-8").split("## Memory extractor (background)", 1)[1]
    assert section.split("```text\n", 1)[1].split("\n```", 1)[0].rstrip() == prompt
