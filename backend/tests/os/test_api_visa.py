"""Slice 6b Task 5: the visa API (spec §4), under /v1/os/visa. os.pack runs in this process. Fictional data."""

import time
from datetime import date

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.kernel import Kernel
from app.os.knowledge import SqlKnowledge
from app.os.packs.config import load_pack_configs
from app.os.packs.run import register_packs
from app.os.packs.visa import VisaChoiceStore
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from app.os.statements.config import load_statement_configs
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT
from tests.os.test_pack_run import Ctx
from tests.os.test_visa_run import OTHER as OTHER_PROG
from tests.os.test_visa_run import PROG, ready_visa

V = "/v1/os/visa"
ME = {"X-Test-Student": TEST_STUDENT.student_ref}
OTHER = {"X-Test-Student": "stu-2"}
T = models.tasks


def _app(svc) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    return TestClient(app)


@pytest.fixture
def api(engine, clean, os_db):
    from dbos import DBOS, DBOSClient

    from app.os.knowledge import SEED_DIR, load_seed
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA, "OS_ENABLED": "true"})
    books, configs, stmt = load_playbook_dir(), load_pack_configs(), load_statement_configs()
    visas = load_pack_configs(kind="visa")
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, "pai"))
    register_packs(engine, settings, SqlKnowledge(engine, "pai"), books, configs, stmt, visas)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 2, 1),
                        dbos_client=lambda: client, statement_configs=stmt, pack_configs=configs, visa_configs=visas)
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    c = _app(svc)
    c.engine, c.svc, c.ctx = engine, svc, Ctx(engine, client)
    c.plan_id = svc.plans.start_plan(TEST_STUDENT).plan_id
    try:
        yield c
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def settled(api, headers=ME, timeout: float = 60) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = api.get(V, headers=headers).json()
        if body["status"] != "building":
            return body
        time.sleep(0.3)
    raise AssertionError("the visa file was not built in time")


def admitted(api, programme: str) -> None:
    with api.engine.begin() as conn:  # the student told us this programme admitted them (the kernel's write, simulated)
        conn.execute(update(T).where(T.c.plan_id == api.plan_id, T.c.instance_key == f"admission_result@{programme}")
                     .values(state="done", result={"choice": "admitted"}))


def test_get_visa_preselects_and_builds(api):
    body = api.get(V, headers=ME).json()
    assert body["status"] == "no_choice" and body["programme_ref"] is None and body["choice"]["preselected"] is None
    assert {p["programme_ref"] for p in body["programmes"]} >= {PROG, OTHER_PROG}
    assert body["funds"]["required"] == 11904.0 and body["funds"]["status"] == "unconfirmed"
    admitted(api, OTHER_PROG)
    body = settled(api)
    assert body["choice"]["preselected"] == OTHER_PROG and body["programme_ref"] == OTHER_PROG
    assert body["status"] == "incomplete" and body["checklist"] and body["data_sheet"] and body["instructions"]
    assert {i["key"] for i in body["checklist"]} >= {"blocked_account", "motivation_letter"}


def test_choice_422(api):
    assert api.put(f"{V}/choice", headers=ME, json={"programme_ref": "not-in-my-plan"}).status_code == 422
    assert api.put(f"{V}/choice", headers=ME, json={"reduction": -1}).status_code == 422
    r = api.put(f"{V}/choice", headers=ME, json={"programme_ref": PROG, "reduction": 2000})
    assert r.status_code == 200
    body = settled(api)
    assert body["programme_ref"] == PROG and body["choice"]["reduction"] == 2000.0
    assert body["funds"]["required"] == 9904.0


def test_visa_items(api):
    api.put(f"{V}/choice", headers=ME, json={"programme_ref": PROG})
    r = api.put(f"{V}/items", headers=ME, json={"tick": ["visa_fee_paid"], "add": [{"label": "Bank statement"}]})
    assert r.status_code == 200
    items = {i["key"]: i for i in settled(api)["checklist"]}
    assert items["visa_fee_paid"]["ticked"] and items["added:1"]["label"] == "Bank statement"
    assert api.put(f"{V}/items", headers=ME, json={"tick": ["fee_paid"]}).status_code == 422  # a pack item


def test_visa_download_per_student(api):
    ready_visa(api.ctx)
    sha = next(f for f in settled(api)["files"] if f["key"] == "blocked_account")["sha256"]
    r = api.get(f"{V}/files/{sha}", headers=ME)
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
    assert api.get(f"{V}/files/{sha}", headers=OTHER).status_code == 404


def test_visa_approve_409_without_choice(api):
    r = api.post(f"{V}/approve", headers=ME, json={"sha256": "0" * 64})
    assert r.status_code == 409 and "programme" in r.json()["detail"]


def test_visa_approve_200_completes_task(api):
    ready_visa(api.ctx)
    with api.engine.begin() as conn:
        conn.execute(update(T).where(T.c.plan_id == api.plan_id, T.c.instance_key == "review_visa_file")
                     .values(state="waiting_student"))
    body = settled(api)
    assert body["status"] == "ready", body["checklist"]
    assert api.post(f"{V}/approve", headers=ME, json={"sha256": "0" * 64}).status_code == 409  # an old tab
    r = api.post(f"{V}/approve", headers=ME, json={"sha256": body["manifest_sha256"]})
    assert r.status_code == 200 and settled(api)["approved"] is True
    with api.engine.connect() as conn:
        state = conn.execute(select(T.c.state).where(T.c.plan_id == api.plan_id,
                                                     T.c.instance_key == "review_visa_file")).scalar()
    assert state == "done"
    VisaChoiceStore(api.engine, "pai").set_programme(TEST_STUDENT.student_ref, OTHER_PROG)
    assert settled(api)["approved"] is False  # another programme: a new version, not approved


def test_route_without_visa_config_404(api):
    assert api.get(V, headers=OTHER).status_code == 404  # no plan
    bare = _app(make_services(api.svc.settings, engine=api.engine, playbooks=load_playbook_dir(),
                              today=lambda: date(2027, 2, 1), visa_configs={}))
    r = bare.get(V, headers=ME)
    assert r.status_code == 404 and "visa" in r.json()["detail"]
