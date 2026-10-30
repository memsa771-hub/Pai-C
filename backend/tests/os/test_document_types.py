"""Slice 3 Task 1: document types as config (spec S3-D2). New types need no code."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.os.documents.types import TYPES_DIR, DocumentTypeError, load_document_types, reading_model

TYPES = {"passport", "degree_certificate", "transcript", "ssc_certificate", "hssc_certificate", "ielts_trf",
         "min_passing_grade_letter",  # the letter: Slice 4 Task 4, added by config only
         "admission_letter", "blocked_account_confirmation", "insurance_certificate"}  # Slice 6b, by config only


def test_all_types_load():
    types = load_document_types()
    assert set(types) == TYPES
    assert all(t.version == 1 for t in types.values())
    assert types["passport"].full_name_from == ["given_names", "surname"]
    assert types["ielts_trf"].full_name_from == ["first_name", "family_name"]
    cross = {f.name: f.cross_check for f in types["transcript"].fields if f.cross_check}
    assert cross == {"student_name": "full_name", "father_name": "father_name", "date_of_birth": "date_of_birth"}
    assert [r.kind for r in types["passport"].rules] == ["mrz"]
    assert [r.kind for r in types["ielts_trf"].rules] == ["band_mean"]


def write(tmp_path: Path, name: str, body: str) -> Path:
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


BASE = """key: sample_doc
version: 1
label: Sample document
fields:
  - {name: student_name, type: name, hint: The student's name, cross_check: full_name}
  - {name: issue_date, type: date, hint: Date of issue}
"""


@pytest.mark.parametrize("body, needle", [
    (BASE.replace("type: date", "type: banana"), "issue_date"),
    (BASE + "  - {name: issue_date, type: date, hint: again}\n", "duplicate field 'issue_date'"),
    (BASE + "rules:\n  - {kind: lte, fields: [issue_date, nope]}\n", "unknown field 'nope'"),
    (BASE + "full_name_from: [nope]\n", "unknown field 'nope'"),
    (BASE.replace("hint: Date of issue", "hint: Date of issue, values: [a]").replace("type: date", "type: enum")
     .replace("values: [a]", "values: []"), "needs values"),
])
def test_invalid_type_stops_startup(tmp_path, body, needle):
    with pytest.raises(DocumentTypeError) as e:
        load_document_types(write(tmp_path, "sample_doc.v1.yaml", body))
    assert "sample_doc.v1.yaml" in str(e.value) and needle in str(e.value)


def test_reading_model_accepts_values():
    types = load_document_types()
    passport = reading_model(types["passport"]).model_validate({
        "surname": "KHAN", "given_names": "SARA AHMED", "date_of_birth": "1999-01-31", "sex": "F",
        "passport_number": "AB1234567", "mrz_line2": "AB12345674PAK9901316F3001017<<<<<<<<<<<<<<02",
        "detected_type": "passport"})
    assert passport.surname == "KHAN" and passport.detected_type == "passport"
    transcript = reading_model(types["transcript"]).model_validate({"cgpa": 3.7, "date_of_birth": "31/02/2024"})
    assert transcript.cgpa == 3.7 and transcript.date_of_birth == "31/02/2024"  # kept as read; validators judge it
    with pytest.raises(ValidationError):
        reading_model(types["ielts_trf"]).model_validate({"module": "Something Else"})  # enum
    empty = reading_model(types["degree_certificate"]).model_validate({})
    assert empty.student_name is None and empty.detected_type is None


def test_new_type_by_config_only(tmp_path):
    body = """key: o_level_statement
version: 1
label: O Level statement of results
full_name_from: [first_name, last_name]
fields:
  - {name: first_name, type: name, hint: Given names}
  - {name: last_name, type: name, hint: Family name}
  - {name: date_of_birth, type: date, hint: Date of birth, cross_check: date_of_birth}
  - {name: subjects_passed, type: number, hint: Number of subjects passed}
"""
    types = load_document_types(write(tmp_path, "o_level_statement.v1.yaml", body))
    model = reading_model(types["o_level_statement"])
    assert model.model_validate({"first_name": "Sara", "subjects_passed": 8}).subjects_passed == 8


def test_newest_version_wins(tmp_path):
    write(tmp_path, "sample_doc.v1.yaml", BASE)
    write(tmp_path, "sample_doc.v2.yaml", BASE.replace("version: 1", "version: 2").replace("Sample document", "V2"))
    assert load_document_types(tmp_path)["sample_doc"].label == "V2"


def test_types_dir_is_the_package_dir():
    assert TYPES_DIR.name == "types" and TYPES_DIR.parent.name == "documents"
