"""P1-T8 Task 2: the student's needs gate (D-w1), gated playbook selection and the upgrade proposal (D-w2, D-w3), the
student state (D-w6), and the refresh after a document change (D-w8). Postgres. Fictional students and values."""

import types as pytypes
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.contracts.route_contract import RouteContract
from app.os.contracts.student_facts import StudentFactsV1
from app.os.documents.store import DocumentStore, FindingStore
from app.os.knowledge import Fact, SqlKnowledge
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.ports import fact_proposals, fact_questions
from app.os.replan.apply import Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.events import pending
from app.os.replan.rules import rules_for
from app.os.requests import gate, state
from app.os.requests.refresh import refresh
from app.os.service import NothingNewer
from app.os.settings import load_settings
from tests.os.test_api import TEST_TERMS, TOKEN, agree, as_student
from tests.os.test_api_documents import FakeClient, confirm_body, jpeg, simulate_read
from tests.os.test_compile_needs import BOOKS

TENANT, NOW, TODAY = "pai", datetime(2026, 11, 5, tzinfo=timezone.utc), date(2027, 3, 1)
OBTAINED, TOTAL = "education.matric.marks_obtained", "education.matric.marks_total"
INTER_MARKS = "education.intermediate.marks_obtained"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
HSSC = {"student_name": "Sara Ahmed Khan", "father_name": "Ahmed Khan", "date_of_birth": "2001-04-12",
        "marks_obtained": 800, "marks_total": 1100, "institution": "Example College"}

pytestmark = pytest.mark.req("R-17")


def facts_of(student, version, **marks) -> dict:
    """The Vault's answer for `student`: each key -> (value, evidence)."""
    items = [{"key": k.replace("__", "."), "value": None if v[1] == "unknown" else v[0], "evidence": v[1], "vault_version": version}
             for k, v in marks.items()]
    return StudentFactsV1.model_validate({"schema": "pai.student_facts.v1", "student_ref": student,
                                          "vault_version": version, "built_at": NOW, "eligible_levels": None,
                                          "facts": items}).model_dump(by_alias=True)


def contract(student="stu-1", level="bachelor", refs=("p1",)) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"self:{student}", "student_ref": student,
        "origin_country": "PK", "destination_country": "PK", "level": level,
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


@pytest.fixture
def world(engine, clean, os_db):
    """Both versions of every fake route loaded; the Vault answers from a dict (empty: the gate is off)."""
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true", "OS_ADMIN_TOKEN": TOKEN})
    fake = FakeClient()
    svc = make_services(settings, engine=engine, playbooks=BOOKS, today=lambda: TODAY, dbos_client=lambda: fake,
                        terms_dir=TEST_TERMS)
    kb = SqlKnowledge(engine, TENANT)
    kb.upsert("programme", "p1", "merit_list_date", Fact({"date": "2027-08-15"}, "q", "https://uni.example/x",
                                                        CHECKED, 2027, "confirmed"), "manual")
    vault: dict[str, dict] = {}
    ports.configure(svc, student_facts=lambda ref: vault.get(ref))
    manifest.set_enabled(engine, TENANT, True)
    try:
        yield pytypes.SimpleNamespace(svc=svc, engine=engine, vault=vault, fake=fake, kb=kb)
    finally:
        ports.configure(None)


def pin(engine, plan_id) -> int:
    with engine.connect() as conn:
        return conn.execute(select(models.playbook_pins.c.version).where(
            models.playbook_pins.c.plan_id == plan_id)).scalar_one()


def keys_of(engine, plan_id) -> dict[str, str]:
    with engine.connect() as conn:
        return {r.instance_key: r.state for r in conn.execute(
            select(models.tasks).where(models.tasks.c.plan_id == plan_id))}


def newer(engine, plan_id) -> list:
    with engine.connect() as conn:
        return conn.execute(select(models.events).where(models.events.c.plan_id == plan_id,
                                                        models.events.c.type == "playbook_newer")).all()


# --- the gate -----------------------------------------------------------------------------------------------------

def test_the_gate_is_on_only_with_a_host_adapter_that_answers(world):
    kw = {"engine": world.engine, "tenant_id": TENANT}
    assert gate.on("stu-1", **kw) is None  # the adapter answers None (the host's part is off)
    world.vault["stu-1"] = facts_of("stu-1", 1)
    assert gate.on("stu-1", **kw).student_ref == "stu-1"
    manifest.set_enabled(world.engine, TENANT, False)
    assert gate.on("stu-1", **kw) is None  # the counsellor module is off
    manifest.set_enabled(world.engine, TENANT, True)
    ports.configure(world.svc)
    assert gate.on("stu-1", **kw) is None  # no adapter


# --- selection ----------------------------------------------------------------------------------------------------

def test_gate_off_selects_v1_and_records_no_playbook_newer(world):
    plan_id = world.svc.plans.start_plan(contract()).plan_id
    assert pin(world.engine, plan_id) == 1
    assert world.svc.plans.check_newer(plan_id) is False and newer(world.engine, plan_id) == []
    assert not [k for k in keys_of(world.engine, plan_id) if k.startswith(("provide@", "which_is_right@"))]
    with pytest.raises(NothingNewer):
        world.svc.plans.upgrade(plan_id)


def test_gate_on_selects_v2_for_a_new_plan_and_asks_for_what_is_missing(world):
    world.vault["stu-1"] = facts_of("stu-1", 1)
    plan_id = world.svc.plans.start_plan(contract()).plan_id
    assert pin(world.engine, plan_id) == 2
    tasks = keys_of(world.engine, plan_id)
    assert tasks[f"provide@fact:{INTER_MARKS}:stated"] == "waiting_student"
    assert tasks["provide@document:hssc_certificate:shown"] == "waiting_student"
    assert tasks["entry_test"] == "blocked"


def test_gate_on_records_playbook_newer_and_upgrade_is_a_proposal(world):
    plan_id = world.svc.plans.start_plan(contract()).plan_id  # the gate was off: v1
    world.vault["stu-1"] = facts_of("stu-1", 1)  # now it is on
    assert world.svc.plans.check_newer(plan_id) is True
    [event] = newer(world.engine, plan_id)
    assert (event.payload["version"], event.payload["from"]) == (2, 1)
    assert pin(world.engine, plan_id) == 1  # nothing moved by itself
    replanner = Replanner(world.engine, world.svc.plans, load_replan_configs(), Outbox(world.engine, TENANT),
                          clock=lambda: NOW)
    e = next(x for x in pending(world.engine, TENANT, plan_id) if x.type == "playbook_newer")
    ops = rules_for(e, replanner.state(plan_id), replanner.config(plan_id))
    decision = replanner.decide(plan_id, [e.id], "rules", ops)
    assert decision.status == "pending"  # a big change: the student decides
    assert [o["op"] for o in replanner.proposals.get(decision.proposal_id).ops] == ["upgrade_playbook"]
    assert pin(world.engine, plan_id) == 1
    revision = world.svc.plans.upgrade(plan_id, 2)  # what accepting it runs
    assert revision and pin(world.engine, plan_id) == 2
    assert f"provide@fact:{INTER_MARKS}:stated" in keys_of(world.engine, plan_id)
    world.vault.clear()  # the gate goes off again: a v2 plan keeps running without the requests
    world.svc.plans.recompile(plan_id, "gate_off")
    assert not [k for k in keys_of(world.engine, plan_id) if k.startswith("provide@") and "#" not in k]


# --- the student state ----------------------------------------------------------------------------------------------

def test_state_is_none_while_the_gate_is_off(world):
    assert state.build(world.svc.plans, "stu-1") is None


def test_state_holds_levels_and_documents_never_values(world):
    world.vault["stu-1"] = facts_of("stu-1", 1, **{INTER_MARKS: (800, "stated"), "education__bachelor__gpa": (3.1, "unknown")})
    got = state.build(world.svc.plans, "stu-1")
    assert got.facts == {INTER_MARKS: "stated"}  # inferred is not held
    store = DocumentStore(world.engine, TENANT)
    uploaded = store.create("stu-1", "hssc_certificate", 1, "a.jpg", "image/jpeg", jpeg(1))
    assert state.build(world.svc.plans, "stu-1").documents == {"hssc_certificate": "uploaded"}
    assert uploaded and "800" not in repr(got) and "3.1" not in repr(got)


@pytest.mark.req("R-21")
def test_impossible_value_is_a_question(world):
    world.vault["stu-1"] = facts_of("stu-1", 1, **{"education__matric__marks_obtained": (1200, "stated"),
                                                   "education__matric__marks_total": (1100, "stated")})
    got = state.build(world.svc.plans, "stu-1")
    assert list(got.questions) == [f"fact:{OBTAINED}"]
    assert got.questions[f"fact:{OBTAINED}"].origin == "impossible"
    inter = BOOKS[("pakistan_inter", 2)]
    draft = world.svc.plans.compile(contract(), inter)  # the compiler reads only the programmes
    assert f"which_is_right@fact:{OBTAINED}:shown" in {t.instance_key for t in draft.tasks}


@pytest.mark.req("R-21")
def test_a_vault_conflict_is_a_question(world):
    world.vault["stu-1"] = facts_of("stu-1", 1, **{"education__matric__marks_obtained": (900, "stated")})
    fact_questions.configure(conflicts=lambda ref: {"conflicts": [{"ref": "profile_issue:4", "key": OBTAINED}]})
    got = state.build(world.svc.plans, "stu-1")
    assert (got.questions[f"fact:{OBTAINED}"].origin, got.questions[f"fact:{OBTAINED}"].ref) == ("vault", "profile_issue:4")
    fact_questions.configure(conflicts=lambda ref: None)  # the host's part is off
    assert state.build(world.svc.plans, "stu-1").questions == {}


@pytest.mark.req("R-21")
def test_a_mismatch_finding_puts_those_documents_in_question(world):
    world.vault["stu-1"] = facts_of("stu-1", 1)
    store = DocumentStore(world.engine, TENANT)
    a = store.create("stu-1", "hssc_certificate", 1, "a.jpg", "image/jpeg", jpeg(1))
    b = store.create("stu-1", "ssc_certificate", 1, "b.jpg", "image/jpeg", jpeg(2))
    FindingStore(world.engine, TENANT).replace_open("stu-1", [{"kind": "mismatch", "field": "father_name",
                                                               "items": [(a, "Ahmed Khan"), (b, "Rashid Khan")]},
                                                              {"kind": "variant", "field": "full_name", "items": []}])
    got = state.build(world.svc.plans, "stu-1")
    assert sorted(got.questions) == ["document:hssc_certificate", "document:ssc_certificate"]
    assert all(q.origin == "documents" for q in got.questions.values())
    draft = world.svc.plans.compile(contract(), BOOKS[("pakistan_bs", 2)])
    merit = next(t for t in draft.tasks if t.instance_key == "merit_list@p1")
    assert merit.blocked_reason == "which_is_right:hssc_certificate"


# --- refresh --------------------------------------------------------------------------------------------------------

@pytest.fixture
def api(world, engine):
    app = FastAPI()
    app.include_router(build_router(lambda: world.svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    return TestClient(app)


def revisions(engine, plan_id) -> list[str]:
    with engine.connect() as conn:
        return [r.cause for r in conn.execute(select(models.plan_revisions).where(
            models.plan_revisions.c.plan_id == plan_id).order_by(models.plan_revisions.c.number))]


def test_document_confirm_refreshes_the_plan(api, world, engine):
    world.vault["stu-1"] = facts_of("stu-1", 1, **{INTER_MARKS: (800, "stated")})
    plan_id = world.svc.plans.start_plan(contract()).plan_id
    asked = "provide@document:hssc_certificate:shown"
    assert keys_of(engine, plan_id)[asked] == "waiting_student"
    agree(api)
    doc_id = api.post("/v1/os/documents", data={"doc_type": "hssc_certificate"},
                      files={"file": ("a.jpg", jpeg(), "image/jpeg")}, headers=as_student()).json()["id"]
    simulate_read(engine, doc_id, "hssc_certificate", HSSC)
    # read but not confirmed: it is still asked for
    assert keys_of(engine, plan_id)[asked] == "waiting_student"
    r = api.post(f"/v1/os/documents/{doc_id}/confirm", json=confirm_body("hssc_certificate", HSSC), headers=as_student())
    assert r.status_code == 200, r.text
    tasks = keys_of(engine, plan_id)
    assert asked not in tasks and [s for k, s in tasks.items() if k.startswith(asked + "#d")] == ["done"]
    assert revisions(engine, plan_id)[-1] == "document_changed"
    # deleting it asks again
    assert api.delete(f"/v1/os/documents/{doc_id}", headers=as_student()).status_code == 204
    assert keys_of(engine, plan_id)[asked] == "waiting_student"
    assert revisions(engine, plan_id)[-1] == "document_changed"


def test_refresh_does_nothing_while_the_gate_is_off(world, engine):
    plan_id = world.svc.plans.start_plan(contract()).plan_id  # v1
    assert refresh(world.svc, "stu-1", "document_changed") == 0
    world.vault["stu-1"] = facts_of("stu-1", 1)
    assert refresh(world.svc, "stu-1", "document_changed") == 0  # a v1 plan declares no needs
    assert len(revisions(engine, plan_id)) == 1


def test_refresh_never_raises(world, monkeypatch):
    world.vault["stu-1"] = facts_of("stu-1", 1)
    world.svc.plans.start_plan(contract())

    def boom(*a, **k):
        raise RuntimeError("secret value 123")

    monkeypatch.setattr(world.svc.plans, "recompile", boom)
    assert refresh(world.svc, "stu-1", "document_changed") == 0


def test_a_failing_adapter_never_turns_a_saved_document_change_into_an_error(api, world, engine, monkeypatch):
    """Confirm, resolve and delete answer as they do today when the host's adapter raises (no 500), and the T7
    proposal nudge still runs on confirm. The log names the error type only."""
    import logging

    world.vault["stu-1"] = facts_of("stu-1", 1, **{INTER_MARKS: (800, "stated")})
    world.svc.plans.start_plan(contract())
    agree(api)
    doc_id = api.post("/v1/os/documents", data={"doc_type": "hssc_certificate"},
                      files={"file": ("a.jpg", jpeg(), "image/jpeg")}, headers=as_student()).json()["id"]
    simulate_read(engine, doc_id, "hssc_certificate", HSSC)
    other = api.post("/v1/os/documents", data={"doc_type": "ssc_certificate"},
                     files={"file": ("b.jpg", jpeg(2), "image/jpeg")}, headers=as_student()).json()["id"]
    nudged = []
    monkeypatch.setattr(fact_proposals, "notify", lambda key: nudged.append(key))
    logged = []
    handler = logging.Handler()
    handler.emit = lambda record: logged.append(record.getMessage())
    logging.getLogger("app.os.requests.refresh").addHandler(handler)

    def boom(ref):
        raise RuntimeError("secret value 123")

    ports.configure(world.svc, student_facts=boom)  # from here on the host's adapter raises

    r = api.post(f"/v1/os/documents/{doc_id}/confirm", json=confirm_body("hssc_certificate", HSSC), headers=as_student())
    assert r.status_code == 200, r.text
    assert len(nudged) == 1  # the T7 nudge still ran after the failed refresh

    a, b = (DocumentStore(engine, TENANT).create("stu-1", t, 1, f"{t}.jpg", "image/jpeg", jpeg(n))
            for t, n in (("hssc_certificate", 7), ("ssc_certificate", 8)))
    FindingStore(engine, TENANT).replace_open("stu-1", [{"kind": "mismatch", "field": "father_name",
                                                        "items": [(a, "Ahmed Khan"), (b, "Rashid Khan")]}])
    [finding] = FindingStore(engine, TENANT).list_open("stu-1")
    r = api.post(f"/v1/os/documents/findings/{finding['id']}/resolve", json={"value": "Ahmed Khan"},
                 headers=as_student())
    assert r.status_code == 200 and r.json()["status"] == "resolved"

    assert api.delete(f"/v1/os/documents/{other}", headers=as_student()).status_code == 204
    assert len(logged) == 3 and all("RuntimeError" in m for m in logged)
    assert not [m for m in logged if "secret" in m or "123" in m]


def test_admin_upgrade_endpoint_moves_a_v1_plan_to_v2_when_the_gate_is_on(api, world, engine):
    plan_id = world.svc.plans.start_plan(contract()).plan_id  # the gate was off: v1
    admin = {"X-OS-Admin-Token": TOKEN}
    assert api.post(f"/v1/os/plans/{plan_id}/upgrade", headers=admin).status_code == 409  # gate off: nothing newer
    assert pin(engine, plan_id) == 1
    world.vault["stu-1"] = facts_of("stu-1", 1)  # now it is on
    r = api.post(f"/v1/os/plans/{plan_id}/upgrade", headers=admin)
    assert r.status_code == 200 and r.json()["revision"], r.text
    assert pin(engine, plan_id) == 2
    assert f"provide@fact:{INTER_MARKS}:stated" in keys_of(engine, plan_id)
    again = api.post(f"/v1/os/plans/{plan_id}/upgrade", headers=admin)
    assert again.status_code == 409 and "nothing newer" in again.json()["detail"]  # never again, never back
    world.vault.clear()  # the gate goes off: a v2 plan is not sent back to v1
    assert api.post(f"/v1/os/plans/{plan_id}/upgrade", headers=admin).status_code == 409
    assert pin(engine, plan_id) == 2
    assert api.post(f"/v1/os/plans/{plan_id}/upgrade").status_code in (401, 403)  # not without the admin token
