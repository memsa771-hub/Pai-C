"""P2-T9: the coverage API and the intake `current` gate (R-34, R-35, R-66). Fictional data."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.os.api import build_router, make_services
from app.os.intakes import IntakeStore
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.store import SqlKnowledge
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.registry.helpers import inst, olist, put, store
from tests.os.test_api import ADMIN, FAKE, TOKEN, as_student
from tests.os.test_p2_coverage_report import FLOOR, fact

pytestmark = pytest.mark.req("R-66")
BASE = "/v1/os/admin"


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1))
    s = store(engine)
    s.record(olist(rows=1, date="2026-10-01"), cause="import")
    s.record(inst("one", attrs={"first_live": ["fall:2027"]}), cause="import")
    ProgrammeStore(engine, "pai").upsert(Programme(ref="p-one", route_key="r", university="U", name="p", aliases=(),
                                                   start_urls=(), official_domains=()))
    s.link_programme("p-one", institution_id="inst:one", family="undergrad", region="punjab", cause="import")
    intake = IntakeStore(engine, "pai").create("punjab", "undergrad", "fall", 2027, state="open")
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    client = TestClient(app)
    client.intake, client.k = intake, SqlKnowledge(engine, "pai")
    return client


def test_admin_only(api):
    for method, path in (("get", "/intakes"), ("get", f"/coverage?intake={api.intake.id}"),
                         ("post", f"/intakes/{api.intake.id}/current")):
        assert getattr(api, method)(BASE + path).status_code == 401
        assert getattr(api, method)(BASE + path, headers=as_student()).status_code == 401


def test_coverage_report_shape(api):
    body = api.get(BASE + "/coverage", params={"intake": api.intake.id}, headers=ADMIN).json()
    assert body["intake"]["state"] == "open" and body["green"] is False
    assert [r["gate"] for r in body["readings"]] == ["a", "b", "c", "d", "e"]
    b = next(r for r in body["readings"] if r["gate"] == "b")
    assert not b["green"] and {i["code"] for i in b["items"]} == {"missing"}
    assert body["rows"][0]["institution_type"] == "university" and body["rows"][0]["institutions"] == 1
    assert set(body["workload"]) >= {"checks_left", "rows_per_hour", "reviewer_hours_left", "rows_per_reviewer_day"}
    assert api.get(BASE + "/coverage", params={"intake": 9999}, headers=ADMIN).status_code == 404
    assert [i["id"] for i in api.get(BASE + "/intakes", headers=ADMIN).json()["intakes"]] == [api.intake.id]


def test_current_is_refused_while_red_and_allowed_when_green(api):
    r = api.post(f"{BASE}/intakes/{api.intake.id}/current", headers=ADMIN)
    assert r.status_code == 409 and len(r.json()["detail"]["failing"]) == 3
    assert api.get(BASE + "/intakes", headers=ADMIN).json()["intakes"][0]["state"] == "open"
    for f in FLOOR:
        put(api.k, "programme", "p-one", f, fact())
    r = api.post(f"{BASE}/intakes/{api.intake.id}/current", headers=ADMIN)
    assert r.status_code == 200 and r.json()["state"] == "current" and r.json()["gate_passed_at"]
    again = api.post(f"{BASE}/intakes/{api.intake.id}/current", headers=ADMIN)
    assert again.status_code == 409  # already current
    assert api.post(f"{BASE}/intakes/9999/current", headers=ADMIN).status_code == 404
