"""P2-T14: a batch file in the one format, built from re-entered values and their checks (P2 spec §4.6, §11.3)."""

import hashlib

import openpyxl
import pytest
import yaml

from app.os.knowledge.sheets.format import load_format
from app.os.knowledge.sheets.reader import read_batch
from scripts.os_import_batch import main as validate
from scripts.os_values_sheet import PROVENANCE_SHEET, main

from .helpers import COUNTRY, NOTICE, fact, inst, prog, workbook

pytestmark = pytest.mark.req("R-67", "R-68", "R-76")

MAPPING = {
    "sheet": "Programmes", "key": "programme_id",
    "values": {"seat_category": "seat_category", "seats": "seats", "quote_verbatim": "quote_verbatim",
               "source_url": "source_url"},
    "checks": [
        {"checker": 1, "columns": {"check1": "checker1_result", "note": "checker_note"}},
        {"checker": 2, "columns": {"check2_result": "checker2_approved", "check2_note": "checker_note"},
         "translate": {"correct": "yes"}},
    ],
}
N1, N2 = "Test check one", "Test check two (independent)"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_csv(path, header, rows):
    path.write_text("\n".join([",".join(header), *(",".join(r) for r in rows)]) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path):
    base = workbook(tmp_path, [inst(1)], [fact(1, "T-INST-001")],
                    [prog(1, "T-INST-001", seats=None, seat_category=None, quote_verbatim="Row 1 | 30",
                          claude_note="base note"),
                     prog(2, "T-INST-001", seats=None, seat_category=None, quote_verbatim="Row 2 | 41"),
                     prog(3, "T-INST-001", seats="7")], name="base.xlsx")
    values = write_csv(tmp_path / "values.csv", ["programme_id", "seat_category", "seats", "quote_verbatim", "source_url"],
                       [["T-PRG-001", "open_merit", "30", "Row 1 | 30", NOTICE],
                        ["T-PRG-002", "", "41", "Row 2 | 41", NOTICE],
                        ["T-PRG-099", "", "5", "Row 99 | 5", NOTICE]])
    c1 = write_csv(tmp_path / "c1.csv", ["programme_id", "check1", "note"],
                   [["T-PRG-001", "correct", "seen on page"], ["T-PRG-002", "correct", ""]])
    c2 = write_csv(tmp_path / "c2.csv", ["programme_id", "check2_result", "check2_note"],
                   [["T-PRG-001", "correct", "value in quote"], ["T-PRG-002", "n/a", "not checked"]])
    mapping = tmp_path / "map.yaml"
    mapping.write_text(yaml.safe_dump(MAPPING, allow_unicode=True), encoding="utf-8")
    return tmp_path, base, values, c1, c2, mapping


def run(tmp, base, values, c1, c2, mapping, out="out.xlsx"):
    lines: list[str] = []
    code = main([str(base), "--mapping", str(mapping), "--values", str(values),
                 "--check", str(c1), "--checker-name", N1, "--checker-date", "2026-11-08",
                 "--check", str(c2), "--checker-name", N2, "--checker-date", "2026-11-09",
                 "--out", str(tmp / out)], out=lines.append)
    return code, "\n".join(lines), tmp / out


def test_builds_a_sheet_the_validator_reads_with_values_and_checks_in_their_columns(files):
    code, text, out = run(*files)
    assert code == 0, text
    fmt = load_format()
    b = read_batch(out)
    assert b.layouts == {} and b.sheets["Institutions"] == [] and b.sheets["Facts"] == []
    rows = {r["programme_id"]: r for r in b.sheets["Programmes"]}
    assert set(rows) == {"T-PRG-001", "T-PRG-002"}  # only the keys of the values CSV
    r1, r2 = rows["T-PRG-001"], rows["T-PRG-002"]
    assert (r1["seats"], r1["seat_category"], r1["quote_verbatim"]) == ("30", "open_merit", "Row 1 | 30")
    assert (r1["checker1_result"], r1["checker1_name"], r1["checker1_date"]) == ("correct", N1, "2026-11-08")
    assert (r1["checker2_approved"], r1["checker2_name"], r1["checker2_date"]) == ("yes", N2, "2026-11-09")
    assert r1["checker_note"] == "C1: seen on page | C2: value in quote"
    # nothing else changes: every other canonical column is the base row's, read the way the import reads it
    base = {r["programme_id"]: r for r in read_batch(files[1]).sheets["Programmes"]}
    others = [c for c in fmt.sheets["Programmes"].columns if c not in MAPPING["values"]]
    assert all(r1[c] == base["T-PRG-001"][c] for c in others) and r1["claude_note"] == "base note"
    assert r2["seat_category"] is None and r2["seats"] == "41"
    lines: list[str] = []  # `os_import_batch validate` reads it unchanged (its institutions are not in this file)
    assert validate(["validate", str(out), "--country", COUNTRY,
                     "--report", str(files[0] / "r.csv")], out=lines.append) == 0
    assert "Programmes: accepted 0, unconfirmed 0, queued 0, rejected 2, skipped 0" in lines
    assert (files[0] / "r.csv").read_text().count("institution_not_loaded") == 2
    # dry run only: the institutions the base file would load resolve the rows' inst_ids
    lines.clear()
    assert validate(["validate", str(out), "--country", COUNTRY, "--no-list-needed", "--institutions-from",
                     str(files[1]), "--report", str(files[0] / "r2.csv")], out=lines.append) == 0
    assert "institutions from base.xlsx: 1" in lines
    assert "institution_not_loaded" not in (files[0] / "r2.csv").read_text()


def test_unknown_key_is_reported_not_written_and_na_check_is_empty(files):
    code, text, out = run(*files)
    assert "not written (not_in_base, 1): T-PRG-099" in text and "not_written 1" in text
    assert "written_without_value 0" in text
    r2 = {r["programme_id"]: r for r in read_batch(out).sheets["Programmes"]}["T-PRG-002"]
    assert r2["checker2_approved"] is None and r2["checker2_name"] is None and r2["checker2_date"] is None
    assert r2["checker1_result"] == "correct" and r2["checker_note"] == "C2: not checked"
    assert "checker2_outside_vocabulary 1" in text and "checker2_yes 1" in text and "checker1_correct 2" in text


def test_provenance_records_each_input_with_its_sha256_and_the_command(files):
    tmp, base, values, c1, c2, mapping = files
    code, _, out = run(*files)
    ws = openpyxl.load_workbook(out)[PROVENANCE_SHEET]
    rows = {r[1]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    for p in (base, values, c1, c2, mapping):
        assert rows[p.name][2] == sha(p)
    command = next(r[1] for r in rows.values() if r[0] == "command")
    assert command.startswith("python -m scripts.os_values_sheet ") and "--checker-name" in command
    assert any(r[0] == f"checker2 ({N2}, 2026-11-09)" for r in rows.values())


def test_inputs_are_unchanged_and_the_output_cannot_be_an_input(files):
    tmp, base, values, c1, c2, mapping = files
    before = [sha(p) for p in (base, values, c1, c2, mapping)]
    assert run(*files)[0] == 0
    code, text, _ = run(*files, out="base.xlsx")
    assert code == 2 and text.startswith("refused:")
    assert [sha(p) for p in (base, values, c1, c2, mapping)] == before


def test_a_mapping_to_a_column_the_sheet_lacks_is_refused(files):
    tmp, base, values, c1, c2, mapping = files
    bad = dict(MAPPING, values={"seats": "no_such_column"})
    mapping.write_text(yaml.safe_dump(bad), encoding="utf-8")
    code, text, out = run(*files)
    assert code == 2 and "no_such_column" in text and not out.exists()


def test_a_legacy_base_layout_is_read_the_way_the_import_reads_it(files):
    tmp, _, values, c1, c2, mapping = files
    fmt = load_format()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name in ("Institutions", "Facts"):
        wb.create_sheet(name).append(list(fmt.all_columns(name)))
    ws = wb.create_sheet("Programmes")
    ws.append(["programme_id", "inst_id", "programme", "intake", "cut_off_out_of_550", "status_on_page", "source_url",
               "quote_verbatim", "retrieved", "claude_status", "checker1_result", "checker1_name"])
    ws.append(["T-PRG-001", "T-INST-001", "Test Medicine", "Session 2026-27", None, "seat allocation", NOTICE,
               "Row 1 | 30", "2026-11-03", "found", "correct", "old check"])
    wb.save(tmp / "legacy.xlsx")
    code, text, out = run(tmp, tmp / "legacy.xlsx", values, c1, c2, mapping)
    assert code == 0 and "not_in_base" in text  # T-PRG-002 and T-PRG-099 are not in this base
    (r,) = read_batch(out).sheets["Programmes"]
    assert r["closing_scale"] == 550 and r["claude_note"] == "status_on_page: seat allocation"
    assert r["seats"] == "30" and r["checker1_name"] == N1  # the base row's old check is not kept


def rewrite(path, header, rows):
    return write_csv(path, header, rows)


def test_a_doubted_check_holds_the_row_and_a_row_without_value_is_not_written(files):
    tmp, base, values, c1, c2, mapping = files
    m = yaml.safe_load(mapping.read_text(encoding="utf-8"))
    m["checks"][1]["skip_results"] = ["Unclear"]
    m["checks"][1]["translate"] = {"Correct": "yes"}  # keys are matched in any case
    mapping.write_text(yaml.safe_dump(m), encoding="utf-8")
    rewrite(values, ["programme_id", "seat_category", "seats", "quote_verbatim", "source_url"],
            [["T-PRG-001", "", "30", "Row 1 | 30", NOTICE], ["T-PRG-002", "", "", "Row 2 | 41", NOTICE],
             ["T-PRG-003", "", "7", "q", NOTICE]])
    rewrite(c2, ["programme_id", "check2_result", "check2_note"],
            [["T-PRG-001", "correct", ""], ["T-PRG-003", "unclear", "cannot see the table"]])
    code, text, out = run(*files)
    assert code == 0, text
    assert "not written (no_value_not_written, 1): T-PRG-002" in text
    assert "not written (held_for_review, 1): T-PRG-003" in text
    (r,) = read_batch(out).sheets["Programmes"]
    assert r["programme_id"] == "T-PRG-001" and r["checker2_approved"] == "yes"


def test_duplicate_and_missing_keys_are_reported(files):
    tmp, base, values, c1, c2, mapping = files
    rewrite(values, ["programme_id", "seat_category", "seats", "quote_verbatim", "source_url"],
            [["T-PRG-001", "", "30", "q", NOTICE], ["T-PRG-001", "", "31", "q", NOTICE],
             ["T-PRG-002", "", "41", "q", NOTICE]])
    rewrite(c1, ["programme_id", "check1", "note"],
            [["T-PRG-002", "correct", ""], ["T-PRG-002", "wrong", ""], ["", "correct", ""], ["T-PRG-077", "x", ""],
             ["T-PRG-077", "y", ""]])
    code, text, out = run(*files)
    assert "not written (duplicate_key, 1): T-PRG-001" in text
    assert "not written (checker1_duplicate_key, 2): T-PRG-002, T-PRG-077" in text
    assert "not written (checker1_no_key, 1): c1.csv line 4" in text
    assert [r["programme_id"] for r in read_batch(out).sheets["Programmes"]] == ["T-PRG-001"]
    assert read_batch(out).sheets["Programmes"][0]["seats"] == "30"  # the first row of a doubled values key


def test_a_key_that_is_several_base_rows_is_not_written(files):
    tmp, _, values, c1, c2, mapping = files
    fmt = load_format()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name in ("Institutions", "Facts"):
        wb.create_sheet(name).append(list(fmt.all_columns(name)))
    ws = wb.create_sheet("Programmes")
    ws.append(["programme_id", "inst_id", "programme", "intake", "open_merit_seats", "total_seats",
               "closing_open_merit_aggregate", "seats_source_url", "seats_quote", "retrieved", "claude_status"])
    ws.append(["T-PRG-001", "T-INST-001", "Test Medicine", "Session 2026-27", "10", "20", None, NOTICE, "q",
               "2026-11-03", "found"])
    wb.save(tmp / "split.xlsx")
    code, text, out = run(tmp, tmp / "split.xlsx", values, c1, c2, mapping)
    assert code == 0 and "not written (several_base_rows, 1): T-PRG-001" in text


@pytest.mark.parametrize("change, message", [
    (lambda m: m["checks"][1].update(checker=1), "distinct `checker` of 1 or 2"),
    (lambda m: m["checks"][1].update(checker=3), "distinct `checker` of 1 or 2"),
])
def test_checker_numbers_must_be_one_and_two(files, change, message):
    tmp, base, values, c1, c2, mapping = files
    m = yaml.safe_load(mapping.read_text(encoding="utf-8"))
    change(m)
    mapping.write_text(yaml.safe_dump(m), encoding="utf-8")
    code, text, out = run(*files)
    assert code == 2 and message in text and not out.exists()


def test_a_values_csv_without_the_key_column_is_refused(files):
    tmp, base, values, c1, c2, mapping = files
    rewrite(values, ["id", "seat_category", "seats", "quote_verbatim", "source_url"], [["T-PRG-001", "", "1", "q", "u"]])
    code, text, out = run(*files)
    assert code == 2 and "no key column programme_id" in text


def test_rows_written_without_any_value_are_counted(files):
    tmp, base, values, c1, c2, mapping = files
    m = yaml.safe_load(mapping.read_text(encoding="utf-8"))
    m["values"] = {"quote_verbatim": "quote_verbatim"}  # no value column mapped: the base rows have no seats
    mapping.write_text(yaml.safe_dump(m), encoding="utf-8")
    code, text, out = run(*files)
    assert code == 0 and "written 2" in text and "written_without_value 2" in text
