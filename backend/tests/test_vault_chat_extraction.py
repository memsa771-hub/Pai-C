# -*- coding: utf-8 -*-
"""Chat extraction writes every catalog type, and every drop is logged.

Fake model output only: the real handler, normalizer and reconciler run on an
isolated SQLite student.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.memory import extractor
from app.memory.catalog import vault_catalog
from app.memory.extractor import ExtractionOutput, SYSTEM_PROMPT, extract_candidates
from app.memory.student_records import StudentRecordService
from app.models import VaultDrop, VaultItem
from scripts.eval import vault_golden
from scripts.eval_vault import VaultSession


def _item(key, value, quote, **extra):
    return {"candidate_type": "vault_item", "operation": "upsert", "key": key,
            "proposed_value": value, "quote": quote, "confidence": 0.9, **extra}


async def _run_turns(turns, outputs):
    """Each turn through the real extract -> reconcile jobs; returns the session's state."""
    index = {"value": 0}

    async def fake_model(**kwargs):
        assert turns[index["value"]] in kwargs["messages"][0]["content"]
        return json.dumps({"candidates": outputs[index["value"]]})

    with VaultSession() as student, \
            patch.object(extractor, "chat_completion", fake_model), \
            patch.object(extractor, "_model_config", return_value=("test", "test", None)):
        events = []
        for i, text in enumerate(turns):
            index["value"] = i
            events.append(student.student_message(text))
            await student.extract_and_reconcile()
        with student.factory() as db:
            items = db.scalars(select(VaultItem).where(VaultItem.workspace_id == student.workspace_id,
                                                       VaultItem.status == "active")).all()
            drops = db.scalars(select(VaultDrop).where(VaultDrop.workspace_id == student.workspace_id)).all()
            goals = StudentRecordService(db).list(student.workspace_id, "goal")
            return SimpleNamespace(
                items=[SimpleNamespace(type=i.item_type, value=i.value, level=i.level, evidence=i.evidence)
                       for i in items],
                drops=[SimpleNamespace(source=d.source, stage=d.stage, reason=d.reason,
                                       payload=d.payload, source_ref=d.source_ref) for d in drops],
                goals=goals, events=events)


def _by_type(state, item_type):
    return [i for i in state.items if i.type == item_type]


@pytest.mark.asyncio
async def test_items_extracted_from_roman_urdu_turn():
    case = next(c for c in vault_golden.load_cases() if c["id"] == "ru-myth-options-certainty")
    # The golden case has no family; a third Roman Urdu turn adds a parent and an interest.
    turns = [*case["turns"], "Abbu chahte hain main engineer banoon. Mujhe robotics bohat pasand hai."]
    outputs = [
        [_item("myth", {"text": "Computer science is only coding and there are no jobs",
                        "about": "Computer science"},
               "Log kehte hain computer science mein sirf coding hoti hai aur naukri nahi milti")],
        [_item("certainty", {"score": 3, "about": "What to do next"}, "Main 10 mein se 3 sure hoon"),
         _item("option", {"text": "Design", "status": "considering"}, "Design ya CS soch raha hoon"),
         _item("option", {"text": "Computer science", "status": "considering"}, "Design ya CS soch raha hoon")],
        [_item("family_member", {"relation": "Abbu", "wish": "Wants the student to become an engineer"},
               "Abbu chahte hain main engineer banoon"),
         _item("interest", {"text": "Robotics"}, "Mujhe robotics bohat pasand hai")],
    ]
    state = await _run_turns(turns, outputs)

    assert [i.value["score"] for i in _by_type(state, "certainty")] == [3]
    assert {i.value["text"] for i in _by_type(state, "option")} == {"Design", "Computer science"}
    assert "coding" in _by_type(state, "myth")[0].value["text"]
    father = _by_type(state, "family_member")
    assert len(father) == 1 and father[0].value["relation"] == "father"
    interest = _by_type(state, "interest")[0]
    assert interest.value == {"text": "Robotics"} and interest.level == "stated"
    # English value, original words kept as the quote.
    assert interest.evidence["quote"] == "Mujhe robotics bohat pasand hai"
    assert interest.evidence["source_language"] == "roman_ur"
    assert state.goals == []  # a certainty rating and options are never goals
    assert state.drops == []


@pytest.mark.asyncio
async def test_unknown_item_type_is_dropped_and_logged():
    text = "Mujhe cricket pasand hai aur main 10 mein se 15 sure hoon"
    outputs = [[
        _item("hobby", {"text": "Cricket"}, "Mujhe cricket pasand hai"),
        _item("certainty", {"score": 15}, "10 mein se 15 sure hoon"),
        _item("interest", {"text": "Cricket"}, "Mujhe cricket pasand hai"),
    ]]
    state = await _run_turns([text], outputs)

    assert [i.value for i in state.items] == [{"text": "Cricket"}]
    assert len(state.drops) == 2
    assert all((d.source, d.stage, d.source_ref) == ("chat", "extract", state.events[0]) for d in state.drops)
    assert any("certainty" in d.reason for d in state.drops)
    hobby = next(d for d in state.drops if "hobby" in d.reason)
    assert hobby.payload["key"] == "hobby" and hobby.payload["proposed_value"] == {"text": "Cricket"}


@pytest.mark.asyncio
async def test_inferred_flag_reaches_evidence():
    text = "Maine school ka science fair jeeta aur robot banaya"
    outputs = [[
        _item("strength", {"text": "Building things", "basis": "Won the school science fair with a robot"},
              "Maine school ka science fair jeeta aur robot banaya", inferred=True),
    ]]
    state = await _run_turns([text], outputs)

    strength = _by_type(state, "strength")[0]
    assert strength.evidence["inferred"] is True
    assert strength.level == "inferred"


def test_prompt_mentions_every_item_type():
    catalog = vault_catalog()
    for spec in catalog.types(storage="item"):
        assert f"- {spec.key}:" in SYSTEM_PROMPT, spec.key
        for field_name in spec.schema["properties"]:
            assert field_name in SYSTEM_PROMPT, (spec.key, field_name)
    for code in ("father", "mother", "grandparent", "punjab", "hafiz_e_quran"):
        assert code in SYSTEM_PROMPT
    for spec in catalog.types(storage="record"):
        assert spec.key in SYSTEM_PROMPT, spec.key
    assert '"inferred": true' in SYSTEM_PROMPT
    assert "household" in SYSTEM_PROMPT and "income" in SYSTEM_PROMPT
    assert "goes to finance.budget" in SYSTEM_PROMPT
    assert "pressure item with kind money and no number" in SYSTEM_PROMPT
    assert "status considering|ruled_out" in SYSTEM_PROMPT
    assert "PAI's own interpretations only with" in SYSTEM_PROMPT
    assert "doubt or confusion" in SYSTEM_PROMPT
    assert "<code" not in SYSTEM_PROMPT and "<enum" not in SYSTEM_PROMPT
    assert "Latin script" in SYSTEM_PROMPT and "verbatim" in SYSTEM_PROMPT
    # The old Truth Map bans are gone.
    assert "Motivations, drivers" not in SYSTEM_PROMPT
    assert "it belongs to the Truth Map" not in SYSTEM_PROMPT


def _turn(text):
    return SimpleNamespace(user_text=text, user_event_id="evt", records={}, vault={},
                           existing_memories=[], recent=[], assistant_text="", is_empty=lambda: False)


async def _extract(text, candidates, keys=("finance.budget",)):
    with patch.object(extractor, "chat_completion", return_value=json.dumps({"candidates": candidates})), \
            patch.object(extractor, "_model_config", return_value=("test", "test", None)):
        return await extract_candidates(_turn(text), set(keys), [])


@pytest.mark.asyncio
async def test_budget_range_must_be_in_the_students_words():
    text = "Hum saal ka 2 se 3 lakh de sakte hain."
    budget = {"candidate_type": "vault_fact", "key": "finance.budget", "quote": "2 se 3 lakh",
              "confidence": 0.9}
    out = await _extract(text, [
        {**budget, "proposed_value": {"min": 200000, "max": 300000, "currency": "PKR", "period": "per_year"}},
        {**budget, "proposed_value": {"min": 500000, "currency": "PKR"}},
    ])
    assert isinstance(out, ExtractionOutput)
    assert [c.proposed_value.get("min") for c in out.candidates] == [200000]
    assert len(out.drops) == 1 and "min" in out.drops[0]["reason"]


def _budget(quote, amount, period="per_month"):
    return {"candidate_type": "vault_fact", "key": "finance.budget", "quote": quote, "confidence": 0.9,
            "proposed_value": {"amount": amount, "currency": "PKR", "period": period}}


@pytest.mark.asyncio
@pytest.mark.parametrize("text,amount", [
    ("Abbu ki tankhwah 80 hazar hai", 80000),
    ("Abbu ki tankhwa 80 hazar", 80000),
    ("Family earns 1 lakh a month", 100000),
    ("Father makes 80,000 a month", 80000),
    ("Ammi ki pension 30 hazar aati hai", 30000),
])
async def test_income_in_the_quote_drops_money_facts_and_family(text, amount):
    out = await _extract(text, [
        _budget(text, amount),
        _item("family_member", {"relation": "father", "occupation": "Teacher"}, text),
        _item("pressure", {"text": "Money is tight", "kind": "money"}, text),
    ])
    assert out.candidates == []
    assert [d["reason"] for d in out.drops] == ["household_income"] * 3
    for d in out.drops:
        # The figure never reaches the drop log: no value, no quote.
        assert set(d["payload"]) == {"candidate_type", "key", "reason"}
        assert not any(ch.isdigit() for ch in json.dumps(d["payload"]))


@pytest.mark.asyncio
async def test_money_for_study_is_kept():
    text = "Mere paas fees ke liye 3 lakh hain"
    out = await _extract(text, [_budget(text, 300000, "total")])
    assert [c.key for c in out.candidates] == ["finance.budget"] and out.drops == []


@pytest.mark.asyncio
async def test_family_member_figure_is_stripped():
    text = "Abbu dukandar hain, mahine ka 50 hazar"
    out = await _extract(text, [_item("family_member", {
        "relation": "father", "occupation": "Shopkeeper, about 50,000 a month",
        "wish": "Wants me to study medicine"}, text)])
    assert [c.proposed_value for c in out.candidates] == [
        {"relation": "father", "wish": "Wants me to study medicine"}]


@pytest.mark.asyncio
async def test_students_own_pay_and_low_income_are_not_income_drops():
    text = ("Main shop par cashier hoon, meri tankhwah 20 hazar hai. Main low-income families ke bachon "
            "ko parhata hoon. We are a low income family, 3 lakh se zyada fees afford nahi kar sakte")
    out = await _extract(text, [
        {"candidate_type": "student_record", "key": "work_experience", "confidence": 0.9,
         "quote": "Main shop par cashier hoon, meri tankhwah 20 hazar hai",
         "proposed_value": {"organization": "Shop", "role": "Cashier",
                            "details": {"responsibilities": ["Paid a salary of 20,000 a month"]}}},
        {"candidate_type": "student_record", "key": "activity", "confidence": 0.9,
         "quote": "Main low-income families ke bachon ko parhata hoon",
         "proposed_value": {"title": "Teaches children from low-income families", "activity_type": "volunteering"}},
        _item("pressure", {"text": "Low income family", "kind": "money"}, "We are a low income family"),
        # An affordability limit is a budget clue, not income (ruling M1).
        _item("pressure", {"text": "Cannot afford fees above 3 lakh", "kind": "money"},
              "3 lakh se zyada fees afford nahi kar sakte"),
    ], keys=())
    assert [c.key for c in out.candidates] == ["work_experience", "activity", "pressure", "pressure"]
    assert out.drops == []


@pytest.mark.asyncio
async def test_drops_reach_the_vault_drop_log_without_the_income_figure():
    text = "Abbu ki tankhwah 85 hazar hai. Mujhe robotics pasand hai"
    outputs = [[
        _budget("Abbu ki tankhwah 85 hazar hai", 85000),
        _item("interest", {"text": "Chess"}, "I love chess"),
        _item("interest", {"text": "Robotics"}, "Mujhe robotics pasand hai"),
    ]]
    state = await _run_turns([text], outputs)
    assert [i.value for i in state.items] == [{"text": "Robotics"}]
    by_reason = {d.reason: d for d in state.drops}
    assert set(by_reason) == {"household_income", "quote not found in the student's message"}
    income = by_reason["household_income"]
    assert income.payload == {"candidate_type": "vault_fact", "key": "finance.budget",
                              "reason": "household_income"}
    assert "85" not in json.dumps([income.reason, income.payload])
    assert by_reason["quote not found in the student's message"].payload["proposed_value"] == {"text": "Chess"}


@pytest.mark.asyncio
async def test_candidates_over_the_limit_are_logged_not_silently_cut():
    text = "I like robotics"
    many = [_item("interest", {"text": f"Robotics {i}"}, "I like robotics") for i in range(extractor.MAX_CANDIDATES + 2)]
    out = await _extract(text, many)
    assert len(out.candidates) == extractor.MAX_CANDIDATES
    assert [d["reason"] for d in out.drops] == ["over_candidate_limit"] * 2


def test_primary_interest_is_not_a_chat_input():
    # Interests from chat are interest items; the catalog must agree with the extractor.
    assert "chat" not in vault_catalog().type("career.primary_interest").inputs


def test_money_kinds_come_from_the_catalog_and_the_view_data(monkeypatch):
    """Where a household's money could land is data: catalog `money` flags and
    vault_view.json's uncatalogued records, never a set in the extractor."""
    from app.memory import vault_view
    kinds = extractor.money_kinds()
    assert {"financial_sponsor", "scholarship_application", "family_member", "pressure",
            "finance.budget", "finance.funding_status", "finance.scholarship_interest"} <= kinds
    assert not hasattr(extractor, "_INCOME_GUARDED_RECORDS")
    raw = {"candidate_type": "student_record", "key": "application", "confidence": 0.9,
           "quote": "Abbu ki tankhwah 80 hazar hai", "proposed_value": {"notes": "80 hazar"}}
    assert not extractor.states_household_income(raw, ())
    copy = json.loads(json.dumps(vault_view.view_copy()))
    copy["uncatalogued_records"]["application"]["money"] = True
    monkeypatch.setattr(vault_view, "view_copy", lambda: copy)
    assert extractor.states_household_income(raw, ())
