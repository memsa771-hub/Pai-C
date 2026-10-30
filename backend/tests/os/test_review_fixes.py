"""Regression tests for the final whole-branch review of Slice 1 (findings C1, C2, I2-I7).

Each test reproduces one finding; see the ledger's "Final:" lines.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.os import models
from app.os.compiler import compile_plan
from app.os.kernel import Outcome, StaleDraft, contract_sha256
from app.os.knowledge import Fact, SqlKnowledge
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from app.os.workers import deadline_engine
from tests.os import test_workers as tw
from tests.os.kernel_helpers import contract, draft, kernel
from tests.os.test_compiler import IE, TODAY, deadlines
from tests.os.test_compiler import contract as ie_contract

FAKE = Path(__file__).parent / "playbooks"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
TOKEN = "t"


def _count(engine, table, *where) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


def _task(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(models.tasks).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.instance_key == key)).one()


def _notices(engine) -> int:
    return _count(engine, models.tasks, models.tasks.c.instance_key.like("plan_updated@%"))


# ---- C1: a started (or done) task that differs from the draft is reported once, not every hour ----

def test_recompute_twice_after_started_change_is_noop(engine, clean):
    svc, kb, k = tw.service(engine)
    tw.seed_deadline(kb)
    ref = svc.start_plan(contract())
    m = tw.task(engine, ref.plan_id, "m@p1")
    assert k.mark_running(m.id, 1)
    tw.seed_deadline(kb, day="2027-06-30")
    assert deadline_engine.run(svc, engine) == 1
    assert deadline_engine.run(svc, engine) == 0
    assert deadline_engine.run(svc, engine) == 0
    assert _notices(engine) == 1


def test_done_task_that_differs_never_revises_again(engine, clean):
    svc, kb, k = tw.service(engine)
    tw.seed_deadline(kb)
    ref = svc.start_plan(contract())
    m = tw.task(engine, ref.plan_id, "m@p1")
    k.mark_running(m.id, 1)
    k.apply_result(m.id, 1, Outcome("done"))
    tw.seed_deadline(kb, day="2027-06-30")
    assert deadline_engine.run(svc, engine) == 1  # apply@p1 (open inbox item) is re-dated
    assert deadline_engine.run(svc, engine) == 0


# ---- C2: a removed task that comes back is a fresh task; nothing stalls on the cancelled row ----

def test_remove_then_readd_programme(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(["p1", "p2"]), draft(refs=("p1", "p2")))
    assert k.revise(ref.plan_id, "programme_dropped", draft(refs=("p1",))) == 2
    assert k.revise(ref.plan_id, "programme_readded", draft(refs=("p1", "p2"))) == 3
    assert _task(engine, ref.plan_id, "apply@p2#c2").state == "cancelled"
    assert _task(engine, ref.plan_id, "apply@p2").state == "pending"
    a = _task(engine, ref.plan_id, "a")
    k.mark_running(a.id, 1)
    k.apply_result(a.id, 1, Outcome("done"))
    for _ in range(5):  # complete every open inbox item until the plan is done
        with engine.connect() as conn:
            open_ids = conn.execute(select(models.tasks.c.id).where(
                models.tasks.c.plan_id == ref.plan_id, models.tasks.c.state == "waiting_student")).scalars().all()
        for tid in open_ids:
            k.complete_student_task(tid, "stu-1", {})
    with engine.connect() as conn:
        status = conn.execute(select(models.plans.c.status)).scalar_one()
    assert _task(engine, ref.plan_id, "visa").state == "done" and status == "done"


# ---- I4: a draft compiled from an older contract cannot overwrite a newer revision ----

def test_revise_rejects_stale_contract(engine, clean):
    k = kernel(engine)
    old = contract(["p1"])
    ref = k.create_plan(old, draft(refs=("p1",)))
    k.create_plan(contract(["p1", "p2"]), draft(refs=("p1", "p2")))  # contract changed -> revision 2
    with pytest.raises(StaleDraft):
        k.revise(ref.plan_id, "deadline_recompute", draft(refs=("p1",)), based_on=contract_sha256(old))
    assert _task(engine, ref.plan_id, "apply@p2").state == "pending"


# ---- I3: one failing plan does not stop the deadline engine for the others ----

def test_deadline_engine_isolates_failing_plan(engine, clean, monkeypatch):
    svc, kb, _ = tw.service(engine)
    tw.seed_deadline(kb)
    first = svc.start_plan(contract(external_ref="e1")).plan_id
    second = svc.start_plan(contract(external_ref="e2", student_ref="stu-2")).plan_id
    real = svc.recompile

    def flaky(plan_id, cause):
        if plan_id == first:
            raise RuntimeError("bad plan")
        return real(plan_id, cause)

    monkeypatch.setattr(svc, "recompile", flaky)
    tw.seed_deadline(kb, day="2027-06-30")
    assert deadline_engine.run(svc, engine) == 1
    assert tw.task(engine, second, "apply@p1").due_at.date() == date(2027, 6, 30)
    assert _count(engine, models.events, models.events.c.type == "recompute_failed",
                  models.events.c.plan_id == first) == 1


# ---- I5: a date computed from a fact cites that fact's page first (invariant 3) ----

def test_anchor_fact_citation_first():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][0]["citations"] = [{"source": "S6", "url": "https://route.example/rule"}]
    from app.os.playbooks import Playbook
    d = compile_plan(ie_contract(["p1"]), Playbook.model_validate(data), {}, deadlines(p1="2027-07-15"), TODAY)
    cites = next(t for t in d.tasks if t.instance_key == "apply@p1").citations
    assert cites[0] == {"source": "fact:deadline_close", "url": "https://uni.example/p"}
    assert cites[1]["url"] == "https://route.example/rule"


# ---- API: I2 supply a missing fact, I3 reject a bad value, I6 write auth, I7 startup validation ----

@pytest.fixture
def api(engine, clean, os_db):
    from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services

    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    services = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1))
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")

    def read(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    def write(x_test_student: str | None = Header(None), x_test_can_write: str | None = Header(None)) -> str:
        if x_test_can_write != "yes":
            raise HTTPException(403, "write access required")
        return read(x_test_student)

    app.dependency_overrides[current_student_ref] = read
    app.dependency_overrides[current_student_ref_for_write] = write
    return TestClient(app)


ADMIN = {"X-OS-Admin-Token": TOKEN}


def _contract_json(refs) -> dict:
    return {
        "contract_version": "1", "source": "self_serve", "external_ref": "ext-1", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "IE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)],
    }


def test_admin_supplies_missing_fact_unblocks(api, engine):
    plan = api.post("/v1/os/plans", json=_contract_json(["nowhere"]), headers=ADMIN).json()
    open_tasks = api.get("/v1/os/facts/open", headers=ADMIN).json()["items"]
    assert {(i["ref"], i["field"]) for i in open_tasks} == {("nowhere", "deadline_close")}
    body = {"scope": "programme", "ref": "nowhere", "field": "deadline_close", "intake_year": 2027,
            "value": {"date": "2027-07-15"}, "quote": "Apply by 15 July", "url": "https://uni.example/nowhere",
            "status": "confirmed"}
    r = api.post("/v1/os/facts", json=body, headers=ADMIN)
    assert r.status_code == 200 and r.json()["revised_plans"] == [plan["plan_id"]]
    apply = _task(engine, plan["plan_id"], "apply@nowhere")
    assert apply.blocked_reason is None and apply.state == "waiting_student"
    assert api.get("/v1/os/facts/open", headers=ADMIN).json()["items"] == []
    assert api.post("/v1/os/facts", json=body, headers={"X-Test-Student": "stu-1"}).status_code == 401


def test_bad_date_rejected_and_not_stored(api, engine):
    kb = SqlKnowledge(engine, "pai")
    fid = kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-07-15"}, "", "", CHECKED, 2027,
                                                             "unconfirmed"))
    api.post("/v1/os/plans", json=_contract_json(["p1"]), headers=ADMIN)
    bad = {"value": "TBD", "quote": "Apply soon", "url": "https://uni.example/p1", "status": "confirmed"}
    r = api.post(f"/v1/os/facts/{fid}/confirm", json=bad, headers=ADMIN)
    assert r.status_code == 422 and "date" in r.json()["detail"]
    assert kb.get(fid)[3].value == {"date": "2027-07-15"}


def test_complete_uses_write_dependency(api, engine):
    SqlKnowledge(engine, "pai").upsert("programme", "p1", "deadline_close", Fact(
        {"date": "2027-07-15"}, "Apply by 15 July", "https://uni.example/p1", CHECKED, 2027, "confirmed"))
    api.post("/v1/os/plans", json=_contract_json(["p1"]), headers=ADMIN)
    item = api.get("/v1/os/inbox", headers={"X-Test-Student": "stu-1"}).json()["items"][0]
    path = f"/v1/os/inbox/{item['id']}/complete"
    assert api.post(path, json={}, headers={"X-Test-Student": "stu-1"}).status_code == 403
    assert api.post(path, json={}, headers={"X-Test-Student": "stu-1", "X-Test-Can-Write": "yes"}).status_code == 200


def test_mount_os_fails_on_invalid_playbook(tmp_path):
    from app.os.api import mount_os

    (tmp_path / "bad.v1.yaml").write_text(yaml.safe_dump({"key": "bad", "version": 1}))
    env = {"DATABASE_URL": "postgresql://x/y", "OS_ENABLED": "true", "OS_ADMIN_TOKEN": "t"}
    with pytest.raises(ValueError, match="bad.v1.yaml"):
        mount_os(FastAPI(), env=env, playbook_dir=tmp_path)


def test_worker_build_validates_registry(monkeypatch, tmp_path):
    from app.os.runner import worker

    data = yaml.safe_load((FAKE / "ireland_master.v1.yaml").read_text())
    data["tasks"][0]["task_type"] = "nobody.owns.this"
    (tmp_path / "x.v1.yaml").write_text(yaml.safe_dump(data))
    monkeypatch.setattr(worker, "PLAYBOOK_SOURCE", tmp_path)
    settings = load_settings({"DATABASE_URL": "postgresql://x/y", "OS_WORKER_ID": "w1"})
    with pytest.raises(ValueError, match="nobody.owns.this"):
        worker.build(settings)
