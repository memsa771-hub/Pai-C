"""Slice 3 Task 6: cross-checks and name variants (spec S3-D7). Synthetic names only."""

from app.os.documents.checks import (
    NAME_VARIANTS,
    Finding,
    compare_names,
    cross_check,
    load_name_variants,
    normalise_name,
)
from app.os.documents.types import load_document_types

TYPES = load_document_types()
V = load_name_variants(NAME_VARIANTS)


def passport(given: str, surname: str, dob: str | None = "2001-03-04") -> dict:
    return {"given_names": given, "surname": surname, "date_of_birth": dob}


def test_normalise_name():
    assert normalise_name("KHAN, SARA AHMED") == ["sara", "ahmed", "khan"]
    assert normalise_name("  Sara-Ahmed   Khan. ") == ["sara", "ahmed", "khan"]
    assert normalise_name("") == []


def test_name_order_and_comma_equal():
    assert compare_names("KHAN, SARA AHMED", "Sara Ahmed Khan", V) == "equal"
    assert compare_names("SARA AHMED KHAN", "Khan Sara Ahmed", V) == "equal"


def test_spelling_variant_flagged():
    assert compare_names("Muhammad Bilal", "MOHAMMAD BILAL", V) == "variant"
    assert compare_names("Ali Raza", "Ali Rezaa", V) == "different"


def test_joined_name_is_variant():
    assert compare_names("Abdul Rehman Tariq", "Abdulrehman Tariq", V) == "variant"


def test_different_names_mismatch():
    assert compare_names("Sara Ahmed Khan", "Sana Ahmed Khan", V) == "different"
    assert compare_names("Sara Khan", "Sara Ahmed Khan", V) == "different"


def test_variants_file_loads():
    assert any({"muhammad", "mohammad"} <= g for g in V)
    assert all(g == {n.casefold() for n in g} for g in V)


def test_dob_mismatch():
    docs = [(1, TYPES["passport"], passport("SARA AHMED", "KHAN")),
            (2, TYPES["ssc_certificate"], {"student_name": "Sara Ahmed Khan", "date_of_birth": "2001-04-03"})]
    [f] = cross_check(docs, V)
    assert f == Finding("mismatch", "date_of_birth", [(1, "2001-03-04"), (2, "2001-04-03")])


def test_nulls_skipped():
    docs = [(1, TYPES["passport"], passport("SARA AHMED", "KHAN", dob=None)),
            (2, TYPES["transcript"], {"student_name": "Sara Ahmed Khan", "date_of_birth": "2001-03-04"}),
            (3, TYPES["degree_certificate"], {"student_name": None, "father_name": "Tariq Khan"})]
    assert cross_check(docs, V) == []


def test_finding_lists_documents():
    docs = [(1, TYPES["passport"], passport("MUHAMMAD BILAL", "TARIQ")),
            (2, TYPES["transcript"], {"student_name": "Mohammad Bilal Tariq", "father_name": "Tariq Mehmood"}),
            (3, TYPES["ssc_certificate"], {"student_name": "Muhammad Bilal Tariq", "father_name": "Tariq Mahmood"}),
            (4, TYPES["ielts_trf"], {"first_name": "MUHAMMAD BILAL", "family_name": "TARIQ"})]
    found = {f.field: f for f in cross_check(docs, V)}
    assert set(found) == {"full_name", "father_name"}
    assert found["full_name"].kind == "variant"
    assert [i for i, _ in found["full_name"].items] == [1, 2, 3, 4]
    assert found["full_name"].items[0] == (1, "MUHAMMAD BILAL TARIQ")
    assert found["father_name"] == Finding("variant", "father_name", [(2, "Tariq Mehmood"), (3, "Tariq Mahmood")])


def test_one_different_name_is_a_mismatch():
    docs = [(1, TYPES["passport"], passport("SARA AHMED", "KHAN")),
            (2, TYPES["transcript"], {"student_name": "Sara Ahmed Khan"}),
            (3, TYPES["ielts_trf"], {"first_name": "Zara", "family_name": "Malik"})]
    [f] = cross_check(docs, V)
    assert f.kind == "mismatch" and f.field == "full_name" and len(f.items) == 3


def test_single_document_no_findings():
    assert cross_check([(1, TYPES["passport"], passport("SARA AHMED", "KHAN"))], V) == []
