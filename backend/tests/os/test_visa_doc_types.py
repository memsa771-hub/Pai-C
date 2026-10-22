"""Slice 6b Task 1: three visa document types, added by YAML only (spec S6b-D6, the Slice 3 promise)."""

from app.os.documents.checks import cross_check, load_name_variants
from app.os.documents.types import TYPES_DIR, load_document_types, reading_model

TYPES = load_document_types()
NEW = {"admission_letter": {"student_name", "institution", "programme", "start_date", "issue_date"},
       "blocked_account_confirmation": {"holder_name", "provider", "amount", "monthly_payout", "issue_date"},
       "insurance_certificate": {"holder_name", "insurer", "cover_start", "cover_end"}}


def test_visa_types_load():
    for key, fields in NEW.items():
        t = TYPES[key]
        assert {f.name for f in t.fields} == fields, key
        reading_model(t)  # the reader's output model builds from the YAML alone
        assert (TYPES_DIR / f"{key}.v1.yaml").is_file()  # config, not code


def test_holder_names_cross_checked():
    for key in NEW:
        names = [f for f in TYPES[key].fields if f.cross_check == "full_name"]
        assert len(names) == 1, key
    docs = [(1, TYPES["passport"], {"given_names": "SARA AHMED", "surname": "KHAN"}),
            (2, TYPES["blocked_account_confirmation"], {"holder_name": "Sara Ahmed Khan"}),
            (3, TYPES["insurance_certificate"], {"holder_name": "Ali Raza"})]
    [finding] = cross_check(docs, load_name_variants())
    assert (finding.kind, finding.field) == ("mismatch", "full_name")
    assert [i[0] for i in finding.items] == [1, 2, 3]


def test_amounts_are_numbers():
    fields = {f.name: f for f in TYPES["blocked_account_confirmation"].fields}
    assert fields["amount"].type == "number" and fields["monthly_payout"].type == "number"
