"""Slice 7 Task 8: the replan API (spec §4): proposals in the inbox, accept and decline, what changed, and the admin
support inbox. No DBOS: proposals are made by the Replanner directly. Fictional data."""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.replan import events
from app.os.replan.apply import Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.ops import CancelProgramme, RequestFromStudent
from app.os.replan.store import SupportStore
from app.os.settings import load_settings
from tests.os.test_golden import TEST_STUDENT

TOKEN = "fictional-admin-token"
ME, OTHER, ADMIN = {"X-Test-Student": TEST_STUDENT.student_ref}, {"X-Test-Student": "stu-2"}, {"X-OS-Admin-Token": TOKEN}
P1 = "tu-chemnitz-embedded-systems"
R = "The programme did not admit you: its remaining steps are removed."


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(), today=lambda: date(2027, 2, 1))
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.engine, c.svc = engine, svc
    c.plan_id = svc.plans.start_plan(TEST_STUDENT).plan_id
    c.r = Replanner(engine, svc.plans, load_replan_configs(), Outbox(engine, "pai"))
    return c


def propose(api, op=None, dedupe="k1") -> int:
    with api.engine.begin() as conn:
        eid = events.record(conn, "pai", api.plan_id, "admission_rejected", {"programme_ref": P1}, dedupe)
    d = api.r.decide(api.plan_id, [eid], "rules", [op or CancelProgramme(programme_ref=P1, reason=R)])
    assert d.status == "pending"
    return d.proposal_id


def test_inbox_lists_pending_proposal(api):
    pid = propose(api)
    body = api.get("/v1/os/inbox", headers=ME).json()
    [p] = body["proposals"]
    assert (p["id"], p["big"], p["ops"][0]["op"], p["ops"][0]["reason"]) == (pid, True, "cancel_programme", R)
    assert p["expires_at"] and body["changes_paused"] is False
    assert api.get("/v1/os/inbox", headers=OTHER).json()["proposals"] == []


def test_accept_applies_200(api):
    pid = propose(api)
    r = api.post(f"/v1/os/proposals/{pid}/accept", headers=ME)
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["revision"] > 1
    assert api.get("/v1/os/inbox", headers=ME).json()["proposals"] == []


def test_decline(api):
    pid = propose(api)
    r = api.post(f"/v1/os/proposals/{pid}/decline", headers=ME)
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert api.post(f"/v1/os/proposals/{pid}/accept", headers=ME).status_code == 409


def test_accept_stale_proposal_409(api):
    """Review Focus #3: the plan changed under the proposal: accepting is refused, never applied to a new state."""
    pid = propose(api)
    keep = lambda c: [p.model_copy(update={"rank": i}) for i, p in  # noqa: E731
                      enumerate((p for p in c.programmes if p.programme_ref != P1), 1)]
    api.svc.plans.change_programmes(api.plan_id, keep, "programmes:remove")
    r = api.post(f"/v1/os/proposals/{pid}/accept", headers=ME)
    assert r.status_code == 409 and "changed" in r.json()["detail"]


def test_accept_expired_409(api):
    pid = propose(api)
    with api.engine.begin() as conn:
        conn.execute(update(models.proposals).where(models.proposals.c.id == pid).values(
            expires_at=models.proposals.c.created_at - timedelta(days=1)))
    r = api.post(f"/v1/os/proposals/{pid}/accept", headers=ME)
    assert r.status_code == 409 and "expired" in r.json()["detail"]


def test_other_student_404(api):
    pid = propose(api)
    assert api.post(f"/v1/os/proposals/{pid}/accept", headers=OTHER).status_code == 404
    assert api.post(f"/v1/os/proposals/{pid}/decline", headers=OTHER).status_code == 404
    assert api.post("/v1/os/proposals/999999/accept", headers=ME).status_code == 404
    assert api.get(f"/v1/os/plans/{api.plan_id}/changes", headers=OTHER).status_code == 404


def test_changes_list(api):
    pid = propose(api)
    api.post(f"/v1/os/proposals/{pid}/accept", headers=ME)
    with api.engine.begin() as conn:
        eid = events.record(conn, "pai", api.plan_id, "document_missing", {"instance_key": "travel_insurance"}, "k2")
    api.r.decide(api.plan_id, [eid], "rules", [RequestFromStudent(instance_key="travel_insurance", message="Please.",
                                                                  reason="Needed on time.")])
    pending = propose(api, dedupe="k3", op=CancelProgramme(programme_ref="ovgu-eeit", reason=R))
    body = api.get(f"/v1/os/plans/{api.plan_id}/changes", headers=ME).json()
    assert [c["status"] for c in body["changes"]] == ["applied", "accepted"]  # newest first
    accepted = body["changes"][1]
    assert accepted["proposal_id"] == pid and accepted["reasons"] == [R] and accepted["revision"] > 1
    assert [p["id"] for p in body["pending"]] == [pending] and body["changes_paused"] is False


def test_admin_list_resolve_unpause(api):
    case = SupportStore(api.engine, "pai").open(api.plan_id, TEST_STUDENT.student_ref, "a step failed twice", [1])
    api.svc.kernel.set_changes_paused(api.plan_id, True)
    assert api.get("/v1/os/inbox", headers=ME).json()["changes_paused"] is True
    listed = api.get("/v1/os/admin/support", headers=ADMIN).json()["cases"]
    assert [c["id"] for c in listed] == [case] and listed[0]["changes_paused"] is True
    r = api.post(f"/v1/os/admin/support/{case}/resolve", headers=ADMIN, json={"note": "Retried by hand.", "unpause": True})
    assert r.status_code == 200 and r.json()["changes_paused"] is False
    assert api.svc.kernel.changes_paused(api.plan_id) is False
    assert api.get("/v1/os/admin/support?status=open", headers=ADMIN).json()["cases"] == []


def test_admin_requires_admin_401(api):
    assert api.get("/v1/os/admin/support").status_code == 401
    assert api.post("/v1/os/admin/support/1/resolve", json={"note": "x"}).status_code == 401
    assert api.post("/v1/os/admin/support/999/resolve", headers=ADMIN, json={"note": "x"}).status_code == 404


def test_my_changes_without_a_plan_id(api):
    """The screens read the student's open plan's changes without knowing its id."""
    pid = propose(api)
    body = api.get("/v1/os/changes", headers=ME).json()
    assert body["plan_id"] == api.plan_id and [p["id"] for p in body["pending"]] == [pid]
    assert api.get("/v1/os/changes", headers=OTHER).status_code == 404  # no plan
