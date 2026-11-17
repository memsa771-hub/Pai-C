"""P2-T10 proof of R-30: a duration without an official figure is marked `estimate: true` and reaches the student as
"estimated". The chain: playbook data -> compiler -> plan JSON (`estimated`) -> the display rule's level. The screens'
own label is proved in frontend/components/os/fact-source.test.tsx (estimated inbox date, step meta)."""

from datetime import UTC, date, datetime

import pytest

from app.os.api.queries import plan_out
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge, display
from app.os.playbooks import PLAYBOOK_DIR, Playbook, load_playbook_dir
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.test_compiler import FAKE, IE, contract

pytestmark = pytest.mark.req("R-30")
DIRS = [PLAYBOOK_DIR, FAKE, FAKE / "needs"]


def _durations(book) -> set[str]:
    """Every constant a step uses as a duration or lead time, or names in a note."""
    from app.os.playbooks.models import placeholders

    out = set()
    for t in book.tasks:
        out |= {n for n in (t.lead_time.constant if t.lead_time else None, t.duration_constant) if n}
        for note in t.anchor.notes() if t.anchor else ():
            out |= placeholders(note or "") & set(book.constants)
    return out


def test_every_duration_without_an_official_source_is_marked_estimate():
    """Data audit over every shipped and fake playbook, by all three uses (duration, lead time, note placeholder)."""
    seen = 0
    for directory in DIRS:
        for book in load_playbook_dir(directory).values():
            for name in _durations(book):
                seen += 1
                const = book.constants[name]
                assert const.estimate or const.citations, f"{book.key} v{book.version}: {name}"
    assert seen >= 4  # the audit looked at the shipped durations


def _with_constant(use: str) -> dict:
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["constants"] = {"wait": {"value": 30}}  # neither cited nor an estimate
    if use == "lead_time":
        data["tasks"][0]["lead_time"] = {"constant": "wait"}
    elif use == "duration_constant":
        data["tasks"][1].pop("duration_days", None)
        data["tasks"][1]["duration_constant"] = "wait"
    else:
        data["tasks"][0]["anchor"]["note"] = "About {wait} days"
    return data


@pytest.mark.parametrize("use", ["lead_time", "duration_constant", "note"])
def test_an_unsourced_unflagged_duration_is_refused(use):
    """The guard is a validator, not only a test: such a playbook cannot load (R-30)."""
    with pytest.raises(ValueError, match="estimate"):
        Playbook.model_validate(_with_constant(use))
    data = _with_constant(use)
    data["constants"]["wait"]["estimate"] = True  # flagged: loads
    Playbook.model_validate(data)
    data["constants"]["wait"] = {"value": 30, "citations": [{"source": "S1", "url": "https://rules.alpha.test/x"}]}
    Playbook.model_validate(data)  # cited: loads


def _book(estimate: bool, cited: bool) -> Playbook:
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    const = {"value": 56, "estimate": estimate,
             "citations": [{"source": "S1", "url": "https://rules.alpha.test/lead"}] if cited else []}
    data["constants"] = {"lead": const}
    data["tasks"][0]["lead_time"] = {"constant": "lead"}
    return Playbook.model_validate(data)


@pytest.mark.parametrize("estimate,cited", [(True, False), (False, True)])
def test_estimate_reaches_the_plan_the_student_reads(engine, clean, estimate, cited):
    book = _book(estimate, cited)
    kb = SqlKnowledge(engine, "pai")
    at = datetime(2026, 11, 1, tzinfo=UTC)
    kb.upsert("programme", "p1", "deadline_close",
              Fact({"date": "2027-07-15"}, "q", "https://alpha.test/n", at, 2027, "confirmed", intake_term="winter"))
    svc = PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), kb,
                      {(book.key, book.version): book}, today=lambda: date(2027, 3, 1))
    tasks = {t["instance_key"]: t for t in plan_out(engine, "pai", svc.start_plan(contract(["p1"])).plan_id)["tasks"]}
    assert tasks["apply@p1"]["estimated"] is estimate
    assert tasks["visa"]["estimated"] is False  # only the step that uses the estimate is labelled


def test_the_display_rule_says_estimated():
    shown = display(None, "lead_days", intake_year=2027, estimate=True)
    assert shown.level == "estimated" and shown.show_value
