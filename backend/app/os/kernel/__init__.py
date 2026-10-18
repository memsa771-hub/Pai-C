"""The kernel: task states, the sole writer of plan state, and plan revisions."""

from app.os.kernel.kernel import Kernel, Outcome, PlanRef, contract_sha256
from app.os.kernel.revisions import RevisionDiff, diff
from app.os.kernel.states import (
    ALLOWED,
    SATISFIES_DEPENDENCY,
    TERMINAL,
    UNSTARTED,
    IllegalTransition,
    TaskState,
    check_transition,
    is_started,
)

__all__ = [
    "ALLOWED", "SATISFIES_DEPENDENCY", "TERMINAL", "UNSTARTED", "IllegalTransition", "Kernel", "Outcome",
    "PlanRef", "RevisionDiff", "TaskState", "check_transition", "contract_sha256", "diff", "is_started",
]
