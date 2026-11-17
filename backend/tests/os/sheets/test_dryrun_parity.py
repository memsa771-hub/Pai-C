"""P2-T31: the dry run plans like the import (P2 spec §4.6; master R-68).

FU-11: an Institutions row whose parent is of a kind the registry refuses (ALLOWED_PARENTS) is rejected by the plan as
`parent_kind_not_allowed`, so validate and import agree. FU-12: `validate --reviewers --assume-attested REF...` plans as
`import --reviewers` would, with the named refs assumed (never checked) to have attested the batch ref. Fictional data
on `.test` domains."""

import copy
from dataclasses import replace
from datetime import date

import pytest
import yaml

from app.os.knowledge.sheets.format import load_format
from app.os.knowledge.sheets.importer import build_context, plan_file, run_import
from app.os.knowledge.sheets.plan import REVIEWERS, summarise
from app.os.registry.store import RegistryStore
from scripts.os_import_batch import main
from tests.os.registry.helpers import LIST_URL

from .helpers import COUNTRY, checks, deps, fact, inst, load_list, workbook

pytestmark = pytest.mark.req("R-68")
DECISION = "ref-1"


def run(argv, d=None):
    out: list[str] = []
    code = main(argv, deps=d, out=out.append)
    return code, "\n".join(out)


def campus_fmt():
    """The format with a campus type: format.yaml names none yet, so a campus row needs a test type."""
    fmt = load_format()
    raw = copy.deepcopy(fmt.raw)
    raw["type_kinds"]["campus"] = ["test_campus"]
    return replace(fmt, raw=raw)


def board(n=4, inst_id="BETA-BOARD"):
    row = inst(n, ctype="examination_board", source_url="https://board.beta.test/about", timezone="Asia/Karachi")
    row.update(inst_id=inst_id, name="Beta board")
    return row


def calendar_under_board():
    row = inst(5, ctype="exam_calendar", source_url="https://board.beta.test/datesheet", parent_id="BETA-BOARD")
    row.update(inst_id="BETA-EXAMS", name="Beta board exam calendar")
    return row


def campus_under_board():
    row = inst(6, ctype="test_campus", parent_id="BETA-BOARD")
    row.update(inst_id="BETA-CAMPUS", name="Beta campus")
    return row


def institution_under_board():
    return inst(7, parent_id="BETA-BOARD")  # an institution may sit only under an institution


def dry_ctx(fmt=None):
    return build_context(None, country=COUNTRY, mode="owner_accepted", batch_ref="b", family="", require_list=False,
                         decision_ref=DECISION, fmt=fmt)


def by_id(results):
    return {r.row_id: r for r in results if r.sheet == "Institutions"}


def fates(results):
    return {(r.sheet, r.row_id): (r.bucket, r.reason) for r in results}


# --- FU-11: the plan checks the parent's kind -------------------------------------------------------------------------

def test_a_campus_under_a_board_is_rejected_by_the_plan(tmp_path):
    fmt = campus_fmt()
    path = workbook(tmp_path, [board(), campus_under_board()])
    res = by_id(plan_file(path, dry_ctx(fmt), fmt)[1])
    assert res["BETA-BOARD"].bucket == "accepted"
    r = res["BETA-CAMPUS"]
    assert (r.bucket, r.reason) == ("rejected", "parent_kind_not_allowed")
    # the detail names the row's kind, the parent's kind and the allowed kinds
    assert "a campus" in r.detail and "is a board" in r.detail and "may be: institution" in r.detail


def test_an_institution_under_a_board_is_rejected_by_the_plan(tmp_path):
    path = workbook(tmp_path, [board(), institution_under_board()])
    r = by_id(plan_file(path, dry_ctx())[1])["T-INST-007"]
    assert (r.bucket, r.reason) == ("rejected", "parent_kind_not_allowed")


def test_a_calendar_under_a_board_is_accepted_by_the_plan(tmp_path):
    path = workbook(tmp_path, [board(), calendar_under_board()])
    r = by_id(plan_file(path, dry_ctx())[1])["BETA-EXAMS"]
    assert (r.bucket, r.reason) == ("accepted", "both_checks")
    assert r.payload["entry"].parent_id == "board:beta-board"


def test_a_calendar_under_a_regulator_is_rejected_by_the_plan(tmp_path):
    reg = inst(8, ctype="professional_regulator", source_url="https://regulator.beta.test/about")
    reg.update(inst_id="BETA-REG", name="Beta regulator")
    cal = calendar_under_board()
    cal.update(parent_id="BETA-REG")
    r = by_id(plan_file(workbook(tmp_path, [reg, cal]), dry_ctx())[1])["BETA-EXAMS"]
    assert (r.bucket, r.reason) == ("rejected", "parent_kind_not_allowed")
    assert "is a regulator" in r.detail and "board" in r.detail


def test_a_parent_of_unknown_kind_keeps_todays_behaviour_and_says_so(tmp_path):
    ctx = dry_ctx(campus_fmt())
    ctx.existing_institutions = lambda i: "board:beta-board" if i == "BETA-BOARD" else None  # no registry_info
    path = workbook(tmp_path, [campus_under_board()])
    r = by_id(plan_file(path, ctx, campus_fmt())[1])["BETA-CAMPUS"]
    assert r.bucket == "accepted"  # as before T31: the registry decides at the import
    assert "board:beta-board: kind unknown, not checked" in r.detail


def test_a_stored_parent_is_judged_by_its_stored_kind(engine, clean, tmp_path):
    load_list(engine)
    fmt = campus_fmt()
    d = deps(engine)
    run_import(workbook(tmp_path, [board()], name="first.xlsx"), d, mode="owner_accepted", actor="dev",
               country=COUNTRY, decision_ref=DECISION, fmt=fmt)
    res = run_import(workbook(tmp_path, [campus_under_board(), calendar_under_board()], name="second.xlsx"), d,
                     mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref=DECISION, fmt=fmt)
    got = by_id(res.rows)
    assert (got["BETA-CAMPUS"].bucket, got["BETA-CAMPUS"].reason) == ("rejected", "parent_kind_not_allowed")
    assert got["BETA-EXAMS"].bucket == "accepted"


def test_validate_and_import_agree_on_both(engine, clean, tmp_path, monkeypatch):
    fmt = campus_fmt()
    monkeypatch.setattr("app.os.knowledge.sheets.importer.load_format", lambda: fmt)  # the CLI's format
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "a.yaml").write_text(yaml.safe_dump({"region": "national", "retrieved": date(2026, 11, 7), "lists": [
        {"id": "alpha-list", "body": "Alpha", "name": "Alpha list", "url": LIST_URL, "row_count": 3}]}))
    path = workbook(tmp_path, [board(), campus_under_board(), calendar_under_board()])
    report = tmp_path / "dry.csv"
    code, dry = run(["validate", str(path), "--country", COUNTRY, "--lists", str(lists), "--report", str(report)])
    assert code == 0 and "Institutions: accepted 2, unconfirmed 0, queued 0, rejected 1" in dry
    planned = fates(plan_file(path, build_context(None, country=COUNTRY, mode="owner_accepted", batch_ref="b",
                                                  family="", decision_ref=DECISION, list_urls={LIST_URL: "list:alpha-list"},
                                                  list_regions={"list:alpha-list": "national"}))[1])
    load_list(engine)
    d = deps(engine)
    code, real = run(["import", str(path), "--country", COUNTRY, "--owner-accepted", DECISION, "--actor", "dev"], d)
    assert code == 0
    n = len(summarise(plan_file(path, dry_ctx(fmt), fmt)[1]))
    assert dry.splitlines()[-n:] == real.splitlines()[-n:]  # the same counts, sheet by sheet
    assert planned[("Institutions", "BETA-CAMPUS")] == ("rejected", "parent_kind_not_allowed")
    assert planned[("Institutions", "BETA-EXAMS")] == ("accepted", "both_checks")
    assert "parent_kind_not_allowed" in report.read_text()
    s = RegistryStore(engine, "pai")
    assert s.get("cal:beta-exams").parent_id == "board:beta-board"
    assert s.get("campus:beta-campus") is None and "registry_refused" not in real


# --- FU-12: validate --reviewers --assume-attested --------------------------------------------------------------------

E1, E2 = "rev-zeta-e1", "rev-zeta-e2"


def reviewers_file(tmp_path):
    chk = checks(n1=E1, n2=E2)
    return workbook(tmp_path, [inst(1, chk=chk), inst(2, chk=chk)], [fact(1, "T-INST-001", chk=chk)],
                    name="zeta-batch.xlsx")


def validate(path, *extra):
    return run(["validate", str(path), "--country", COUNTRY, "--no-list-needed", *extra])


def test_both_refs_assumed_plan_as_an_import_with_attested_refs(engine, clean, tmp_path):
    path = reviewers_file(tmp_path)
    code, dry = validate(path, "--reviewers", "--assume-attested", E1, E2)
    assert code == 0
    assert "Institutions: accepted 2, unconfirmed 0" in dry and "Facts: accepted 1, unconfirmed 0" in dry
    assert "ASSUMED, NOT checked" in dry and E1 in dry and E2 in dry and "'zeta-batch'" in dry
    # the same as plan_file in REVIEWERS mode with those refs attested for the batch ref
    ctx = build_context(None, country=COUNTRY, mode=REVIEWERS, batch_ref="zeta-batch", family="", require_list=False)
    ctx.attested = lambda name, ref: name in (E1, E2) and ref == "zeta-batch"
    results = plan_file(path, ctx)[1]
    assert {r.level for r in results if r.sheet in ("Institutions", "Facts")} == {"verified"}
    want = [f"{sheet}: " + ", ".join(f"{k} {v}" for k, v in c.items()) for sheet, c in summarise(results).items()]
    assert dry.splitlines()[-len(want):] == want
    # and the same as the real reviewers import with attested refs
    load_list(engine)
    d = deps(engine, attested=lambda name, ref: name in (E1, E2) and ref == "zeta-batch")
    code, real = run(["import", str(path), "--country", COUNTRY, "--reviewers", "--actor", "dev"], d)
    assert code == 0 and real.splitlines()[-len(want):] == want


def test_only_one_ref_assumed_is_never_verified_and_matches_the_import(engine, clean, tmp_path):
    path = reviewers_file(tmp_path)
    # checker 2 alone: checker 1's result does not count, so the rows stay unconfirmed
    code, dry = validate(path, "--reviewers", "--assume-attested", E2)
    assert code == 0 and "Institutions: accepted 0, unconfirmed 2" in dry and "Facts: accepted 0, unconfirmed 1" in dry
    # checker 1 alone: one check counts (`one_check` / `second_check_missing`), as in the import: confirmed, not verified
    code, dry = validate(path, "--reviewers", "--assume-attested", E1)
    assert code == 0 and "verified" not in dry.split("Institutions:")[1] and "confirmed 2" in dry
    load_list(engine)
    d = deps(engine, attested=lambda name, ref: name == E1 and ref == "zeta-batch")
    code, real = run(["import", str(path), "--country", COUNTRY, "--reviewers", "--actor", "dev"], d)
    n = len(summarise(plan_file(path, build_context(None, country=COUNTRY, mode=REVIEWERS, batch_ref="zeta-batch",
                                                    family="", require_list=False))[1]))
    assert code == 0 and real.splitlines()[-n:] == dry.splitlines()[-n:]


def test_reviewers_with_nobody_assumed_stays_unconfirmed(tmp_path):
    code, dry = validate(reviewers_file(tmp_path), "--reviewers")
    assert code == 0 and "Institutions: accepted 0, unconfirmed 2" in dry and "for: nobody" in dry


def test_without_the_flag_validate_is_unchanged(tmp_path):
    code, dry = validate(reviewers_file(tmp_path))
    assert code == 0 and "Institutions: accepted 0, unconfirmed 2" in dry and "ASSUMED" not in dry
    ctx = build_context(None, country=COUNTRY, mode="owner_accepted", batch_ref="", family="", require_list=False)
    results = plan_file(reviewers_file(tmp_path), ctx)[1]
    assert {r.reason for r in results if r.sheet == "Institutions"} == {"check_unclear_or_missing"}


def test_assume_attested_needs_reviewers(tmp_path):
    code, text = validate(reviewers_file(tmp_path), "--assume-attested", E1, E2)
    assert code == 2 and text.startswith("refused:") and "--reviewers" in text


def test_the_import_never_accepts_the_assume_flag(engine, clean, tmp_path):
    path = reviewers_file(tmp_path)
    for flag in (["--assume-attested", E1, E2], ["--assume-aliases-attested"]):
        with pytest.raises(SystemExit):
            run(["import", str(path), "--country", COUNTRY, "--reviewers", "--actor", "dev", *flag], deps(engine))
    assert RegistryStore(engine, "pai").get("inst:t-inst-001") is None
