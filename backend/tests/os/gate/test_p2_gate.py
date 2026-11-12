"""P2 gate (master §12, P2 spec §9): the scripted proofs that are T12's, and a manifest that names the proof for every
other gate item. Fictional `.test` sites and fictional students; no model or network call."""

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.os import models, ports
from app.os.consistency import facts as rules
from app.os.contracts.programme_facts import FactEntry, SourceRef
from app.os.contracts.route_contract import IntakeRef
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.research.readability import NotReadableStore
from app.os.knowledge.review import ReviewerStore, ReviewQueue
from app.os.knowledge.review.export import export_queue
from app.os.knowledge.review.hooks import open_suspect_item
from app.os.knowledge.sheets.importer import run_import
from app.os.knowledge.sources.allowlist import SourceDomains, load_allowlist
from app.os.knowledge.sheets.undo import undo_import
from app.os.ports import consistency as os_consistency
from app.os.registry.store import RegistryStore
from tests.os.sheets.helpers import COUNTRY, NOTICE, FakeDisputes, FakeFetcher, Page, checks, deps, fact, inst, load_list, workbook
from tests.os.test_p2_monitor import World, page, w  # noqa: F401  (w: a fixture, a fictional university and student)
from tests.os.test_p2_sources_gateway import BETA, NORTH, build
from tests.os.test_p2_sources_gateway import fact as src_fact

URL, QUOTE = "https://admissions.alpha.test/n", "Apply by 15 July 2027"
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\n" + b"scan"
PROOFS = Path(__file__).parent

# --- the manifest: every gate item has a proof, and the proof exists -------------------------------------------------------

#  gate item -> (what proves it, [(module, test)] that are tagged and run in the suite)
MANIFEST = {
    4: [("tests.os.gate.test_p2_gate", "test_gate_4_spam_page_is_refused_the_domain_suspect_facts_unconfirmed_item_open")],
    5: [("tests.os.gate.test_p2_gate", "test_gate_5_a_not_readable_source_is_collected_with_evidence_and_approved_by_a_second_reviewer")],
    6: [("tests.os.test_p2_coverage_report", "test_gate_a_the_denominator"),
        ("tests.os.test_p2_coverage_report", "test_green_when_everything_holds_and_pass_gate_records_it")],
    8: [("tests.os.test_p2_monitor", "test_a_page_change_in_season_resets_the_fact_pauses_the_step_and_queues_the_item"),
        ("tests.os.test_p2_monitor", "test_a_report_shows_not_confirmed_to_everyone_but_only_the_reporters_steps_wait")],
    9: [("tests.os.test_p2_intakes_proof", "test_rollover_proof_2026_to_2027")],
    10: [("tests.os.gate.test_p2_gate", "test_gate_10_a_spreadsheet_round_trip_with_deliberate_errors_catches_each_and_undo_restores")],
    11: [("tests.os.gate.test_p2_gate", "test_gate_11_consistency_rules_9_to_12_find_nothing_for_a_clean_student_and_each_violation"),
         ("tests.os.test_calendar_plan", "test_6_20_the_result_step_follows_the_official_calendar"),
         ("tests.os.test_p2_merit_ports", "test_programme_list_v2_coverage_levels")],
}


def test_every_gate_item_names_a_proof_that_exists():
    for item, proofs in MANIFEST.items():
        for module, name in proofs:
            fn = getattr(importlib.import_module(module), name, None)
            assert callable(fn), f"gate item {item}: {module}.{name} does not exist"


# --- 4: the spam page ------------------------------------------------------------------------------------------------------------

@pytest.mark.req("R-71")
def test_gate_4_spam_page_is_refused_the_domain_suspect_facts_unconfirmed_item_open(engine, clean, fixture_sites):
    k = SqlKnowledge(engine, "pai")
    queue = ReviewQueue(engine, "pai", k)
    on_beta = k.upsert("programme", "beta-bs", "deadline", src_fact("https://beta-college.test/old"))
    gw, guard, _ = build(engine, fixture_sites, hook=open_suspect_item(queue))
    page_ = gw.fetch(fixture_sites.url(BETA, "/admissions"), [], [], NORTH)
    assert page_.blocked == "integrity:spam" and page_.text == ""  # refused
    assert guard.domains.state_of(BETA).state == "suspect"  # domain suspect
    assert k.get(on_beta)[3].status == "unconfirmed"  # its facts unconfirmed
    [item] = queue.list_items(kind="suspect_domain")  # review item open, with the evidence to look at
    assert item.subject == BETA and item.payload["snapshot_id"] == page_.snapshot_id
    assert guard.snapshots.get(item.payload["snapshot_id"]).flagged == "spam"


# --- 5: a not-readable source, collected with evidence and approved by a second reviewer --------------------------------------------

@pytest.mark.req("R-72")
def test_gate_5_a_not_readable_source_is_collected_with_evidence_and_approved_by_a_second_reviewer(engine, clean):
    k = SqlKnowledge(engine, "pai")
    queue = ReviewQueue(engine, "pai", k)
    people = ReviewerStore(engine, "pai")
    collector, _ = people.add("amina", "Amina", "checker")  # the owner's ruling: AI checks may be the two checks
    check1, _ = people.add("ai_check_1", "AI check 1", "checker", "ai", identity="model-a/prompt-1")
    check2, _ = people.add("ai_check_2", "AI check 2", "approver", "ai", identity="model-b/prompt-2")
    NotReadableStore(engine, "pai").mark("https://admissions.alpha.test/scan", "not_readable:ocr", programme_ref="p1",
                                          fields=["deadline_close"], intake_year=2027)
    assert queue.sync_not_readable() == 1 and queue.sync_not_readable() == 0  # one collect item, once
    [item] = queue.list_items(kind="collect")
    f = queue.add_file(item.id, collector, "notice.png", "image/png", PNG)  # the evidence: the original scan
    out = queue.collect(item.id, collector, value={"date": "2027-07-15"}, quote=QUOTE, url=URL, language="en",
                        evidence_file_id=f["id"], note="read from the scan")
    fid = out["fact_id"]
    fact_ = k.get(fid)[3]
    assert (fact_.status, fact_.read_method) == ("unconfirmed", "human")  # a person's reading is not yet a fact
    left = NotReadableStore(engine, "pai").open_rows(programme_ref="p1")
    assert [r.field for r in left] == [""]  # the field no longer waits; the source itself stays unreadable by machine
    verify = out["verify_item_id"]
    queue.submit_review(verify, check1, "check", "correct")  # compared with the original: confirmed
    assert k.get(fid)[3].status == "confirmed"
    done = queue.submit_review(verify, check2, "approve", "approve")  # two more reviews, none of them the collector
    assert done["fact_status"] == "confirmed"  # the comparing check does not count towards verified
    third, _ = people.add("owner", "Owner", "admin")
    assert queue.submit_review(verify, third, "check", "correct")["fact_status"] == "verified"
    audit = queue.audit(verify)  # the queue audit
    assert [r["reviewer"] for r in audit["reviews"]] == ["ai_check_1", "ai_check_2", "owner"]
    assert queue.detail(item.id, collector)["files"][0]["sha256"]  # the evidence stays with the item


# --- 10: a spreadsheet round trip with deliberate errors ---------------------------------------------------------------------------------

@pytest.mark.req("R-68")
def test_gate_10_a_spreadsheet_round_trip_with_deliberate_errors_catches_each_and_undo_restores(engine, clean, tmp_path):
    load_list(engine)
    before = RegistryStore(engine, "pai").get("inst:t-inst-001")
    assert before is None
    ok = checks(n1="amina", n2="bilal")
    d = deps(engine, disputes=FakeDisputes(), attested=lambda ref, batch: ref in ("amina", "bilal"),
             fetcher=FakeFetcher({NOTICE: Page("Admissions. Last date 2027-07-15 for all.")}),
             official=lambda url, scope: "bad-host" not in url)
    institutions = [inst(1, chk=ok), inst(2, region="Narnia", chk=ok)]  # a typed region spelling no list allows
    facts = [
        fact(1, "T-INST-001", field_="good", chk=ok),
        fact(2, "T-INST-001", field_="bad_url", source_url="https://bad-host.alpha.test/x", chk=ok),
        fact(3, "T-INST-001", field_="no_quote", quote_verbatim=None, chk=ok),
        fact(4, "T-INST-001", field_="one_checker", chk=checks("correct", None, n1="amina")),  # high-stakes, one checker
        fact(5, "T-INST-001", field_="model_quote", quote_verbatim="Not on the page", chk=ok,
             read_method="webfetch (model-extracted)"),  # a model-extracted quote that is not on the page
    ]
    path = workbook(tmp_path, institutions, facts)
    res = run_import(path, d, mode="reviewers", actor="dev", country=COUNTRY, batch_ref="b7")
    reasons = {r.row_id: (r.bucket, r.reason) for r in res.rows}
    assert reasons["T-INST-002"] == ("rejected", "unknown_region")  # a typed region spelling no list allows
    assert reasons["T-F-001"] == ("accepted", "both_checks")  # the good row is not caught
    assert reasons["T-F-002"] == ("unconfirmed", "source_not_on_allow_list")  # a bad URL
    assert reasons["T-F-003"] == ("unconfirmed", "no_quote")  # a missing quote
    assert reasons["T-F-004"] == ("accepted", "second_check_missing")  # one checker on a high-stakes row
    assert reasons["T-F-005"] == ("unconfirmed", "quote_not_found")  # a model-extracted quote not on the re-fetched page
    with engine.connect() as conn:
        held = {r.field: r.status for r in conn.execute(select(models.knowledge_facts))}
    assert held["good"] == "verified"
    assert held["bad_url"] == "unconfirmed" and held["no_quote"] == "unconfirmed"
    assert held["one_checker"] == "confirmed"  # one checker never makes a high-stakes row verified
    assert held["model_quote"] == "unconfirmed"  # the quote is not on the re-fetched page
    assert RegistryStore(engine, "pai").get("inst:t-inst-002") is None
    # undo withdraws what the import loaded: nothing is deleted, every fact goes stale and the entity is closed
    undo_import(engine, "pai", res.import_id, actor="admin")
    with engine.connect() as conn:
        assert {r.status for r in conn.execute(select(models.knowledge_facts))} == {"stale"}
    assert RegistryStore(engine, "pai").get("inst:t-inst-001").status == "closed"


# --- R-69: the queue as the same spreadsheet --------------------------------------------------------------------------------------

@pytest.mark.req("R-69")
def test_the_review_queue_exports_the_one_spreadsheet_format_and_the_file_imports_back(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    run_import(workbook(tmp_path, [inst(1)], [fact(1, "T-INST-001", chk=checks("unclear", None))], name="first.xlsx"), d,
               mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="owner chat")
    k = SqlKnowledge(engine, "pai")
    queue = ReviewQueue(engine, "pai", k)
    [fid] = [r.id for r in _facts(engine)]
    queue.open_item("change", dedupe_key="c1", fact_id=fid)
    queue.open_item("suspect_domain", dedupe_key="s1", subject="x.test")  # no fact: no row, and it is said so
    path, n, skipped = export_queue(queue, tmp_path / "queue.xlsx")
    assert n == 1 and len(skipped) == 1
    res = run_import(path, deps(engine, disputes=FakeDisputes()), mode="reviewers", actor="dev", country=COUNTRY,
                     batch_ref="queue")  # the same file, the normal import
    assert not [r for r in res.rows if r.bucket == "rejected"], [(r.row_id, r.reason) for r in res.rows]
    assert res.counts["Facts"]["rejected"] == 0
    assert _facts(engine)[0].quote and _facts(engine)[0].status in ("unconfirmed", "confirmed")  # same fact, not lowered


@pytest.mark.req("R-69")
def test_the_queue_export_round_trips_risky_text_and_session_intakes(engine, clean, tmp_path):
    from app.os.knowledge.sheets.reader import read_batch

    load_list(engine)
    k = SqlKnowledge(engine, "pai")
    queue = ReviewQueue(engine, "pai", k)
    run_import(workbook(tmp_path, [inst(1)], [], name="first.xlsx"), deps(engine), mode="owner_accepted", actor="dev",
               country=COUNTRY, decision_ref="owner chat")
    e = "inst:t-inst-001"
    values = {"f_eq": "=1+1", "f_minus": "-5 units", "f_plus": "+92 300", "f_at": "@home", "f_apostrophe": "'Tis the season"}
    for field, text in values.items():
        fid = k.upsert("registry", e, field, Fact(text, "the notice says so", NOTICE, AT, 2026, "unconfirmed",
                                                  intake_term="session"))
        queue.open_item("change", dedupe_key=field, fact_id=fid)
    path, n, _ = export_queue(queue, tmp_path / "queue.xlsx")
    assert n == len(values)
    back = {r["field"]: r for r in read_batch(path).sheets["Facts"]}
    assert {f: r["value"] for f, r in back.items()} == values  # what we wrote comes back as it was, formula-like or not
    assert {r["intake"] for r in back.values()} == {"2026-27"}  # a session is written the way the sheet reads it
    res = run_import(path, deps(engine, disputes=FakeDisputes()), mode="reviewers", actor="dev", country=COUNTRY,
                     batch_ref="queue")
    assert res.counts["Facts"]["rejected"] == 0
    with engine.connect() as conn:
        held = {r.field: (r.intake_term, r.intake_year) for r in conn.execute(select(models.knowledge_facts))}
    assert set(held.values()) == {("session", 2026)}


def _facts(engine):
    with engine.connect() as conn:
        return list(conn.execute(select(models.knowledge_facts).order_by(models.knowledge_facts.c.id)))


# --- 11: consistency rules 9-12 -----------------------------------------------------------------------------------------------------

def entry(field="deadline_close", *, value="2027-08-01", level="verified", url=URL, intake=None, other=False, high=True):
    return FactEntry(field=field, fact_class="deadline" if high else "application_route", high_stakes=high, level=level, value=value,
                     source=SourceRef(url=url, quote="q", checked_at=AT) if url else None,
                     fact_intake=intake or IntakeRef(term="winter", year=2027), other_intake=other)


I27 = IntakeRef(term="winter", year=2027)


def listed_on(*domains):
    return lambda url: any(d in url for d in domains)


def _unchecked(field, *, level="verified", url=URL, intake=None, fact_class="deadline", high_stakes=True):
    """An entry as a surface that bypassed the contract's own checks would hand over."""
    return FactEntry.model_construct(
        field=field, fact_class=fact_class, high_stakes=high_stakes, level=level, value="v",
        source=SourceRef(url=url, quote="q", checked_at=AT) if url else None, fact_intake=intake or I27,
        other_intake=False, owner_ref=None, read_method=None, language=None)


@pytest.mark.req("R-05")
def test_the_four_rules_in_isolation():
    ok = listed_on("alpha.test")
    clean = rules.check_entries([entry(), entry("application_route", level="confirmed", high=False)], I27, ok, set())
    assert all(not codes for codes in clean.values())  # a verified high-stakes fact, an allowed source, its own year
    bad = rules.check_entries([
        _unchecked("a", url="https://elsewhere.test/x"),  # 9: not on the allow-list
        _unchecked("b", level="confirmed"),  # 10: high-stakes shown below verified (the contract forbids it; the check holds anyway)
        _unchecked("c", intake=IntakeRef(term="winter", year=2026)),  # 11: another year, not labelled
        _unchecked("d", url="https://www.spam.test/p"),  # 12: suspect domain
        entry("e", level="not_confirmed", value=None, url="https://elsewhere.test/y"),  # no value shown: nothing to break
    ], I27, ok, {"spam.test"})
    assert bad == {9: ["domain_not_listed:a"], 10: ["high_stakes_not_verified:b"],
                   11: ["other_intake_unlabelled:c"], 12: ["suspect_domain:d"]}
    labelled = rules.check_entries([entry("c", intake=IntakeRef(term="winter", year=2026), other=True)], I27, ok, set())
    assert not labelled[11]  # another year shown with its year is fine


@pytest.mark.req("R-05")
def test_a_shown_value_with_no_source_is_caught_and_the_raw_url_is_checked_too():
    ok = listed_on("alpha.test")
    got = rules.check_entries([_unchecked("a", url=None)], I27, ok, set())
    assert got[9] == ["no_source:a"]  # a value with no source at all escapes nothing
    got = rules.check_entries([_unchecked("a", url=None)], I27, None, None)  # even when the list and the guard cannot run
    assert got[9] == ["no_source:a"]
    # the entry shows no SourceRef, but the fact holds a URL on a suspect domain: rule 12 reads the raw URL
    got = rules.check_entries([_unchecked("b", url=None)], I27, ok, {"spam.test"}, urls={"b": "https://www.spam.test/p"})
    assert got[12] == ["suspect_domain:b"] and not got[9]
    got = rules.check_entries([_unchecked("c", url=None)], I27, ok, set(), urls={"c": "https://elsewhere.test/p"})
    assert got[9] == ["domain_not_listed:c"]


@pytest.mark.req("R-05")
def test_high_stakes_is_recomputed_from_the_fact_classes_not_taken_from_the_entry():
    liar = _unchecked("deadline_close", level="confirmed", fact_class=None, high_stakes=False)  # says it is not high-stakes
    assert rules.check_entries([liar], I27, listed_on("alpha.test"), set())[10] == ["high_stakes_not_verified:deadline_close"]
    other = _unchecked("application_route", level="confirmed", fact_class="application_route", high_stakes=True)
    assert rules.check_entries([other], I27, listed_on("alpha.test"), set())[10] == []  # a class that is not high-stakes


def _lists(tmp_path, region, family, *domains):
    import yaml

    (tmp_path / f"{region}.yaml").write_text(yaml.safe_dump({
        "region": region, "family": family,
        "bodies": [{"body_ref": f"body-{region}", "tier": "regulator", "domains": list(domains),
                    "list_ref": "https://lists.alpha.test/x", "reviewed_by": "tester-1"}]}), encoding="utf-8")
    return load_allowlist(tmp_path)


@pytest.mark.req("R-05")
def test_gate_11_consistency_rules_9_to_12_find_nothing_for_a_clean_student_and_each_violation(w, tmp_path):
    from dataclasses import replace

    plan = w.plan("stu-1")
    w.kb.set_status(w.fact_id, "verified", cause="review", actor="tester")  # a verified fact on the programme's own domain
    off = replace(w.svc, settings=replace(w.svc.settings, source_guard=False))
    on = replace(w.svc, settings=replace(w.svc.settings, source_guard=True))
    ports.configure(off)
    try:
        # no allow-list loaded and the guard off: rules 9 and 12 are NOT RUN, which is not the same as zero findings
        assert os_consistency.fact_rules_status() == {9: rules.NO_ALLOW_LIST, 10: None, 11: None, 12: rules.GUARD_OFF}
        assert os_consistency.fact_students() == ["stu-1"] and os_consistency.fact_findings("stu-1") == []
        ports.configure(on)
        assert os_consistency.fact_rules_status() == {9: rules.NO_ALLOW_LIST, 10: None, 11: None, 12: None}
        # the list for the programme's own region and family is loaded: rule 9 runs
        SourceDomains(w.engine, "pai").sync(_lists(tmp_path, "punjab", "university", "higher-ed-regulator.test"))
        assert os_consistency.fact_rules_status() == {9: None, 10: None, 11: None, 12: None}
        assert os_consistency.fact_findings("stu-1") == []  # zero, and now it means zero
        # a source on a domain the list does not name for this programme's region and family: rule 9
        w.kb.revise(w.fact_id, url="https://unlisted.test/notice", cause="manual")
        w.kb.set_status(w.fact_id, "verified", cause="review", actor="tester")
        [f9] = os_consistency.fact_findings("stu-1")
        assert (f9.rule, f9.codes, f9.plan_id) == (9, ("domain_not_listed:deadline_close",), plan)
        # a domain listed only for another region is not enough (the scope is the programme's own)
        w.kb.revise(w.fact_id, url="https://www.beta-college.test/notice", cause="manual")
        w.kb.set_status(w.fact_id, "verified", cause="review", actor="tester")
        SourceDomains(w.engine, "pai").sync(_lists(tmp_path, "sindh", "university", "beta-college.test"))
        assert [f.rule for f in os_consistency.fact_findings("stu-1")] == [9]
        # the domain of the list for this region and family: listed, nothing found
        w.kb.revise(w.fact_id, url="https://www.higher-ed-regulator.test/notice", cause="manual")
        w.kb.set_status(w.fact_id, "verified", cause="review", actor="tester")
        assert os_consistency.fact_findings("stu-1") == []
        # the same domain marked suspect without the facts being dropped: rule 12, and a case a person sees
        SourceDomains(w.engine, "pai").mark_suspect("higher-ed-regulator.test", "spam", lambda conn: {})
        [f12] = os_consistency.fact_findings("stu-1")
        assert (f12.rule, f12.codes) == (12, ("suspect_domain:deadline_close",))
        case_id, created = os_consistency.open_case("stu-1", f12.rule, f12.plan_id, list(f12.codes))
        assert created and [c.rule for c in os_consistency.cases("open")] == [12]  # rule 12 fits the case table
        assert os_consistency.open_case("stu-1", 12, plan, list(f12.codes)) == (case_id, False)  # touched, not repeated
        ports.configure(off)  # the guard off again: rule 12 is not run, so it finds nothing and says so
        assert os_consistency.fact_rules_status()[12] == rules.GUARD_OFF and not [
            f for f in os_consistency.fact_findings("stu-1") if f.rule == 12]
    finally:
        ports.configure(None)


# --- the Spike 1 harness (item 7): scoring, no live call -----------------------------------------------------------------------------------

def spike_world(w, n_institutions=5, programmes_per=1, right="2027-08-01"):
    """`n_institutions` institutions with `programmes_per` programmes each, a verified deadline on every programme."""
    from app.os.knowledge.programmes import Programme, ProgrammeStore
    from tests.os.registry.helpers import inst as reg_inst

    reg, progs, refs = RegistryStore(w.engine, "pai"), ProgrammeStore(w.engine, "pai"), []
    for i in range(1, n_institutions + 1):
        reg.record(reg_inst(f"s{i}", region="punjab"), cause="import")
        for j in range(programmes_per):
            ref = f"q{i}-{j}"
            progs.upsert(Programme(ref=ref, route_key="ireland_master", university=f"U{i}", name=ref, aliases=(),
                                   start_urls=(URL,), official_domains=("alpha.test",)))
            reg.link_programme(ref, institution_id=f"inst:s{i}", cause="import")
            fid = w.kb.upsert("programme", ref, "deadline_close", Fact({"date": right}, QUOTE, URL, AT, 2027, "confirmed",
                                                                       intake_term="winter"))
            w.kb.set_status(fid, "verified", cause="review", actor="tester")
            refs.append(ref)
    return refs


def write_key(tmp_path, refs, region="punjab", value=None, extra=()):
    key = tmp_path / f"{region}_answer_key.yaml"
    entries = [{"scope": "programme", "ref": r, "field": "deadline_close", "value": value or {"date": "2027-08-01"}}
               for r in refs] + list(extra)
    key.write_text(json.dumps({"version": 1, "region": region, "intake": {"term": "winter", "year": 2027},
                               "checker": "bilal", "entries": entries}), encoding="utf-8")
    return key


def run_score(w, tmp_path, *args):
    from scripts import os_spike1_rerun as cli

    out: list[str] = []
    code = cli.main(["score", *args], engine=w.engine, tenant_id="pai", key_dir=tmp_path, out=out.append)
    return code, (json.loads(out[-1]) if out and out[-1].startswith("{") else None)


@pytest.mark.req("R-35")
def test_spike1_harness_passes_only_when_every_entry_is_held_and_right(w, tmp_path):
    refs = spike_world(w)
    write_key(tmp_path, refs)
    code, report = run_score(w, tmp_path, "--region", "punjab")
    r = report["regions"][0]
    assert code == 0 and report["passed"] and r["institutions"] == 5 and r["verified"] == {"held": 5, "correct": 5, "rate": 1.0}
    # one wrong verified fact fails the 100% bar
    fid = w.kb.programme_facts([refs[4]], ["deadline_close"], 2027)[(refs[4], "deadline_close")].id
    w.kb.revise(fid, value={"date": "2027-09-09"}, quote=QUOTE, cause="manual")
    w.kb.set_status(fid, "verified", cause="review", actor="tester")
    code, report = run_score(w, tmp_path, "--region", "punjab")
    assert code == 1 and report["regions"][0]["verified"]["rate"] == 0.8
    assert report["regions"][0]["wrong"] == [{"scope": "programme", "ref": refs[4], "field": "deadline_close",
                                              "status": "verified"}]


@pytest.mark.req("R-35")
def test_spike1_one_correct_entry_and_ninety_nine_missing_fails(w, tmp_path):
    refs = spike_world(w, n_institutions=5)
    ghosts = [{"scope": "programme", "ref": f"ghost-{i}", "field": "deadline_close", "value": {"date": "2027-08-01"}}
              for i in range(99)]
    write_key(tmp_path, refs[:1], extra=ghosts)
    code, report = run_score(w, tmp_path, "--region", "punjab")
    r = report["regions"][0]
    assert code == 1 and not report["passed"] and len(r["missing"]) == 99
    assert r["verified"] == {"held": 1, "correct": 1, "rate": 1.0}  # the rate alone would say 100%: the missing ones fail it


@pytest.mark.req("R-35")
def test_spike1_five_programmes_of_one_institution_are_not_a_sample(w, tmp_path):
    refs = spike_world(w, n_institutions=1, programmes_per=5)
    write_key(tmp_path, refs)
    code, report = run_score(w, tmp_path, "--region", "punjab")
    r = report["regions"][0]
    assert code == 1 and r["institutions"] == 1 and r["verified"]["rate"] == 1.0 and not report["passed"]


@pytest.mark.req("R-35")
def test_spike1_an_entry_below_confirmed_fails_the_region(w, tmp_path):
    refs = spike_world(w)
    write_key(tmp_path, refs)
    fid = w.kb.programme_facts([refs[0]], ["deadline_close"], 2027)[(refs[0], "deadline_close")].id
    w.kb.revise(fid, status="unconfirmed", cause="manual")
    code, report = run_score(w, tmp_path, "--region", "punjab")
    assert code == 1 and report["regions"][0]["not_confirmed"] == [
        {"scope": "programme", "ref": refs[0], "field": "deadline_close", "status": "unconfirmed"}]


def test_spike1_values_compare_in_one_form_and_nan_matches_nothing():
    from app.os.gate.spike1 import normal

    assert normal({"date": "2027-08-01", "tz": "Europe/Dublin"}) == normal("2027-08-01") == normal({"value": "2027-08-01", "unit": "date"})
    assert normal(" 1,000 ") == normal(1000) == 1000.0
    assert normal(float("nan")) != normal(float("nan")) and normal(float("inf")) != normal(float("inf"))
    assert normal("NaN") == "nan" and normal("inf") == "inf"  # words, not numbers
    assert normal({"date": "2027-08-01"}) != normal({"date": "2027-08-02"})


@pytest.mark.req("R-35")
def test_spike1_plan_and_the_refusals(w, tmp_path):
    from scripts import os_spike1_rerun as cli

    refs = spike_world(w)
    write_key(tmp_path, refs)
    out: list[str] = []
    assert cli.main(["plan", "--region", "punjab", "--cost-per-fact", "0.04", "--spent", "19.9"], key_dir=tmp_path,
                    out=out.append) == 0
    plan_ = json.loads(out[-1])
    assert plan_["facts"] == 5 and plan_["within_cap"] is False and plan_["estimated_cost_usd"] == 0.2
    assert run_score(w, tmp_path, "--region", "sindh")[0] == 2


# --- the admin API for the queue export and the sync, and the migration ----------------------------------------------------------

@pytest.mark.req("R-69")
def test_the_admin_api_exports_the_queue_and_syncs_collect_items(w):
    from io import BytesIO

    from openpyxl import load_workbook

    from tests.os.test_api import ADMIN
    from tests.os.test_p2_monitor import make_api

    c = make_api(w)
    w.queue.open_item("change", dedupe_key="c1", fact_id=w.fact_id)
    NotReadableStore(w.engine, "pai").mark("https://admissions.alpha.test/scan", "not_readable:ocr", programme_ref="p1",
                                            fields=["fee"], intake_year=2027)
    assert c.get("/v1/os/admin/review/export").status_code == 401
    r = c.get("/v1/os/admin/review/export?kind=change", headers=ADMIN)
    assert r.status_code == 200 and r.headers["x-rows"] == "1" and r.headers["x-items-without-row"] == ""
    sheet = load_workbook(BytesIO(r.content))["Facts"]
    header = [cell.value for cell in sheet[1]]
    row = dict(zip(header, [cell.value for cell in sheet[2]], strict=False))
    assert row["field"] == "deadline_close" and row["fact_id"].startswith("Q-") and row["source_url"].startswith("https://")
    assert c.get("/v1/os/admin/review/export?kind=nonsense", headers=ADMIN).status_code == 422
    got = c.post("/v1/os/admin/review/sync", headers=ADMIN, json={})
    assert got.status_code == 200 and got.json()["collect_opened"] == 1


@pytest.mark.req("R-05")
def test_os_0033_widens_the_case_rule_and_goes_back_only_when_no_new_case_exists(engine, clean, os_db):
    from sqlalchemy import create_engine

    from tests.os.conftest import run_alembic, truncate_os_tables

    cases = models.consistency_cases
    with engine.begin() as conn:
        conn.execute(cases.insert().values(tenant_id="pai", student_ref="s1", rule=11, codes=["other_intake_unlabelled:x"]))
        with pytest.raises(Exception):  # still a closed range: 13 is P4's
            with conn.begin_nested():
                conn.execute(cases.insert().values(tenant_id="pai", student_ref="s1", rule=13, codes=[]))
    engine.dispose()
    with pytest.raises(Exception):
        run_alembic(["downgrade", "os_0032"], os_db)  # a case for rule 11 exists: nothing is thrown away
    eng = create_engine(os_db)
    try:
        truncate_os_tables(eng)
    finally:
        eng.dispose()
    run_alembic(["downgrade", "os_0032"], os_db)
    run_alembic(["upgrade", "os@head"], os_db)


@pytest.mark.req("R-24")
def test_the_allow_lists_are_loaded_whether_or_not_the_source_guard_is_on(engine, clean, tmp_path, monkeypatch):
    from app.os.knowledge.sources import allowlist
    from app.os.runner.worker import load_allow_lists
    from app.os.settings import load_settings

    settings = load_settings({"DATABASE_URL": "x"})
    assert settings.source_guard is False
    assert load_allow_lists(settings, engine) == 0  # no list files: nothing to load, and no error
    assert SourceDomains(engine, "pai").domains() == []
    monkeypatch.setattr(allowlist, "load_allowlist", lambda *a, **k: _lists(tmp_path, "punjab", "university", "a.test"))
    assert load_allow_lists(settings, engine) == 1
    assert SourceDomains(engine, "pai").domains() == ["a.test"]
    assert load_allow_lists(settings, engine) == 1  # again: idempotent
