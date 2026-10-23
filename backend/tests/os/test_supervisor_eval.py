"""Slice 7 Task 10: the Supervisor evaluation harness (spec §8). It is billed, so these tests never call a model:
they check that it refuses without the owners' OK, that the 20 cases load, and that grading works."""

import importlib.util
from pathlib import Path

import yaml

from app.os.playbooks import load_playbook_dir
from app.os.replan.ops import Escalate, RequestFromStudent, SkipTask

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "os_supervisor_eval.py"
spec = importlib.util.spec_from_file_location("os_supervisor_eval", SCRIPT)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
BOOK = next(b for (k, _), b in load_playbook_dir().items() if k == "germany_master")
CASES = yaml.safe_load(ev.DEFAULT_CASES.read_text(encoding="utf-8"))


def test_refuses_without_the_owners_ok(capsys):
    assert ev.main([]) == 2
    assert "billed" in capsys.readouterr().err


def test_twenty_cases_build():
    assert len(CASES) == 20 and len({c["id"] for c in CASES}) == 20
    for case in CASES:
        state, events = ev.case_state(case)
        assert state.tasks and events


def test_grading():
    case = next(c for c in CASES if c["id"] == "insurance_late_ask_student")
    state, _ = ev.case_state(case)
    good = [RequestFromStudent(instance_key="travel_insurance", message="Please buy it.", reason="Needed.")]
    assert ev.grade(case, good, state, BOOK) == (True, [])
    ok, why = ev.grade(case, [Escalate(reason="x")], state, BOOK)
    assert not ok and why == ["missing request_from_student"]
    ok, why = ev.grade(case, [*good, SkipTask(instance_key="travel_insurance", reason="x")], state, BOOK)
    assert not ok and any("kernel refuses skip_task" in w for w in why)
