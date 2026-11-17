"""P2-T19: the allow-list family of a row is the family of every official list its entity is on (H3 data), not one
`--family` per run, and `validate --allow-list DIR` judges the sources as the import does (P2 spec §4.2, §4.6, P2-D10;
master R-24, R-68, R-71). Fictional lists, hosts and institutions on `.test` domains only."""

import csv
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.os.knowledge.sheets.aliases import load_aliases
from app.os.knowledge.sheets.importer import build_context, official_by_host, plan_file, run_import
from app.os.knowledge.sheets.plan import PlanContext
from app.os.knowledge.sources.allowlist import SourceDomains, file_lookup, load_allowlist
from app.os.registry.lists import load_official_lists
from app.os.registry.model import NATIONAL
from app.os.registry.store import RegistryStore
from scripts.os_import_batch import main
from tests.os.registry.helpers import LIST_URL

from .helpers import COUNTRY, deps, fact, inst, prog, workbook
from .test_aliases import alias, alias_file, attested

pytestmark = [pytest.mark.req("R-24"), pytest.mark.req("R-68"), pytest.mark.req("R-71")]
BETA_URL = "https://lists.beta.test/colleges"
A, B = "list:alpha-list", "list:beta-list"
FAMILIES = {A: "bachelor", B: "intermediate"}  # what the list files say; the code reads it, never names it
ALPHA_NOTICE = "https://admissions.alpha.test/notice"
BETA_NOTICE = "https://admissions.beta.test/notice"


def allow_files(tmp: Path, extra: dict | None = None) -> Path:
    """Two region x family files: the alpha hosts serve (punjab, bachelor), the beta hosts (punjab, intermediate)."""
    d = tmp / "allow"
    d.mkdir(exist_ok=True)
    body = {"tier": "institution", "list_ref": "fictional list page", "reviewed_by": "tester",
            "multiple_domains_ok": True}  # one body, two hosts, confirmed (else R-71 sets both suspect)
    files = {"punjab-bachelor.yaml": {"region": "punjab", "family": "bachelor", "bodies": [
                 {**body, "body_ref": "body:alpha", "domains": ["lists.alpha.test", "admissions.alpha.test"]}]},
             "punjab-intermediate.yaml": {"region": "punjab", "family": "intermediate", "bodies": [
                 {**body, "body_ref": "body:beta", "domains": ["lists.beta.test", "admissions.beta.test"]}]}}
    files.update(extra or {})
    for name, data in files.items():
        (d / name).write_text(yaml.safe_dump(data), encoding="utf-8")
    return d


def list_files(tmp: Path, families: dict[str, str] | None = None) -> Path:
    """The official-list files (H3 shape): alpha-list at LIST_URL, beta-list at BETA_URL, both national."""
    fam = FAMILIES if families is None else families
    d = tmp / "lists"
    d.mkdir(exist_ok=True)
    lists = []
    for lid, url in ((A, LIST_URL), (B, BETA_URL)):
        item = {"id": lid.split(":")[1], "body": "Fictional body", "name": f"{lid} institutions", "url": url,
                "row_count": 3}
        if fam.get(lid):
            item["family"] = fam[lid]
        lists.append(item)
    (d / "national.yaml").write_text(yaml.safe_dump({"region": "national", "retrieved": date(2026, 11, 7),
                                                     "lists": lists}), encoding="utf-8")
    return d


def context(tmp: Path, *, families=None, family="", allow: Path | None = None, **kw) -> PlanContext:
    ctx = build_context(None, country=COUNTRY, mode="owner_accepted", batch_ref="b", family=family,
                        list_urls={LIST_URL.lower(): A, BETA_URL.lower(): B}, list_regions={A: NATIONAL, B: NATIONAL},
                        list_families=FAMILIES if families is None else families)
    ctx.official = official_by_host(file_lookup(load_allowlist(allow or allow_files(tmp))))
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def plan(tmp, ctx, institutions=(), facts=(), programmes=()):
    path = workbook(tmp, institutions, facts, programmes)
    return {(r.sheet, r.row_id): r for r in plan_file(path, ctx)[1]}


def fate(r) -> tuple:
    return r.bucket, r.level, r.reason


def scope_of(r) -> dict | None:
    return r.payload.get("provenance", {}).get("allow_list_scope")


def test_a_mixed_batch_judges_each_row_with_the_family_of_its_own_list(tmp_path):
    rows = plan(tmp_path, context(tmp_path),
                [inst(1), inst(2, source_url=BETA_URL)],
                [fact(1, "T-INST-001", source_url=ALPHA_NOTICE), fact(2, "T-INST-002", source_url=BETA_NOTICE),
                 fact(3, "T-INST-002", field_="x", source_url=ALPHA_NOTICE)])  # an alpha host for a beta-list entity
    assert fate(rows[("Institutions", "T-INST-001")]) == ("accepted", "verified", "both_checks")
    assert fate(rows[("Institutions", "T-INST-002")]) == ("accepted", "verified", "both_checks")
    assert scope_of(rows[("Institutions", "T-INST-001")]) == {"region": "punjab", "family": "bachelor"}
    assert scope_of(rows[("Institutions", "T-INST-002")]) == {"region": "punjab", "family": "intermediate"}
    assert fate(rows[("Facts", "T-F-001")])[0] == "accepted"
    assert scope_of(rows[("Facts", "T-F-001")]) == {"region": "punjab", "family": "bachelor"}
    assert fate(rows[("Facts", "T-F-002")])[0] == "accepted"
    assert scope_of(rows[("Facts", "T-F-002")]) == {"region": "punjab", "family": "intermediate"}
    no = rows[("Facts", "T-F-003")]  # per row, not a union over the batch: the alpha host serves only bachelor
    assert fate(no) == ("unconfirmed", "unconfirmed", "source_not_on_allow_list")
    assert "punjab/intermediate" in no.detail and scope_of(no) is None
    # the W4 finding, for contrast: one --family for the run (no list families) passes only half of the same batch
    rows = plan(tmp_path, context(tmp_path, families={}, family="bachelor"), [inst(1), inst(2, source_url=BETA_URL)])
    assert fate(rows[("Institutions", "T-INST-001")])[0] == "accepted"
    assert fate(rows[("Institutions", "T-INST-002")])[2] == "source_not_on_allow_list"


def test_an_entity_on_lists_of_two_families_passes_with_either(tmp_path):
    # in the file: two rows of one entity, one per list; its fact's host serves only the second list's family
    rows = plan(tmp_path, context(tmp_path), [inst(1), inst(1, source_url=BETA_URL)],
                [fact(1, "T-INST-001", source_url=BETA_NOTICE)])
    assert scope_of(rows[("Facts", "T-F-001")]) == {"region": "punjab", "family": "intermediate"}
    assert fate(rows[("Facts", "T-F-001")])[0] == "accepted"
    # stored: the entity is already on the alpha list; its new row comes from the beta list (T16 union)
    ctx = context(tmp_path, existing_lists=lambda rid: (A,) if rid == "inst:t-inst-001" else ())
    rows = plan(tmp_path, ctx, [inst(1, source_url=BETA_URL, source_quote="x")],
                [fact(1, "T-INST-001", source_url=ALPHA_NOTICE)])
    assert rows[("Institutions", "T-INST-001")].payload["lists"] == (A, B)
    assert scope_of(rows[("Facts", "T-F-001")]) == {"region": "punjab", "family": "bachelor"}


def test_with_no_list_family_the_run_family_is_used_and_with_none_nothing_changes(tmp_path):
    seen = []
    ctx = context(tmp_path, families={}, family="intermediate")
    inner = ctx.official
    ctx.official = lambda url, sc: seen.append(sc) or inner(url, sc)
    rows = plan(tmp_path, ctx, [inst(1, source_url=BETA_URL)])
    assert [(s.region, s.family) for s in seen] == [("punjab", "intermediate")]
    assert scope_of(rows[("Institutions", "T-INST-001")]) == {"region": "punjab", "family": "intermediate"}
    rows = plan(tmp_path, context(tmp_path, families={}, family=""), [inst(1)])  # as before T19: no family matches
    r = rows[("Institutions", "T-INST-001")]
    assert fate(r) == ("unconfirmed", "unconfirmed", "source_not_on_allow_list") and "punjab/-" in r.detail


def test_an_aliased_entity_is_judged_by_the_lists_of_its_target(tmp_path):
    institutions = [inst(1, source_url=BETA_URL)]
    facts = [fact(1, "T-UNI-X", source_url=BETA_NOTICE)]
    path = workbook(tmp_path, institutions, facts)
    af = alias_file(tmp_path, path, alias())
    ctx = context(tmp_path)
    ctx.aliases, ctx.attested = (__import__("app.os.knowledge.sheets.aliases", fromlist=["x"]).load_aliases(af),), \
        attested(af)
    rows = {(r.sheet, r.row_id): r for r in plan_file(path, ctx)[1]}
    r = rows[("Facts", "T-F-001")]
    assert fate(r)[0] == "accepted" and r.payload["ref"] == "inst:t-inst-001"
    assert scope_of(r) == {"region": "punjab", "family": "intermediate"}


def test_facts_on_a_programme_use_the_region_and_lists_of_its_institution(tmp_path):
    rows = plan(tmp_path, context(tmp_path), [inst(1, source_url=BETA_URL)],
                [fact(1, "T-PRG-001", source_url=BETA_NOTICE)], [prog(1, "T-INST-001", source_url=BETA_NOTICE)])
    assert scope_of(rows[("Programmes", "T-PRG-001")]) == {"region": "punjab", "family": "intermediate"}
    r = rows[("Facts", "T-F-001")]
    assert r.payload["scope"] == "programme" and r.payload["region"] == "punjab"
    assert fate(r)[0] == "accepted" and scope_of(r) == {"region": "punjab", "family": "intermediate"}
    # a programme stored by an earlier import: its institution comes from the programme store
    ctx = context(tmp_path, existing_programmes=lambda ref: ref == "T-PRG-009",
                  existing_programme_institution=lambda ref: "inst:t-old" if ref == "T-PRG-009" else None,
                  existing_region=lambda rid: "punjab" if rid == "inst:t-old" else None,
                  existing_lists=lambda rid: (A,) if rid == "inst:t-old" else ())
    rows = plan(tmp_path, ctx, [], [fact(1, "T-PRG-009", source_url=ALPHA_NOTICE),
                                    fact(2, "T-PRG-009", field_="x", source_url=BETA_NOTICE)])
    assert scope_of(rows[("Facts", "T-F-001")]) == {"region": "punjab", "family": "bachelor"}
    assert fate(rows[("Facts", "T-F-002")])[2] == "source_not_on_allow_list"


# --- the dry run and the import agree ---------------------------------------------------------------------------------


def run_cli(argv):
    out: list[str] = []
    return main(argv, out=out.append), "\n".join(out)


def report(path: Path) -> list[tuple]:
    with path.open(encoding="utf-8") as f:
        return [(r["sheet"], r["row_id"], r["bucket"], r["level"], r["reason"]) for r in csv.DictReader(f)]


def mixed(tmp: Path) -> Path:
    return workbook(tmp, [inst(1), inst(2, source_url=BETA_URL), inst(3, source_url=BETA_URL)],
                    [fact(1, "T-INST-001", source_url=ALPHA_NOTICE), fact(2, "T-INST-002", source_url=BETA_NOTICE),
                     fact(3, "T-INST-002", field_="x", source_url=ALPHA_NOTICE),
                     fact(4, "T-INST-003", source_url="https://admissions.gamma.test/notice"),
                     fact(5, "T-PRG-001", source_url=BETA_NOTICE)],
                    [prog(1, "T-INST-002", source_url=BETA_NOTICE)])


def claimed() -> dict:
    """gamma: two domains claim one body with no preferred suffix, so both are suspect (R-71)."""
    return {"punjab-intermediate-gamma.yaml": {"region": "punjab", "family": "intermediate", "bodies": [
        {"tier": "institution", "list_ref": "fictional", "reviewed_by": "tester", "body_ref": "body:gamma",
         "domains": ["admissions.gamma.test", "gamma-other.test"]}]}}


def test_validate_with_the_allow_list_plans_every_row_as_the_import(engine, clean, tmp_path):
    lists, allow, path = list_files(tmp_path), allow_files(tmp_path, claimed()), mixed(tmp_path)
    code, text = run_cli(["validate", str(path), "--country", COUNTRY, "--lists", str(lists),
                          "--allow-list", str(allow), "--report", str(tmp_path / "dry.csv")])
    assert code == 0 and "allow-list: checked against 6 entries" in text and "suspect in the database" in text
    dry = report(tmp_path / "dry.csv")

    reg = RegistryStore(engine, "pai")
    load_official_lists(reg, lists / "national.yaml", country=COUNTRY)
    domains = SourceDomains(engine, "pai")
    domains.sync(load_allowlist(allow))
    d = deps(engine, official=official_by_host(domains.is_listed))
    res = run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1",
                     report_path=tmp_path / "real.csv")
    real = report(tmp_path / "real.csv")
    assert dry == real
    got = {(s, i): (b, reason) for s, i, b, _, reason in real}
    assert got[("Facts", "T-F-001")][0] == got[("Facts", "T-F-002")][0] == got[("Facts", "T-F-005")][0] == "accepted"
    assert got[("Facts", "T-F-003")] == ("unconfirmed", "source_not_on_allow_list")
    assert got[("Facts", "T-F-004")] == ("unconfirmed", "source_not_on_allow_list")  # a suspect claim, in both
    assert reg.get("inst:t-inst-002").attrs["provenance"]["allow_list_scope"] == {"region": "punjab",
                                                                                  "family": "intermediate"}
    assert res.counts["Facts"]["accepted"] == 3


def test_validate_without_the_allow_list_says_it_was_not_checked(tmp_path):
    path = workbook(tmp_path, [inst(1)])
    code, text = run_cli(["validate", str(path), "--country", COUNTRY, "--no-list-needed"])
    assert code == 0 and "allow-list: NOT checked" in text and "Institutions: accepted 1" in text
    code, text = run_cli(["validate", str(path), "--country", COUNTRY, "--no-list-needed", "--allow-list",
                          str(allow_files(tmp_path))])
    assert "no list families (give --lists)" in text and "source_not_on_allow_list" not in text
    assert "Institutions: accepted 0, unconfirmed 1" in text


# --- the re-fetch reads the page for the scope the plan accepted (review S1) --------------------------------------------


class ScopedFetcher:
    """A page gateway that reads a page only when its host is on the allow-list files for the scope asked."""

    def __init__(self, allow: Path, text: str):
        self.listed, self.text, self.calls = file_lookup(load_allowlist(allow)), text, []

    def fetch(self, url, own, shared, scope=None):
        from urllib.parse import urlsplit

        from .helpers import Page

        self.calls.append((url, scope.region, scope.family))
        ok = self.listed(urlsplit(url).hostname or "", scope)
        return Page(self.text) if ok else Page(blocked="not_official")


def test_a_refetched_row_of_another_family_than_the_run_keeps_its_level(engine, clean, tmp_path):
    lists, allow = list_files(tmp_path), allow_files(tmp_path)
    load_official_lists(RegistryStore(engine, "pai"), lists / "national.yaml", country=COUNTRY)
    model = {"read_method": "webfetch (model-extracted)", "source_url": BETA_NOTICE}
    path = workbook(tmp_path, [inst(1), inst(2, source_url=BETA_URL)],
                    [fact(1, "T-INST-002", **model),  # accepted by both checks: re-fetched (no waiver for this file)
                     fact(2, "T-INST-002", field_="y", chk={"checker1_result": "unclear"}, **model)])  # promotable
    fetcher = ScopedFetcher(allow, "Notice. Last date 2027-07-15 for all.")
    d = deps(engine, official=official_by_host(file_lookup(load_allowlist(allow))), fetcher=fetcher)
    res = run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1",
                     family="bachelor")  # the run's family is the other one
    got = {r.row_id: fate(r) for r in res.rows if r.sheet == "Facts"}
    assert got["T-F-001"] == ("accepted", "verified", "both_checks")
    assert got["T-F-002"] == ("accepted", "confirmed", "quote_matched_on_refetch")
    assert {(region, fam) for _, region, fam in fetcher.calls} == {("punjab", "intermediate")}


def test_with_the_real_gateway_a_row_is_fetched_only_under_scopes_it_is_listed_for(engine, clean, tmp_path,
                                                                                    fixture_sites):
    """Re-review R1-S1: the gateway caches a refusal by URL, so a fetch under an unlisted scope would also refuse the
    same URL for a listed one. The import asks the allow-list first and fetches only listed scopes."""
    from app.os.knowledge.research.pages import PageGateway
    from app.os.knowledge.sources.suspect import SourceGuard
    from app.os.settings import load_settings

    host = "www.alpha-university.test"  # a fixture site; listed only for (punjab, intermediate) here
    allow = allow_files(tmp_path, {"punjab-intermediate-uni.yaml": {"region": "punjab", "family": "intermediate",
        "bodies": [{"tier": "institution", "list_ref": "fictional", "reviewed_by": "tester", "body_ref": "body:uni",
                    "domains": ["alpha-university.test"]}]}})
    load_official_lists(RegistryStore(engine, "pai"), list_files(tmp_path) / "national.yaml", country=COUNTRY)
    domains = SourceDomains(engine, "pai")
    domains.sync(load_allowlist(allow))
    gw = PageGateway(engine, "pai", load_settings({"DATABASE_URL": "x"}), client=fixture_sites.client(),
                     sleep=lambda s: None, sources=SourceGuard(engine, "pai"))
    url = fixture_sites.url(host, "/admissions/notice")
    unclear = {"read_method": "webfetch (model-extracted)", "source_url": url, "chk": {"checker1_result": "unclear"},
               "quote_verbatim": "Applications close on 1 August 2027."}
    path = workbook(tmp_path, [inst(1), inst(1, source_url=BETA_URL), inst(2)],
                    [fact(1, "T-INST-002", field_="first", **unclear),  # on a bachelor list only: listed for no scope
                     fact(2, "T-INST-001", field_="second", **unclear)])  # lists of both families; bachelor sorts first
    d = deps(engine, official=official_by_host(domains.is_listed), fetcher=gw)
    res = run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")
    got = {r.row_id: (r.bucket, r.reason) for r in res.rows if r.sheet == "Facts"}
    assert got["T-F-001"] == ("unconfirmed", "check_unclear_or_missing")  # refused without a fetch: not promoted
    assert got["T-F-002"] == ("accepted", "quote_matched_on_refetch")  # fetched under (punjab, intermediate) only
