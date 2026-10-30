"""Slice 7 Task 6: the Supervisor (spec S7-D8): a tool-less actor that proposes typed operations from structured plan
state only. FunctionModel only; fictional data."""

import json

from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.playbooks import load_playbook_dir
from app.os.replan.events import Event
from app.os.replan.ops import TaskRow
from app.os.replan.rules import PlanState
from app.os.replan.supervisor import build_supervisor, propose, supervisor_input

SPEC = load_agent_spec(AGENT_DIR / "supervisor.v1.yaml")
BOOK = next(b for (k, _), b in load_playbook_dir().items() if k == "germany_master")
MARKER = "IGNORE-PREVIOUS-INSTRUCTIONS-7f3"
GOOD = {"ops": [{"op": "request_from_student", "instance_key": "travel_insurance", "message": "Please buy it.",
                 "reason": "Needed for the visa."}], "summary": "Ask for the insurance."}


def state() -> PlanState:
    tasks = {"travel_insurance": TaskRow("travel_insurance", "travel_insurance", None, "waiting_student", "student",
                                         True, False, None, -2, 2, ())}
    return PlanState(plan_id=1, route_key="germany_master", programmes=["p1"], tasks=tasks, suggestions={"p1": []})


EVENTS = [Event(4, 1, None, "escalate", {"instance_key": "travel_insurance", "title": MARKER, "slot": "esc:x",
                                         "note": MARKER, "dedupe": "k"})]


def answering(args_list, seen=None):
    calls = {"n": 0}

    def fn(messages, info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append((messages, info))
        args = args_list[min(calls["n"], len(args_list) - 1)]
        calls["n"] += 1
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    return FunctionModel(fn), calls


def prompt_text(messages) -> str:
    return " ".join(str(p.content) for m in messages for p in m.parts if isinstance(p, UserPromptPart))


def test_spec():
    assert (SPEC.zone, SPEC.tier, SPEC.tools, SPEC.output) == ("actor", "strong", [], "replan_ops")
    assert SPEC.retries.output == 2 and SPEC.limits.spend_usd_per_wake == 0.20


def test_input_has_no_free_text():
    """Invariant 9: no titles, no free text from events, only structured fields."""
    text = supervisor_input(state(), EVENTS, [{"op": {"op": "skip_task"}, "why": "'x' has started"}], BOOK)
    assert MARKER not in text
    body = json.loads(text)
    assert body["tasks"][0]["key"] == "travel_insurance" and body["events"][0] == {
        "type": "escalate", "instance_key": "travel_insurance"}
    assert body["refused"] == [{"op": "skip_task", "why": "'x' has started"}]
    assert "review_visa_file" in {t["template_key"] for t in body["steps"]}


def test_valid_ops_returned():
    seen = []
    model, _ = answering([GOOD], seen)
    got = propose(build_supervisor(model, SPEC), SPEC, state(), EVENTS, [], BOOK)
    assert got.error is None and got.output.ops[0].instance_key == "travel_insurance"
    assert seen[0][1].function_tools == []  # a tool-less actor


def test_invalid_output_repaired_then_error_after_2():
    bad = {"ops": [{"op": "delete_everything", "reason": "x"}], "summary": "?"}
    model, calls = answering([bad, GOOD])
    assert propose(build_supervisor(model, SPEC), SPEC, state(), EVENTS, [], BOOK).output is not None
    model, calls = answering([bad, bad, bad, GOOD])
    got = propose(build_supervisor(model, SPEC), SPEC, state(), EVENTS, [], BOOK)
    assert got.output is None and got.error and calls["n"] == 3  # the first try and 2 repairs, no more


def test_more_than_10_ops_invalid():
    many = {"ops": [{"op": "escalate", "reason": "x"}] * 11, "summary": "?"}
    model, _ = answering([many] * 3)
    assert propose(build_supervisor(model, SPEC), SPEC, state(), EVENTS, [], BOOK).output is None


def test_supervisor_cannot_upgrade_playbook():
    up = {"ops": [{"op": "upgrade_playbook", "version": 9, "reason": "x"}], "summary": "?"}
    model, _ = answering([up] * 3)
    assert propose(build_supervisor(model, SPEC), SPEC, state(), EVENTS, [], BOOK).output is None
