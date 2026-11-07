"""P2-T6: the format file, the template and the reader with its legacy layouts (P2 spec §4.6; master R-67, R-68)."""

import csv

import openpyxl
import pytest

from app.os.knowledge.sheets.format import load_format
from app.os.knowledge.sheets.reader import SheetError, read_batch
from app.os.knowledge.sheets.template import queue_export, write_template

from .helpers import fact, inst, workbook

pytestmark = pytest.mark.req("R-67")


def test_template_has_the_three_sheets_the_checker_columns_and_lists(tmp_path):
    path = write_template(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(path)
    fmt = load_format()
    assert wb.sheetnames == ["Institutions", "Programmes", "Facts", "Lists"]
    for name in ("Institutions", "Programmes", "Facts"):
        assert [c.value for c in wb[name][1]] == list(fmt.all_columns(name))
    assert [c.value for c in wb["Programmes"][1]][:6] == ["programme_id", "inst_id", "campus", "programme", "level", "field"]
    assert "checker2_approved" in [c.value for c in wb["Facts"][1]]
    lists = {wb["Lists"].cell(1, c).value: [wb["Lists"].cell(r, c).value for r in range(2, 12)]
             for c in range(1, wb["Lists"].max_column + 1)}
    assert set(fmt.claude_statuses) <= set(lists["claude_status"])  # found / unconfirmed / conflict / ... (R-67)
    b = read_batch(path)
    assert all(rows == [] for rows in b.sheets.values())


def test_reads_rows_with_their_file_row_numbers_and_skips_blank_rows(tmp_path):
    path = workbook(tmp_path, [inst(1), {}, inst(2)], [fact(1, "T-INST-001")])
    b = read_batch(path)
    assert [r["inst_id"] for r in b.sheets["Institutions"]] == ["T-INST-001", "T-INST-002"]
    assert [r["_row"] for r in b.sheets["Institutions"]] == [2, 4]
    assert b.blank_rows["Institutions"] == 1 and len(b.sha256) == 64


def test_csv_folder_is_the_same_batch(tmp_path):
    xlsx = workbook(tmp_path, [inst(1)], [fact(1, "T-INST-001")])
    folder = tmp_path / "csv"
    folder.mkdir()
    wb = openpyxl.load_workbook(xlsx)
    for name in ("Institutions", "Facts"):
        with (folder / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows([[("" if c is None else c) for c in row] for row in wb[name].iter_rows(values_only=True)])
    a, b = read_batch(xlsx), read_batch(folder)
    strip = lambda rows: [{k: v for k, v in r.items() if k != "_row"} for r in rows]
    assert strip(a.sheets["Institutions"]) == strip(b.sheets["Institutions"])
    assert strip(a.sheets["Facts"]) == strip(b.sheets["Facts"])


def test_missing_sheet_or_column_refuses_the_whole_file(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Institutions"
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(SheetError, match="Facts"):
        read_batch(tmp_path / "x.xlsx")
    wb = openpyxl.Workbook()
    wb.active.title = "Institutions"
    wb.active.append(["inst_id", "name"])
    wb.create_sheet("Facts").append(["fact_id"])
    wb.save(tmp_path / "y.xlsx")
    with pytest.raises(SheetError, match="required column"):
        read_batch(tmp_path / "y.xlsx")
    with pytest.raises(SheetError):
        read_batch(tmp_path / "nope.xlsx")


def _legacy(tmp_path, header, rows):
    wb = openpyxl.Workbook()
    wb.active.title = "Institutions"
    wb.active.append(list(load_format().all_columns("Institutions")))
    wb.create_sheet("Facts").append(list(load_format().all_columns("Facts")))
    ws = wb.create_sheet("Programmes")
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(tmp_path / "legacy.xlsx")
    return read_batch(tmp_path / "legacy.xlsx")


COMMON = ["inst_id", "intake", "retrieved", "claude_status", "claude_note", "checker1_result", "checker2_approved"]


def test_legacy_seats_and_closing_layout_becomes_up_to_three_canonical_rows(tmp_path):
    header = ["programme_id", "programme", "open_merit_seats", "total_seats", "closing_open_merit_aggregate",
              "closing_source_url", "seats_source_url", "seats_quote", *COMMON]
    b = _legacy(tmp_path, header, [["P1", "Test Medicine", "313", "325", "94.8", "https://a.test/closing",
                                     "https://a.test/seats", "| 1 | Alpha | 313 |", "I1", "Session 2025-26",
                                     "2026-11-03", "found", None, "correct", "yes"]])
    assert b.layouts == {"Programmes": "programmes_seats_closing"}
    seats, total, closing = b.sheets["Programmes"]
    assert (seats["seat_category"], seats["seats"], seats["source_url"], seats["quote_verbatim"]) == (
        "open_merit", "313", "https://a.test/seats", "| 1 | Alpha | 313 |")
    assert (total["seat_category"], total["seats"], total["quote_verbatim"]) == ("total", "325", None)
    assert (closing["closing_merit"], closing["source_url"], closing["quote_verbatim"]) == (
        "94.8", "https://a.test/closing", None)
    assert {r["programme_id"] for r in b.sheets["Programmes"]} == {"P1"} and seats["checker1_result"] == "correct"
    assert [r["_row"] for r in b.sheets["Programmes"]] == [2, 2, 2]


def test_legacy_cut_off_layout_keeps_the_scale_and_the_page_status_in_the_note(tmp_path):
    header = ["programme_id", "programme", "cut_off_out_of_550", "status_on_page", "source_url", "quote_verbatim", *COMMON]
    b = _legacy(tmp_path, header, [["P1", "Commerce", "291", "Open", "https://a.test/c", "| X | 291 |", "I1",
                                     "previous cycle", "2026-11-03", "found", "a note", "correct", "yes"]])
    [row] = b.sheets["Programmes"]
    assert (row["closing_merit"], row["closing_scale"]) == ("291", 550)
    assert row["claude_note"] == "a note | status_on_page: Open"


def test_legacy_merit_formula_and_programme_name_layouts(tmp_path):
    header = ["programme_id", "programme_group", "merit_formula", "intermediate_marks_used", "source_url",
              "quote_verbatim", *COMMON]
    b = _legacy(tmp_path, header, [["P1", "BS Engineering", "Test 33% + HSSC 50% + SSC 17%", "Part I", "https://a.test/m",
                                     "| 33% |", "I1", "Fall 2026", "2026-11-03", "found", None, "correct", "yes"]])
    [row] = b.sheets["Programmes"]
    assert row["programme"] == "BS Engineering" and row["merit_formula"].startswith("Test 33%")
    assert "intermediate_marks_used: Part I" in row["claude_note"]
    header = ["programme_id", "campus", "programme_name", "level", "source_url", *COMMON]
    b = _legacy(tmp_path, header, [["P1", "Main", "Test Law", "bachelor", "https://a.test/l", "I1", "2026", "2026-11-03",
                                     "found", None, "correct", "yes"]])
    assert b.layouts == {"Programmes": "programmes_batch1"} and b.sheets["Programmes"][0]["programme"] == "Test Law"


def test_queue_export_writes_the_same_format_for_the_reviewers(tmp_path):
    path = queue_export([{"entity_id": "T-INST-001", "field": "deadline_close", "value": "x", "intake": "Fall 2027",
                          "source_url": "https://a.test/n", "quote_verbatim": "q", "status": "unconfirmed"}],
                        tmp_path / "queue.xlsx")
    b = read_batch(path)
    [row] = b.sheets["Facts"]
    assert (row["fact_id"], row["claude_status"], row["checker1_result"]) == ("Q-0001", "unconfirmed", None)
