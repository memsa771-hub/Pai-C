"""Task states and the only transitions the kernel allows (spec §4.4)."""

from collections.abc import Mapping
from enum import StrEnum


class TaskState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_STUDENT = "waiting_student"
    WAITING_REVIEW = "waiting_review"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


S = TaskState
ALLOWED: Mapping[TaskState, frozenset[TaskState]] = {
    S.PENDING: frozenset({S.READY, S.SKIPPED, S.BLOCKED, S.CANCELLED}),
    S.READY: frozenset({S.RUNNING, S.WAITING_STUDENT, S.BLOCKED, S.CANCELLED}),
    S.RUNNING: frozenset({S.DONE, S.FAILED, S.WAITING_STUDENT, S.WAITING_REVIEW, S.CANCELLED}),
    S.WAITING_STUDENT: frozenset({S.READY, S.DONE, S.CANCELLED}),
    S.WAITING_REVIEW: frozenset({S.READY, S.DONE, S.CANCELLED}),
    S.FAILED: frozenset({S.READY, S.CANCELLED}),
    S.BLOCKED: frozenset({S.READY, S.CANCELLED}),
    S.DONE: frozenset(),
    S.SKIPPED: frozenset(),
    S.CANCELLED: frozenset(),
}
TERMINAL = frozenset({S.DONE, S.SKIPPED, S.CANCELLED})
SATISFIES_DEPENDENCY = frozenset({S.DONE, S.SKIPPED})
UNSTARTED = frozenset({S.PENDING, S.READY, S.BLOCKED})


class IllegalTransition(ValueError):
    pass


def check_transition(frm: TaskState | str, to: TaskState | str) -> None:
    frm, to = TaskState(frm), TaskState(to)
    if to not in ALLOWED[frm]:
        raise IllegalTransition(f"{frm} -> {to} is not allowed")
