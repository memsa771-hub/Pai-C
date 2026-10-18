import itertools

import pytest

from app.os.kernel import ALLOWED, TERMINAL, IllegalTransition, TaskState, check_transition

S = TaskState
ALL_PAIRS = list(itertools.product(list(S), list(S)))

EXPECTED = {
    S.PENDING: {S.READY, S.SKIPPED, S.BLOCKED, S.CANCELLED},
    S.READY: {S.RUNNING, S.WAITING_STUDENT, S.BLOCKED, S.CANCELLED},
    S.RUNNING: {S.DONE, S.FAILED, S.WAITING_STUDENT, S.WAITING_REVIEW, S.CANCELLED},
    S.WAITING_STUDENT: {S.READY, S.DONE, S.CANCELLED},
    S.WAITING_REVIEW: {S.READY, S.DONE, S.CANCELLED},
    S.FAILED: {S.READY, S.CANCELLED},
    S.BLOCKED: {S.READY, S.CANCELLED},
    S.DONE: set(),
    S.SKIPPED: set(),
    S.CANCELLED: set(),
}


def test_ten_states():
    assert {s.value for s in S} == {
        "pending", "ready", "running", "waiting_student", "waiting_review",
        "done", "failed", "skipped", "cancelled", "blocked",
    }


def test_table_is_exactly_the_spec():
    assert {k: set(v) for k, v in ALLOWED.items()} == EXPECTED
    assert TERMINAL == {S.DONE, S.SKIPPED, S.CANCELLED}


@pytest.mark.parametrize("frm,to", ALL_PAIRS)
def test_transition_table(frm, to):
    if to in EXPECTED[frm]:
        check_transition(frm, to)
    else:
        with pytest.raises(IllegalTransition):
            check_transition(frm, to)
