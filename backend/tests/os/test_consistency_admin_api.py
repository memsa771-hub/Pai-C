"""P1-T10 A1: the admin list of consistency cases (R-05): 401 without the admin token, list and resolve."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.os import models
from app.os.api import build_router, make_services
from app.os.consistency.store import ConsistencyStore
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings

pytestmark = pytest.mark.req("R-05")
TOKEN = "fictional-admin-token"
ADMIN = {"X-OS-Admin-Token": TOKEN}


@pytest.fixture
def api(engine, clean, os_db):
    svc = make_services(load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"}),
                        engine=engine, playbooks=load_playbook_dir(), today=lambda: date(2027, 2, 1))
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")
    c = TestClient(app)
    c.store = ConsistencyStore(engine, "pai")
    c.engine = engine
    return c


def test_admin_token_is_required(api):
    assert api.get("/v1/os/admin/consistency").status_code == 401
    assert api.get("/v1/os/admin/consistency", headers={"X-OS-Admin-Token": "wrong"}).status_code == 401
    assert api.post("/v1/os/admin/consistency/1/resolve", json={"note": "x"}).status_code == 401


def test_list_filters_by_status_and_holds_codes_only(api):
    a, _ = api.store.open_or_touch("stu-1", 2, None, ["contract_hash"])
    b, _ = api.store.open_or_touch("stu-1", 3, None, ["plan_not_stopped"])
    api.store.resolve(b, "checked")
    allc = api.get("/v1/os/admin/consistency", headers=ADMIN).json()["cases"]
    assert [c["id"] for c in allc] == [a, b]
    assert set(allc[0]) == {"id", "student_ref", "rule", "plan_id", "codes", "status", "resolution", "first_seen_at",
                            "last_seen_at", "resolved_at"}
    opened = api.get("/v1/os/admin/consistency?status=open", headers=ADMIN).json()["cases"]
    assert [(c["id"], c["codes"]) for c in opened] == [(a, ["contract_hash"])]
    assert api.get("/v1/os/admin/consistency?status=bogus", headers=ADMIN).status_code == 422


def test_resolve_closes_the_case_and_only_that(api):
    a, _ = api.store.open_or_touch("stu-1", 2, None, ["contract_hash"])
    r = api.post(f"/v1/os/admin/consistency/{a}/resolve", headers=ADMIN, json={"note": "Checked by a person."})
    assert r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["resolution"].startswith("Checked")
    assert api.post(f"/v1/os/admin/consistency/{a}/resolve", headers=ADMIN, json={"note": "again"}).status_code == 409
    assert api.post("/v1/os/admin/consistency/999/resolve", headers=ADMIN, json={"note": "x"}).status_code == 404
    assert api.post(f"/v1/os/admin/consistency/{a}/resolve", headers=ADMIN, json={"note": ""}).status_code == 422
    with api.engine.connect() as conn:
        assert conn.execute(select(models.support_cases.c.id)).all() == []
