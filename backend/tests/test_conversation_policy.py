"""Offline controller policy, causal signals and classifier contracts."""
import json
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.pai_c.policy import controller, classifier
from app.pai_c.policy.state import derive_state, decision_log


def state(**changes):
    base = {**classifier.fallback_signals().model_dump(), "coverage": {
        area: {"covered": True} for area in controller.load_data("areas_policy.json")["priority"]},
        "student_count": 10, "mirror_due": False, "summary_due": False,
        "invite_pending": False, "insight_available": False,
        "questions_in_last_two": False, "short_reply_streak": 0, "previous": {}, "question_needed": True}
    return {**base, **changes}


def test_data_edits_change_decisions(tmp_path,monkeypatch):
    for source in controller.POLICY_DIR.glob("*.json"):
        shutil.copyfile(source,tmp_path/source.name)
    monkeypatch.setattr(controller,"POLICY_DIR",tmp_path)
    assert controller.decide(state(coverage={})).topic == "history"
    path=tmp_path/"areas_policy.json"; data=json.loads(path.read_text());data["priority"].reverse();path.write_text(json.dumps(data))
    assert controller.decide(state(coverage={})).topic == "interests"
    path=tmp_path/"guided_table.json";data=json.loads(path.read_text());data["rows"][0]["when"]=True;path.write_text(json.dumps(data))
    assert controller.decide(state(coverage={})).action == "care"


def test_area_gating_mentions_priority_and_decline_cooldown():
    sample=state(coverage={},student_count=1)
    assert controller.askable_areas(sample)==["history","goals","options","interests","status","sure"]
    sample["mentioned_areas"]=["pressures","family_social"]
    assert controller.askable_areas(sample)[:2]==["pressures","family_social"]
    sample["mentioned_areas"]=[];sample["previous_mentioned_areas"]=["pressures"]
    assert controller.askable_areas(sample)[0]=="pressures"
    sample.update(student_count=13,declined_at={"status":2})
    assert "status" not in controller.askable_areas(sample)
    sample["student_count"]=14
    assert "status" in controller.askable_areas(sample)


def test_derived_cadence_streak_invite_decline_and_plan():
    signals=classifier.fallback_signals().model_copy(update={"intent":"short_reply","declined_area":"pressures"})
    prior=[{"event_id":"e1","decision":{"action":"ask","invite":True,"signals":{"intent":"short_reply","mentioned_areas":["history"]}}}]
    args=dict(coverage={"history":{"covered":True},"interests":{"covered":True}},
        mirror_ready=False,plan=SimpleNamespace(give="An observation"),student_count=4,
        prior_decisions=prior,replies=["First?","Second?"],student_ordinals={"e1":3,"e2":4},current_event_id="e2")
    result=derive_state(signals,**args)
    assert result["questions_in_last_two"] and result["short_reply_streak"]==2
    assert result["summary_due"] and result["insight_available"] and not result["invite_pending"]
    assert result["declined_at"]=={"pressures":4} and result["previous_mentioned_areas"]==["history"]
    prior[0]["decision"]["action"]="summarize"
    result=derive_state(signals,**{**args,"plan":None,"replies":["Statement.","Question?"]})
    assert not result["summary_due"] and not result["questions_in_last_two"] and not result["insight_available"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw",["{}","not JSON",json.dumps({**classifier.fallback_signals().model_dump(),"extra":"private"}),
    json.dumps({**classifier.fallback_signals().model_dump(),"request":{"text":"private","kind":"task","needs_research":"false","needs_context":False}})])
async def test_classifier_strict_fallback_and_private_logging(raw,caplog):
    with patch.object(classifier,"complete",AsyncMock(return_value=raw)):
        assert await classifier.classify("private student text",[])==classifier.fallback_signals()
    assert "classifier_result status=fallback error_type=ValidationError" in caplog.text
    assert "private" not in caplog.text


def test_decision_log_never_contains_request_text():
    signals=classifier.fallback_signals().model_copy(update={"intent":"asking_info",
        "request":classifier.Request(text="private request",kind="information",needs_context=False,needs_research=False)})
    result=controller.decide(state(**signals.model_dump()))
    record=decision_log(result,signals)
    assert record["topic"]=="request" and "private request" not in json.dumps(record)
