"""P2-T21: a body (a regulator, board, admission body or system, entry test: a kind in SERVES_A_REGION) is on no list
with a family, so its rows are judged against every family the run knows from its official lists, `--family` first.
Every other kind keeps the P2-T19 rule. Controller decision under the owner's delegation of 2026-11-14 (P2 spec §4.2,
P2-D10; master R-24, R-68, R-71). Fictional lists, hosts and bodies on `.test` domains only."""

import pytest

from app.os.knowledge.sheets.importer import official_by_host, run_import
from app.os.knowledge.sources.allowlist import SourceDomains, file_lookup, load_allowlist
from app.os.registry.lists import load_official_lists
from app.os.registry.store import RegistryStore

from .helpers import COUNTRY, deps, fact, inst
from .test_allowlist_family import (A, ALPHA_NOTICE, BETA_NOTICE, BETA_URL, ScopedFetcher, allow_files, context, fate,
                                    list_files, plan, report, run_cli, scope_of, workbook)

pytestmark = [pytest.mark.req("R-24"), pytest.mark.req("R-68"), pytest.mark.req("R-71")]
BODY = "body:t-body-001"


def body(n=1, *, ctype="admission_body", **kw) -> dict:
    """A body row of the Institutions sheet: no official list names it; its source is its own notice."""
    return inst(n, ctype=ctype, inst_id=f"T-BODY-{n:03d}", name=f"Test Admission Body {n}",
                **{"source_url": BETA_NOTICE, "source_quote": f"Test Admission Body {n}", **kw})


def basis(r) -> str | None:
    return r.payload.get("provenance", {}).get("family_basis")


def spy(ctx) -> list:
    seen, inner = [], ctx.official
    ctx.official = lambda url, sc: seen.append((sc.region, sc.family)) or inner(url, sc)
    return seen


def test_a_body_passes_on_a_host_listed_only_under_the_other_family(tmp_path):
    ctx = context(tmp_path, family="bachelor")  # the run's family is bachelor; the beta host serves intermediate only
    seen = spy(ctx)
    rows = plan(tmp_path, ctx, [body()])
    r = rows[("Institutions", "T-BODY-001")]
    assert fate(r) == ("accepted", "verified", "both_checks")
    assert scope_of(r) == {"region": "punjab", "family": "intermediate"} and basis(r) == "body_any"
    assert seen == [("punjab", "bachelor"), ("punjab", "intermediate")]  # --family first, then the others sorted
    assert r.payload["allow_list_families"] == ("bachelor", "intermediate")
    # with no --family: every family of the loaded lists, sorted
    rows = plan(tmp_path, context(tmp_path), [body(ctype="professional_regulator")])
    r = rows[("Institutions", "T-BODY-001")]
    assert fate(r)[0] == "accepted" and basis(r) == "body_any"
    assert r.payload["allow_list_families"] == ("bachelor", "intermediate")


def test_an_institution_on_no_list_with_a_family_still_uses_only_the_run_family(tmp_path):
    ctx = context(tmp_path, families={A: "bachelor"}, family="bachelor")  # the beta list has no family here
    seen = spy(ctx)
    rows = plan(tmp_path, ctx, [inst(2, source_url=BETA_URL)])  # beta hosts serve intermediate only
    r = rows[("Institutions", "T-INST-002")]
    assert fate(r) == ("unconfirmed", "unconfirmed", "source_not_on_allow_list")
    assert seen == [("punjab", "bachelor")] and "punjab/intermediate" not in r.detail
    assert r.payload["allow_list_families"] == ("bachelor",)
    ctx = context(tmp_path, families={A: "bachelor"}, family="intermediate")
    r = plan(tmp_path, ctx, [inst(2, source_url=BETA_URL)])[("Institutions", "T-INST-002")]
    assert fate(r)[0] == "accepted" and basis(r) == "run"
    # an entity of an unknown kind (no meta: a stored id the plan knows nothing of) keeps T19's rule
    ctx = context(tmp_path, family="bachelor", existing_institutions=lambda i: "x:t-old" if i == "T-OLD" else None,
                  existing_region=lambda rid: "punjab" if rid == "x:t-old" else None)
    r = plan(tmp_path, ctx, [], [fact(1, "T-OLD", source_url=BETA_NOTICE)])[("Facts", "T-F-001")]
    assert fate(r)[2] == "source_not_on_allow_list" and r.payload["allow_list_families"] == ("bachelor",)
    assert "scopes tried: punjab/bachelor" in r.detail


def test_a_body_in_another_region_still_fails(tmp_path):
    rows = plan(tmp_path, context(tmp_path, family="bachelor"), [body(region="Sindh")])
    r = rows[("Institutions", "T-BODY-001")]
    assert fate(r) == ("unconfirmed", "unconfirmed", "source_not_on_allow_list") and scope_of(r) is None
    assert "scopes tried: sindh/bachelor, sindh/intermediate" in r.detail  # every family, never another region


def test_facts_on_a_body_are_judged_against_every_family(tmp_path):
    # planned in the file: the body's own row is on a bachelor host, its fact on an intermediate one
    rows = plan(tmp_path, context(tmp_path, family="bachelor"), [body(source_url=ALPHA_NOTICE)],
                [fact(1, "T-BODY-001", source_url=BETA_NOTICE),
                 fact(2, "T-BODY-001", field_="x", source_url="https://admissions.unlisted.test/notice")])
    assert scope_of(rows[("Institutions", "T-BODY-001")]) == {"region": "punjab", "family": "bachelor"}
    r = rows[("Facts", "T-F-001")]
    assert fate(r)[0] == "accepted" and r.payload["ref"] == BODY
    assert scope_of(r) == {"region": "punjab", "family": "intermediate"} and basis(r) == "body_any"
    no = rows[("Facts", "T-F-002")]  # a host on no entry stays refused
    assert fate(no)[2] == "source_not_on_allow_list" and "punjab/bachelor, punjab/intermediate" in no.detail
    # stored by an earlier import: the kind comes from the registry
    ctx = context(tmp_path, existing_institutions=lambda i: "reg:t-reg-001" if i == "T-REG-001" else None,
                  existing_region=lambda rid: "punjab" if rid == "reg:t-reg-001" else None,
                  registry_info=lambda rid: {"kind": "regulator", "calendar_type": None, "timezone": None,
                                             "parent_id": None} if rid == "reg:t-reg-001" else None)
    r = plan(tmp_path, ctx, [], [fact(1, "T-REG-001", source_url=BETA_NOTICE)])[("Facts", "T-F-001")]
    assert fate(r)[0] == "accepted" and basis(r) == "body_any"
    assert scope_of(r) == {"region": "punjab", "family": "intermediate"}


def test_the_provenance_says_why_the_families_were_tried(tmp_path):
    rows = plan(tmp_path, context(tmp_path, family="intermediate"), [inst(1), body()],
                [fact(1, "T-INST-001", source_url=ALPHA_NOTICE), fact(2, "T-BODY-001", source_url=BETA_NOTICE)])
    assert basis(rows[("Institutions", "T-INST-001")]) == "lists"
    assert basis(rows[("Facts", "T-F-001")]) == "lists"
    assert basis(rows[("Institutions", "T-BODY-001")]) == "body_any"
    assert basis(rows[("Facts", "T-F-002")]) == "body_any"
    # no list family loaded at all: the run's family, as before
    r = plan(tmp_path, context(tmp_path, families={}, family="intermediate"), [body()])[("Institutions", "T-BODY-001")]
    assert fate(r)[0] == "accepted" and basis(r) == "run"


def test_validate_with_the_allow_list_judges_bodies_as_the_import(engine, clean, tmp_path):
    lists, allow = list_files(tmp_path), allow_files(tmp_path)
    path = workbook(tmp_path, [inst(1), body(), body(2, region="Sindh")],
                    [fact(1, "T-BODY-001", source_url=ALPHA_NOTICE), fact(2, "T-BODY-002", source_url=BETA_NOTICE),
                     fact(3, "T-INST-001", source_url=BETA_NOTICE)])
    code, text = run_cli(["validate", str(path), "--country", COUNTRY, "--lists", str(lists), "--family", "bachelor",
                          "--allow-list", str(allow), "--report", str(tmp_path / "dry.csv")])
    assert code == 0
    dry = report(tmp_path / "dry.csv")

    reg = RegistryStore(engine, "pai")
    load_official_lists(reg, lists / "national.yaml", country=COUNTRY)
    domains = SourceDomains(engine, "pai")
    domains.sync(load_allowlist(allow))
    res = run_import(path, deps(engine, official=official_by_host(domains.is_listed)), mode="owner_accepted",
                     actor="dev", country=COUNTRY, decision_ref="ref-1", family="bachelor",
                     report_path=tmp_path / "real.csv")
    real = report(tmp_path / "real.csv")
    assert dry == real
    got = {(s, i): (b, reason) for s, i, b, _, reason in real}
    assert got[("Institutions", "T-BODY-001")] == ("accepted", "both_checks")
    assert got[("Facts", "T-F-001")][0] == "accepted"
    assert got[("Institutions", "T-BODY-002")] == ("unconfirmed", "source_not_on_allow_list")  # region sindh
    assert got[("Facts", "T-F-003")] == ("unconfirmed", "source_not_on_allow_list")  # an institution: lists only
    prov = reg.get(BODY).attrs["provenance"]
    assert prov["allow_list_scope"] == {"region": "punjab", "family": "intermediate"}
    assert prov["family_basis"] == "body_any"
    assert res.counts["Institutions"]["accepted"] == 2


def test_a_body_row_is_refetched_under_the_families_it_is_listed_for(engine, clean, tmp_path):
    lists, allow = list_files(tmp_path), allow_files(tmp_path)
    load_official_lists(RegistryStore(engine, "pai"), lists / "national.yaml", country=COUNTRY)
    model = {"read_method": "webfetch (model-extracted)", "source_url": BETA_NOTICE}
    path = workbook(tmp_path, [body()],
                    [fact(1, "T-BODY-001", **model),  # accepted by both checks: re-fetched
                     fact(2, "T-BODY-001", field_="y", chk={"checker1_result": "unclear"}, **model)])  # promotable
    fetcher = ScopedFetcher(allow, "Notice. Last date 2027-07-15 for all.")
    d = deps(engine, official=official_by_host(file_lookup(load_allowlist(allow))), fetcher=fetcher)
    res = run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1",
                     family="bachelor")
    got = {r.row_id: fate(r) for r in res.rows if r.sheet == "Facts"}
    assert got["T-F-001"] == ("accepted", "verified", "both_checks")
    assert got["T-F-002"] == ("accepted", "confirmed", "quote_matched_on_refetch")
    assert {(region, fam) for _, region, fam in fetcher.calls} == {("punjab", "intermediate")}


def test_a_calendar_under_an_institution_stays_narrow(tmp_path):
    """Fix round 1 (review S1): only the kinds that serve a region (SERVES_A_REGION) are judged against every family. A
    college's own calendar, and the dates on it, keep the T19 rule: the run's family, basis `run`."""
    cal = inst(9, ctype="admission_calendar", inst_id="T-CAL-001", name="Test College 1 admission calendar",
               parent_id="T-INST-001", timezone="Asia/Karachi", source_url=BETA_NOTICE, source_quote="Admission calendar")
    date_ = fact(1, "T-CAL-001", field_="application_close", source_url=BETA_NOTICE)
    ctx = context(tmp_path, family="bachelor")  # the beta host serves intermediate only
    seen = spy(ctx)
    rows = plan(tmp_path, ctx, [inst(1), cal], [date_])
    for key in (("Institutions", "T-CAL-001"), ("Facts", "T-F-001")):
        r = rows[key]
        assert fate(r) == ("unconfirmed", "unconfirmed", "source_not_on_allow_list"), key
        assert r.payload["allow_list_families"] == ("bachelor",) and "punjab/intermediate" not in r.detail
    assert ("punjab", "intermediate") not in seen
    rows = plan(tmp_path, context(tmp_path, family="intermediate"), [inst(1), cal], [date_])
    for key in (("Institutions", "T-CAL-001"), ("Facts", "T-F-001")):
        assert fate(rows[key])[0] == "accepted" and basis(rows[key]) == "run", key
