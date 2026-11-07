"""P1-T8 Task 6 fix (R-21): what each value of a "which is right" question says about where it comes from. A value said
in the chat or on the profile page (no document) is not "From your document", and the proposed side is not "saved"."""

import pytest

from app.os.contracts.fact_conflicts import FactConflict, ConflictValue
from app.os.requests import answers, texts

pytestmark = pytest.mark.req("R-21")


def conflict(proposed_document):
    return FactConflict(
        ref="profile_issue:7", key="education.matric.marks_obtained", answers=["keep_current", "accept_proposed", "provide_new"],
        values=[ConflictValue(side="current", value=800, evidence="shown", document_ref="f1"),
                ConflictValue(side="proposed", value=760, evidence="stated", document_ref=proposed_document)])


def test_a_proposed_value_with_no_document_is_what_the_student_told_pai():
    current, proposed = answers._from_conflict(conflict(None), "k").choices
    assert proposed["label"] == texts.text("proposed_said_label") != texts.text("proposed_label")
    assert proposed["source"]["kind"] == "said" and proposed["source"]["document_ref"] is None
    assert current["source"]["kind"] == "document" and current["label"] == texts.text("current_label")


def test_a_proposed_value_from_a_document_keeps_its_label():
    current, proposed = answers._from_conflict(conflict("f2"), "k").choices
    assert proposed["label"] == texts.text("proposed_label") and proposed["source"]["kind"] == "document"


def test_a_current_value_with_no_document_is_saved_in_pai():
    c = conflict("f2")
    c = c.model_copy(update={"values": [c.values[0].model_copy(update={"document_ref": None}), c.values[1]]})
    current, _ = answers._from_conflict(c, "k").choices
    assert current["source"]["kind"] == "vault"
