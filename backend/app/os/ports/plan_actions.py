"""The PlanActions port (P1-T5, R-04): the Counsellor completes a student's step through PAI OS, in process. It runs
the same function as the inbox route, so the review guard and the visa-date recompute always apply."""

from typing import Literal

from app.os import inbox_actions, ports
from app.os.replan.events import REVIEW_TEMPLATES
from app.os.inbox_actions import StepActionError  # noqa: F401  (the port's error)


def complete_step(student_ref: str, task_id: int, payload: dict | None = None) -> Literal["done", "already_done"]:
    """Raises StepActionError with code not_found, not_yours, not_waiting, review_required or answer_required."""
    return inbox_actions.complete(ports.services(), student_ref, task_id, payload)


def review_templates() -> frozenset[str]:
    """The template keys of review steps: closed by approving a pack or visa file, never by a tick."""
    return frozenset(REVIEW_TEMPLATES)
