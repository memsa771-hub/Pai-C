"""P2-T6: a cell that starts like a formula is neutralised in everything the import writes (CSV formula injection)."""

import csv
import io

import openpyxl
import pytest

from app.os.knowledge.sheets.importer import report_text
from app.os.knowledge.sheets.plan import RowResult
from app.os.knowledge.sheets.safe import safe_cell
from app.os.knowledge.sheets.template import (
    queue_export,
    workbook_bytes,
    write_workbook,
)

pytestmark = pytest.mark.req("R-68")


@pytest.mark.parametrize("text", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx", " =1+1", "  @x", " \t-1"])
def test_risky_starts_get_an_apostrophe(text):
    assert safe_cell(text) == "'" + text


@pytest.mark.parametrize("value", ["plain", "a=b", "", None, 5, 2.5])
def test_everything_else_is_unchanged(value):
    assert safe_cell(value) == value


def test_the_report_neutralises_cells_from_the_file():
    rows = [RowResult("Facts", "=cmd|' /C calc'!A0", 2, "rejected", None, "bad", "@evil"),
            RowResult("Facts", "F-2", 3, "accepted", "verified", "both_checks", "")]
    parsed = list(csv.reader(io.StringIO(report_text(rows))))
    assert parsed[1][1] == "'=cmd|' /C calc'!A0" and parsed[1][6] == "'@evil" and parsed[2][1] == "F-2"


def test_workbooks_the_import_writes_carry_no_formulas(tmp_path):
    rows = {"Facts": [{"fact_id": "=1+1", "entity_id": "-5", "field": "ok"}]}
    for wb in (openpyxl.load_workbook(write_workbook(tmp_path / "w.xlsx", rows)),
               openpyxl.load_workbook(io.BytesIO(workbook_bytes(rows)))):
        ws = wb["Facts"]
        assert ws["A2"].value == "'=1+1" and ws["A2"].data_type != "f" and ws["B2"].value == "'-5"
    q = openpyxl.load_workbook(queue_export([{"entity_id": "@x", "field": "f", "value": "=2", "status": "unconfirmed"}],
                                            tmp_path / "q.xlsx"))["Facts"]
    assert q["B2"].value == "'@x" and q["D2"].value == "'=2" and q["A2"].value == "Q-0001"
