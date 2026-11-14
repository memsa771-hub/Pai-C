"""P2-T16: an institution on several official lists keeps every list through imports, and undo of an import gives an
entity back the state it had before that import (P2 spec §4.1, §4.6; master R-32, R-35a, R-60, R-68). Fictional data."""

from dataclasses import replace

import pytest
import yaml

from app.os.knowledge.sheets.importer import build_context, plan_file, run_import
from app.os.knowledge.sheets.importlog import ImportLog
from app.os.knowledge.sheets.undo import UndoRefused, undo_import
from app.os.registry.lists import load_official_lists
from app.os.registry.store import RegistryError, RegistryStore
from tests.os.registry.helpers import LIST_URL, olist

from .helpers import COUNTRY, deps, fact, inst, load_list, prog, workbook
from .test_aliases import alias, alias_file, attested

pytestmark = [pytest.mark.req("R-32"), pytest.mark.req("R-35"), pytest.mark.req("R-60"), pytest.mark.req("R-68")]
E = "inst:t-inst-001"
A, B = "list:alpha-list", "list:beta-list"
BETA_URL = "https://lists.beta.test/colleges"


def two_lists(engine) -> RegistryStore:
    load_list(engine)
    s = RegistryStore(engine, "pai")
    s.record(replace(olist("beta-list"), name="Beta recognised colleges", source_url=BETA_URL), cause="import")
    return s


def do_import(engine, tmp_path, institutions, name):
    return run_import(workbook(tmp_path, institutions, name=name), deps(engine), mode="owner_accepted", actor="dev",
                      country=COUNTRY, decision_ref="ref-1")


def loaded(s: RegistryStore) -> dict[str, int]:
    return {p.list_id: p.loaded for p in s.list_progresses()}


def test_two_imports_from_two_lists_keep_both_lists_on_the_entity(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    assert s.get(E).list_ids == (A,) and loaded(s) == {A: 1, B: 0}
    do_import(engine, tmp_path, [inst(1, source_url=BETA_URL)], "b.xlsx")
    assert s.get(E).list_ids == (A, B)  # existing first, then the new one
    assert loaded(s) == {A: 1, B: 1}  # the first list's count does not fall
    assert s.list_progress(A).loaded == 1 and s.list_progress(B).loaded == 1
    assert [e.entity_id for e in s.list(list_id=A)] == [E] and [e.entity_id for e in s.list(list_id=B)] == [E]


def test_one_import_with_the_entity_on_two_lists_names_both(engine, clean, tmp_path):
    s = two_lists(engine)
    res = do_import(engine, tmp_path, [inst(1), inst(1, source_url=BETA_URL)], "a.xlsx")
    assert [r.bucket for r in res.rows if r.sheet == "Institutions"] == ["accepted", "accepted"]
    assert s.get(E).list_ids == (A, B) and loaded(s) == {A: 1, B: 1}


def test_the_same_list_twice_in_one_import_is_still_a_duplicate(engine, clean, tmp_path):
    s = two_lists(engine)
    res = do_import(engine, tmp_path, [inst(1), inst(1, name="Again")], "a.xlsx")
    assert [r.reason for r in res.rows if r.sheet == "Institutions"][1] == "duplicate_id"
    assert s.get(E).list_ids == (A,) and s.get(E).name == "Test College 1"


def test_undo_of_the_second_import_gives_back_only_the_first_list_and_does_not_close(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    first = s.get(E)
    second = do_import(engine, tmp_path, [inst(1, source_url=BETA_URL, name="Test College One")], "b.xlsx")
    assert s.get(E).list_ids == (A, B)
    r = undo_import(engine, "pai", second.import_id, actor="admin")
    assert r.registry == 1
    back = s.get(E)
    assert back.list_ids == (A,) and back.status == "active" == first.status
    assert back == first  # every column as it was before the second import
    assert "withdrawn_by_import" not in back.attrs
    assert loaded(s) == {A: 1, B: 0}
    assert [x.action for x in s.revisions(E)] == ["insert", "change", "undo"]


def test_undo_of_the_import_that_created_the_entity_withdraws_it(engine, clean, tmp_path):
    s = two_lists(engine)
    res = do_import(engine, tmp_path, [inst(1), inst(1, source_url=BETA_URL)], "a.xlsx")
    undo_import(engine, "pai", res.import_id, actor="admin")
    e = s.get(E)
    assert e.status == "closed" and e.attrs["withdrawn_by_import"] == res.import_id
    assert e.list_ids == (A, B)  # closed, not deleted (R-60): the row keeps what it was


def test_recording_once_or_without_keep_lists_is_unchanged(engine, clean):
    s = two_lists(engine)
    from tests.os.registry.helpers import inst as reg_inst

    assert s.record(reg_inst("one"), cause="import", keep_lists=True).action == "insert"
    assert s.get("inst:one").list_ids == (A,)
    assert s.record(reg_inst("one"), cause="import", keep_lists=True).action == "unchanged"
    s.record(reg_inst("one", lists=(B,)), cause="review")  # a plain update still replaces the lists (a reviewer's fix)
    assert s.get("inst:one").list_ids == (B,)


def test_re_import_of_a_withdrawn_entity_does_not_bring_back_the_lists_of_the_undone_import(engine, clean, tmp_path):
    s = two_lists(engine)
    first = do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    undo_import(engine, "pai", first.import_id, actor="admin")
    assert s.get(E).status == "closed" and s.get(E).list_ids == (A,)
    do_import(engine, tmp_path, [inst(1, source_url=BETA_URL)], "b.xlsx")
    back = s.get(E)
    assert back.status == "active" and back.list_ids == (B,)  # list A came only from the undone import
    assert "withdrawn_by_import" not in back.attrs and loaded(s) == {A: 0, B: 1}


def test_the_first_import_cannot_be_undone_under_the_second_until_the_second_is(engine, clean, tmp_path):
    s = two_lists(engine)
    first = do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    second = do_import(engine, tmp_path, [inst(1, source_url=BETA_URL)], "b.xlsx")
    with pytest.raises(UndoRefused):
        undo_import(engine, "pai", first.import_id, actor="admin")
    assert s.get(E).list_ids == (A, B) and s.get(E).status == "active"  # the refused undo changed nothing
    undo_import(engine, "pai", second.import_id, actor="admin")
    undo_import(engine, "pai", first.import_id, actor="admin")
    assert s.get(E).status == "closed" and s.get(E).attrs["withdrawn_by_import"] == first.import_id


def _alias_import(engine, tmp_path, institutions, facts=()):
    path = workbook(tmp_path, institutions, facts, name="b.xlsx")
    afile = alias_file(tmp_path, path, alias())
    return run_import(path, deps(engine, attested=attested(afile)), mode="owner_accepted", actor="dev",
                      country=COUNTRY, decision_ref="ref-1", aliases=[afile])


def test_alias_and_union_together(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    # the target on a second list, and the aliased id on both lists: the aliased rows load nothing, whatever list
    aliased = [inst(9, inst_id="T-UNI-X", source_url=BETA_URL), inst(9, inst_id="T-UNI-X")]
    res = _alias_import(engine, tmp_path, [inst(1, source_url=BETA_URL), *aliased], [fact(1, "T-UNI-X")])
    rows = [(r.row_id, r.bucket, r.reason) for r in res.rows if r.sheet == "Institutions"]
    assert rows[0][:2] == ("T-INST-001", "accepted")
    assert rows[1:] == [("T-UNI-X", "skipped", "aliased"), ("T-UNI-X", "skipped", "aliased")]
    assert s.get("inst:t-uni-x") is None
    assert s.get(E).list_ids == (A, B) and loaded(s) == {A: 1, B: 1}  # the target keeps the list it was on
    assert [r.payload["ref"] for r in res.rows if r.sheet == "Facts"] == [E]
    undo_import(engine, "pai", res.import_id, actor="admin")
    assert s.get(E).list_ids == (A,) and s.get(E).status == "active"


def test_an_aliased_row_alone_on_another_list_adds_that_list_to_the_target(engine, clean, tmp_path):
    # P2-T28 (FU-3, controller decision under the owner's delegation of 2026-11-14) changed this on purpose: it was
    # test_an_aliased_row_alone_on_another_list_adds_nothing_to_the_target, which asserted ("skipped", "aliased") and
    # list_ids == (A,). An aliased row on no list still adds nothing (test_alias_membership.py, rule 11).
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    before = s.revisions(E)
    res = _alias_import(engine, tmp_path, [inst(9, inst_id="T-UNI-X", source_url=BETA_URL)])
    assert [(r.bucket, r.reason) for r in res.rows if r.sheet == "Institutions"] == [("accepted", "alias_membership")]
    assert s.get(E).list_ids == (A, B) and loaded(s) == {A: 1, B: 1}
    assert s.revisions(E)[:-1] == before and s.revisions(E)[-1].action == "change"


# --- fix round 1 (review F1-F4) ---------------------------------------------------------------------------------------
GAMMA_URL = "https://lists.gamma.test/punjab-colleges"
G = "list:gamma-list"


def three_lists(engine) -> RegistryStore:
    """A (national), B (national) and G, a regional list of punjab."""
    s = two_lists(engine)
    s.record(replace(olist("gamma-list", region="punjab"), name="Gamma regional colleges", source_url=GAMMA_URL),
             cause="import")
    return s


def dry(engine, path, **kw):
    ctx = build_context(deps(engine), country=COUNTRY, mode="owner_accepted", batch_ref="b", family="",
                        decision_ref="ref-1", **kw)
    return [(r.row_id, r.bucket, r.reason) for r in plan_file(path, ctx)[1] if r.sheet == "Institutions"]


def inst_rows(res):
    return [(r.row_id, r.bucket, r.reason) for r in res.rows if r.sheet == "Institutions"]


def test_f1_a_region_change_against_a_kept_regional_list_is_rejected_in_the_plan_and_the_rest_loads(
        engine, clean, tmp_path):
    s = three_lists(engine)
    do_import(engine, tmp_path, [inst(1, source_url=GAMMA_URL)], "a.xlsx")
    first = s.get(E)
    rows = [inst(2, source_url=BETA_URL), inst(1, source_url=BETA_URL, region="Sindh"), inst(3, source_url=BETA_URL)]
    path = workbook(tmp_path, rows, name="b.xlsx")
    planned = dry(engine, path)
    assert planned[1] == ("T-INST-001", "rejected", "region_conflicts_with_list")  # the dry run shows it
    res = run_import(path, deps(engine), mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")
    assert inst_rows(res) == planned  # the import does what the dry run said
    assert ImportLog(engine, "pai").get(res.import_id).status == "done"
    assert s.get(E) == first  # loads nothing
    assert s.get("inst:t-inst-002") is not None and s.get("inst:t-inst-003") is not None
    assert loaded(s) == {A: 0, B: 2, G: 1}


def test_f1_and_f3_in_one_file_a_second_row_of_the_id_with_another_region_is_rejected(engine, clean, tmp_path):
    s = three_lists(engine)
    rows = [inst(1, source_url=GAMMA_URL), inst(1, source_url=BETA_URL, region="Sindh"), inst(2)]
    path = workbook(tmp_path, rows, name="a.xlsx")
    planned = dry(engine, path)
    res = do_import(engine, tmp_path, rows, "a.xlsx")
    assert inst_rows(res) == planned
    assert [r[1:] for r in planned] == [("accepted", "both_checks"), ("rejected", "duplicate_id_conflict"),
                                        ("accepted", "both_checks")]
    assert ImportLog(engine, "pai").get(res.import_id).status == "done"
    assert s.get(E).list_ids == (G,) and s.get(E).region == "punjab" and s.get("inst:t-inst-002") is not None


def test_f1_the_rows_own_regional_list_of_another_region_is_rejected_in_the_plan(engine, clean, tmp_path):
    s = three_lists(engine)
    res = do_import(engine, tmp_path, [inst(1, source_url=GAMMA_URL, region="Sindh"), inst(2)], "a.xlsx")
    assert [r[2] for r in inst_rows(res)] == ["region_conflicts_with_list", "both_checks"]
    assert s.get(E) is None and s.get("inst:t-inst-002") is not None


def test_f1_backstop_a_row_the_registry_refuses_is_rejected_and_the_import_goes_on(engine, clean, tmp_path,
                                                                                   monkeypatch):
    s = two_lists(engine)
    d = deps(engine)
    real = d.registry.record

    def refuse_e(entry, **kw):
        if entry.entity_id == E:
            raise RegistryError(f"{E}: refused by the test")
        return real(entry, **kw)

    monkeypatch.setattr(d.registry, "record", refuse_e)
    path = workbook(tmp_path, [inst(1), inst(2)], [fact(1, "T-INST-001"), fact(2, "T-INST-002"), fact(3, "T-PRG-001")],
                    [prog(1, "T-INST-001")], name="a.xlsx")
    res = run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")
    rec = ImportLog(engine, "pai").get(res.import_id)
    assert rec.status == "done" and "registry_refused" in rec.report_csv  # reported, never silent
    by = {(r.sheet, r.row_id): (r.bucket, r.reason) for r in res.rows}
    assert by[("Institutions", "T-INST-001")] == ("rejected", "registry_refused")
    assert by[("Institutions", "T-INST-002")][0] == "accepted"
    assert by[("Programmes", "T-PRG-001")] == ("rejected", "institution_not_loaded")
    assert by[("Facts", "T-F-001")] == ("rejected", "entity_unknown") and by[("Facts", "T-F-002")][0] == "accepted"
    assert by[("Facts", "T-F-003")] == ("rejected", "programme_not_loaded")  # no fact on a programme never created
    assert d.programmes.get("T-PRG-001") is None
    assert res.counts["Institutions"]["rejected"] == 1
    assert s.get(E) is None and s.get("inst:t-inst-002") is not None


def test_f2_the_duplicate_key_does_not_depend_on_which_lists_are_loaded(engine, clean, tmp_path):
    other = "https://lists.delta.test/colleges"  # no list of the registry has this URL
    path = workbook(tmp_path, [inst(1), inst(1, source_url=other), inst(1, source_url=other + "/")], name="a.xlsx")
    ctx = build_context(None, country=COUNTRY, mode="owner_accepted", batch_ref="b", family="", require_list=False,
                        decision_ref="ref-1")
    reasons = [r.reason for r in plan_file(path, ctx)[1] if r.sheet == "Institutions"]
    assert reasons == ["both_checks", "both_checks", "duplicate_id"]  # two lists by URL; the same URL twice


def test_f3_a_second_row_of_the_id_of_another_kind_is_rejected(engine, clean, tmp_path):
    s = two_lists(engine)
    res = do_import(engine, tmp_path, [inst(1), inst(1, source_url=BETA_URL, type="exam_board")], "a.xlsx")
    assert [r[1:] for r in inst_rows(res)] == [("accepted", "both_checks"), ("rejected", "duplicate_id_conflict")]
    assert s.get(E).list_ids == (A,) and s.get("board:t-inst-001") is None


def test_f4_a_row_a_reviewer_made_active_again_keeps_its_lists(engine, clean, tmp_path):
    s = two_lists(engine)
    first = do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    undo_import(engine, "pai", first.import_id, actor="admin")
    s.record(replace(s.get(E), status="active"), cause="review")  # attrs copied: withdrawn_by_import still there
    assert "withdrawn_by_import" in s.get(E).attrs
    do_import(engine, tmp_path, [inst(1, source_url=BETA_URL)], "b.xlsx")
    assert s.get(E).list_ids == (A, B)


def test_n1_validate_from_the_command_line_knows_the_regions_of_the_list_files(tmp_path):
    from scripts.os_import_batch import main

    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "g.yaml").write_text(yaml.safe_dump({"region": "Punjab", "retrieved": "2026-11-07", "lists": [
        {"id": "gamma-list", "body": "Gamma", "name": "Gamma regional colleges", "url": GAMMA_URL, "row_count": 2}]}))
    path = workbook(tmp_path, [inst(1, source_url=GAMMA_URL, region="Sindh"), inst(2, source_url=GAMMA_URL)],
                    name="a.xlsx")
    out: list[str] = []
    code = main(["validate", str(path), "--country", COUNTRY, "--lists", str(lists), "--decision-ref", "ref-1",
                 "--report", str(tmp_path / "r.csv")], out=out.append)
    [line] = [x for x in out if x.startswith("Institutions:")]
    assert code == 0 and "accepted 1," in line and "rejected 1," in line
    report = (tmp_path / "r.csv").read_text()
    assert "T-INST-001" in report and "region_conflicts_with_list" in report
    # with --institutions-from, the lists the other file would give the entity are kept, so they are checked too
    (lists / "b.yaml").write_text(yaml.safe_dump({"region": "national", "retrieved": "2026-11-07", "lists": [
        {"id": "beta-list", "body": "Beta", "name": "Beta recognised colleges", "url": BETA_URL, "row_count": 2}]}))
    other = workbook(tmp_path, [inst(1, source_url=GAMMA_URL)], name="other.xlsx")
    path = workbook(tmp_path, [inst(1, source_url=BETA_URL, region="Sindh")], name="c.xlsx")
    argv = ["validate", str(path), "--country", COUNTRY, "--lists", str(lists), "--decision-ref", "ref-1", "--report",
            str(tmp_path / "c.csv")]
    assert main(argv, out=[].append) == 0 and "region_conflicts_with_list" not in (tmp_path / "c.csv").read_text()
    assert main([*argv, "--institutions-from", str(other)], out=[].append) == 0
    assert "region_conflicts_with_list" in (tmp_path / "c.csv").read_text()


# --- fix round 3: one URL, several lists (a national page and regional views of it) -----------------------------------
PAGE = "https://lists.omega.test/recognised"  # the national list and two regional lists are published at this one page
ONLY_REGIONAL = "https://lists.sigma.test/recognised"  # two regional lists, no national one
ON, OP, OS = "list:omega-national", "list:omega-punjab", "list:omega-sindh"


def list_files(tmp_path):
    d = tmp_path / "lists"
    d.mkdir()

    def write(name, region, *items):
        (d / name).write_text(yaml.safe_dump({"region": region, "retrieved": "2026-11-07", "lists": [
            {"id": i, "body": "Omega", "name": f"Omega {i}", "url": url, "row_count": 5} for i, url in items]}))

    write("national.yaml", "national", ("omega-national", PAGE), ("alpha-list", LIST_URL))
    write("punjab.yaml", "Punjab", ("omega-punjab", PAGE), ("sigma-punjab", ONLY_REGIONAL))
    write("sindh.yaml", "Sindh", ("omega-sindh", PAGE), ("sigma-sindh", ONLY_REGIONAL))
    return d


def shared_rows():
    return [inst(1, source_url=PAGE),  # punjab: the national list and the punjab view
            inst(2, source_url=PAGE, region="Sindh"),  # sindh: the national list and the sindh view
            inst(3, source_url=PAGE, region="Balochistan"),  # no balochistan view: the national list only
            inst(4, source_url=ONLY_REGIONAL, region="KP"),  # regional views only, none of its region: rejected
            inst(5, source_url=ONLY_REGIONAL),  # punjab: the punjab view
            inst(6),  # a URL of one list: as before
            inst(1, source_url=PAGE, name="Again")]  # the same row's lists again: a duplicate


def test_r3_a_url_of_several_lists_puts_the_row_on_the_national_list_and_its_regions(engine, clean, tmp_path):
    d = list_files(tmp_path)
    s = RegistryStore(engine, "pai")
    for f in sorted(d.glob("*.yaml")):
        load_official_lists(s, f, country=COUNTRY)
    res = do_import(engine, tmp_path, shared_rows(), "a.xlsx")
    assert [r[2] for r in inst_rows(res)] == ["both_checks"] * 3 + ["region_conflicts_with_list"] + \
        ["both_checks"] * 2 + ["duplicate_id"]
    lists_of = {n: s.get(f"inst:t-inst-00{n}").list_ids for n in (1, 2, 3, 5, 6)}
    assert lists_of == {1: (ON, OP), 2: (ON, OS), 3: (ON,), 5: ("list:sigma-punjab",), 6: (A,)}
    assert s.get("inst:t-inst-004") is None
    assert loaded(s) == {A: 1, ON: 3, OP: 1, OS: 1, "list:sigma-punjab": 1, "list:sigma-sindh": 0}


def test_r3_the_command_line_dry_run_agrees_with_the_import(engine, clean, tmp_path):
    from scripts.os_import_batch import main

    d = list_files(tmp_path)
    path = workbook(tmp_path, shared_rows(), name="a.xlsx")
    assert main(["validate", str(path), "--country", COUNTRY, "--lists", str(d), "--decision-ref", "ref-1",
                 "--report", str(tmp_path / "dry.csv")], out=[].append) == 0
    s = RegistryStore(engine, "pai")
    for f in sorted(d.glob("*.yaml")):
        load_official_lists(s, f, country=COUNTRY)
    res = run_import(path, deps(engine), mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1",
                     report_path=tmp_path / "real.csv")
    dry = [x.split(",")[:6] for x in (tmp_path / "dry.csv").read_text().splitlines() if x.startswith("Institutions")]
    real = [x.split(",")[:6] for x in (tmp_path / "real.csv").read_text().splitlines() if x.startswith("Institutions")]
    assert dry == real and len(real) == 7 and res.counts["Institutions"]["rejected"] == 2
