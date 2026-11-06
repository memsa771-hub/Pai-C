"""P1-T6 Task 5 (R-09, rows 6.13 and 6.17): with the Counsellor module and the host part on, the route builder hands the
student's choice to the host (ChoiceSink) instead of starting a self-serve plan. With the module off, the host part off
(the host answers None) or the port unconfigured, the builder works standalone exactly as before. Fictional data."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.api import self_serve
from app.os.api.schemas import SelfPlanOut
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.ports import choice_sink
from app.os.replan import choice_texts
from app.os.settings import load_settings
from tests.os.test_api import TEST_TERMS, agree
from tests.os.test_api_knowledge import FakeClient
from tests.os.test_api_self_serve import CHECKED, FAKE, TOKEN, me

pytestmark = pytest.mark.req("R-09")

P = "/v1/os"
GERMANY = {"route": "germany_master", "intake": {"term": "winter", "year": 2027},
           "choices": [{"programme_ref": "g1", "rank": 1}]}
BODY = {"route": "ireland_master", "intake": {"term": "winter", "year": 2027},
        "choices": [{"programme_ref": "p1", "rank": 1}, {"programme_ref": "p2", "rank": 2}]}


class Host:
    """A fake host: records the calls and answers what the test says."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, *args):
        self.calls.append(args)
        return self.answer


def build(engine, os_db, rehearsal=False) -> TestClient:
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true",
                              "OS_REHEARSAL": "on" if rehearsal else ""})
    books = load_playbook_dir(FAKE) | load_playbook_dir(PLAYBOOK_DIR)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1),
                        dbos_client=lambda: FakeClient(), terms_dir=TEST_TERMS)
    store, kb = ProgrammeStore(engine, "pai"), SqlKnowledge(engine, "pai")
    for ref in ("p1", "p2"):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="Uni X", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
        kb.upsert("programme", ref, "deadline_close", Fact({"date": "2027-07-15"}, "q", "https://uni.example/r",
                                                            CHECKED, 2027, "confirmed"), "manual")
    store.upsert(Programme(ref="g1", route_key="germany_master", university="Uni X", name="Programme g1", aliases=(),
                           start_urls=("https://uni.example/g1",), official_domains=("uni.example",)))
    kb.upsert("programme", "g1", "deadline_close", Fact({"date": "2027-07-15"}, "q", "https://uni.example/r",
                                                        CHECKED, 2027, "confirmed"), "manual")
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    client = TestClient(app)
    client.engine, client.svc = engine, svc
    return client


@pytest.fixture
def api(engine, clean, os_db):
    client = build(engine, os_db)
    try:
        yield client
    finally:
        choice_sink.configure(None)


def post_start(api, student="stu-1", body=BODY):
    agree(api, student)
    return api.post(f"{P}/plans/self", headers=me(student), json=body)


def connect(host, on=True) -> None:
    choice_sink.configure(host, lambda: on)


def plans(api, source=None) -> int:
    q = select(func.count()).select_from(models.plans)
    if source:
        q = q.where(models.plans.c.source == source)
    with api.engine.connect() as conn:
        return conn.execute(q).scalar()


def module_on(api) -> None:
    manifest.set_enabled(api.engine, "pai", True)


def standalone_ok(r, api) -> None:
    """Exactly today's answer: 201, one self-serve plan, the playbook's choose task done, and the body is the plan."""
    assert r.status_code == 201, r.text
    assert plans(api, "self_serve") == 1
    with api.engine.connect() as conn:
        state = conn.execute(select(models.tasks.c.state).where(models.tasks.c.instance_key == "choose_programmes")
                             ).scalar()
        plan_id = conn.execute(select(models.plans.c.id).where(models.plans.c.source == "self_serve")).scalar()
    assert state == "done"
    assert SelfPlanOut.model_validate(r.json()) == SelfPlanOut.model_validate(self_serve.self_plan_out(api.svc.plans, plan_id))


# --- row 6.17: flags off is today -----------------------------------------------------------------------------

def test_module_off_builder_standalone(api):
    host = Host({"outcome": "written", "decision_version": 2, "code": None})
    connect(host)  # a host that would take it, but the module is off
    r = post_start(api, body=GERMANY)
    standalone_ok(r, api)
    assert host.calls == [] and r.json().get("state") != "preparing"


def test_handoff_off_builder_standalone(api):
    module_on(api)
    host = Host(None)  # the host answers None
    connect(host)
    r = post_start(api, body=GERMANY)
    standalone_ok(r, api)
    assert len(host.calls) == 1


def test_part_off_gate_builder_standalone_and_host_not_asked(api):
    module_on(api)
    host = Host({"outcome": "written", "decision_version": 2, "code": None})
    connect(host, on=False)
    standalone_ok(post_start(api, body=GERMANY), api)
    assert host.calls == []
    again = api.post(f"{P}/plans/self", headers=me(), json={**GERMANY, "intake": {"term": "winter", "year": 2028}})
    # as today: the part is off, so the other intake is a second standalone plan of its own (201), not adopt_first
    assert again.status_code == 201 and plans(api, "self_serve") == 2 and host.calls == []


def test_open_self_serve_plan_means_adopt_first_same_and_other_identity(api):
    module_on(api)
    host = Host({"outcome": "written", "decision_version": 2, "code": None})
    connect(host, on=False)
    assert post_start(api, body=GERMANY).status_code == 201  # a plan of the student's own, made standalone
    connect(host)  # the part is now on
    for body in (GERMANY, {**GERMANY, "intake": {"term": "winter", "year": 2028}}):
        r = api.post(f"{P}/plans/self", headers=me(), json=body)
        assert r.status_code == 409 and r.json() == {"detail": "adopt_first", "note": None}, r.text
    assert host.calls == [] and plans(api, "self_serve") == 1


def test_host_raising_is_503_and_never_standalone(api):
    module_on(api)

    def boom(*a):
        raise RuntimeError("down")

    connect(boom)
    r = post_start(api, body=GERMANY)
    assert r.status_code == 503 and r.json() == {"detail": "counsellor_unavailable"}
    assert plans(api) == 0


def test_unconfigured_sink_standalone(api):
    module_on(api)
    choice_sink.configure(None)
    standalone_ok(post_start(api, body=GERMANY), api)


# --- row 6.13 ---------------------------------------------------------------------------------------------------

def test_written_is_202_preparing_and_no_plan(api):
    module_on(api)
    host = Host({"outcome": "written", "decision_version": 4, "code": None})
    connect(host)
    r = post_start(api)
    assert r.status_code == 202 and r.json() == {"state": "preparing", "decision_version": 4, "note": None}
    assert plans(api) == 0
    assert host.calls == [("stu-1", "PK", "IE", "master", {"term": "winter", "year": 2027},
                           [{"programme_ref": "p1", "rank": 1}, {"programme_ref": "p2", "rank": 2}])]


def test_unchanged_is_202_too(api):
    module_on(api)
    connect(Host({"outcome": "unchanged", "decision_version": 3, "code": None}))
    r = post_start(api)
    assert r.status_code == 202 and r.json()["decision_version"] == 3 and plans(api) == 0


@pytest.mark.parametrize("code", ["choose_field_first", "too_many_places"])
def test_refused_is_409_with_the_code(api, code):
    module_on(api)
    connect(Host({"outcome": "refused", "decision_version": None, "code": code}))
    r = post_start(api)
    assert r.status_code == 409 and r.json() == {"detail": code, "note": None}
    assert plans(api) == 0


def test_validation_comes_before_the_host(api):
    module_on(api)
    host = Host({"outcome": "written", "decision_version": 2, "code": None})
    connect(host)
    agree(api)
    bad = {**BODY, "choices": [{"programme_ref": "nope", "rank": 1}]}
    assert api.post(f"{P}/plans/self", headers=me(), json=bad).status_code == 422
    assert host.calls == []


def test_note_null_until_approved_then_only_in_rehearsal(engine, clean, os_db):
    assert yaml.safe_load(choice_texts.PATH.read_text())["approved"] is False
    for key in ("preparing", "choose_field_first", "too_many_places", "adopt_first"):
        assert choice_texts.note(key, load_settings({"OS_DATABASE_URL": os_db})) is None
    api = build(engine, os_db, rehearsal=True)
    try:
        module_on(api)
        connect(Host({"outcome": "written", "decision_version": 2, "code": None}))
        r = post_start(api)
        assert r.json()["note"] == yaml.safe_load(choice_texts.PATH.read_text())["preparing"]
        connect(Host({"outcome": "refused", "decision_version": None, "code": "choose_field_first"}))
        r = api.post(f"{P}/plans/self", headers=me(), json=BODY)
        assert r.status_code == 409
        assert r.json()["note"] == yaml.safe_load(choice_texts.PATH.read_text())["choose_field_first"]
    finally:
        choice_sink.configure(None)


def test_mount_configure_sets_the_sink():
    called = []
    ports.configure(None, choice_sink=lambda *a: called.append(a) or None, choice_sink_enabled=lambda: True)
    try:
        assert choice_sink.request("s", "PK", "IE", "master", {"term": "winter", "year": 2027}, []) is None
        assert len(called) == 1 and choice_sink.enabled() is True
    finally:
        ports.configure(None)
    assert choice_sink.enabled() is False
    assert choice_sink.request("s", "PK", "IE", "master", {"term": "winter", "year": 2027}, []) is None
