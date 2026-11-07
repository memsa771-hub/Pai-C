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


def test_every_duration_without_an_official_source_is_marked_estimate():
    """Data audit over every shipped and fake playbook: a constant a step uses as its lead time has either a cited
    figure or `estimate: true`. None is neither."""
    seen = 0
    for directory in DIRS:
        for book in load_playbook_dir(directory).values():
            for t in book.tasks:
                if t.lead_time and t.lead_time.constant:
                    const = book.constants[t.lead_time.constant]
                    seen += 1
                    assert const.estimate or const.citations, f"{book.key} v{book.version}: {t.lead_time.constant}"
    assert seen >= 1  # the audit looked at something


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
