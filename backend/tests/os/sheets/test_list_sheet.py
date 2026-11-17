"""P2-T29: an Institutions workbook for one official list, built from two independent extractions (P2 spec §4.6;
master R-35a, R-67, R-68). Fictional lists and colleges on `.test` domains only."""

import csv
import hashlib

import openpyxl
import pytest
import yaml

from app.os.knowledge.sheets.importer import build_context, plan_file
from app.os.knowledge.sheets.plan import REVIEWERS
from app.os.knowledge.sheets.reader import read_batch
from scripts.os_import_batch import _lists
from scripts.os_import_batch import main as import_main
from scripts.os_list_sheet import PROVENANCE_SHEET, main, norm

from .helpers import COUNTRY

pytestmark = pytest.mark.req("R-35", "R-67", "R-68")

URL = "https://lists.zeta.test/Colleges/Degree-Colleges/"  # mixed case and a trailing slash: written byte for byte
SHA, SHA_B = "a" * 64, "b" * 64
MAPPING = {"id_prefix": "ZT-DC-", "type": "public_college", "region": "list", "city_column": "city",
           "read_method": "curl + stdlib html.parser (HTML table)", "retrieved": "2026-11-14"}
C1, C2 = ("zeta-extract-check-1", "2026-11-14"), ("zeta-extract-check-2", "2026-11-15")
M1, M2 = "stdlib html.parser", "lxml xpath"
HEADER = ["key", "name", "quote", "city", "page", "doc_sha256"]


def row(k, name=None, quote=None, city="Zeta Town", sha=SHA):
    name = name or f"Test Degree College {k}"
    return [str(k), name, quote if quote is not None else f"{k} {name} {city}", city, "1", sha]


def alike(rows):
    """A second extraction that agrees after normalising but is not the same bytes: other row order, upper case."""
    return [[r[0], r[1].upper(), r[2].upper(), *r[3:]] for r in reversed(rows)]


def write_csv(path, rows, header=HEADER):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def lists_dir(tmp, *, row_count=3, check2="correct"):
    d = tmp / "lists"
    d.mkdir(exist_ok=True)
    (d / "zeta.yaml").write_text(yaml.safe_dump({"region": "Punjab", "retrieved": "2026-11-07", "lists": [
        {"id": "zeta-degree-colleges", "body": "Zeta Department", "name": "Degree Colleges", "url": URL,
         "institution_type": "public_college", "family": "intermediate", "row_count": row_count,
         "count_method": "counted table rows", "check2": check2}]}), encoding="utf-8")
    return d


def mapping(tmp, drop=(), **kw):
    p = tmp / "map.yaml"
    p.write_text(yaml.safe_dump({**{k: v for k, v in MAPPING.items() if k not in drop}, **kw}), encoding="utf-8")
    return p


def argv(tmp, e1, e2, *extra, lists=None, mp=None, methods=(M1, M2), checker2=C2, out="out.xlsx"):
    return ["--lists", str(lists or lists_dir(tmp)), "--list", "zeta-degree-colleges", "--country", COUNTRY,
            "--e1", str(e1), "--e2", str(e2), "--e1-method", methods[0], "--e2-method", methods[1],
            "--mapping", str(mp or mapping(tmp)), "--checker1", *C1, "--checker2", *checker2,
            "--out", str(tmp / out), *extra]


def run(tmp, e1_rows, e2_rows, *extra, e2_header=HEADER, header=HEADER, force=True, **kw):
    e1 = write_csv(tmp / "e1.csv", e1_rows, header)
    e2 = write_csv(tmp / "e2.csv", e2_rows, e2_header if e2_header is not HEADER else header)
    lines: list[str] = []
    code = main(argv(tmp, e1, e2, *extra, *(["--force"] if force else []), **kw), out=lines.append)
    return code, "\n".join(lines), tmp / "out.xlsx"


def held(tmp):
    with (tmp / "out.held.csv").open(newline="", encoding="utf-8") as fh:
        return {r["key"] or r["detail"]: r for r in csv.DictReader(fh)}


def rows_of(out):
    return {r["inst_id"]: r for r in read_batch(out).sheets["Institutions"]}


def prov_of(out):
    return {r[0]: r for r in openpyxl.load_workbook(out)[PROVENANCE_SHEET].iter_rows(values_only=True)}


THREE = [row(1), row(2), row(3)]


def test_rows_the_two_agree_on_are_written_with_both_checks_and_the_fixed_cells(tmp_path):
    e1 = [row(1, "Govt.  Degree College ‘Alpha’ – Zeta"), row(2), row(3)]
    e2 = [row(1, "govt. degree college 'alpha' - zeta"), row(2), row(3)]  # differs only in case, spaces, quotes, dash
    code, text, out = run(tmp_path, e1, e2)
    assert code == 0, text
    got = rows_of(out)
    assert set(got) == {"ZT-DC-1", "ZT-DC-2", "ZT-DC-3"}
    r = got["ZT-DC-1"]
    assert r["name"] == "Govt.  Degree College ‘Alpha’ – Zeta"  # E1's verbatim text, not the normalised form
    assert (r["type"], r["region"], r["city"]) == ("public_college", "Punjab", "Zeta Town")
    assert r["source_url"] == URL and r["retrieved"] == "2026-11-14" and r["claude_status"] == "found"
    assert r["read_method"] == MAPPING["read_method"]
    assert (r["checker1_result"], r["checker1_name"], r["checker1_date"]) == ("correct", *C1)
    assert (r["checker2_approved"], r["checker2_name"], r["checker2_date"]) == ("yes", *C2)
    assert r["checker_note"] == f"E1 doc sha256 {SHA}; E2 doc sha256 {SHA}"
    assert held(tmp_path) == {}
    # the source URL cell is exactly the list URL, byte for byte
    ws = openpyxl.load_workbook(out)["Institutions"]
    col = [c.value for c in ws[1]].index("source_url")
    assert {ws.cell(row=i, column=col + 1).value for i in range(2, 5)} == {URL}


def test_rows_that_disagree_or_are_in_one_extraction_only_are_held_not_written(tmp_path):
    e1 = [row(1), row(2, "Test College Two"), row(3)]
    e2 = [row(1, quote="1 Test Degree College 1 Other Town"), row(2, "Test College 2"), row(4)]
    code, text, out = run(tmp_path, e1, e2)
    assert code == 0, text
    assert rows_of(out) == {}
    h = held(tmp_path)
    assert h["1"]["reason"] == "quote_disagrees"
    assert h["2"]["reason"].startswith("name_disagrees") and h["2"]["e2_name"] == "Test College 2"
    assert h["3"]["reason"] == "only_in_e1" and h["4"]["reason"] == "only_in_e2"
    assert h["3"]["inst_id"] == "ZT-DC-3"
    assert "held (only_in_e1): 1" in text and "0 rows" in text


def test_a_duplicate_key_no_key_and_an_empty_name_or_quote_are_held(tmp_path):
    e1 = [row(1), row(1, "Another College"), row("", "Keyless College"), row(2, quote=""), row(3, name=" ")]
    e2 = [row(1), row(2, quote=""), row(3, name=" "), row(4), row(5)]
    code, text, out = run(tmp_path, e1, e2, "--allow-count-mismatch", lists=lists_dir(tmp_path, row_count=None))
    assert code == 0, text
    h = held(tmp_path)
    assert h["1"]["reason"] == "duplicate_key"
    assert h["e1 line 4"]["reason"] == "no_key_e1" and h["e1 line 4"]["e1_name"] == "Keyless College"
    assert h["2"]["reason"] == "quote_empty" and h["3"]["reason"] == "name_empty"
    assert "ZT-DC-1" not in rows_of(out) and rows_of(out) == {}


def test_a_single_row_whose_doc_sha256_disagrees_is_held(tmp_path):
    # both files name the same two documents, but rows 1 and 2 are read from different ones
    e1 = [row(1, sha=SHA), row(2, sha=SHA_B), row(3, sha=SHA)]
    e2 = [row(1, sha=SHA_B), row(2, sha=SHA), row(3, sha=SHA.upper())]
    code, text, out = run(tmp_path, e1, e2)
    assert code == 0, text
    h = held(tmp_path)
    assert h["1"]["reason"] == "doc_sha256_disagrees" and h["2"]["reason"] == "doc_sha256_disagrees"
    assert set(rows_of(out)) == {"ZT-DC-3"}  # the hex case is not a difference


def test_different_documents_and_bad_sha256s_are_refused(tmp_path):
    code, text, out = run(tmp_path, THREE, [row(1), row(2), row(3, sha=SHA_B)])
    assert code == 2 and text.startswith("refused: doc_sha256 differs") and not out.exists()
    code, text, _ = run(tmp_path, THREE, [r[:-1] for r in THREE], e2_header=HEADER[:-1])
    assert code == 2 and "missing column(s) doc_sha256" in text
    code, text, _ = run(tmp_path, THREE, [row(1), row(2, sha="a" * 63), row(3)])
    assert code == 2 and "e2.csv line 3 (key '2')" in text and "not 64 hex characters" in text
    code, text, _ = run(tmp_path, THREE, [row(1), row(2, sha="g" * 64), row(3)])
    assert code == 2 and "not 64 hex characters" in text


def test_identical_extractions_are_refused_unless_a_reason_is_recorded(tmp_path):
    code, text, out = run(tmp_path, THREE, THREE)
    assert code == 2 and "same sha256" in text and not out.exists()
    reason = "both parsers emit the table cells unchanged; checked by diffing the parser outputs"
    code, text, out = run(tmp_path, THREE, THREE, "--identical-extractions", reason)
    assert code == 0 and f"identical extractions accepted: {reason}" in text
    assert prov_of(out)["identical_extractions"][1] == reason
    code, text, out = run(tmp_path, THREE, alike(THREE))
    assert code == 0 and "identical_extractions" not in prov_of(out)


def test_two_different_methods_are_needed_and_recorded(tmp_path):
    code, text, _ = run(tmp_path, THREE, alike(THREE), methods=("lxml XPath", "LXML  xpath"))
    assert code == 2 and "same method" in text
    code, text, out = run(tmp_path, THREE, alike(THREE))
    p = prov_of(out)
    assert code == 0 and (p["e1_method"][1], p["e2_method"][1]) == (M1, M2)


def test_a_count_mismatch_is_refused_and_the_override_only_works_when_the_count_is_not_confirmed(tmp_path):
    two = [row(1), row(2)]
    code, text, _ = run(tmp_path, two, alike(two))
    assert code == 2 and "count mismatch" in text
    code, text, _ = run(tmp_path, two, alike(two), "--allow-count-mismatch")  # the count is confirmed: no override
    assert code == 2 and "only for a list whose count is not confirmed" in text
    unconfirmed = lists_dir(tmp_path, check2="unclear")
    code, text, out = run(tmp_path, two, alike(two), lists=unconfirmed)
    assert code == 2 and "count mismatch" in text
    code, text, out = run(tmp_path, two, alike(two), "--allow-count-mismatch", lists=unconfirmed)
    assert code == 0 and "count mismatch allowed: row_count 3; e1 2 rows, e2 2 rows" in text
    assert set(rows_of(out)) == {"ZT-DC-1", "ZT-DC-2"}
    assert prov_of(out)["count_mismatch_allowed"][1] == "row_count 3; e1 2 rows, e2 2 rows"


def test_a_formula_cell_is_neutralised_and_reads_back_as_written(tmp_path):
    bad = "=HYPERLINK(\"https://evil.test\",\"x\")"
    rows = [row(1, bad), row(2), row(3)]
    code, text, out = run(tmp_path, rows, alike(rows))
    assert code == 0, text
    ws = openpyxl.load_workbook(out)["Institutions"]
    col = [c.value for c in ws[1]].index("name")
    assert {ws.cell(row=i, column=col + 1).value for i in range(2, 5)} >= {"'" + bad}
    assert rows_of(out)["ZT-DC-1"]["name"] == bad
    # a held row's cells are neutralised in the CSV too
    assert run(tmp_path, rows, [row(1, "-1 other"), row(2), row(3)])[0] == 0
    assert held(tmp_path)["1"]["e1_name"] == "'" + bad and held(tmp_path)["1"]["e2_name"] == "'-1 other"


@pytest.mark.parametrize("method", ["webfetch (model-extracted)", "pdf parse (OCR)", "human (collected)",
                                    "headless render", "non_official_lead", "something else"])
def test_a_read_method_that_is_not_fetch_is_refused(tmp_path, method):
    code, text, out = run(tmp_path, THREE, alike(THREE), mp=mapping(tmp_path, read_method=method))
    assert code == 2 and "does not map to fetch" in text and not out.exists()


def test_the_mapping_and_checkers_are_checked(tmp_path):
    code, text, _ = run(tmp_path, THREE, alike(THREE), mp=mapping(tmp_path, type="examination_board"))
    assert code == 2 and "not a type of kind" in text
    code, text, _ = run(tmp_path, THREE, alike(THREE), mp=mapping(tmp_path, retrieved="2026-11-15"))
    assert code == 2 and "after a checker date" in text
    e1 = write_csv(tmp_path / "e1.csv", THREE)
    assert main(argv(tmp_path, e1, e1), out=[].append) == 2  # one extraction twice is not two
    lines: list[str] = []
    main(argv(tmp_path, e1, write_csv(tmp_path / "e2.csv", alike(THREE)), checker2=(C1[0], "2026-11-15")),
         out=lines.append)
    assert "must be different" in lines[0]


def test_the_mapping_type_must_be_the_list_type(tmp_path):
    code, text, out = run(tmp_path, THREE, alike(THREE), mp=mapping(tmp_path, type="private_college"))
    assert code == 2 and "not the list's institution_type 'public_college'" in text and not out.exists()


def test_a_per_row_type_column_and_a_region_column_must_agree_and_types_are_counted(tmp_path):
    header = [*HEADER, "section", "province"]
    e1 = [[*row(1), "public_college", "Punjab"], [*row(2), "private_college", "Punjab"],
          [*row(3), "private_college", "Punjab"], [*row(4), "Public_College", "Punjab"]]
    e2 = [[*row(1), "public_college", "Punjab"], [*row(2), "public_college", "Sindh"],
          [*row(3), "private_college", "Punjab"], [*row(4), "public_college", "Punjab"]]
    mp = mapping(tmp_path, drop=("type", "region"), type_column="section", region="column", region_column="province")
    code, text, out = run(tmp_path, e1, e2, mp=mp, header=header, lists=lists_dir(tmp_path, row_count=4))
    assert code == 0, text
    got = rows_of(out)
    assert set(got) == {"ZT-DC-1", "ZT-DC-3"} and got["ZT-DC-3"]["type"] == "private_college"
    h = held(tmp_path)
    assert h["2"]["reason"] == "section_disagrees;province_disagrees"
    assert h["4"]["reason"] == "type_not_a_list_kind" and h["4"]["detail"] == "Public_College"  # exact spelling only
    p = prov_of(out)
    assert p["type_count (public_college)"][1] == 1 and p["type_count (private_college)"][1] == 1
    assert p["list_institution_type"][1] == "public_college" and "type public_college: 1" in text


def test_an_existing_output_is_refused_and_a_refused_forced_run_leaves_no_stale_output(tmp_path):
    code, _, out = run(tmp_path, THREE, alike(THREE), force=False)
    assert code == 0 and out.exists() and (tmp_path / "out.held.csv").exists()
    before = out.read_bytes()
    code, text, _ = run(tmp_path, THREE, alike(THREE), force=False)
    assert code == 2 and "output exists" in text and out.read_bytes() == before
    code, text, _ = run(tmp_path, THREE, [row(1), row(2), row(3, sha=SHA_B)])  # --force, then refused
    assert code == 2 and not out.exists() and not (tmp_path / "out.held.csv").exists()


def test_derived_from_records_every_input_and_the_command(tmp_path):
    code, text, out = run(tmp_path, THREE, alike(THREE))
    assert code == 0, text
    prov = prov_of(out)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert prov["e1"][2] == sha(tmp_path / "e1.csv") and prov["e2"][2] == sha(tmp_path / "e2.csv")
    assert prov["mapping"][2] == sha(tmp_path / "map.yaml")
    assert prov["lists"][1:] == ("zeta.yaml", sha(tmp_path / "lists" / "zeta.yaml"))
    assert prov["list"][1] == "list:zeta-degree-colleges" and f"checker1 ({C1[0]}, {C1[1]})" in prov
    assert prov["command"][1].startswith("python -m scripts.os_list_sheet --lists ")
    assert "count_mismatch_allowed" not in prov and not any(k.startswith("type_count") for k in prov)


def test_validate_dry_run_of_the_output_passes_with_lists_and_plans_the_rows_onto_the_list(tmp_path):
    code, text, out = run(tmp_path, THREE, alike(THREE))
    assert code == 0, text
    lists = tmp_path / "lists"
    lines: list[str] = []
    assert import_main(["validate", str(out), "--country", COUNTRY, "--lists", str(lists), "--report",
                        str(tmp_path / "r.csv")], out=lines.append) == 0
    # validate plans in the owner-accepted mode, where only the owner's AI check names count as checks: the rows are
    # planned (none rejected, none short of a list) and wait as unconfirmed
    assert "Institutions: accepted 0, unconfirmed 3, queued 0, rejected 0, skipped 0" in lines
    assert "no_official_list" not in (tmp_path / "r.csv").read_text()
    # in the reviewers mode, with both checker refs attested, the same plan accepts every row as verified, on the list
    urls, regions, fams = _lists(lists, COUNTRY)
    ctx = build_context(None, country=COUNTRY, mode=REVIEWERS, batch_ref="batch-zeta", family="", decision_ref=None,
                        list_urls=urls, list_regions=regions, list_families=fams, require_list=True)
    ctx.attested = lambda name, ref: name in (C1[0], C2[0]) and ref == "batch-zeta"
    _, results = plan_file(out, ctx)
    inst = [r for r in results if r.sheet == "Institutions"]
    assert [(r.bucket, r.level) for r in inst] == [("accepted", "verified")] * 3
    assert {r.payload["lists"] for r in inst} == {("list:zeta-degree-colleges",)}
    assert {r.payload["entry"].institution_type for r in inst} == {"public_college"}


def test_norm_is_only_for_comparison():
    assert norm("  A “B”\t‘c’ — d ") == norm('a "b" \'c\' - d') == 'a "b" \'c\' - d'
