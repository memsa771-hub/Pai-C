"""P2-T6: the command line (P2 spec §4.6): template, validate (no database), import in either mode, undo, list."""

from datetime import date

import openpyxl
import pytest
import yaml

from scripts.os_import_batch import main
from tests.os.registry.helpers import LIST_URL

from .helpers import COUNTRY, deps, fact, inst, load_list, workbook

pytestmark = pytest.mark.req("R-68")


def run(argv, d=None):
    out: list[str] = []
    code = main(argv, deps=d, out=out.append)
    return code, "\n".join(out)


def test_template_command(tmp_path):
    code, text = run(["template", str(tmp_path / "t.xlsx")])
    assert code == 0 and openpyxl.load_workbook(tmp_path / "t.xlsx").sheetnames[:3] == ["Institutions", "Programmes", "Facts"]


def test_validate_is_a_dry_run_with_list_files_and_a_report(tmp_path):
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "a.yaml").write_text(yaml.safe_dump({"region": "national", "retrieved": date(2026, 11, 7), "lists": [
        {"id": "alpha-list", "body": "Alpha", "name": "Alpha list", "url": LIST_URL, "row_count": 2}]}))
    path = workbook(tmp_path, [inst(1), inst(2, source_url="https://elsewhere.alpha.test/x")], [fact(1, "T-INST-001")])
    code, text = run(["validate", str(path), "--country", COUNTRY, "--lists", str(lists), "--report",
                      str(tmp_path / "r.csv")])
    assert code == 0 and "Institutions: accepted 1" in text and "rejected 1" in text and "verified 1" in text
    assert "no_official_list" in (tmp_path / "r.csv").read_text()
    code, text = run(["validate", str(path), "--country", COUNTRY, "--lists", str(lists), "--no-list-needed"])
    assert "rejected" in text and "Institutions: accepted 2" in text


def test_bad_arguments_and_files_are_refused_with_exit_code_2(tmp_path):
    code, text = run(["validate", str(tmp_path / "missing.xlsx"), "--country", COUNTRY])
    assert code == 2 and text.startswith("refused:")
    with pytest.raises(SystemExit):  # one of the two modes is required
        run(["import", "x.xlsx", "--country", COUNTRY, "--actor", "dev"])


def test_import_undo_and_list(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    path = workbook(tmp_path, [inst(1)], [fact(1, "T-INST-001")])
    code, text = run(["import", str(path), "--country", COUNTRY, "--owner-accepted", "chat 2026-11-07", "--actor", "dev"], d)
    assert code == 0 and "import 1 done" in text
    code, text = run(["import", str(path), "--country", COUNTRY, "--owner-accepted", "chat 2026-11-07", "--actor", "dev"], d)
    assert code == 2 and "already imported" in text
    code, text = run(["list"], d)
    assert "owner_accepted" in text and "batch.xlsx" in text and "\tdone\t" in text
    code, text = run(["undo", "1", "--actor", "admin"], d)
    assert code == 0 and "1 facts, 1 registry rows" in text
    code, text = run(["undo", "1", "--actor", "admin"], d)
    assert code == 2 and "already undone" in text
    code, text = run(["undo", "99", "--actor", "admin"], d)
    assert code == 2
