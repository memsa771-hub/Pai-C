"""P2-T6: importing a batch end to end on fictional data: statuses, provenance, queue items, the report, the log, the
refusal of a second import, and the quote match on re-fetched pages (P2 spec §4.6; master R-68, R-72)."""

import csv
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge.sheets.importer import AlreadyImported, run_import
from app.os.knowledge.sheets.importlog import ImportLog
from app.os.registry.store import RegistryStore

from .helpers import (
    C1,
    C2,
    COUNTRY,
    NOTICE,
    FakeDisputes,
    FakeFetcher,
    Page,
    checks,
    deps,
    fact,
    inst,
    load_list,
    workbook,
)

pytestmark = pytest.mark.req("R-68")
DECISION = "owner chat 2026-11-07"
E = "inst:t-inst-001"


def imp(tmp_path, d, institutions, facts=(), programmes=(), **kw):
    path = workbook(tmp_path, institutions, facts, programmes)
    return run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref=DECISION, **kw)


def fact_row(engine, field):
    with engine.connect() as conn:
        return conn.execute(select(models.knowledge_facts).where(models.knowledge_facts.c.field == field)).one()


def test_both_ai_checks_make_a_verified_fact_with_the_owner_provenance(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    res = imp(tmp_path, d, [inst(1)], [fact(1, "T-INST-001")])
    assert res.counts["Institutions"]["verified"] == 1 and res.counts["Facts"]["verified"] == 1
    e = RegistryStore(engine, "pai").get(E)
    assert e.attrs["trust"] == "verified" and e.list_ids == ("list:alpha-list",) and e.region == "punjab"
    assert e.official_domains == ("college1.alpha.test",) and e.institution_type == "private_medical_college"
    row = fact_row(engine, "deadline_close")
    assert (row.scope, row.ref, row.status, row.intake_term, row.intake_year) == ("registry", E, "verified", "fall", 2027)
    assert row.value == {"value": "2027-07-15", "unit": "date"} and row.read_method == "fetch" and row.language == "en"
    ev = row.evidence[0]
    assert (ev["checker1"], ev["checker2"], ev["accepted_by"], ev["decision_ref"]) == (
        "claude_check_1", "claude_check_2", "owner", DECISION)
    assert ev["import_id"] == res.import_id and "AI checks" in ev["note"]
    revs = d.knowledge.revisions(row.id)
    assert [r.action for r in revs] == ["insert", "status"] and {r.cause_ref for r in revs} == {f"import-{res.import_id}"}
    assert revs[1].actor == f"owner-accepted:{DECISION}" and revs[0].actor == "dev"
    assert [r.cause for r in RegistryStore(engine, "pai").revisions(E)] == ["import"]


def test_unclear_conflict_and_missing_second_check_levels(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine, disputes=FakeDisputes())
    imp(tmp_path, d, [inst(1)], [
        fact(1, "T-INST-001", field_="f_unclear", chk=checks("unclear", None)),
        fact(2, "T-INST-001", field_="f_conflict", status="conflict"),
        fact(3, "T-INST-001", field_="f_one", chk=checks("correct", None)),
        fact(4, "T-INST-001", field_="f_noquote", quote_verbatim=None)])
    assert fact_row(engine, "f_unclear").status == "unconfirmed"
    c = fact_row(engine, "f_conflict")
    assert c.status == "unconfirmed" and c.conflict_note.startswith("conflict")
    assert fact_row(engine, "f_one").status == "confirmed"
    nq = fact_row(engine, "f_noquote")
    assert nq.status == "unconfirmed" and nq.quote == ""
    assert [i["kind"] for i in d.disputes.items] == ["conflict"] and d.disputes.items[0]["fact_id"] == c.id


def test_queued_rows_open_review_items_and_are_not_loaded(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine, disputes=FakeDisputes())
    res = imp(tmp_path, d, [inst(1), inst(2, chk=checks("correct", "no")), inst(3, status="not_readable")],
              [fact(1, "T-INST-001", field_="wrong_one", chk=checks("wrong", None)),
               fact(2, "T-INST-001", field_="odd_intake", intake="standing")])
    assert [i["kind"] for i in d.disputes.items] == ["import_dispute", "collect", "import_dispute", "import_dispute"]
    assert res.queued_items == 4
    first = d.disputes.items[0]
    assert first["batch_ref"] == "batch" and first["opened_by"] == "import" and first["payload"]["row"]["inst_id"] == "T-INST-002"
    s = RegistryStore(engine, "pai")
    assert s.get("inst:t-inst-002") is None and s.get("inst:t-inst-003") is None and s.get(E) is not None
    with engine.connect() as conn:
        assert conn.execute(select(models.knowledge_facts.c.field)).scalars().all() == []


def test_without_a_queue_the_rows_are_still_reported(engine, clean, tmp_path):
    load_list(engine)
    res = imp(tmp_path, deps(engine), [inst(1, chk=checks("correct", "no"))])
    assert res.queued_items == 0 and res.counts["Institutions"]["queued"] == 1


def test_report_log_and_second_import_refused(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    path = workbook(tmp_path, [inst(1), inst(2, region="Narnia"), inst(3, in_scope="no")], [fact(1, "T-INST-001")])
    res = run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref=DECISION)
    rows = list(csv.DictReader(res.report_path.open(encoding="utf-8")))
    assert res.report_path.name == "batch.import-report.csv"
    byid = {r["row_id"]: r for r in rows}
    assert byid["T-INST-002"]["bucket"] == "rejected" and byid["T-INST-002"]["reason"] == "unknown_region"
    assert byid["T-INST-002"]["source_row"] == "3" and byid["T-INST-003"]["reason"] == "out_of_scope"
    assert len(rows) == 4
    rec = ImportLog(engine, "pai").get(res.import_id)
    assert (rec.status, rec.mode, rec.decision_ref, rec.actor, rec.file_name) == (
        "done", "owner_accepted", DECISION, "dev", "batch.xlsx")
    assert len(rec.sha256) == 64 and rec.counts["Institutions"]["rejected"] == 1 and rec.report_path
    with pytest.raises(AlreadyImported):
        run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref=DECISION)


def test_the_owner_accepted_mode_needs_its_decision_reference(engine, clean, tmp_path):
    load_list(engine)
    path = workbook(tmp_path, [inst(1)])
    with pytest.raises(ValueError, match="decision"):
        run_import(path, deps(engine), mode="owner_accepted", actor="dev", country=COUNTRY)
    with pytest.raises(ValueError, match="mode"):
        run_import(path, deps(engine), mode="whatever", actor="dev", country=COUNTRY)
    assert ImportLog(engine, "pai").list() == []  # refused before anything was logged


def test_an_unreadable_file_leaves_no_log_row_and_a_failure_is_logged(engine, clean, tmp_path):
    load_list(engine)
    from app.os.knowledge.sheets.reader import SheetError

    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a workbook")
    with pytest.raises(Exception):
        run_import(bad, deps(engine), mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref=DECISION)
    assert SheetError and ImportLog(engine, "pai").list() == []


def test_reviewer_mode_verifies_only_with_two_attested_different_reviewers(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine, attested=lambda ref, batch: ref in ("amina", "bilal") and batch == "b7")
    ok = checks(n1="amina", n2="bilal")
    rows = [fact(1, "T-INST-001", chk=ok), fact(2, "T-INST-001", field_="same", chk=checks(n1="amina", n2="amina")),
            fact(3, "T-INST-001", field_="stranger", chk=checks(n1="amina", n2="zed"))]
    path = workbook(tmp_path, [inst(1, chk=ok)], rows)
    run_import(path, d, mode="reviewers", actor="dev", country=COUNTRY, batch_ref="b7")
    assert fact_row(engine, "deadline_close").status == "verified"
    assert fact_row(engine, "same").status == "confirmed" and fact_row(engine, "stranger").status == "confirmed"
    ev = fact_row(engine, "deadline_close").evidence[0]
    assert (ev["checker1"], ev["checker2"], ev["mode"]) == ("amina", "bilal", "reviewers")
    assert "accepted_by" not in ev


def test_model_read_rows_stay_unconfirmed_until_the_quote_matches_on_a_refetched_page(engine, clean, tmp_path):
    load_list(engine)
    model = dict(read_method="webfetch (model-extracted)")
    rows = [fact(1, "T-INST-001", field_="m_ok", **model), fact(2, "T-INST-001", field_="m_bad", quote_verbatim="Not on it",
                                                                    **model),
            fact(3, "T-INST-001", field_="m_blocked", source_url="https://blocked.alpha.test/x", **model)]
    page = Page("Admissions. Last date 2027-07-15 for all.")
    fetcher = FakeFetcher({NOTICE: page})
    res = imp(tmp_path, deps(engine, fetcher=fetcher), [inst(1)], rows)
    assert fact_row(engine, "m_ok").status == "verified"
    assert fact_row(engine, "m_bad").status == "unconfirmed"
    assert fact_row(engine, "m_blocked").status == "unconfirmed"
    reasons = {r.row_id: r.reason for r in res.rows if r.sheet == "Facts"}
    assert reasons["T-F-002"] == "quote_not_found" and reasons["T-F-003"] == "refetch_blocked:not_official"
    assert sum(1 for url, _ in fetcher.calls if url == NOTICE) == 1  # one fetch per URL
    assert fetcher.calls[0][1].region == "punjab"


def test_without_a_fetcher_a_model_read_row_cannot_be_confirmed(engine, clean, tmp_path):
    load_list(engine)
    res = imp(tmp_path, deps(engine), [inst(1)], [fact(1, "T-INST-001", read_method="image (machine-read)")])
    assert fact_row(engine, "deadline_close").status == "unconfirmed"
    assert [r.reason for r in res.rows if r.sheet == "Facts"] == ["refetch_not_run"]


def test_an_unconfirmed_row_is_promoted_when_its_quote_is_on_the_page(engine, clean, tmp_path):
    load_list(engine)
    fetcher = FakeFetcher({NOTICE: Page("Last   date 2027-07-15")})
    imp(tmp_path, deps(engine, fetcher=fetcher), [inst(1)],
        [fact(1, "T-INST-001", chk=checks("unclear", None)), fact(2, "T-INST-001", field_="c", status="conflict")])
    assert fact_row(engine, "deadline_close").status == "confirmed"  # never verified by a re-fetch alone
    assert fact_row(engine, "c").status == "unconfirmed"  # a conflict is not promoted


def test_import_does_not_lower_a_fact_a_reviewer_verified(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    imp(tmp_path, d, [inst(1)], [fact(1, "T-INST-001")])
    other = tmp_path / "second"
    other.mkdir()
    imp(other, d, [inst(1, name="Test College 1 (renamed)")],
        [fact(1, "T-INST-001", chk=checks("unclear", None))])  # same value, weaker checks, another file
    assert fact_row(engine, "deadline_close").status == "verified"
    assert RegistryStore(engine, "pai").get(E).name == "Test College 1 (renamed)"
    assert datetime(2026, 11, 3, tzinfo=UTC) == fact_row(engine, "deadline_close").checked_at and C1 and C2
