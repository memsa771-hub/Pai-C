"""Evaluates a playbook task's structured condition against one fact (no eval)."""

from app.os.knowledge import Fact
from app.os.playbooks import Condition


def evaluate(cond: Condition, fact: Fact | None) -> bool | None:
    """True/False when the fact decides it; None when the fact is missing (caller treats as true, provisional)."""
    if fact is None:
        return None
    value = fact.value
    if cond.present is not None:
        return bool(value) == cond.present
    return isinstance(value, str) and value in (cond.in_ or [])
