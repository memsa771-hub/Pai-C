"""P1-T8 Task 4 review fix (R-21, R-19): a Vault card with more than one differing value is asked one value at a time
(owner ruling, 2026-11-07). The route here needs two facts of the same record (marks obtained and marks total), so one
card makes two requests. Each answer saves only that value; the card stays open until every differing value has an
answer; nothing is saved that the student did not choose. Fictional student and marks. No model call."""

import pytest
from sqlalchemy import select

from app.models import MemoryCandidate, ProfileIssue
from app.os.playbooks.loader import load_playbook_dir
from app.pai_c.connect import document_facts
from tests.os.test_compile_needs import BOOKS as PLAYBOOKS
from tests.os.test_which_is_right import (  # noqa: F401  (the fixtures and the world are shared)
    OBTAINED, TOTAL, World, last_written, world)
from tests.test_document_facts import add_file, education, proposal, reconcile_all

pytestmark = pytest.mark.req("R-21")

FAKE = (__import__("pathlib").Path(__file__).parent / "playbooks" / "needs" / "pakistan_bs.v2.yaml")
ONE = "      - {fact: education.intermediate.marks_obtained, evidence: stated}\n"
BOTH = ONE + "      - {fact: education.intermediate.marks_total, evidence: stated}\n"
ASKS = ("  education.intermediate.marks_obtained:\n    stated: Tell us your intermediate marks\n"
        "    which_is_right: Which intermediate marks are right?\n")
MORE = ASKS + ("  education.intermediate.marks_total:\n    stated: Tell us your intermediate total marks\n"
               "    which_is_right: Which intermediate total is right?\n")


@pytest.fixture
def books(tmp_path):
    """The fake bachelor route whose entry test needs both the marks and their total."""
    text = FAKE.read_text(encoding="utf-8")
    assert ONE in text and ASKS in text
    (tmp_path / "pakistan_bs.v2.yaml").write_text(text.replace(ONE, BOTH).replace(ASKS, MORE), encoding="utf-8")
    return {**PLAYBOOKS, **load_playbook_dir(tmp_path)}


def two_cards(world):
    """Saved: 800 of 1100 (said by the student). A certificate then reads 760 of 1050: one card, two values."""
    from app.os.requests.refresh import refresh

    with world.who.factory() as db:
        world.saved(db)
    plan_id = world.start()
    with world.who.factory() as db:
        outcome, ids = document_facts.apply(db, proposal(world.who, add_file(db, world.ws), [
            {"key": OBTAINED, "value": 760}, {"key": TOTAL, "value": 1050}], doc_type="hssc_certificate"))
        db.commit()
        assert outcome == "written"
        reconcile_all(db, ids)
    assert refresh(world.svc, world.ws, "test") == 1
    asked = {r["need"]["ref"]: r for r in world.requests() if r["kind"] == "which_is_right" and r["status"] == "open"}
    assert set(asked) == {OBTAINED, TOTAL}
    return plan_id, asked


def card_status(world) -> str:
    with world.who.factory() as db:
        return world.card(db).status


def open_asks(world) -> set[str]:
    return {r["need"]["ref"] for r in world.requests() if r["kind"] == "which_is_right" and r["status"] == "open"}


def test_answering_one_value_saves_only_that_value_and_the_card_stays_open(world):
    plan_id, asked = two_cards(world)
    assert asked[OBTAINED]["ref"] == asked[TOTAL]["ref"]  # one card
    got = world.answer(asked[OBTAINED]["id"], "proposed")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    with world.who.factory() as db:
        (row,) = education(db, world.ws)
        assert row["result"] == {"marks_obtained": 760, "marks_total": 1100}  # the total is not touched
        assert world.card(db).status == "open"
        candidate = last_written(db)
        assert candidate.evidence["os_request_id"] == asked[OBTAINED]["id"]
        assert candidate.proposed_value["value"] == {"result": {"marks_obtained": 760}}
    assert open_asks(world) == {TOTAL}  # exactly one request is still open
    assert world.row(asked[OBTAINED]["id"]).status == "answered" and world.row(asked[TOTAL]["id"]).status == "open"
    # the other value is still asked, with both of its values
    (rest,) = [r for r in world.requests() if r["id"] == asked[TOTAL]["id"]]
    assert [c["value"] for c in rest["choices"]] == [1100, 1050]


def test_answering_the_last_value_current_closes_the_card_and_both_requests(world):
    plan_id, asked = two_cards(world)
    assert world.answer(asked[OBTAINED]["id"], "proposed").status_code == 200
    got = world.answer(asked[TOTAL]["id"], "current")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    assert card_status(world) == "resolved"
    with world.who.factory() as db:
        (row,) = education(db, world.ws)
        assert row["result"] == {"marks_obtained": 760, "marks_total": 1100}  # 1050 was never saved
        assert world.card(db).resolution["answers"] == {
            OBTAINED: {"choice": "proposed", "request_id": asked[OBTAINED]["id"]},
            TOTAL: {"choice": "current", "request_id": asked[TOTAL]["id"]}}
    assert {world.row(r["id"]).status for r in asked.values()} == {"answered"}
    assert open_asks(world) == set()


def test_new_on_one_value_leaves_the_other_asked(world):
    plan_id, asked = two_cards(world)
    got = world.answer(asked[TOTAL]["id"], "new", "1000")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"] == {"marks_obtained": 800, "marks_total": 1000}
    assert card_status(world) == "open" and open_asks(world) == {OBTAINED}


def test_the_card_closing_on_the_vault_page_after_a_part_answer_closes_the_rest(world):
    """R-19: one value answered here, then the student keeps the rest on the Vault page; the other request closes."""
    plan_id, asked = two_cards(world)
    assert world.answer(asked[OBTAINED]["id"], "current").status_code == 200
    with world.who.factory() as db:
        card_id = world.card(db).id
    got = world.client.post(f"/v1/vault/conflicts/{card_id}/resolve?network={world.ws}", headers=world.auth,
                            json={"answer": "keep_current"})
    assert got.status_code == 200, got.text
    from app import pai_os_bridge as bridge

    with world.who.factory() as db:
        assert bridge.deliver_pending(db, world.ws)["failed"] == 0
    assert open_asks(world) == set()
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"] == {"marks_obtained": 800, "marks_total": 1100}
