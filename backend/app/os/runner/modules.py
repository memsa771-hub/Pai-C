"""The modules: inbox (student tasks), milestone, and knowledge.research (confirm_fact, Slice 2 S2-D2)."""

from functools import cache

from app.os.compiler import CONFIRM_TYPE
from app.os.kernel import Outcome
from app.os.runner.registry import Module, Registry, TaskContext

STUDENT_TYPES = frozenset({"student.provide", "student.act", "student.choose", "student.approve"})
MILESTONE_TYPE = "system.milestone"


def _milestone(ctx: TaskContext) -> Outcome:
    return Outcome("done", {"milestone": True})


@cache
def _researched_fields() -> frozenset[str]:
    from app.os.knowledge.profile import load_profile_dir  # imported here: profiles are data, loaded once

    return frozenset(f.name for p in load_profile_dir().values() for f in p.fields)


def _confirm_fact(ctx: TaskContext) -> Outcome:
    """A programme fact the research profiles define waits for the day's research run (the worker's enqueue
    loop starts it, R2-P1); any other fact waits for an admin (spec S2-D1). Either way the admin API can
    complete the review."""
    scope, ref, name = ctx.fact_refs[0] if ctx.fact_refs else (None, None, None)
    if scope == "programme" and name in _researched_fields():
        return Outcome("needs_review", {"waiting_for": "research", "programme": ref, "field": name})
    return Outcome("needs_review", {"waiting_for": "admin_fact_confirmation"})


INBOX = Module(name="inbox", owns=STUDENT_TYPES, handler=None)
MILESTONE = Module(name="milestone", owns=frozenset({MILESTONE_TYPE}), handler=_milestone)
KNOWLEDGE_RESEARCH = Module(name="knowledge.research", owns=frozenset({CONFIRM_TYPE}), handler=_confirm_fact)


def default_registry() -> Registry:
    reg = Registry()
    for module in (INBOX, MILESTONE, KNOWLEDGE_RESEARCH):
        reg.register(module)
    return reg
