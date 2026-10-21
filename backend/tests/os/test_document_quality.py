"""Slice 3 Task 10: the sample set, the scoring and the Spike 2 runner, offline (no model, no real document)."""

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.os.documents.checks import cross_check, load_name_variants
from app.os.documents.types import load_document_types
from app.os.documents.validators import validate
from tests.os.quality import make_sample_docs as samples
from tests.os.quality.doc_scoring import score
from tests.os.quality.run_document_quality import bundle_verdict, main

TYPES = load_document_types()
KEY = yaml.safe_load((samples.SAMPLES / samples.KEY_NAME).read_text(encoding="utf-8"))


def test_sample_set_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    samples.write(a)
    samples.write(b)
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir())
    assert all((a / n).read_bytes() == (b / n).read_bytes() for n in names)  # the same bytes every time
    assert names == sorted(p.name for p in samples.SAMPLES.iterdir())  # the committed set is the generated one
    assert (a / samples.KEY_NAME).read_text(encoding="utf-8") == \
        (samples.SAMPLES / samples.KEY_NAME).read_text(encoding="utf-8")


def test_sample_set_shape():
    docs = KEY["documents"]
    base = {n: d for n, d in docs.items() if not d.get("variant_of")}
    assert len(base) == 30 and {d["type"] for d in base.values()} == set(TYPES)  # 5 bundles x 6 types
    assert sorted({d["person"] for d in base.values()}) == ["b1", "b2", "b3", "b4", "b5"]
    assert {n for n, d in docs.items() if d.get("variant_of")} == {"b1_passport_rotated.png", "b5_transcript_lowres.jpg"}
    for name, d in docs.items():
        assert set(d["fields"]) == {f.name for f in TYPES[d["type"]].fields}, name  # every field, null if absent


def test_sample_values_pass_their_checks():
    """The fictional documents are valid: MRZ check digits, band means, marks and CGPA within their totals."""
    for name, d in KEY["documents"].items():
        checks = validate(TYPES[d["type"]], d["fields"], date(2026, 10, 21))
        failed = {f: r for f, (c, r) in checks.items() if c == "check_failed"}
        assert failed == {}, (name, failed)


def test_sample_images_carry_the_mark():
    from PIL import Image

    for p in samples.SAMPLES.iterdir():
        if p.suffix in (".png", ".jpg"):
            with Image.open(p) as img:
                assert min(img.size) >= 300, p.name
    assert "SAMPLE" in samples.MARK and "TEST DOCUMENT" in samples.MARK


def test_scoring_invented_counts_wrong():
    key = {"t.png": {"type": "transcript", "fields": {
        "student_name": "KHAN, SARA AHMED", "cgpa": 3.7, "issue_date": "2024-08-01", "serial_number": None,
        "registration_number": "UOE-1014-CS", "institution": "University of Exampleton", "percentage": None}}}
    reading = {"student_name": "Sara Ahmed Khan", "cgpa": 3.70, "issue_date": "2024-08-01",
               "serial_number": "S-123",  # the key says absent: invented
               "registration_number": "UOE-1014-C5",  # one character wrong
               "institution": "university of  exampleton", "percentage": None}
    s = score(key, {"t.png": reading}, TYPES)
    assert (s.correct, s.scored, s.invented) == (4, 6, 1)  # percentage is absent in both: not scored
    assert s.rate == pytest.approx(4 / 6)
    assert s.type_rates() == {"transcript": round(4 / 6, 3)}
    failed = score(key, {"t.png": None}, TYPES)  # a failed reading: every keyed value is wrong
    assert (failed.correct, failed.scored) == (0, 5)


def test_planted_mismatches_found():
    """Cross-checks on the sample key values find exactly the planted findings."""
    variants = load_name_variants()
    found = {}
    for b in ("b1", "b2", "b3", "b4", "b5"):
        docs = [(i, TYPES[d["type"]], d["fields"]) for i, (n, d) in enumerate(sorted(KEY["documents"].items()))
                if d["person"] == b and not d.get("variant_of")]
        found[b] = [{"kind": f.kind, "field": f.field} for f in cross_check(docs, variants)]
    assert found == {b: e["expect"] for b, e in KEY["bundles"].items()}
    assert bundle_verdict(KEY["bundles"], found) == (True, [])


def test_bundle_verdict_fails_a_missed_or_extra_finding():
    expect = KEY["bundles"]
    ok, fails = bundle_verdict(expect, {"b1": [{"kind": "mismatch", "field": "father_name"}],
                                        "b2": [], "b3": [{"kind": "variant", "field": "father_name"}],
                                        "b4": [{"kind": "mismatch", "field": "date_of_birth"}],
                                        "b5": [{"kind": "variant", "field": "full_name"}] * 2})
    assert not ok
    assert fails == ["b1: consistent bundle got a mismatch", "b2: planted variant on full_name not caught",
                     "b3: planted mismatch on father_name not caught",
                     "b5: consistent bundle got more than one variant flag"]


def test_runner_offline_sample_set(tmp_path, capsys):
    out = tmp_path / "s.json"
    assert main(["--model", "test", "--set", "sample", "--mode", "whole", "--runs", "1", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    result = json.loads(out.read_text(encoding="utf-8"))
    [run] = result["runs"]
    assert result["gate_passed"] and run["correct_rate"] == 1.0 and run["invented"] == 0 and run["bundles_passed"]
    assert run["files"] == 32 and run["failed_readings"] == 0
    # rates and counts only: no value from the key is printed or written
    values = {str(v) for d in KEY["documents"].values() for v in d["fields"].values() if v is not None and len(str(v)) > 4}
    assert not [v for v in values if v in printed or v in out.read_text(encoding="utf-8")]


def test_runner_tiles_mode_offline(tmp_path):
    out = tmp_path / "t.json"
    assert main(["--model", "test", "--set", "sample", "--mode", "tiles", "--runs", "1", "--out", str(out)]) == 0


def test_runner_refuses_billed_run_on_unverified_key(tmp_path, monkeypatch):
    key = tmp_path / "answer_key.yaml"
    key.write_text(yaml.safe_dump({"verified": False, "documents": {}}), encoding="utf-8")
    monkeypatch.setenv("OS_OPENAI_API_KEY", "sk-test-not-a-real-key")
    args = ["--model", "openai", "--set", "real", "--docs", str(tmp_path), "--key", str(key), "--mode", "whole",
            "--out", str(tmp_path / "r.json")]
    assert main(args) == 2
    monkeypatch.delenv("OS_OPENAI_API_KEY")
    key.write_text(yaml.safe_dump({"verified": True, "documents": {}}), encoding="utf-8")
    assert main(args) == 2  # no model key: no billed run either


def test_runner_reports_a_missing_real_set(tmp_path, capsys):
    args = ["--model", "test", "--set", "real", "--docs", str(tmp_path / "nowhere"), "--key", str(tmp_path / "k.yaml"),
            "--mode", "whole", "--out", str(tmp_path / "r.json")]
    assert main(args) == 2
    assert "not here" in capsys.readouterr().err


def test_real_set_defaults_outside_the_repo():
    from tests.os.quality.run_document_quality import REAL_DOCS, REAL_KEY

    repo = Path(__file__).resolve().parents[3]
    assert not REAL_DOCS.is_relative_to(repo) and not REAL_KEY.is_relative_to(repo)


def test_scoring_counts_per_field():
    """The breakdown the owners need after a failed gate: per field name, how many were correct, wrong (both
    present, different), missed (the key has a value, the reader none) and invented. Names only, never values."""
    key = {"a.png": {"type": "transcript", "fields": {"cgpa": 3.7, "serial_number": None, "degree_title": "BS CS",
                                                       "issue_date": "2024-08-01"}},
           "b.png": {"type": "transcript", "fields": {"cgpa": 3.1, "serial_number": "S-1", "degree_title": "BS CS",
                                                       "issue_date": None}}}
    readings = {"a.png": {"cgpa": 3.7, "serial_number": "S-9", "degree_title": "BS Computer Science",
                          "issue_date": None},
                "b.png": {"cgpa": 3.1, "serial_number": "S-1", "degree_title": "BS CS", "issue_date": None}}
    s = score(key, readings, TYPES)
    assert s.field_counts() == {
        "transcript.cgpa": {"correct": 2, "wrong": 0, "missed": 0, "invented": 0},
        "transcript.degree_title": {"correct": 1, "wrong": 1, "missed": 0, "invented": 0},
        "transcript.issue_date": {"correct": 0, "wrong": 0, "missed": 1, "invented": 0},
        "transcript.serial_number": {"correct": 1, "wrong": 0, "missed": 0, "invented": 1},
    }


def test_runner_prints_field_breakdown_names_only(tmp_path, capsys):
    out = tmp_path / "s.json"
    assert main(["--model", "test", "--set", "sample", "--mode", "tiles", "--tier", "strong", "--runs", "1",
                 "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    result = json.loads(out.read_text(encoding="utf-8"))
    assert (result["mode"], result["tier"]) == ("tiles", "strong")
    [run] = result["runs"]
    assert run["per_field"]["passport.mrz_line2"] == {"correct": 6, "wrong": 0, "missed": 0, "invented": 0}
    assert "per field" in printed and "passport.mrz_line2" in printed
    values = {str(v) for d in KEY["documents"].values() for v in d["fields"].values() if v is not None and len(str(v)) > 4}
    assert not [v for v in values if v in printed or v in out.read_text(encoding="utf-8")]


def _verified_empty_set(tmp_path):
    key = tmp_path / "answer_key.yaml"
    key.write_text(yaml.safe_dump({"verified": True, "documents": {}}), encoding="utf-8")
    return ["--set", "real", "--docs", str(tmp_path), "--key", str(key), "--mode", "tiles",
            "--out", str(tmp_path / "r.json")]


def test_strong_tier_needs_its_prices(tmp_path, monkeypatch, capsys):
    """A billed strong run must not start without the strong model's list prices (cost() refuses to guess)."""
    monkeypatch.setenv("OS_OPENAI_API_KEY", "sk-test-not-a-real-key")
    for name in ("OS_PRICE_STRONG_IN", "OS_PRICE_STRONG_CACHED", "OS_PRICE_STRONG_OUT"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--model", "openai", "--tier", "strong", *_verified_empty_set(tmp_path)]) == 2
    assert "OS_PRICE_STRONG_CACHED" in capsys.readouterr().err


def test_runner_reads_model_and_prices_from_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OS_OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("OS_PRICE_STRONG_CACHED", "0.25")
    monkeypatch.setenv("OS_PRICE_STRONG_OUT", "15")
    monkeypatch.setenv("OS_MODEL_STRONG", "a-strong-model")
    assert main(["--model", "openai", "--tier", "strong", "--runs", "1", *_verified_empty_set(tmp_path)]) == 1
    result = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert (result["model"], result["tier"]) == ("a-strong-model", "strong")  # no files: nothing billed, gate fails
    assert "OS_PRICE" not in capsys.readouterr().err


# --- why a value is wrong (gate fix round): categories only, never a value ------------------------------------


@pytest.mark.parametrize("want, have, why", [
    ("Board of Education, Lahore", "BOARD OF EDUCATION LAHORE", "punctuation"),
    ("B.Sc. (Hons) Physics", "BSc Hons Physics", "punctuation"),
    ("University of X", "University of X, Lahore Campus", "words added"),
    ("Secondary School Certificate Examination, Annual 2020", "Secondary School Certificate Examination", "words missing"),
    ("12345678", "12345679", "one character"),
    ("2021-07-15", "2021-08-15", "one character"),
    ("Physics", "Chemistry", "other"),
])
def test_why_wrong_categories(want, have, why):
    from tests.os.quality.doc_scoring import why_wrong

    assert why_wrong(want, have) == why


def test_scoring_explains_wrong_values():
    key = {"a.png": {"type": "ssc_certificate", "fields": {"board": "Board of Education, Lahore",
                                                           "exam": "SSC Examination, Annual 2020", "grade": "A1"}},
           "b.png": {"type": "ssc_certificate", "fields": {"board": "Board of Education, Multan", "grade": "A"}}}
    readings = {"a.png": {"board": "BOARD OF EDUCATION LAHORE", "exam": "SSC Examination", "grade": "A1"},
                "b.png": {"board": "Board of Education, Multan", "grade": "B"}}
    s = score(key, readings, TYPES)
    assert s.wrong_why() == {"ssc_certificate.board": {"punctuation": 1},
                             "ssc_certificate.exam": {"words missing": 1},
                             "ssc_certificate.grade": {"one character": 1}}
    assert (s.correct, s.scored) == (2, 5)
    assert s.correct_ignoring_punctuation == 3  # informational: the gate still scores strictly


def test_runner_reports_why_names_only(tmp_path, capsys):
    out = tmp_path / "s.json"
    assert main(["--model", "test", "--set", "sample", "--mode", "whole", "--runs", "1", "--out", str(out)]) == 0
    [run] = json.loads(out.read_text(encoding="utf-8"))["runs"]
    assert run["wrong_why"] == {} and run["correct_rate_ignoring_punctuation"] == 1.0
    assert "ignoring punctuation" in capsys.readouterr().out
