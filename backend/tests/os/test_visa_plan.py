"""Slice 6b (plan Task 4, built third): the review_visa_file plan task (spec S6b-D9)."""

from pathlib import Path

from app.os.playbooks import load_playbook_dir

BOOKS = {key: b for (key, _), b in {**load_playbook_dir(),
                                    **load_playbook_dir(Path(__file__).parent / "playbooks")}.items()}


def task(book, key):
    return next((t for t in book.tasks if t.template_key == key), None)


def test_review_visa_file_before_visa_apply():
    book = BOOKS["germany_master"]
    t = task(book, "review_visa_file")
    assert t is not None
    assert (t.task_type, t.kind, t.inbox_kind, t.fan_out) == ("student.approve", "student", "approve", "none")
    assert {d.key for d in t.depends_on} == {"blocked_account", "travel_insurance"}
    assert t.citations
    assert "review_visa_file" in {d.key for d in task(book, "visa_apply").depends_on}


def test_fake_routes_unchanged():
    """The fake playbooks are shared Slice 1 fixtures: the visa step is route data, they have none (6a lesson)."""
    assert task(BOOKS["ireland_master"], "review_visa_file") is None
    assert task(BOOKS["pakistan_bs"], "review_visa_file") is None
