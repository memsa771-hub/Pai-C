"""P2-T2: the admin read API of the registry (P2 spec §4.1; R-32, R-33, R-34). Fictional data."""

from dataclasses import replace
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.os.api import build_router, make_services
from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.registry.helpers import AT, child, put, seed_basic, store
from tests.os.test_api import ADMIN, FAKE, TOKEN, as_student

pytestmark = pytest.mark.req("R-32")
BASE = "/v1/os/admin/registry"


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1))
    s = store(engine)
    seed_basic(s, rows=3)
    s.record(child("admission_body", "body", "central", None, region="national"), cause="import")
    s.record(child("admission_system", "sys", "central-merit", "body:central"), cause="import")
    s.link("sys:central-merit", "admits", "inst:one", cause="import")
    put(SqlKnowledge(engine, "pai"), "registry", "inst:one", "deadline_close",
        Fact({"d": 1}, "q", "https://admissions.alpha.test/n", AT, 2027, "verified"))
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    return TestClient(app)


def test_admin_only(api):
    for path in ("/entities", "/entities/inst:one", "/lists", "/coverage?intake_year=2027"):
        assert api.get(BASE + path).status_code == 401
        assert api.get(BASE + path, headers=as_student()).status_code == 401
        assert api.get(BASE + path, headers=ADMIN).status_code == 200


def test_entities_filters(api):
    r = api.get(BASE + "/entities", params={"kind": "institution", "region": "sindh"}, headers=ADMIN).json()
    assert [e["entity_id"] for e in r["entities"]] == ["inst:two"]
    r = api.get(BASE + "/entities", params={"q": "one"}, headers=ADMIN).json()
    assert [e["entity_id"] for e in r["entities"]] == ["inst:one"]
    assert api.get(BASE + "/entities", params={"kind": "college"}, headers=ADMIN).status_code == 422
    assert api.get(BASE + "/entities", params={"limit": 0}, headers=ADMIN).status_code == 422
    e = api.get(BASE + "/entities", params={"kind": "institution", "limit": 1}, headers=ADMIN).json()["entities"][0]
    assert e["list_ids"] == ["list:alpha-list"] and e["source_url"].startswith("https://")
    assert e["checked_at"].startswith("2026-11-01")


def test_entity_detail(api):
    e = api.get(BASE + "/entities/inst:one", headers=ADMIN).json()
    assert e["entity"]["name"] == "One Test University"
    assert [l["from_id"] for l in e["links_in"]] == ["sys:central-merit"]
    assert e["programmes"] == [] and e["children"] == []
    assert [r["action"] for r in e["revisions"]] == ["insert"]
    assert api.get(BASE + "/entities/inst:ghost", headers=ADMIN).status_code == 404
    s = api.get(BASE + "/entities/sys:central-merit", headers=ADMIN).json()
    assert s["links_out"] == [{"from_id": "sys:central-merit", "rel": "admits", "to_kind": "registry",
                               "to_id": "inst:one"}]


def test_lists_with_progress(api):
    [lst] = api.get(BASE + "/lists", headers=ADMIN).json()["lists"]
    assert lst["list_id"] == "list:alpha-list"
    assert (lst["published"], lst["loaded"], lst["complete"], lst["count_confirmed"]) == (3, 2, False, True)
    assert lst["ratio"] == pytest.approx(2 / 3)


def test_coverage(api):
    r = api.get(BASE + "/coverage", params={"intake_year": 2027}, headers=ADMIN).json()
    assert r["summary"] == {"listed": 1, "researched": 0, "verified": 1}
    assert {c["entity_id"]: c["level"] for c in r["institutions"]} == {"inst:one": "verified", "inst:two": "listed"}
    r = api.get(BASE + "/coverage", params={"intake_year": 2027, "region": "sindh"}, headers=ADMIN).json()
    assert r["summary"] == {"listed": 1, "researched": 0, "verified": 0}
    assert api.get(BASE + "/coverage", headers=ADMIN).status_code == 422  # the intake year is required
    assert api.get(BASE + "/coverage", params={"intake_year": 2027, "region": "narnia"}, headers=ADMIN).status_code == 422


def test_unknown_region_is_refused_on_entities_and_lists(api):
    for path in ("/entities", "/lists"):
        assert api.get(BASE + path, params={"region": "narnia"}, headers=ADMIN).status_code == 422
        assert api.get(BASE + path, params={"region": "sindh"}, headers=ADMIN).status_code == 200
