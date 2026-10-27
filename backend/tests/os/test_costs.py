"""Slice 9 Task 8: the cost report (spec §3.4). Fictional rows seeded directly, so the sums are exact."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app.os import models
from app.os.api import build_router, make_services
from app.os.costs import cost_report
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings

FAKE = Path(__file__).parent / "playbooks"
TOKEN = "test-admin-token"
ADMIN = {"X-OS-Admin-Token": TOKEN}
URL = "/v1/os/admin/costs"
D = Decimal
JUNE = (date(2027, 6, 1), date(2027, 6, 30))


def at(day: int, hour: int = 12, month: int = 6) -> datetime:
    return datetime(2027, month, day, hour, 0, tzinfo=timezone.utc)


def run(engine, cost, when=None, tenant="pai", **link) -> None:
    n = run.n = getattr(run, "n", 0) + 1
    with engine.begin() as conn:
        conn.execute(insert(models.agent_runs).values(
            tenant_id=tenant, reading=f"r{n}", agent="a", agent_version=1, model="m",
            cost_usd=D(cost), at=when or at(10), **link))


def document(engine, student, tenant="pai") -> int:
    with engine.begin() as conn:
        n = run.n = getattr(run, "n", 0) + 1
        return conn.execute(insert(models.documents).values(
            tenant_id=tenant, student_ref=student, doc_type="passport", type_version=1, filename="f", content_type="x",
            size=1, sha256=f"{n:064d}").returning(models.documents.c.id)).scalar_one()


def artifact(engine, student, kind="sop", tenant="pai") -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.artifacts).values(
            tenant_id=tenant, student_ref=student, kind=kind).returning(models.artifacts.c.id)).scalar_one()


def plan(engine, student, tenant="pai") -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.plans).values(
            tenant_id=tenant, source="self_serve", external_ref=f"e-{student}-{tenant}", student_ref=student,
            contract={}, contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()


def research_run(engine) -> int:
    with engine.begin() as conn:
        return conn.execute(insert(models.research_runs).values(
            tenant_id="pai", programme_ref="p", intake_year=2027,
            workflow_id=f"w{run.n + 1000}").returning(models.research_runs.c.id)).scalar_one()


def by_ref(report):
    return {s.student_ref: s for s in report.students}


def test_costs_per_student(engine, clean):
    d1, d2 = document(engine, "s1"), document(engine, "s2")
    a1, a2 = artifact(engine, "s1"), artifact(engine, "s2", kind="cv")
    p1 = plan(engine, "s1")
    run(engine, "0.100001", document_id=d1)
    run(engine, "0.200002", document_id=d1)
    run(engine, "0.5", document_id=d2)
    run(engine, "1.25", artifact_id=a1)
    run(engine, "2", artifact_id=a2)
    run(engine, "0.3", plan_id=p1)
    rep = cost_report(engine, "pai", *JUNE)
    got = by_ref(rep)
    assert got["s1"].documents_usd == D("0.300003")
    assert got["s1"].statements_usd == D("1.25")
    assert got["s1"].replan_usd == D("0.3")
    assert got["s1"].total_usd == D("1.850003")
    assert got["s2"].documents_usd == D("0.5") and got["s2"].statements_usd == D("2")
    assert got["s2"].replan_usd == D("0") and got["s2"].total_usd == D("2.5")
    assert [s.student_ref for s in rep.students] == ["s2", "s1"]  # total descending
    assert rep.research_usd == D("0") and rep.unlinked_rows == 0 and rep.unlinked_usd == D("0")


def test_research_is_shared(engine, clean):
    rr = research_run(engine)
    run(engine, "0.4", research_run_id=rr)
    run(engine, "0.35", research_run_id=rr)
    run(engine, "1", document_id=document(engine, "s1"))
    rep = cost_report(engine, "pai", *JUNE)
    assert rep.research_usd == D("0.75")
    assert [s.student_ref for s in rep.students] == ["s1"]
    assert rep.students[0].total_usd == D("1")
    assert rep.unlinked_rows == 0


def test_unlinked_counted_not_guessed(engine, clean):
    d = document(engine, "s1")
    run(engine, "0.7")  # no link at all
    run(engine, "0.2", document_id=d)
    run(engine, "0.1", document_id=d)
    with engine.begin() as conn:  # the document was deleted: the link is nulled
        conn.execute(models.documents.delete().where(models.documents.c.id == d))
    run(engine, "5", document_id=document(engine, "s2"))
    rep = cost_report(engine, "pai", *JUNE)
    assert rep.unlinked_rows == 3 and rep.unlinked_usd == D("1.0")
    assert [s.student_ref for s in rep.students] == ["s2"]
    assert rep.students[0].total_usd == D("5")


def test_other_tenant_not_counted(engine, clean):
    run(engine, "9", tenant="other", document_id=document(engine, "s1", tenant="other"))
    run(engine, "9", tenant="other")
    rep = cost_report(engine, "pai", *JUNE)
    assert rep.students == [] and rep.unlinked_rows == 0 and rep.research_usd == D("0")


def test_flags_at_8_and_10(engine, clean):
    for ref, cost in (("a", "7.999999"), ("b", "8"), ("c", "9.999999"), ("d", "10"), ("e", "12.5")):
        run(engine, cost, document_id=document(engine, ref))
    got = by_ref(cost_report(engine, "pai", *JUNE))
    assert {k: v.flag for k, v in got.items()} == {"a": "ok", "b": "alert", "c": "alert", "d": "over", "e": "over"}
    # the total across buckets decides, not one bucket
    run(engine, "4", document_id=document(engine, "f"))
    run(engine, "4", artifact_id=artifact(engine, "f"))
    assert by_ref(cost_report(engine, "pai", *JUNE))["f"].flag == "alert"


def test_date_range_inclusive(engine, clean):
    d = document(engine, "s1")
    run(engine, "1", at(1, 0), document_id=d)          # first instant of start: in
    run(engine, "10", at(30, 23), document_id=d)       # late on end day: in
    run(engine, "100", datetime(2027, 7, 1, 0, 0, tzinfo=timezone.utc), document_id=d)   # first instant after: out
    run(engine, "1000", datetime(2027, 5, 31, 23, 59, 59, tzinfo=timezone.utc), document_id=d)  # before: out
    rep = cost_report(engine, "pai", *JUNE)
    assert rep.students[0].total_usd == D("11")
    one_day = cost_report(engine, "pai", date(2027, 6, 30), date(2027, 6, 30))
    assert one_day.students[0].total_usd == D("10")


def _api(engine, os_db) -> TestClient:
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE),
                             today=lambda: date(2027, 3, 1), dbos_client=lambda: None)
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    return TestClient(app)


def test_costs_needs_admin(engine, clean, os_db):
    api = _api(engine, os_db)
    q = "?from=2027-06-01&to=2027-06-30"
    assert api.get(URL + q).status_code == 401
    assert api.get(URL + q, headers={"X-OS-Admin-Token": "wrong"}).status_code == 401
    run(engine, "9.5", document_id=document(engine, "s1"))
    ok = api.get(URL + q, headers=ADMIN)
    assert ok.status_code == 200
    body = ok.json()
    assert body["start"] == "2027-06-01" and body["end"] == "2027-06-30"
    assert body["students"][0]["student_ref"] == "s1" and body["students"][0]["flag"] == "alert"
    assert D(body["students"][0]["total_usd"]) == D("9.5")
    for bad in ("", "?from=2027-06-01", "?from=nope&to=2027-06-30", "?from=2027-06-30&to=2027-06-01",
                "?from=2027-02-30&to=2027-06-30"):
        assert api.get(URL + bad, headers=ADMIN).status_code == 422, bad


def test_script_prints_refs_and_money(engine, clean, os_db, monkeypatch, capsys):
    from scripts import os_costs
    run(engine, "9.5", document_id=document(engine, "s1"))
    run(engine, "0.25")
    monkeypatch.setenv("OS_DATABASE_URL", os_db)
    assert os_costs.main(["--from", "2027-06-01", "--to", "2027-06-30"]) == 0
    out = capsys.readouterr().out
    assert "s1  documents=9.500000" in out and "total=9.500000  alert" in out
    assert "research (shared) = 0" in out and "unlinked = 1 rows, 0.250000" in out
    with pytest.raises(SystemExit):
        os_costs.main(["--from", "2027-06-30", "--to", "2027-06-01"])
