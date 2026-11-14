"""P2-T28 (W12 "T28 rules"; FU-2 evidence part, FU-3): a row of an aliased id whose source is an official list adds that
list to the entity already loaded under the alias's target, and nothing else; a `required` alias that is not accepted
never lets its id load as a duplicate entity (P2 spec §4.1, gate 6; master R-32, R-35a, R-60, R-68, R-76). Fictional
data only."""

from dataclasses import replace

import pytest
import yaml

from app.os.knowledge.sheets.aliases import AliasError, load_aliases
from app.os.knowledge.sheets.importer import run_import
from app.os.knowledge.sheets.reader import file_sha256
from app.os.knowledge.sheets.undo import undo_import
from app.os.registry.lists import load_official_lists
from app.os.registry.store import RegistryError, RegistryStore
from tests.os.registry.helpers import LIST_URL, olist
from tests.os.registry.helpers import inst as reg_inst

from .helpers import COUNTRY, FakeFetcher, Page, deps, fact, inst, prog, workbook
from .test_aliases import A1, A2, EVIDENCE, alias, alias_file, attested
from .test_list_union import BETA_URL, A, B, E, do_import, loaded, two_lists

pytestmark = [pytest.mark.req("R-32"), pytest.mark.req("R-35"), pytest.mark.req("R-60"), pytest.mark.req("R-68"),
              pytest.mark.req("R-76")]
SINDH_URL = "https://lists.sindh.test/colleges"
S = "list:sindh-list"
TARGET_EV = {"url": "https://college1.alpha.test/about", "quote": "Test College 1, Alpha Town"}


def line(n=9, inst_id="T-UNI-X", **kw) -> dict:
    """A list line of the alias: its own name and quote as printed on list B, region left empty by default."""
    row = inst(n, inst_id=inst_id, source_url=BETA_URL, region="", name="TEST COLLEGE ONE (ALPHA)",
               source_quote="TEST COLLEGE ONE (ALPHA)", official_url=None)
    row.update(kw)
    return row


def alias_import(engine, tmp_path, institutions, *aliases, facts=(), name="b.xlsx", **dkw):
    path = workbook(tmp_path, institutions, facts, name=name)
    afile = alias_file(tmp_path, path, *(aliases or (alias(),)), name=name + ".aliases.yaml")
    res = run_import(path, deps(engine, attested=attested(afile), **dkw), mode="owner_accepted", actor="dev",
                     country=COUNTRY, decision_ref="ref-1", aliases=[afile])
    return res, afile


def rows_of(res, sheet="Institutions"):
    return [(r.row_id, r.bucket, r.reason) for r in res.rows if r.sheet == sheet]


# --- rules 1, 7: a list line adds the list, touches nothing else, one revision, undo restores --------------------------

def test_a_list_line_of_an_alias_adds_its_list_and_evidence_to_the_stored_target_only(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    before = s.get(E)
    res, afile = alias_import(engine, tmp_path, [line()])
    [r] = [x for x in res.rows if x.sheet == "Institutions"]
    assert (r.bucket, r.level, r.reason) == ("accepted", "verified", "alias_membership")
    assert r.detail.startswith(f"{E} + {B}")
    after = s.get(E)
    assert after.list_ids == (A, B) and loaded(s) == {A: 1, B: 1}
    # FU-2: the list line's name, quote, source and (empty) domains never replace the entity's own
    assert replace(after, list_ids=before.list_ids, attrs=before.attrs) == before
    assert {k: v for k, v in after.attrs.items() if k != "list_evidence"} == before.attrs
    ev = after.attrs["list_evidence"][B]
    assert (ev["url"], ev["quote"], ev["inst_id"], ev["import_id"]) == (BETA_URL, "TEST COLLEGE ONE (ALPHA)",
                                                                         "T-UNI-X", res.import_id)
    assert (ev["alias"]["from"], ev["alias"]["to"], ev["alias"]["checker1"], ev["alias"]["checker2"]) == (
        "T-UNI-X", "T-INST-001", A1, A2)
    assert ev["alias"]["alias_sha256"] == load_aliases(afile).sha256 and ev["alias"]["evidence"] == EVIDENCE
    assert s.get("inst:t-uni-x") is None
    revs = s.revisions(E)
    assert [x.action for x in revs] == ["insert", "change"] and revs[-1].cause_ref == f"import-{res.import_id}"
    changed = {k for k in revs[-1].after if revs[-1].after[k] != revs[-1].before[k]}
    assert changed == {"list_ids", "attrs"}
    undo_import(engine, "pai", res.import_id, actor="admin")
    assert s.get(E) == before and loaded(s) == {A: 1, B: 0}
    assert [x.action for x in s.revisions(E)] == ["insert", "change", "undo"]


def test_the_target_may_come_after_the_list_line_in_the_same_file(engine, clean, tmp_path):
    s = two_lists(engine)
    res, _ = alias_import(engine, tmp_path, [line(), inst(1)])
    assert rows_of(res) == [("T-UNI-X", "accepted", "alias_membership"), ("T-INST-001", "accepted", "both_checks")]
    assert s.get(E).list_ids == (A, B) and s.get(E).name == "Test College 1"
    assert s.get(E).attrs["list_evidence"][B]["inst_id"] == "T-UNI-X"
    undo_import(engine, "pai", res.import_id, actor="admin")
    assert s.get(E).status == "closed"  # the import created it: withdrawn, never deleted (R-60)


def test_an_unconfirmed_list_line_still_adds_the_list_at_its_level(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(checker1_result=None, checker1_name=None, checker2_approved=None,
                                                  checker2_name=None)])
    [r] = [x for x in res.rows if x.sheet == "Institutions"]
    assert (r.bucket, r.level, r.reason) == ("unconfirmed", "unconfirmed", "alias_membership")
    assert "check_unclear_or_missing" in r.detail
    assert s.get(E).list_ids == (A, B) and s.get(E).attrs["list_evidence"][B]["trust"] == "unconfirmed"


# --- rule 2: the target must be loaded, as an institution or campus ---------------------------------------------------

def test_a_list_line_whose_target_is_not_loaded_is_rejected_and_loads_nothing(engine, clean, tmp_path):
    s = two_lists(engine)
    res, _ = alias_import(engine, tmp_path, [line()])
    assert rows_of(res) == [("T-UNI-X", "rejected", "alias_target_not_loaded")]
    assert s.get(E) is None and s.get("inst:t-uni-x") is None and loaded(s) == {A: 0, B: 0}


def test_a_list_line_whose_target_row_is_rejected_in_the_file_is_rejected(engine, clean, tmp_path):
    s = two_lists(engine)
    res, _ = alias_import(engine, tmp_path, [inst(1, source_quote=None), line()])
    assert rows_of(res) == [("T-INST-001", "rejected", "no_quote"), ("T-UNI-X", "rejected", "alias_target_not_loaded")]
    assert s.get(E) is None


def test_a_list_line_whose_target_is_not_an_institution_is_rejected(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1, type="exam_board")], "a.xlsx")
    assert s.get("board:t-inst-001") is not None
    res, _ = alias_import(engine, tmp_path, [line()])
    [(_, bucket, reason)] = rows_of(res)
    assert (bucket, reason) == ("rejected", "alias_target_not_loaded")
    assert s.get("board:t-inst-001").list_ids == ()


def test_a_list_line_whose_target_was_withdrawn_is_rejected(engine, clean, tmp_path):
    s = two_lists(engine)
    first = do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    undo_import(engine, "pai", first.import_id, actor="admin")
    res, _ = alias_import(engine, tmp_path, [line()])
    assert rows_of(res) == [("T-UNI-X", "rejected", "alias_target_not_loaded")]
    assert s.get(E).list_ids == (A,) and s.get(E).status == "closed"


# --- rules 3-5: kind, region, the list's region ------------------------------------------------------------------------

def test_a_list_line_of_another_kind_is_rejected(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(type="exam_board", region="Punjab")])
    assert rows_of(res) == [("T-UNI-X", "rejected", "alias_kind_conflict")]
    assert s.get(E).list_ids == (A,)


@pytest.mark.parametrize("region, outcome", [("", ("accepted", "alias_membership")),
                                             ("Punjab", ("accepted", "alias_membership")),
                                             ("Sindh", ("rejected", "region_conflicts_with_alias"))])
def test_the_region_of_a_list_line_is_the_targets(engine, clean, tmp_path, region, outcome):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(region=region)])
    assert rows_of(res) == [("T-UNI-X", *outcome)]
    assert s.get(E).region == "punjab"
    assert s.get(E).list_ids == ((A, B) if outcome[0] == "accepted" else (A,))


def test_a_list_line_on_a_list_of_another_region_than_the_targets_is_rejected(engine, clean, tmp_path):
    s = two_lists(engine)
    s.record(replace(olist("sindh-list", region="sindh"), name="Sindh colleges", source_url=SINDH_URL), cause="import")
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(source_url=SINDH_URL)])  # region empty: the target's, punjab
    assert rows_of(res) == [("T-UNI-X", "rejected", "region_conflicts_with_list")]
    assert s.get(E).list_ids == (A,) and loaded(s)[S] == 0


# --- rule 6: the allow-list scope is the target's region and the families of all its lists -----------------------------

def test_the_allow_list_check_uses_the_targets_region_and_the_union_of_its_families(engine, clean, tmp_path):
    s = RegistryStore(engine, "pai")
    s.record(olist(family="bachelor"), cause="import")
    s.record(replace(olist("beta-list", family="intermediate"), name="Beta colleges", source_url=BETA_URL),
             cause="import")
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    tried = []

    def official(url, scope):
        tried.append((scope.region, scope.family))
        return scope.family == "intermediate"

    res, _ = alias_import(engine, tmp_path, [line()], official=official)
    [r] = [x for x in res.rows if x.sheet == "Institutions"]
    assert (r.bucket, r.reason) == ("accepted", "alias_membership")
    assert tried == [("punjab", "bachelor"), ("punjab", "intermediate")]
    assert r.payload["provenance"]["allow_list_scope"] == {"region": "punjab", "family": "intermediate"}
    assert s.get(E).attrs["list_evidence"][B]["allow_list_scope"]["family"] == "intermediate"


def test_a_list_line_off_the_allow_list_is_unconfirmed_and_still_counts(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line()], official=lambda url, scope: False)
    [r] = [x for x in res.rows if x.sheet == "Institutions"]
    assert (r.bucket, r.reason) == ("unconfirmed", "alias_membership") and "source_not_on_allow_list" in r.detail
    assert s.get(E).list_ids == (A, B)


# --- rule 8: one membership per target and list in a file ----------------------------------------------------------------

def test_a_second_list_line_adding_the_same_list_to_the_same_target_is_a_duplicate_membership(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(), line(10, inst_id="T-UNI-Y")],
                          alias(), alias(frm="T-UNI-Y"))
    assert rows_of(res) == [("T-UNI-X", "accepted", "alias_membership"),
                            ("T-UNI-Y", "rejected", "duplicate_membership")]
    assert s.get(E).list_ids == (A, B) and list(s.get(E).attrs["list_evidence"]) == [B]
    assert [x.action for x in s.revisions(E)] == ["insert", "change"]


# --- rules 9, 10: required aliases and target evidence --------------------------------------------------------------------

@pytest.mark.parametrize("where", ["alias", "file"])
def test_a_required_alias_not_accepted_rejects_every_row_of_its_id_and_creates_no_duplicate(engine, clean, tmp_path,
                                                                                            where):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    path = workbook(tmp_path, [line(official_url="https://unix.alpha.test/")], [fact(1, "T-UNI-X")], name="b.xlsx")
    a = alias(c2="no")
    doc = {"file": path.name, "sha256": file_sha256(path),
           "aliases": [{**a, "required": True} if where == "alias" else a]}
    if where == "file":
        doc["required"] = True
    afile = tmp_path / "req.yaml"
    afile.write_text(yaml.safe_dump(doc), encoding="utf-8")
    res = run_import(path, deps(engine, attested=attested(afile)), mode="owner_accepted", actor="dev", country=COUNTRY,
                     decision_ref="ref-1", aliases=[afile])
    assert rows_of(res, "Aliases") == [("T-UNI-X", "rejected", "alias_required_not_accepted")]
    assert rows_of(res) == [("T-UNI-X", "rejected", "alias_required_not_accepted")]
    assert rows_of(res, "Facts") == [("T-F-001", "rejected", "alias_required_not_accepted")]
    assert s.get("inst:t-uni-x") is None and s.get(E).list_ids == (A,)


def test_an_alias_not_required_and_not_accepted_still_loads_its_row_as_before(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(region="Punjab")], alias(c2="no"))
    assert rows_of(res) == [("T-UNI-X", "accepted", "both_checks")]  # the duplicate `required` exists to prevent
    assert s.get("inst:t-uni-x") is not None


def test_target_evidence_is_kept_with_the_alias_in_provenance(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line()], {**alias(), "required": True, "target_evidence": TARGET_EV})
    used = s.get(E).attrs["list_evidence"][B]["alias"]
    assert used["target_evidence"] == TARGET_EV and used["required"] is True
    assert res.rows[0].sheet == "Aliases" and res.rows[0].reason == "alias_applied"


@pytest.mark.parametrize("bad", [{"required": "yes please"}, {"target_evidence": "https://a.test/"},
                                 {"target_evidence": {"url": "ftp://a.test/", "quote": "q"}},
                                 {"target_evidence": {"url": "https://a.test/"}}])
def test_a_malformed_required_or_target_evidence_refuses_the_alias_file(tmp_path, bad):
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump({"file": "x.xlsx", "sha256": "ab", "aliases": [{**alias(), **bad}]}), encoding="utf-8")
    with pytest.raises(AliasError):
        load_aliases(p)
    p.write_text(yaml.safe_dump({"file": "x.xlsx", "sha256": "ab", "required": "no", "aliases": [alias()]}),
                 encoding="utf-8")
    with pytest.raises(AliasError):
        load_aliases(p)


def test_an_old_alias_file_without_the_new_keys_is_still_valid(tmp_path):
    p = tmp_path / "old.yaml"
    p.write_text(yaml.safe_dump({"file": "x.xlsx", "sha256": "ab", "aliases": [alias()]}), encoding="utf-8")
    [a] = load_aliases(p).aliases
    assert (a.required, a.target_evidence) == (False, None)


# --- rule 11: an aliased row on no list behaves as before ----------------------------------------------------------------

def test_an_aliased_row_on_no_official_list_adds_nothing_to_the_target(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    before = s.revisions(E)
    res, _ = alias_import(engine, tmp_path, [line(source_url="https://college1.alpha.test/about")])
    assert rows_of(res) == [("T-UNI-X", "skipped", "aliased")]
    assert s.get(E).list_ids == (A,) and loaded(s) == {A: 1, B: 0} and s.revisions(E) == before


# --- rule 12: validate gives the plan the import carries out ----------------------------------------------------------

def test_validate_plans_the_list_lines_as_the_import_does(engine, clean, tmp_path):
    from scripts.os_import_batch import main

    d = tmp_path / "lists"
    d.mkdir()
    (d / "national.yaml").write_text(yaml.safe_dump({"region": "national", "retrieved": "2026-11-07", "lists": [
        {"id": "alpha-list", "body": "Alpha", "name": "Alpha colleges", "url": LIST_URL, "row_count": 3},
        {"id": "beta-list", "body": "Beta", "name": "Beta colleges", "url": BETA_URL, "row_count": 3}]}))
    (d / "sindh.yaml").write_text(yaml.safe_dump({"region": "Sindh", "retrieved": "2026-11-07", "lists": [
        {"id": "sindh-list", "body": "Sindh", "name": "Sindh colleges", "url": SINDH_URL, "row_count": 3}]}))
    other = workbook(tmp_path, [inst(1), inst(2, type="exam_board")], name="other.xlsx")
    rows = [line(), line(10, inst_id="T-UNI-Y"), line(11, inst_id="T-UNI-Z", source_url=SINDH_URL),
            line(12, inst_id="T-UNI-K", type="exam_board"), line(13, inst_id="T-UNI-S", region="Sindh"),
            line(14, inst_id="T-UNI-B"), line(15, inst_id="T-UNI-N", source_url="https://college1.alpha.test/"),
            line(16, inst_id="T-UNI-A", source_url=LIST_URL)]
    path = workbook(tmp_path, rows, name="b.xlsx")
    afile = alias_file(tmp_path, path, alias(), alias(frm="T-UNI-Y"), alias(frm="T-UNI-Z"), alias(frm="T-UNI-K"),
                       alias(frm="T-UNI-S"), alias(frm="T-UNI-B", to="T-INST-002"), alias(frm="T-UNI-N"),
                       alias(frm="T-UNI-A"))
    assert main(["validate", str(path), "--country", COUNTRY, "--lists", str(d), "--decision-ref", "ref-1",
                 "--institutions-from", str(other), "--aliases", str(afile), "--assume-aliases-attested",
                 "--report", str(tmp_path / "dry.csv")], out=[].append) == 0
    s = RegistryStore(engine, "pai")
    for f in sorted(d.glob("*.yaml")):
        load_official_lists(s, f, country=COUNTRY)
    run_import(other, deps(engine), mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")
    run_import(path, deps(engine, attested=attested(afile)), mode="owner_accepted", actor="dev", country=COUNTRY,
               decision_ref="ref-1", aliases=[afile], report_path=tmp_path / "real.csv")

    def inst_lines(name):
        return [x.split(",")[:6] for x in (tmp_path / name).read_text().splitlines() if x.startswith("Institutions")]

    real = inst_lines("real.csv")
    assert inst_lines("dry.csv") == real
    assert [x[5] for x in real] == ["alias_membership", "duplicate_membership", "region_conflicts_with_list",
                                    "alias_kind_conflict", "region_conflicts_with_alias", "alias_target_not_loaded",
                                    "aliased", "aliased"]
    assert s.get(E).list_ids == (A, B)


# --- the store method itself ---------------------------------------------------------------------------------------------

def test_add_lists_appends_merges_evidence_and_refuses_what_a_list_cannot_name(engine, clean):
    s = two_lists(engine)
    s.record(replace(olist("sindh-list", region="sindh"), name="Sindh colleges", source_url=SINDH_URL), cause="import")
    s.record(reg_inst("one", attrs={"keep": 1}), cause="import")
    assert s.add_lists("inst:one", [B], {"url": BETA_URL}, cause="import", cause_ref="import-9").action == "change"
    e = s.get("inst:one")
    assert e.list_ids == (A, B) and e.attrs == {"keep": 1, "list_evidence": {B: {"url": BETA_URL}}}
    again = s.add_lists("inst:one", [B], {"url": "https://other.test/"}, cause="import")
    assert again.action == "unchanged" and s.get("inst:one").attrs["list_evidence"][B] == {"url": BETA_URL}
    with pytest.raises(RegistryError, match="region"):
        s.add_lists("inst:one", [S], {}, cause="import")  # a sindh list for a punjab institution
    with pytest.raises(RegistryError, match="not in the registry"):
        s.add_lists("inst:none", [B], {}, cause="import")
    with pytest.raises(RegistryError, match="not in the registry"):
        s.add_lists("inst:one", ["list:missing"], {}, cause="import")
    with pytest.raises(RegistryError, match="official list"):
        s.add_lists(A, [B], {}, cause="import")
    assert s.get("inst:one").list_ids == (A, B) and [x.action for x in s.revisions("inst:one")] == ["insert", "change"]


# --- fix round 1 (review of T28) -------------------------------------------------------------------------------------

UNCLEAR = {"checker1_result": None, "checker1_name": None, "checker2_approved": None, "checker2_name": None}


def _required_refused(tmp_path, path):
    """An alias file for `path` whose one alias is required and not accepted (check 2 says no)."""
    afile = tmp_path / "req.yaml"
    afile.write_text(yaml.safe_dump({"file": path.name, "sha256": file_sha256(path),
                                     "aliases": [{**alias(c2="no"), "required": True}]}), encoding="utf-8")
    return afile


def test_s1_a_required_alias_not_accepted_also_rejects_its_programmes_and_child_rows(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    child = inst(5, ctype="exam_calendar", parent_id="T-UNI-X", timezone="Etc/UTC")
    path = workbook(tmp_path, [line(official_url="https://unix.alpha.test/"), child], (), [prog(1, "T-UNI-X")],
                    name="b.xlsx")
    afile = _required_refused(tmp_path, path)
    res = run_import(path, deps(engine, attested=attested(afile)), mode="owner_accepted", actor="dev", country=COUNTRY,
                     decision_ref="ref-1", aliases=[afile])
    assert rows_of(res) == [("T-UNI-X", "rejected", "alias_required_not_accepted"),
                            ("T-INST-005", "rejected", "alias_required_not_accepted")]  # its parent_id names the id
    assert rows_of(res, "Programmes") == [("T-PRG-001", "rejected", "alias_required_not_accepted")]
    assert s.get("inst:t-uni-x") is None and s.list(parent_id="inst:t-uni-x") == []
    assert deps(engine).programmes.get("T-PRG-001") is None


def _fetching(pages):
    return {"fetcher": FakeFetcher({u: Page(text=t) for u, t in pages.items()})}


def test_s2_a_refetch_mismatch_keeps_alias_membership_and_reports_the_mismatch_beside_it(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(read_method="webfetch (model-extracted)")],
                          **_fetching({BETA_URL: "a page without the line"}))
    [r] = [x for x in res.rows if x.sheet == "Institutions"]
    assert (r.bucket, r.level, r.reason) == ("unconfirmed", "unconfirmed", "alias_membership")
    assert r.payload["level_reason"] == "quote_not_found" and "quote_not_found" in r.detail
    assert s.get(E).list_ids == (A, B) and s.get(E).attrs["list_evidence"][B]["trust"] == "unconfirmed"


def test_s2_an_unclear_list_line_whose_quote_matches_on_refetch_is_promoted(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line(**UNCLEAR)],
                          **_fetching({BETA_URL: "1. TEST COLLEGE ONE (ALPHA), Alpha Town"}))
    [r] = [x for x in res.rows if x.sheet == "Institutions"]
    assert (r.bucket, r.level, r.reason) == ("accepted", "confirmed", "alias_membership")
    assert r.payload["level_reason"] == "quote_matched_on_refetch" and "quote_matched_on_refetch" in r.detail
    assert s.get(E).attrs["list_evidence"][B]["trust"] == "confirmed"


def test_s3_a_stronger_line_upgrades_weaker_list_evidence_and_undo_restores_it(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    alias_import(engine, tmp_path, [line(**UNCLEAR)])
    weak = s.get(E)
    assert weak.attrs["list_evidence"][B]["trust"] == "unconfirmed"
    res, _ = alias_import(engine, tmp_path, [line(10)], name="c.xlsx")  # the same line, checked by both checks
    [r] = [x for x in res.rows if x.sheet == "Institutions"]
    assert (r.bucket, r.level, r.reason) == ("accepted", "verified", "alias_membership")
    assert "evidence upgraded: " + B in r.detail and r.payload["membership"]["lists"] == ()
    up = s.get(E)
    assert up.list_ids == weak.list_ids == (A, B)
    assert up.attrs["list_evidence"][B]["trust"] == "verified"
    assert up.attrs["list_evidence"][B]["import_id"] == res.import_id
    assert replace(up, attrs=weak.attrs) == weak  # nothing else moved
    assert {k: v for k, v in up.attrs.items() if k != "list_evidence"} == \
        {k: v for k, v in weak.attrs.items() if k != "list_evidence"}
    assert [x.action for x in s.revisions(E)] == ["insert", "change", "change"]
    undo_import(engine, "pai", res.import_id, actor="admin")
    assert s.get(E) == weak


def test_s3_a_line_no_stronger_than_the_stored_evidence_changes_nothing(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    alias_import(engine, tmp_path, [line()])  # verified evidence
    before, stored = s.revisions(E), s.get(E)
    res, _ = alias_import(engine, tmp_path, [line(retrieved="2026-11-05")], name="c.xlsx")  # re-read, also verified
    assert rows_of(res) == [("T-UNI-X", "skipped", "aliased")]
    res, _ = alias_import(engine, tmp_path, [line(11, **UNCLEAR)], name="d.xlsx")
    assert rows_of(res) == [("T-UNI-X", "skipped", "aliased")]
    assert s.revisions(E) == before and s.get(E) == stored


def test_s3_a_line_capped_to_the_stored_level_upgrades_nothing(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    alias_import(engine, tmp_path, [line(**UNCLEAR)])
    before = s.revisions(E)
    res, _ = alias_import(engine, tmp_path, [line(10)], name="c.xlsx", official=lambda url, scope: False)
    assert rows_of(res) == [("T-UNI-X", "skipped", "aliased")]  # off the allow-list: unconfirmed, no better than stored
    assert s.revisions(E) == before


@pytest.mark.parametrize("status", ["merged", "renamed"])
def test_m1_a_merged_or_renamed_target_is_not_loaded_for_a_list_line(engine, clean, tmp_path, status):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1), inst(2)], "a.xlsx")
    s.record(replace(s.get(E), status=status, successor_id="inst:t-inst-002"), cause="review")
    res, _ = alias_import(engine, tmp_path, [line()])
    assert rows_of(res) == [("T-UNI-X", "rejected", "alias_target_not_loaded")]
    assert s.get(E).list_ids == (A,) and s.get("inst:t-inst-002").list_ids == (A,)
    with pytest.raises(RegistryError, match=status):
        s.add_lists(E, [B], {}, cause="import")


def test_m5_two_sessions_adding_lists_at_once_lose_nothing(engine, clean):
    import threading

    s = two_lists(engine)
    for name in ("c-list", "d-list"):
        s.record(replace(olist(name), source_url=f"https://lists.{name}.test/"), cause="import")
    s.record(reg_inst("one"), cause="import")
    gate, errors = threading.Barrier(2), []

    def add(list_id):
        try:
            gate.wait(5)
            RegistryStore(engine, "pai").add_lists("inst:one", [list_id], {"url": list_id}, cause="import")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=add, args=(x,)) for x in ("list:c-list", "list:d-list")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    e = s.get("inst:one")
    assert set(e.list_ids) == {A, "list:c-list", "list:d-list"} and e.list_ids[0] == A
    assert set(e.attrs["list_evidence"]) == {"list:c-list", "list:d-list"}
    revs = s.revisions("inst:one")
    assert [x.action for x in revs] == ["insert", "change", "change"]
    assert revs[2].before == revs[1].after  # serialised: the second saw the first's write
