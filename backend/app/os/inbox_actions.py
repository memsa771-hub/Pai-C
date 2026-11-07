"""One way to finish a student's inbox step (P1-T5, R-04). The inbox route and the PlanActions port both call it, so
the review guard and the visa-date recompute always run. Only the kernel changes the task (invariant 1)."""

from typing import Literal

from app.os.kernel import IllegalTransition
from app.os.packs.visa import ADMISSION_TASK
from app.os.replan.events import REVIEW_TEMPLATES
from app.os.requests import keys, texts

Code = Literal["not_found", "not_yours", "not_waiting", "review_required", "answer_required"]


class StepActionError(Exception):
    """A step could not be completed. `code` is the reason; `message` is the words the inbox route shows."""

    def __init__(self, code: Code, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def complete(svc, student_ref: str, task_id: int, payload: dict | None = None) -> Literal["done", "already_done"]:
    """Marks the student's waiting step done: `done`, or `already_done` on a repeat. An admission answer recompiles the
    plan for the visa step's date. A review step is closed by approving its artifact, and a request step (P1-T8, D-w11)
    by the answer, never by hand."""
    from app.os.api.packs import refresh_visa_date  # late: the API package imports this module
    from app.os.api.queries import task_plan_and_template

    found = task_plan_and_template(svc.engine, svc.settings.tenant_id, task_id)
    if found is not None and found[1] in keys.TEMPLATES:  # a request closes when PAI has what it asked for (R-18)
        raise StepActionError("answer_required", texts.text("answer_required"))
    if found is not None and found[1] in REVIEW_TEMPLATES:
        noun = "visa file" if REVIEW_TEMPLATES[found[1]] == "visa" else "pack"
        raise StepActionError("review_required", f"approve the {noun} to finish this step")
    try:
        done = svc.kernel.complete_student_task(task_id, student_ref, payload or {})
    except KeyError:
        raise StepActionError("not_found", "inbox item not found") from None
    except PermissionError:
        raise StepActionError("not_yours", "inbox item not found") from None
    except IllegalTransition as e:
        raise StepActionError("not_waiting", str(e)) from None
    if done and found is not None and found[1] == ADMISSION_TASK:  # an admission answer can move the visa date (F1)
        refresh_visa_date(svc, found[0])
    return "done" if done else "already_done"
