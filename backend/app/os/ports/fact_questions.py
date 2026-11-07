"""The FactQuestions port (P1-T8, D-w12): the student's open Vault conflicts, read from the host, and the student's
answer to one, sent back to the host. It mirrors the StudentFacts port (invariant 11: no host import here).

- the API process: the host passes the two callables to `ports.configure`;
- the worker process: `OS_FACT_CONFLICTS=module.path:callable`, imported at worker start. The worker must have it
  whenever it has `OS_STUDENT_FACTS`, or the API and the worker would compile different plans (D-w1).

A source returns None while the host's own part is off. Unconfigured, or None, means no conflicts."""

import importlib
import logging
from collections.abc import Callable

from app.os.contracts.fact_conflicts import FactConflict, FactConflictsV1
from app.os.settings import OsSettings

log = logging.getLogger("app.os.ports.fact_questions")

ConflictsSource = Callable[[str], dict | None]
AnswerSink = Callable[..., dict | None]


class FactQuestionsSourceError(ValueError):
    """OS_FACT_CONFLICTS cannot be loaded, or is missing while OS_STUDENT_FACTS is set: the worker must not start."""


_conflicts: ConflictsSource | None = None
_answer: AnswerSink | None = None


def configure(conflicts: ConflictsSource | None = None, answer: AnswerSink | None = None) -> None:
    global _conflicts, _answer
    _conflicts, _answer = conflicts, answer


def load(spec: str) -> ConflictsSource:
    """Imports `module.path:callable`. Any problem is a FactQuestionsSourceError naming the setting (never a value)."""
    module_path, _, name = (spec or "").strip().partition(":")
    if not module_path or not name:
        raise FactQuestionsSourceError("OS_FACT_CONFLICTS must look like 'module.path:callable'")
    try:
        found = getattr(importlib.import_module(module_path), name)
    except (ImportError, AttributeError) as e:
        raise FactQuestionsSourceError(f"OS_FACT_CONFLICTS cannot be imported ({type(e).__name__})") from None
    if not callable(found):
        raise FactQuestionsSourceError("OS_FACT_CONFLICTS is not callable")
    return found


def from_settings(settings: OsSettings) -> ConflictsSource | None:
    """The worker's host adapter: loaded from OS_FACT_CONFLICTS, or None. Needed whenever OS_STUDENT_FACTS is set."""
    if settings.fact_conflicts:
        return load(settings.fact_conflicts)
    if settings.student_facts:
        raise FactQuestionsSourceError("OS_FACT_CONFLICTS must be set when OS_STUDENT_FACTS is set")
    return None


def read(student_ref: str) -> FactConflictsV1 | None:
    """The host's open conflicts for the student, validated as `FactConflictsV1`. None while unconfigured, when the host
    answers None, and when it answers for another student (logged by class only). An invalid document is not hidden
    (ValidationError): the caller retries or fails, as with StudentFacts."""
    if _conflicts is None:
        return None
    raw = _conflicts(student_ref)
    if not raw:
        return None
    found = FactConflictsV1.model_validate(raw)
    if found.student_ref != student_ref:
        log.error("FactConflicts adapter answered for another student (student_ref_mismatch); no conflicts are seen")
        return None
    return found


def conflicts(student_ref: str) -> dict[str, str]:
    """`fact key -> conflict ref` for the student's open Vault conflicts; empty while unconfigured, when the host answers
    None and when it answers for another student."""
    found = read(student_ref)
    return {c.key: c.ref for c in found.conflicts} if found else {}


def conflict_for(student_ref: str, key: str) -> FactConflict | None:
    """The open conflict on one fact, with both values and their sources (read live, never stored)."""
    found = read(student_ref)
    return next((c for c in found.conflicts if c.key == key), None) if found else None


def answer(student_ref: str, ref: str, key: str, choice: str, value=None) -> dict | None:
    """Sends the student's answer to the host: `{"status": "resolved" | "gone" | "refused", "code"?}`, or None when no
    callback is configured or the host's part is off (the API then answers 404). A synchronous call, like the choice sink;
    the host writes the Vault and commits before it returns."""
    if _answer is None:
        return None
    return _answer(student_ref, ref, key, choice, value)
