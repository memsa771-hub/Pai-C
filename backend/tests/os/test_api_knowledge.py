"""Slice 2 Task 8: the knowledge API (spec §4.8): research trigger and runs (admin), open facts with evidence
(admin), and the student's programme facts."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.research.run import research_workflow_id
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.test_api import ADMIN, TOKEN, as_student, contract

FAKE = Path(__file__).parent / "playbooks"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
TODAY = date(2027, 3, 1)
URL = "https://uni.example/apply"


class FakeClient:
    """Stands in for DBOSClient: records what would be enqueued."""

    def __init__(self):
        self.calls = []

    def enqueue(self, options, *args):
        self.calls.append((dict(options), args))


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    fake = FakeClient()
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: TODAY,
                             dbos_client=lambda: fake)
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-07-15"}, "Apply by 15 July", URL, CHECKED,
                                                        2027, "confirmed"))
    kb.upsert("programme", "p2", "deadline_close", Fact({"date": "2027-06-01"}, "", "", CHECKED, 2027, "unconfirmed",
                                                        conflict_note="page shows WS 2026/27"))
    store = ProgrammeStore(engine, "pai")
    for ref, name in (("p1", "Data Science"), ("p2", "Robotics"), ("p3", "Physics")):
        store.upsert(Programme(ref=ref, route_key="test_route", university="Uni X", name=name, aliases=(),
                               start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.fake = fake
    return c


def _run(engine, ref="p2", status="done", wid="w1") -> int:
    with engine.begin() as conn:
        run_id = conn.execute(insert(models.research_runs).values(
            tenant_id="pai", programme_ref=ref, intake_year=2027, workflow_id=wid, status=status, pages=3,
            confirmed=1, unconfirmed=2, cost_usd=0.012,
            ended_at=datetime(2027, 3, 1, 8, tzinfo=timezone.utc)).returning(models.research_runs.c.id)).scalar()
        for reading, err in (("A", None), ("B", "Timeout")):
            conn.execute(insert(models.agent_runs).values(
                tenant_id="pai", research_run_id=run_id, reading=reading, agent="research", agent_version=1,
                model="gpt-5.4-mini", input_tokens=9000, cached_tokens=1000, output_tokens=400, cost_usd=0.006,
                error=err))
    return run_id


def test_research_trigger_admin_only(api):
    assert api.post("/v1/os/research/p1?intake_year=2027", headers=as_student()).status_code == 401
    r = api.post("/v1/os/research/p1?intake_year=2027", headers=ADMIN)
    assert r.status_code == 202
    wid = research_workflow_id("pai", "p1", 2027, TODAY)
    assert r.json() == {"workflow_id": wid, "enqueued": True}
    [(options, args)] = api.fake.calls
    assert options["workflow_id"] == wid and options["workflow_name"] == "os.research" and args == ("p1", 2027, "2027-03-01")
    assert api.post("/v1/os/research/nope?intake_year=2027", headers=ADMIN).status_code == 404


def test_research_trigger_after_todays_run_is_not_sent_again(api, engine):
    _run(engine, ref="p1", wid=research_workflow_id("pai", "p1", 2027, TODAY))
    r = api.post("/v1/os/research/p1?intake_year=2027", headers=ADMIN)
    assert r.status_code == 202 and r.json()["enqueued"] is False and api.fake.calls == []


def test_research_runs_list(api, engine):
    run_id = _run(engine)
    _run(engine, ref="p1", wid="w2")
    assert api.get("/v1/os/research/runs", headers=as_student()).status_code == 401
    runs = api.get("/v1/os/research/runs?programme=p2", headers=ADMIN).json()["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert (run["id"], run["programme_ref"], run["status"], run["pages"], run["confirmed"], run["unconfirmed"]) == \
        (run_id, "p2", "done", 3, 1, 2)
    assert run["cost_usd"] == pytest.approx(0.012)
    assert [(x["reading"], x["error"], x["input_tokens"], x["cached_tokens"]) for x in run["readings"]] == \
        [("A", None, 9000, 1000), ("B", "Timeout", 9000, 1000)]
    assert len(api.get("/v1/os/research/runs", headers=ADMIN).json()["runs"]) == 2


def test_facts_open_has_evidence(api, engine):
    api.post("/v1/os/plans", json=contract(refs=("p1", "p2")), headers=ADMIN)
    run_id = _run(engine)
    evidence = [{"reading": "A", "value": "06-01", "quote": "1 June", "url": URL, "cycle": "WS 2026/27",
                 "scope_quote": None, "reasons": ["cycle_old:2026"]}]
    with engine.begin() as conn:
        conn.execute(models.knowledge_facts.update().where(models.knowledge_facts.c.ref == "p2")
                     .values(evidence=evidence, research_run_id=run_id, source="research"))
    items = {i["ref"]: i for i in api.get("/v1/os/facts/open", headers=ADMIN).json()["items"]}
    p2 = items["p2"]
    assert p2["field"] == "deadline_close" and p2["fact"]["status"] == "unconfirmed"
    assert p2["fact"]["evidence"] == evidence and p2["fact"]["conflict_note"] == "page shows WS 2026/27"
    assert p2["fact"]["source"] == "research"
    assert p2["last_research_run"]["id"] == run_id and p2["last_research_run"]["status"] == "done"


def test_student_sees_only_own_programmes(api):
    api.post("/v1/os/plans", json=contract(student="stu-1", refs=("p1", "p2")), headers=ADMIN)
    api.post("/v1/os/plans", json=contract(student="stu-2", refs=("p3",), external_ref="ext-2"), headers=ADMIN)
    assert api.get("/v1/os/programmes").status_code == 401
    mine = api.get("/v1/os/programmes", headers=as_student("stu-1")).json()["programmes"]
    assert [p["ref"] for p in mine] == ["p1", "p2"]
    theirs = api.get("/v1/os/programmes", headers=as_student("stu-2")).json()["programmes"]
    assert [p["ref"] for p in theirs] == ["p3"]
    assert api.get("/v1/os/programmes", headers=as_student("nobody")).json()["programmes"] == []


def test_programme_facts_show_status_source_quote(api):
    api.post("/v1/os/plans", json=contract(refs=("p1", "p2")), headers=ADMIN)
    progs = {p["ref"]: p for p in api.get("/v1/os/programmes", headers=as_student()).json()["programmes"]}
    p1 = progs["p1"]
    assert (p1["name"], p1["university"], p1["intake_year"]) == ("Data Science", "Uni X", 2027)
    [f1] = p1["facts"]
    assert (f1["field"], f1["value"], f1["status"], f1["source_url"], f1["quote"]) == \
        ("deadline_close", {"date": "2027-07-15"}, "confirmed", URL, "Apply by 15 July")
    assert f1["checked_at"].startswith("2026-10-17") and f1["conflict_note"] is None
    [f2] = progs["p2"]["facts"]
    assert f2["status"] == "unconfirmed" and f2["conflict_note"] == "page shows WS 2026/27"
    assert "evidence" not in f2  # the evidence is for admins
