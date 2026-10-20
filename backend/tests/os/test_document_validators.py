"""Slice 3 Task 4: validators (spec S3-D6). The MRZ is the ICAO 9303 specimen; every other value is synthetic."""

from datetime import date

import pytest

from app.os.documents.types import load_document_types
from app.os.documents.validators import band_round, check_value, mrz_check, mrz_fields, validate

L1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
L2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
TODAY = date(2026, 10, 20)
TYPES = load_document_types()


def passport(**over) -> dict:
    v = {"surname": "ERIKSSON", "given_names": "ANNA MARIA", "date_of_birth": "1974-08-12", "sex": "F",
         "passport_number": "L898902C3", "issue_date": "2022-04-16", "expiry_date": "2032-04-15",
         "country_code": "UTO", "mrz_line1": L1, "mrz_line2": L2.replace("120415", "320415")}
    return v | over


def _with_digit(line2: str, pos: int, digit: str) -> str:
    return line2[:pos] + digit + line2[pos + 1:]


# --- MRZ -----------------------------------------------------------------------------------------------------


def test_mrz_specimen_valid():
    assert len(L1) == len(L2) == 44
    assert mrz_check(L1, L2) == []
    f = mrz_fields(L2)
    assert f == {"number": "L898902C3", "birth": date(1974, 8, 12), "expiry": date(2012, 4, 15)}


def test_mrz_one_digit_wrong():
    bad = _with_digit(L2, 9, "7")  # the document number's check digit
    assert any("document number" in r for r in mrz_check(L1, bad))
    bad = _with_digit(L2, 43, "1")  # the composite check digit
    assert any("composite" in r for r in mrz_check(L1, bad))
    assert any("44" in r for r in mrz_check(L1, L2[:-1]))


def test_mrz_disagrees_with_visual():
    # An expiry of 2032 keeps the passport valid; recompute the check digits for that line
    line2 = _fix_digits(L2.replace("120415", "320415"))
    out = validate(TYPES["passport"], passport(mrz_line2=line2, passport_number="L898902C4"), TODAY)
    assert out["passport_number"][0] == "check_failed"
    assert any("machine-readable" in r for r in out["passport_number"][1])
    assert out["date_of_birth"] == ("ok", [])
    assert out["mrz_line2"] == ("ok", [])


def test_mrz_wrong_check_digit_marks_line():
    out = validate(TYPES["passport"], passport(mrz_line2=L2.replace("120415", "320415")), TODAY)
    # the expiry changed but its check digit did not
    assert out["mrz_line2"][0] == "check_failed"


# --- values --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("x, want", [(7.25, 7.5), (7.75, 8.0), (8.125, 8.0), (7.125, 7.0), (6.5, 6.5), (6.6, 6.5)])
def test_band_mean_rounding(x, want):
    assert band_round(x) == want


def test_band_mean_rule():
    t = TYPES["ielts_trf"]
    ok = {"listening": 8.0, "reading": 7.5, "writing": 6.5, "speaking": 7.0, "overall": 7.5}  # mean 7.25 → 7.5
    assert validate(t, ok, TODAY)["overall"] == ("ok", [])
    out = validate(t, ok | {"overall": 8.0}, TODAY)
    assert out["overall"][0] == "check_failed" and "7.5" in out["overall"][1][0]


def test_band_value_steps():
    spec = TYPES["ielts_trf"].field("writing")
    assert check_value(spec, 6.5) == [] and check_value(spec, 6.3) and check_value(spec, 9.5)


def test_marks_lte_total():
    t = TYPES["ssc_certificate"]
    out = validate(t, {"marks_obtained": 1050.0, "marks_total": 1100.0}, TODAY)
    assert out["marks_obtained"] == ("ok", [])
    out = validate(t, {"marks_obtained": 1150.0, "marks_total": 1100.0}, TODAY)
    assert out["marks_obtained"][0] == "check_failed" and out["marks_total"] == ("ok", [])


def test_lte_skipped_when_scale_missing():
    out = validate(TYPES["transcript"], {"cgpa": 3.4}, TODAY)
    assert out["cgpa"] == ("ok", []) and out["cgpa_scale"] == ("missing", [])


def test_expired_passport_flagged():
    line2 = _fix_digits(L2)  # the specimen expired in 2012
    out = validate(TYPES["passport"], passport(expiry_date="2012-04-15", mrz_line2=line2), TODAY)
    assert out["expiry_date"] == ("check_failed", ["expired"])


def test_bad_date_marked_not_dropped():
    values = passport(issue_date="31/02/2024")
    out = validate(TYPES["passport"], values, TODAY)
    assert out["issue_date"][0] == "check_failed"
    assert values["issue_date"] == "31/02/2024"  # kept as read; the student confirms or clears it
    assert check_value(TYPES["passport"].field("issue_date"), "2024-02-31")  # ISO shape, not a real date


def test_code_pattern_and_enum():
    p = TYPES["passport"]
    assert check_value(p.field("country_code"), "UTO") == []
    assert check_value(p.field("country_code"), "ut0")
    assert check_value(p.field("sex"), "F") == [] and check_value(p.field("sex"), "Q")


def test_missing_values():
    out = validate(TYPES["passport"], {}, TODAY)
    assert out["surname"] == ("missing", []) and set(out) == {f.name for f in TYPES["passport"].fields}


def _fix_digits(line2: str) -> str:
    """Recompute every check digit of a TD3 second line (test helper)."""
    from app.os.documents.validators import check_digit

    s = list(line2)
    s[9] = check_digit(line2[0:9])
    s[19] = check_digit(line2[13:19])
    s[27] = check_digit(line2[21:27])
    s[42] = check_digit(line2[28:42])
    j = "".join(s)
    s[43] = check_digit(j[0:10] + j[13:20] + j[21:43])
    return "".join(s)
