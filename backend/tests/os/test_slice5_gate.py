"""The Slice 5 gate (spec §8): interview -> draft -> edit -> approve -> the plan's documents task is done, through
the API with os.statement running in this process, on Germany and on the fake Ireland route (same code, other
config). The Writer and Critic are the Spike 4 runner's test model; every answer is fictional."""

import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.os import models
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings
from app.os.statements.agents import build_agents
from app.os.statements.config import load_statement_configs
from app.os.statements.run import register_statements
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.quality.run_statement_quality import _test_model
from tests.os.test_api import TEST_TERMS, agree

HERE = Path(__file__).parent
CONFIGS = load_statement_configs() | load_statement_configs(HERE / "statements")
CHECKED = datetime(2027, 3, 1, tzinfo=timezone.utc)
TENANT = "pai"
P = "/v1/os"
ME = {"X-Test-Student": "stu-1"}


@pytest.fixture
def api(engine, clean, os_db):
    from dbos import DBOS, DBOSClient

    from app.os.kernel import Kernel
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA, "OS_ENABLED": "true"})
    wspec, cspec = load_agent_spec(AGENT_DIR / "writer.v1.yaml"), load_agent_spec(AGENT_DIR / "critic.v1.yaml")
    writer, critic = build_agents(_test_model(), wspec, cspec)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, TENANT))
    register_statements(engine, settings, writer, critic, wspec, cspec, CONFIGS, SqlKnowledge(engine, TENANT))
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    books = load_playbook_dir(HERE / "playbooks") | load_playbook_dir(PLAYBOOK_DIR)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1),
                        dbos_client=lambda: client, statement_configs=CONFIGS, terms_dir=TEST_TERMS)
    store, kb = ProgrammeStore(engine, TENANT), SqlKnowledge(engine, TENANT)
    for ref, route in (("g1", "germany_master"), ("i1", "ireland_master")):
        store.upsert(Programme(ref=ref, route_key=route, university="Uni X", name=f"Programme {ref}", aliases=(),
                               start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
        kb.upsert("programme", ref, "deadline_close", Fact({"date": "2027-07-15"}, "Apply by 15 July",
                                                            "https://uni.example/d", CHECKED, 2027, "confirmed"))
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.engine = engine
    try:
        yield c
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def drafted(api, kind: str, timeout: float = 30) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = [s for s in api.get(f"{P}/statements", headers=ME).json()["statements"] if s["kind"] == kind]
        if found and found[0]["status"] not in ("empty", "drafting"):
            return found[0]
        time.sleep(0.2)
    raise AssertionError(f"no {kind} draft within {timeout}s")


@pytest.mark.parametrize("route,programme,task", [("germany_master", "g1", "application_documents"),
                                                  ("ireland_master", "i1", "apply")])
def test_slice5_gate(api, route, programme, task):
    agree(api)
    r = api.post(f"{P}/plans/self", headers=ME, json={"route": route, "intake": {"term": "winter", "year": 2027},
                                                      "choices": [{"programme_ref": programme, "rank": 1}]})
    assert r.status_code == 201, r.text
    plan_id = r.json()["plan_id"]
    T = models.tasks
    with api.engine.begin() as conn:  # the documents task's turn has come (the kernel's promotion, simulated)
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.template_key == task).values(state="waiting_student"))
        task_id = conn.execute(select(T.c.id).where(T.c.plan_id == plan_id, T.c.template_key == task)).scalar_one()

    # the interview
    interview = api.get(f"{P}/statements/interview", headers=ME).json()
    assert interview["route"] == route
    assert api.post(f"{P}/statements/sop/draft", headers=ME).status_code == 409  # nothing answered yet
    for q in interview["questions"]:
        if q["required"]:
            r = api.put(f"{P}/statements/answers/{q['id']}", headers=ME,
                        json={"answer": f"My fictional answer about {q['id'].replace('_', ' ')}."})
            assert r.status_code == 200
    assert api.get(f"{P}/statements/interview", headers=ME).json()["missing"] == []

    # draft, edit, approve: the SOP and the CV
    for kind in ("sop", "cv"):
        assert api.post(f"{P}/statements/{kind}/draft", headers=ME).status_code == 202
        s = drafted(api, kind)
        assert s["status"] == "draft" and s["version"]["author"] == "writer" and s["version"]["flags"] == []
        edited = s["version"]["text"] + " I am ready to begin."
        s = api.put(f"{P}/statements/{s['id']}/text", headers=ME, json={"text": edited}).json()
        assert s["version"]["number"] == 2 and s["version"]["author"] == "student" and s["version"]["flags"] == []
        approved = api.post(f"{P}/statements/{s['id']}/approve", headers=ME, json={"version": 2}).json()
        assert len(approved["sha256"]) == 64

    # the plan's documents task is done, with the approved texts' fingerprints
    with api.engine.connect() as conn:
        state, result = conn.execute(select(T.c.state, T.c.result).where(T.c.id == task_id)).one()
    assert state == "done" and set(result["artifacts"]) == {"sop", "cv"}
    listed = {s["kind"]: s for s in api.get(f"{P}/statements", headers=ME).json()["statements"]}
    assert result["artifacts"]["cv"] == listed["cv"]["approval"]["sha256"]
