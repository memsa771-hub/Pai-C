"""The Slice 1 modules: inbox (student tasks), milestone, and knowledge.manual (confirm_fact)."""

from app.os.compiler import CONFIRM_TYPE
from app.os.kernel import Outcome
from app.os.runner.registry import Module, Registry, TaskContext

STUDENT_TYPES = frozenset({"student.provide", "student.act", "student.choose", "student.approve"})
MILESTONE_TYPE = "system.milestone"


def _milestone(ctx: TaskContext) -> Outcome:
    return Outcome("done", {"milestone": True})


def _confirm_fact(ctx: TaskContext) -> Outcome:
    # An admin confirms the fact through the API (knowledge.manual), which completes the review.
    return Outcome("needs_review", {"waiting_for": "admin_fact_confirmation"})


INBOX = Module(name="inbox", owns=STUDENT_TYPES, handler=None)
MILESTONE = Module(name="milestone", owns=frozenset({MILESTONE_TYPE}), handler=_milestone)
KNOWLEDGE_MANUAL = Module(name="knowledge.manual", owns=frozenset({CONFIRM_TYPE}), handler=_confirm_fact)


def default_registry() -> Registry:
    reg = Registry()
    for module in (INBOX, MILESTONE, KNOWLEDGE_MANUAL):
        reg.register(module)
    return reg
