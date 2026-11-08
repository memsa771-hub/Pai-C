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
    assert reasons["T-INST-002"] == ("rejected", "unknown_region")  # each deliberate error is caught, by name
    with engine.connect() as conn:
        held = {r.field: r.status for r in conn.execute(select(models.knowledge_facts))}
    assert held["good"] == "verified"
    assert held["bad_url"] == "unconfirmed" and held["no_quote"] == "unconfirmed"
    assert held["one_checker"] == "confirmed"  # one checker never makes a high-stakes row verified
    assert held["model_quote"] == "unconfirmed"  # the quote is not on the re-fetched page
    assert RegistryStore(engine, "pai").get("inst:t-inst-002") is None
    # undo restores the state before the import: nothing is deleted, every fact is withdrawn
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


def _facts(engine):
    with engine.connect() as conn:
        return list(conn.execute(select(models.knowledge_facts).order_by(models.knowledge_facts.c.id)))


# --- 11: consistency rules 9-12 -----------------------------------------------------------------------------------------------------

def entry(field="deadline_close", *, value="2027-08-01", level="verified", high=True, url=URL, intake=None, other=False):
    return FactEntry(field=field, fact_class="deadline", high_stakes=high, level=level, value=value,
                     source=SourceRef(url=url, quote="q", checked_at=AT) if url else None,
                     fact_intake=intake or IntakeRef(term="winter", year=2027), other_intake=other)


I27 = IntakeRef(term="winter", year=2027)
ALLOWED = {"alpha.test"}


@pytest.mark.req("R-05")
def test_the_four_rules_in_isolation():
    clean = rules.check_entries([entry(), entry("fee", level="confirmed", high=False)], I27, ALLOWED, set())
    assert all(not codes for codes in clean.values())  # a verified high-stakes fact, an allowed source, its own year
    bad = rules.check_entries([
        _unchecked("a", url="https://elsewhere.test/x"),  # 9: not on the allow-list
        _unchecked("b", level="confirmed"),  # 10: high-stakes shown below verified (the contract forbids it; the check holds anyway)
        _unchecked("c", intake=IntakeRef(term="winter", year=2026)),  # 11: another year, not labelled
        _unchecked("d", url="https://www.spam.test/p"),  # 12: suspect domain
        entry("e", level="not_confirmed", value=None, url="https://elsewhere.test/y"),  # no value shown: nothing to break
    ], I27, ALLOWED, {"spam.test"})
    assert bad == {9: ["domain_not_listed:a"], 10: ["high_stakes_not_verified:b"],
                   11: ["other_intake_unlabelled:c"], 12: ["suspect_domain:d"]}
    labelled = rules.check_entries([entry("c", intake=IntakeRef(term="winter", year=2026), other=True)], I27, ALLOWED, set())
    assert not labelled[11]  # another year shown with its year is fine


def _unchecked(field, *, level="verified", url=URL, intake=None):
    """An entry as a surface that bypassed the contract's own checks would hand over."""
    return FactEntry.model_construct(
        field=field, fact_class="deadline", high_stakes=True, level=level, value="v",
        source=SourceRef(url=url, quote="q", checked_at=AT), fact_intake=intake or I27, other_intake=False,
        owner_ref=None, read_method=None, language=None)


@pytest.mark.req("R-05")
def test_gate_11_consistency_rules_9_to_12_find_nothing_for_a_clean_student_and_each_violation(w):
    plan = w.plan("stu-1")
    ports.configure(w.svc)
    try:
        w.kb.set_status(w.fact_id, "verified", cause="review", actor="tester")  # a verified fact on an allowed domain
        assert os_consistency.fact_students() == ["stu-1"]
        assert os_consistency.fact_findings("stu-1") == []  # zero on a fictional student
        # a fact whose source is no longer on the lists is shown: rule 9
        w.kb.revise(w.fact_id, url="https://unlisted.test/notice", cause="manual")
        w.kb.set_status(w.fact_id, "verified", cause="review", actor="tester")
        [f9] = os_consistency.fact_findings("stu-1")
        assert (f9.rule, f9.codes, f9.plan_id) == (9, ("domain_not_listed:deadline_close",), plan)
        # the same domain marked suspect without the facts being dropped: rule 12, and a case a person sees
        from app.os.knowledge.sources.allowlist import SourceDomains

        SourceDomains(w.engine, "pai").mark_suspect("unlisted.test", "spam", lambda conn: {})
        [f12] = os_consistency.fact_findings("stu-1")
        assert (f12.rule, f12.codes) == (12, ("suspect_domain:deadline_close",))
        case_id, created = os_consistency.open_case("stu-1", f12.rule, f12.plan_id, list(f12.codes))
        assert created and [c.rule for c in os_consistency.cases("open")] == [12]  # rule 12 fits the case table
        assert os_consistency.open_case("stu-1", 12, plan, list(f12.codes)) == (case_id, False)  # touched, not repeated
    finally:
        ports.configure(None)


# --- the Spike 1 harness (item 7): scoring, no live call -----------------------------------------------------------------------------------

@pytest.mark.req("R-35")
def test_spike1_harness_scores_the_bars_per_region_and_calls_nothing(w, tmp_path):
    from scripts import os_spike1_rerun as cli

    key = tmp_path / "punjab_answer_key.yaml"
    entries = [{"scope": "programme", "ref": f"p{i}", "field": "deadline_close", "value": {"date": "2027-08-01"}}
               for i in range(1, 6)]
    key.write_text(json.dumps({"version": 1, "region": "punjab", "intake": {"term": "winter", "year": 2027},
                               "checker": "bilal", "entries": entries}), encoding="utf-8")
    out: list[str] = []
    # the programmes p1..p5 hold verified facts: four right, one wrong (the wrong one must fail the 100% bar)
    for i in range(1, 6):
        date_ = "2027-08-01" if i != 5 else "2027-09-09"
        fid = w.kb.upsert("programme", f"p{i}", "deadline_close", Fact({"date": date_}, QUOTE, URL, AT, 2027, "confirmed",
                                                                       intake_term="winter"))
        w.kb.set_status(fid, "verified", cause="review", actor="tester")
    code = cli.main(["score", "--region", "punjab"], engine=w.engine, tenant_id="pai", key_dir=tmp_path, out=out.append)
    report = json.loads(out[-1])
    assert code == 1 and report["passed"] is False
    assert report["regions"][0]["verified"] == {"held": 5, "correct": 4, "rate": 0.8}
    assert report["regions"][0]["wrong"] == [{"scope": "programme", "ref": "p5", "field": "deadline_close", "status": "verified"}]
    w.kb.revise(w.kb.programme_facts(["p5"], ["deadline_close"], 2027)[("p5", "deadline_close")].id,
                value={"date": "2027-08-01"}, quote=QUOTE, cause="manual")
    w.kb.set_status(w.kb.programme_facts(["p5"], ["deadline_close"], 2027)[("p5", "deadline_close")].id, "confirmed",
                    cause="manual")
    out.clear()
    code = cli.main(["score", "--all"], engine=w.engine, tenant_id="pai", key_dir=tmp_path, out=out.append)
    report = json.loads(out[-1])
    assert code == 0 and report["passed"] and report["regions"][0]["confirmed"]["rate"] == 1.0
    out.clear()
    assert cli.main(["plan", "--region", "punjab", "--cost-per-fact", "0.04", "--spent", "19.9"], key_dir=tmp_path,
                    out=out.append) == 0
    plan_ = json.loads(out[-1])
    assert plan_["facts"] == 5 and plan_["within_cap"] is False and plan_["estimated_cost_usd"] == 0.2
    assert cli.main(["score", "--region", "sindh"], engine=w.engine, tenant_id="pai", key_dir=tmp_path, out=out.append) == 2


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
