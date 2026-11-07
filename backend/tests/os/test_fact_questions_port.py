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
