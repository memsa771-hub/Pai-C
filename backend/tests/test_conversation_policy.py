"""Offline controller policy, causal signals and classifier contracts."""
import asyncio
import json
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.config import config
from app.pai_c.policy import controller, classifier
from app.pai_c.policy.state import derive_state, decision_log


@pytest.fixture(autouse=True)
def strict_policy_mode(monkeypatch):
    """These contracts describe the strict decision table."""
    monkeypatch.setattr(config, "PAI_POLICY_MODE", "strict")


def state(**changes):
    base = {**classifier.fallback_signals().model_dump(), "coverage": {
        area: {"covered": True} for area in controller.load_data("areas_policy.json")["priority"]},
        "student_count": 10, "mirror_allowed": False, "summary_due": False,
        "invite_pending": False, "insight_available": False,
        "questions_in_last_two": False, "short_reply_streak": 0, "previous": {}, "question_needed": True}
    return {**base, **changes}


@pytest.mark.parametrize("changes,rule,action,question", [
    ({"safety":{"level":"concern"},"intent":"pushback"}, "care", "care", False),
    ({"intent":"pushback","mirror_allowed":True}, "adjust", "adjust", True),
    ({"intent":"asking_info","request":{"needs_context":False}}, "answer", "answer_request", False),
    ({"intent":"deciding","mirror_allowed":True}, "guide", "guide", True),
    ({"mirror_allowed":True,"summary_due":True}, "mirror", "mirror", False),
    ({"summary_due":True,"emotion":"stressed"}, "summarize", "summarize", True),
    ({"emotion":"stressed","questions_in_last_two":True}, "listen", "listen_reflect", False),
    ({"questions_in_last_two":True,"coverage":{},"question_needed":False}, "default", "listen_reflect", False),
    ({"short_reply_streak":2,"coverage":{}}, "choice", "ask_choice", True),
    ({"coverage":{}}, "ask", "ask", True),
    ({}, "default", "listen_reflect", False),
])
def test_every_first_match_row_and_priority(changes,rule,action,question):
    result = controller.decide(state(**changes))
    assert (result.rule_id,result.action,result.question_allowed) == (rule,action,question)


def test_data_edits_change_decisions(tmp_path,monkeypatch):
    for name in ("decision_table.json","areas_policy.json"):
        shutil.copyfile(controller.POLICY_DIR/name,tmp_path/name)
    monkeypatch.setattr(controller,"POLICY_DIR",tmp_path)
    assert controller.decide(state(coverage={})).topic == "status"
    path=tmp_path/"areas_policy.json"; data=json.loads(path.read_text());data["priority"].reverse();path.write_text(json.dumps(data))
    assert controller.decide(state(coverage={})).topic == "options"
    path=tmp_path/"decision_table.json";data=json.loads(path.read_text());data["rows"][0]["when"]=True;path.write_text(json.dumps(data))
    assert controller.decide(state(coverage={})).action == "care"


def test_area_gating_mentions_priority_and_decline_cooldown():
    sample=state(coverage={},student_count=1)
    assert controller.askable_areas(sample)==["status","interests","history","values","strengths","sure","goals","options"]
    sample["mentioned_areas"]=["pressures","family_social"]
    assert controller.askable_areas(sample)[:2]==["family_social","pressures"]
    sample["mentioned_areas"]=[];sample["previous_mentioned_areas"]=["pressures"]
    assert controller.askable_areas(sample)[0]=="pressures"
    sample.update(student_count=13,declined_at={"status":2})
    assert "status" not in controller.askable_areas(sample)
    sample["student_count"]=14
    assert "status" in controller.askable_areas(sample)


@pytest.mark.parametrize("action,available,expected", [
    ("listen_reflect",False,"listen_reflect"),("listen_reflect",True,"insight"),
    ("insight",True,"listen_reflect")])
def test_no_repeat_never_turns_a_statement_into_question(action,available,expected):
    sample=state(coverage={},questions_in_last_two=True,insight_available=available,
                 previous={"action":action,"topic":None}, question_needed=False)
    if action=="listen_reflect":sample["emotion"]="stressed"
    result=controller.decide(sample)
    assert result.action==expected and not result.question_allowed
    assert result.rule_id.endswith("+no_repeat") == (action!=expected)


@pytest.mark.parametrize("action",["ask","ask_choice"])
def test_repeated_ask_changes_area_then_falls_back_without_question(action):
    sample=state(coverage={},short_reply_streak=2 if action=="ask_choice" else 0,
                 previous={"action":action,"topic":"status"})
    result=controller.decide(sample)
    assert result.topic=="interests" and result.action==action and result.question_allowed
    sample["coverage"]={a:{"covered":a!="status"} for a in controller.load_data("areas_policy.json")["priority"]}
    for available in (False,True):
        sample["insight_available"]=available
        result=controller.decide(sample)
        assert result.action==("insight" if available else "listen_reflect") and not result.question_allowed


@pytest.mark.parametrize("action,changes",[("care",{"safety":{"level":"urgent"}}),
    ("mirror",{"mirror_allowed":True}),("guide",{"intent":"deciding"}),
    ("answer_request",{"intent":"asking_task","request":{"needs_context":True}})])
def test_no_repeat_exemptions(action,changes):
    result=controller.decide(state(**changes,previous={"action":action,"topic":"request" if action=="answer_request" else None}))
    assert result.action==action and "+no_repeat" not in result.rule_id


@pytest.mark.parametrize("action",["adjust","summarize"])
def test_repeated_adjust_and_summary(action):
    sample=state(coverage={},intent="pushback" if action=="adjust" else "sharing",
                 summary_due=action=="summarize",previous={"action":action,"topic":None})
    result=controller.decide(sample)
    assert result.action=="ask" and result.topic=="status" and result.question_allowed
    sample["coverage"]=state()["coverage"]
    result=controller.decide(sample)
    assert result.action==("summarize" if action=="adjust" else "listen_reflect")
    assert result.question_allowed==(action=="adjust")


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


def replay_founder():
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/"fixtures/policy/founder_test_1.json").read_text())
    prior=[]; replies=[fixture["opening"]]; ordinals={}; results=[]
    for index,turn in enumerate(fixture["turns"],1):
        event=f"s{index}";ordinals[event]=index
        signals=classifier.Signals.model_validate(turn["signals"])
        derived=derive_state(signals,coverage={area:{"covered":True} for area in turn["coverage"]},
            mirror_ready=False,plan=SimpleNamespace(give=turn["insight_candidate"]),student_count=index,
            prior_decisions=prior,replies=replies,student_ordinals=ordinals,current_event_id=event)
        decision=controller.decide(derived); results.append(decision)
        prior.append({"event_id":event,"decision":decision_log(decision,signals)})
        replies.append("Replay question?" if decision.question_allowed else "Replay statement.")
    return results


def test_founder_replay_does_not_force_question_cadence():
    # Old recorded signals do not establish a necessary follow-up. The new policy
    # must not turn uncovered fields or short replies into compulsory questions.
    rows=replay_founder()
    assert rows[4].rule_id=="adjust" and not rows[4].question_allowed
    assert all(not row.question_allowed for row in rows)
    assert [(row.rule_id,row.action,row.topic,row.question_allowed) for row in rows]==[
        ("default","listen_reflect",None,False), ("default","insight",None,False),
        ("default+no_repeat","listen_reflect",None,False), ("summarize","summarize",None,False),
        ("adjust","adjust",None,False), ("default","insight",None,False),
        ("default+no_repeat","listen_reflect",None,False)]
