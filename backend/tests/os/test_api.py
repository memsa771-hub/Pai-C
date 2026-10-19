from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.knowledge import Fact, SqlKnowledge
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings

FAKE = Path(__file__).parent / "playbooks"
TOKEN = "test-admin-token"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)


def contract(student="stu-1", refs=("p1",), external_ref="ext-1", destination="IE") -> dict:
    return {
        "contract_version": "1", "source": "self_serve", "external_ref": external_ref, "student_ref": student,
        "origin_country": "PK", "destination_country": destination, "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)],
    }


@pytest.fixture
def client(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1))
    SqlKnowledge(engine, "pai").upsert("programme", "p1", "deadline_close", Fact(
        {"date": "2027-07-15"}, "Apply by 15 July", "https://uni.example/apply", CHECKED, 2027, "confirmed"))
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            from fastapi import HTTPException
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student  # write access is tested elsewhere
    return TestClient(app)


ADMIN = {"X-OS-Admin-Token": TOKEN}


def as_student(name="stu-1") -> dict:
    return {"X-Test-Student": name}


def test_post_plan_requires_admin_token(client):
    assert client.post("/v1/os/plans", json=contract()).status_code == 401
    assert client.post("/v1/os/plans", json=contract(), headers={"X-OS-Admin-Token": "wrong"}).status_code == 401
    # A bearer is not the admin channel (the host's session middleware rewrites Authorization anyway).
    assert client.post("/v1/os/plans", json=contract(), headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401


def test_post_plan_invalid_contract_422(client):
    assert client.post("/v1/os/plans", json={**contract(), "origin_country": "PAK"}, headers=ADMIN).status_code == 422


def test_post_plan_no_playbook_422(client):
    r = client.post("/v1/os/plans", json=contract(destination="FR"), headers=ADMIN)
    assert r.status_code == 422 and "no playbook" in r.json()["detail"]


def test_post_plan_idempotent(client):
    first = client.post("/v1/os/plans", json=contract(), headers=ADMIN)
    second = client.post("/v1/os/plans", json=contract(), headers=ADMIN)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["plan_id"] == second.json()["plan_id"]
    keys = {t["instance_key"] for t in first.json()["tasks"]}
    assert keys == {"apply@p1", "visa"}


def test_post_plan_unknown_programme_201(client):
    r = client.post("/v1/os/plans", json=contract(refs=("p1", "nowhere")), headers=ADMIN)
    assert r.status_code == 201
    tasks = {t["instance_key"]: t for t in r.json()["tasks"]}
    assert tasks["apply@nowhere"]["state"] == "blocked"
    assert tasks["apply@nowhere"]["blocked_reason"] == "fact_missing:deadline_close"
    assert "confirm_fact@nowhere:deadline_close" in tasks


def test_get_plan_admin_only(client):
    plan_id = client.post("/v1/os/plans", json=contract(), headers=ADMIN).json()["plan_id"]
    assert client.get(f"/v1/os/plans/{plan_id}", headers=ADMIN).json()["plan_id"] == plan_id
    assert client.get(f"/v1/os/plans/{plan_id}", headers=as_student()).status_code == 401
    assert client.get("/v1/os/plans/999", headers=ADMIN).status_code == 404


def test_student_sees_only_own_inbox(client):
    client.post("/v1/os/plans", json=contract(student="stu-1"), headers=ADMIN)
    client.post("/v1/os/plans", json=contract(student="stu-2", external_ref="ext-2"), headers=ADMIN)
    mine = client.get("/v1/os/inbox", headers=as_student("stu-1")).json()["items"]
    assert [i["instance_key"] for i in mine] == ["apply@p1"]
    assert mine[0]["citations"] == [{"source": "fact:deadline_close", "url": "https://uni.example/apply"}]
    assert mine[0]["due_tz"] == "Europe/Dublin"
    assert client.get("/v1/os/inbox").status_code == 401


def test_complete_inbox_twice_200(client):
    client.post("/v1/os/plans", json=contract(), headers=ADMIN)
    item = client.get("/v1/os/inbox", headers=as_student()).json()["items"][0]
    first = client.post(f"/v1/os/inbox/{item['id']}/complete", json={}, headers=as_student())
    second = client.post(f"/v1/os/inbox/{item['id']}/complete", json={}, headers=as_student())
    assert (first.status_code, second.status_code) == (200, 200)
    assert (first.json()["completed"], second.json()["completed"]) == (True, False)
    assert [i["instance_key"] for i in client.get("/v1/os/inbox", headers=as_student()).json()["items"]] == ["visa"]


def test_other_student_cannot_complete(client):
    client.post("/v1/os/plans", json=contract(), headers=ADMIN)
    item = client.get("/v1/os/inbox", headers=as_student()).json()["items"][0]
    assert client.post(f"/v1/os/inbox/{item['id']}/complete", json={}, headers=as_student("stu-2")).status_code == 404


def test_confirm_fact_admin_only(client, engine):
    fid = SqlKnowledge(engine, "pai").upsert("programme", "p2", "deadline_close", Fact(
        {"date": "2027-06-01"}, "", "", CHECKED, 2027, "unconfirmed"))
    client.post("/v1/os/plans", json=contract(refs=("p1", "p2")), headers=ADMIN)
    body = {"value": {"date": "2027-06-01"}, "quote": "Apply by 1 June", "url": "https://uni.example/p2",
            "status": "confirmed"}
    assert client.post(f"/v1/os/facts/{fid}/confirm", json=body, headers=as_student()).status_code == 401
    r = client.post(f"/v1/os/facts/{fid}/confirm", json=body, headers=ADMIN)
    assert r.status_code == 200 and len(r.json()["revised_plans"]) == 1
    bad = {**body, "quote": ""}
    assert client.post(f"/v1/os/facts/{fid}/confirm", json=bad, headers=ADMIN).status_code == 422
    assert client.post("/v1/os/facts/999/confirm", json=body, headers=ADMIN).status_code == 404


def test_router_not_mounted_when_disabled(monkeypatch):
    from app.os.api.mount import mount_os

    app = FastAPI()
    mount_os(app, env={"DATABASE_URL": "postgresql://x/y"}, student_dependency=lambda: "s")
    assert TestClient(app).post("/v1/os/plans", json={}).status_code == 404
    enabled = FastAPI()
    mount_os(enabled, env={"DATABASE_URL": "postgresql://x/y", "OS_ENABLED": "true", "OS_ADMIN_TOKEN": "t"},
             student_dependency=lambda: "s")
    assert TestClient(enabled).post("/v1/os/plans", json={}).status_code == 401
