"""Slice 6a Task 8: the packs API (spec §4). os.pack runs in this process (as in the Slice 5 gate). Fictional data."""

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
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from app.os.statements.config import load_statement_configs
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT
from tests.os.test_pack_run import ENTERED, PROG, Ctx, ready_inputs

P = "/v1/os/packs"
ME = {"X-Test-Student": TEST_STUDENT.student_ref}
OTHER = {"X-Test-Student": "stu-2"}


@pytest.fixture
def api(engine, clean, os_db):
    from dbos import DBOS, DBOSClient

    from app.os.knowledge import SEED_DIR, load_seed
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA, "OS_ENABLED": "true"})
    books, configs, stmt = load_playbook_dir(), load_pack_configs(), load_statement_configs()
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, "pai"))
    register_packs(engine, settings, SqlKnowledge(engine, "pai"), books, configs, stmt)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 2, 1),
                        dbos_client=lambda: client, statement_configs=stmt, pack_configs=configs)
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.engine, c.svc, c.ctx = engine, svc, Ctx(engine, client)
    c.plan_id = svc.plans.start_plan(TEST_STUDENT).plan_id
    try:
        yield c
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def settled(api, programme=PROG, headers=ME, timeout: float = 60) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = {p["programme_ref"]: p for p in api.get(P, headers=headers).json()["programmes"]}
        if found[programme]["status"] not in ("building",):
            return found[programme]
        time.sleep(0.3)
    raise AssertionError("the pack was not built in time")


def test_get_packs_enqueues_and_lists(api):
    body = api.get(P, headers=ME).json()
    refs = {p["programme_ref"] for p in body["programmes"]}
    assert PROG in refs and len(refs) == 3  # every programme in the plan
    pack = settled(api)
    assert pack["status"] == "incomplete" and pack["checklist"] and pack["data_sheet"] and pack["instructions"]
    assert {r["key"] for r in pack["data_sheet"] if r["gap"]} >= {"passport_number", "email"}


def test_build_202_idempotent(api):
    first = api.post(f"{P}/{PROG}/build", headers=ME)
    assert first.status_code == 202
    assert api.post(f"{P}/{PROG}/build", headers=ME).json()["workflow_id"] == first.json()["workflow_id"]


def test_details_put_and_422(api):
    assert api.put(f"{P}/details", headers=ME, json={"fields": ENTERED}).status_code == 200
    rows = {r["key"]: r for r in settled(api)["data_sheet"]}
    assert rows["email"]["value"] == ENTERED["email"] and rows["email"]["source"] == "entered"
    r = api.put(f"{P}/details", headers=ME, json={"fields": {"passport_number": "AB123"}})
    assert r.status_code == 422 and "passport_number" in r.json()["detail"]


def test_items_tick_untick_add(api):
    r = api.put(f"{P}/{PROG}/items", headers=ME, json={"tick": ["fee_paid"], "add": [{"label": "Module descriptions"}]})
    assert r.status_code == 200
    items = {i["key"]: i for i in settled(api)["checklist"]}
    assert items["fee_paid"]["ticked"] and items["added:1"]["label"] == "Module descriptions"
    api.put(f"{P}/{PROG}/items", headers=ME, json={"untick": ["fee_paid"]})
    assert not {i["key"]: i for i in settled(api)["checklist"]}["fee_paid"]["ticked"]
    assert api.put(f"{P}/{PROG}/items", headers=ME, json={"tick": ["no_such_item"]}).status_code == 422


def test_download_own_file(api):
    ready_inputs(api.ctx)
    pack = settled(api)
    sheet = next(f for f in pack["files"] if f["key"] == "data_sheet")
    r = api.get(f"{P}/{PROG}/files/{sheet['sha256']}", headers=ME)
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
    assert r.headers["content-type"] == "application/pdf" and sheet["filename"] in r.headers["content-disposition"]


def test_file_download_is_per_student(api):
    """Review Focus #4: another student's file is 404, even though the stored file exists."""
    ready_inputs(api.ctx)
    sha = next(f for f in settled(api)["files"] if f["key"] == "passport")["sha256"]
    assert api.get(f"{P}/{PROG}/files/{sha}", headers=ME).status_code == 200
    assert api.get(f"{P}/{PROG}/files/{sha}", headers=OTHER).status_code == 404


def test_approve_409_stale_and_incomplete(api):
    pack = settled(api)  # incomplete
    r = api.post(f"{P}/{PROG}/approve", headers=ME, json={"sha256": pack["manifest_sha256"]})
    assert r.status_code == 409 and "not complete" in r.json()["detail"]
    ready_inputs(api.ctx)
    pack = settled(api)
    assert api.post(f"{P}/{PROG}/approve", headers=ME, json={"sha256": "0" * 64}).status_code == 409


def test_approve_200_completes_task(api):
    ready_inputs(api.ctx)
    T = models.tasks
    with api.engine.begin() as conn:
        conn.execute(update(T).where(T.c.plan_id == api.plan_id, T.c.instance_key == f"review_pack@{PROG}")
                     .values(state="waiting_student"))
    pack = settled(api)
    assert pack["status"] == "ready"
    r = api.post(f"{P}/{PROG}/approve", headers=ME, json={"sha256": pack["manifest_sha256"]})
    assert r.status_code == 200 and r.json()["sha256"] == pack["manifest_sha256"]
    assert settled(api)["approved"] is True
    with api.engine.connect() as conn:
        state = conn.execute(select(T.c.state).where(T.c.plan_id == api.plan_id,
                                                     T.c.instance_key == f"review_pack@{PROG}")).scalar()
    assert state == "done"


def test_other_students_pack_404(api):
    assert api.get(P, headers=OTHER).status_code == 404  # no plan: no packs
    assert api.post(f"{P}/{PROG}/build", headers=OTHER).status_code == 404
    assert api.post(f"{P}/{PROG}/approve", headers=OTHER, json={"sha256": "0" * 64}).status_code == 404
    assert api.post(f"{P}/not-in-my-plan/build", headers=ME).status_code == 404


# --- final review fixes ---------------------------------------------------------------------------------------


def test_failed_build_shows_failed_and_rebuild_retries(api, monkeypatch):
    """Review C1: a failed build shows `failed` (never "being prepared" for ever), and Rebuild really runs again."""
    from app.os.packs import render

    real = render.render_sheet
    monkeypatch.setattr(render, "render_sheet", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("renderer down")))
    assert settled(api)["status"] == "failed"
    monkeypatch.setattr(render, "render_sheet", real)
    retried = api.post(f"{P}/{PROG}/build", headers=ME).json()["workflow_id"]
    assert retried.endswith(":r1")  # a new attempt, not the failed run again
    built = settled(api)
    assert built["status"] == "incomplete" and built["version"] == 1
    again = api.post(f"{P}/{PROG}/build", headers=ME).json()["workflow_id"]
    assert api.post(f"{P}/{PROG}/build", headers=ME).json()["workflow_id"] == again  # nothing changed: one build
    assert settled(api)["version"] == 1  # and no new version


def test_return_to_earlier_inputs_rebuilds(api):
    """Review C2: inputs that change and change back (A -> B -> A) still settle; the pack is never stuck."""
    assert settled(api)["status"] == "incomplete"
    api.put(f"{P}/{PROG}/items", headers=ME, json={"tick": ["fee_paid"]})
    assert {i["key"]: i for i in settled(api)["checklist"]}["fee_paid"]["ticked"]
    api.put(f"{P}/{PROG}/items", headers=ME, json={"untick": ["fee_paid"]})
    back = settled(api)
    assert back["status"] == "incomplete" and not {i["key"]: i for i in back["checklist"]}["fee_paid"]["ticked"]


def test_approve_refuses_when_inputs_changed(api):
    """Review I1: an old tab cannot approve a version whose inputs have changed since (invariant 5)."""
    ready_inputs(api.ctx)
    pack = settled(api)
    assert pack["status"] == "ready"
    api.put(f"{P}/{PROG}/items", headers=ME, json={"untick": ["fee_paid"]})  # before any rebuild runs
    r = api.post(f"{P}/{PROG}/approve", headers=ME, json={"sha256": pack["manifest_sha256"]})
    assert r.status_code == 409 and "changed" in r.json()["detail"]
