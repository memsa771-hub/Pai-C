"""Slice 7 Task 5: replan rules (spec §2 rules.py), pure, on hand-built plan states. Fictional data."""

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.os.replan import rules
from app.os.replan.config import ReplanConfig, load_replan_configs
from app.os.replan.events import Event
from app.os.replan.ops import (
    AddTask, CancelProgramme, Escalate, Reprioritise, RequestFromStudent, SwapProgramme, TaskRow, UpgradePlaybook,
)
from app.os.replan.rules import Handover, PlanState, Retry, rules_for

CFG = ReplanConfig()
A, B = "prog-a", "prog-b"


def row(key, *, ref=None, state="pending", kind="student", critical=False, deps=(), finish=None) -> TaskRow:
    return TaskRow(key, key.split("@")[0].split("#")[0], ref, state, kind, critical, False, finish, 3, 2, tuple(deps))


def state(programmes=(A, B), suggestions=None, **extra) -> PlanState:
    tasks = {
        f"apply@{A}": row(f"apply@{A}", ref=A),
        f"apply@{B}": row(f"apply@{B}", ref=B),
        "certificates": row("certificates", critical=True),
        "language_test": row("language_test", finish=datetime(2027, 6, 1, tzinfo=timezone.utc)),
        "visa_apply": row("visa_apply", critical=True, deps=[("certificates", True)]),
        "review_visa_file": row("review_visa_file", state="done"),
        "sync_work": row("sync_work", kind="work", critical=True, deps=[("certificates", True)]),
    }
    tasks.update(extra)
    return PlanState(plan_id=1, route_key="fake_route", programmes=list(programmes), tasks=tasks,
                     suggestions=suggestions or {}, playbook_version=1)


def ev(type_, **payload) -> Event:
    return Event(9, 1, None, type_, payload)


def test_rejection_cancels_the_programme():
    got = rules_for(ev("admission_rejected", programme_ref=A), state(), CFG)
    assert got == [CancelProgramme(programme_ref=A, reason=rules.REASONS["rejected"])]


def test_rejection_below_minimum_swaps():
    got = rules_for(ev("admission_rejected", programme_ref=A), state(programmes=[A], suggestions={A: ["prog-c"]}),
                    CFG)
    assert got == [SwapProgramme(out_ref=A, in_ref="prog-c", reason=rules.REASONS["swap"])]


def test_rejection_without_suggestions_hands_over():
    got = rules_for(ev("admission_rejected", programme_ref=A), state(programmes=[A]), CFG)
    assert isinstance(got, Handover) and "no close match" in got.reason


def test_rejection_of_a_programme_not_in_the_plan_does_nothing():
    assert rules_for(ev("admission_rejected", programme_ref="gone"), state(), CFG) == []


def test_min_programmes_from_config():
    got = rules_for(ev("admission_rejected", programme_ref=A), state(suggestions={A: ["prog-c"]}),
                    ReplanConfig(min_programmes=2))
    assert got == [SwapProgramme(out_ref=A, in_ref="prog-c", reason=rules.REASONS["swap"])]


def test_deadline_at_risk_asks_for_the_blocking_item_first():
    got = rules_for(ev("deadline_at_risk", instance_key="visa_apply"), state(), CFG)
    assert got == [Reprioritise(instance_key="certificates", before="language_test", reason=rules.REASONS["critical"]),
                   RequestFromStudent(instance_key="certificates", message=rules.MESSAGE,
                                      reason=rules.REASONS["request"])]


def test_deadline_at_risk_for_a_programme_without_student_work_hands_over():
    s = state(**{f"deadline@{A}": row(f"deadline@{A}", ref=A, kind="work", critical=True)})
    assert isinstance(rules_for(ev("deadline_at_risk", instance_key=f"deadline@{A}"), s, CFG), Handover)


def test_deadline_at_risk_route_step_without_student_work_escalates():
    s = state(other=row("other", kind="work", critical=True))
    assert rules_for(ev("deadline_at_risk", instance_key="other"), s, CFG) == [Escalate(reason=rules.REASONS["late"])]


def test_document_missing_requests_it():
    got = rules_for(ev("document_missing", instance_key="language_test"), state(), CFG)
    assert got == [RequestFromStudent(instance_key="language_test", message=rules.MESSAGE,
                                      reason=rules.REASONS["request"])]


def test_document_missing_but_done_does_nothing():
    s = state(language_test=row("language_test", state="done"))
    assert rules_for(ev("document_missing", instance_key="language_test"), s, CFG) == []


def test_task_failed_retries_once_then_escalates():
    assert rules_for(ev("task_failed", instance_key="sync_work", attempt=1), state(), CFG) == Retry("sync_work")
    assert rules_for(ev("task_failed", instance_key="sync_work", attempt=2), state(), CFG) == [
        Escalate(reason=rules.REASONS["failed"])]


def test_playbook_newer_proposes_upgrade():
    assert rules_for(ev("playbook_newer", version=2), state(), CFG) == [
        UpgradePlaybook(version=2, reason=rules.REASONS["upgrade"])]


def test_approved_changed_re_adds_review():
    got = rules_for(ev("approved_changed", template_key="review_visa_file", programme_ref=None), state(), CFG)
    assert got == [AddTask(template_key="review_visa_file", programme_ref=None, reason=rules.REASONS["review"])]


def test_escalate_and_route_invalid_hand_over():
    for t in ("escalate", "route_invalid"):
        assert isinstance(rules_for(ev(t), state(), CFG), Handover)


def test_replan_configs_load():
    cfgs = load_replan_configs()
    assert cfgs["germany_master"].min_programmes == 1
    assert load_replan_configs().get("ireland_master", ReplanConfig()).min_programmes == 1


def test_no_route_terms_in_replan():
    words = re.compile(r"\bgermany\b|\bgerman\b|\bireland\b|\bpakistan\b|\beur\b|euro|€|\bpkr\b|uni-assist|"
                       r"\bdaad\b|\bhec\b|embassy", re.IGNORECASE)
    root = Path(rules.__file__).parent
    hits = [f"{p.name}:{n}" for p in root.glob("*.py")
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if words.search(line)]
    assert hits == []


def test_reprioritise_skips_started_or_dependent_targets():
    s = state(language_test=row("language_test", state="waiting_student", deps=[("certificates", True)]))
    got = rules_for(ev("deadline_at_risk", instance_key="visa_apply"), s, CFG)
    moves = [o for o in got if o.op == "reprioritise"]
    assert moves and all(o.before != "language_test" for o in moves)  # never ahead of a step that needs it
    assert got[-1].op == "request_from_student" and replace(s.tasks["certificates"]).critical
