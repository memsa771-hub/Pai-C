"""P1-T8 Task 2: the FactQuestions port names a bad setting, never its value (R-19 plumbing). Pure: no database."""

import pytest

from app.os.ports import fact_questions


@pytest.mark.parametrize("spec", ["no.such.module:secret-looking-name", "json:no_such_attribute_xyz", "json:__name__"])
def test_a_bad_source_error_names_the_setting_and_never_its_value(spec):
    with pytest.raises(fact_questions.FactQuestionsSourceError) as e:
        fact_questions.load(spec)
    text = str(e.value)
    assert "OS_FACT_CONFLICTS" in text
    assert spec not in text and "secret-looking-name" not in text and "no_such_attribute_xyz" not in text


# ---- P1-T8 Task 4: the port validates FactConflictsV1 and carries the answer ----

import logging  # noqa: E402

from tests.os.contracts.test_contracts_v2 import fact_conflicts as sample  # noqa: E402


@pytest.fixture
def configured():
    yield
    fact_questions.configure(None, None)


def test_conflicts_are_validated_and_read_by_key(configured):
    fact_questions.configure(lambda ref: sample(student_ref=ref))
    assert fact_questions.conflicts("ws-1") == {"education.bachelor.gpa": "profile_issue:abc-123"}
    found = fact_questions.conflict_for("ws-1", "education.bachelor.gpa")
    assert [v.value for v in found.values] == [3.4, 3.2] and fact_questions.conflict_for("ws-1", "x.y") is None


@pytest.mark.standalone
def test_unconfigured_or_none_means_no_conflicts_and_no_answer(configured):
    assert fact_questions.conflicts("ws-1") == {} and fact_questions.read("ws-1") is None
    assert fact_questions.answer("ws-1", "profile_issue:a", "education.bachelor.gpa", "current") is None
    fact_questions.configure(lambda ref: None)
    assert fact_questions.conflicts("ws-1") == {} and fact_questions.conflict_for("ws-1", "a.b") is None


def test_a_wrong_student_ref_is_logged_by_class_and_gives_no_conflicts(configured, caplog):
    fact_questions.configure(lambda ref: sample(student_ref="another-student"))
    with caplog.at_level(logging.ERROR, logger="app.os.ports.fact_questions"):
        assert fact_questions.conflicts("ws-1") == {}
    assert "student_ref_mismatch" in caplog.text and "another-student" not in caplog.text and "3.4" not in caplog.text


def test_an_invalid_document_is_not_hidden(configured):
    from pydantic import ValidationError

    fact_questions.configure(lambda ref: sample(student_ref=ref, extra="x"))
    with pytest.raises(ValidationError):
        fact_questions.conflicts("ws-1")


def test_the_answer_goes_to_the_host_callback(configured):
    seen = []
    fact_questions.configure(None, lambda *a: seen.append(a) or {"status": "resolved"})
    assert fact_questions.answer("ws-1", "profile_issue:a", "education.bachelor.gpa", "new", "3.3", 9) == {"status": "resolved"}
    assert seen == [("ws-1", "profile_issue:a", "education.bachelor.gpa", "new", "3.3", 9)]  # the OS request, for the evidence
