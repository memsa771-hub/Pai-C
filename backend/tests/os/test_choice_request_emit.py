"""P1-T6 Task 2: on a Counsellor plan an accepted choice change (and the builder's swap or remove) becomes a
choice_request, written in the same transaction as the proposal's new status `requested`; the contract is not touched
(R-07, rows 6.5 and 6.6). With the module or the host part off, today's paths run unchanged. Fictional data."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update

from app.os import models, ports
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.contracts.choice_request import ChoiceRequestV1
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.knowledge.programmes import PROGRAMME_SEED, ProgrammeStore, load_programme_seed
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.ports import choice_requests
from app.os.replan import choice_texts, events
from app.os.replan.apply import Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.ops import AddTask, CancelProgramme, SwapProgramme
from app.os.settings import load_settings

pytestmark = pytest.mark.req("R-07")

SAMPLES = Path(__file__).resolve().parents[2] / "app" / "os" / "contracts" / "samples"
FAKE = Path(__file__).parent / "playbooks"
P, O, PR, OV = models.plans, models.outbox, models.proposals, models.plan_overrides
STUDENT = "ws-sample-1"
ME = {"X-Test-Student": STUDENT}
FIRST, SECOND, THIRD = "tu-chemnitz-embedded-systems", "ovgu-eeit", "btu-artificial-intelligence"
WHY = "The programme did not admit you: its remaining steps are removed."


def decision(**over) -> dict:
    return {**json.loads((SAMPLES / "v2" / "decision_chosen_de.json").read_text()), **over}


class World:
    def __init__(self, client, svc, plan_id, hooks):
        self.client, self.svc, self.plan_id, self.hooks = client, svc, plan_id, hooks
        self.engine = svc.engine
        self.r = Replanner(svc.engine, svc.plans, load_replan_configs(), Outbox(svc.engine, "pai"))

    def propose(self, *ops, dedupe="k1") -> int:
        with self.engine.begin() as conn:
            eid = events.record(conn, "pai", self.plan_id, "admission_rejected", {"programme_ref": FIRST}, dedupe)
        d = self.r.decide(self.plan_id, [eid], "rules", list(ops))
        assert d.status == "pending"
        return d.proposal_id

    def plan(self):
        with self.engine.connect() as conn:
            return conn.execute(select(P).where(P.c.id == self.plan_id)).one()

    def proposal(self, pid: int):
        with self.engine.connect() as conn:
            return conn.execute(select(PR).where(PR.c.id == pid)).one()

    def requests(self) -> list:
        with self.engine.connect() as conn:
            return conn.execute(select(O).where(O.c.template == "choice_request").order_by(O.c.id)).all()

    def overrides(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(OV)).scalar()


def make_world(engine, os_db, *, module=True, enabled=True, source="counsellor"):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE) | load_playbook_dir(),
                        today=lambda: date(2027, 2, 1))
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    load_programme_seed(PROGRAMME_SEED, ProgrammeStore(engine, "pai"))
    with engine.begin() as conn:  # the swap-in programme's facts are confirmed, so the checks keep a swap to it
        conn.execute(update(models.knowledge_facts).where(models.knowledge_facts.c.ref == THIRD)
                     .values(status="confirmed", quote="fictional quote", url="https://example.org/f"))
    if module:
        with engine.begin() as conn:
            conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    if source == "counsellor":
        store = IntakeStore(engine, "pai")
        store.add(decision(), "0" * 64)
        done = process(svc, store.get("d-sample-1"))
        store.finish(store.get("d-sample-1").id, done.status, None, done.plan_id)  # as the intake workflow does
        plan_id = done.plan_id
    else:
        from tests.os.test_golden import TEST_STUDENT
        plan_id = svc.plans.start_plan(TEST_STUDENT.model_copy(update={"student_ref": STUDENT})).plan_id
    hooks: list[str] = []
    ports.configure(svc, choice_enabled=(lambda: True) if enabled else None, on_choice_request=hooks.append)
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    return World(TestClient(app), svc, plan_id, hooks)


@pytest.fixture
def world(engine, clean, os_db):
    w = make_world(engine, os_db)
    try:
        yield w
    finally:
        ports.configure(None)


def accept(w, pid):
    return w.client.post(f"/v1/os/proposals/{pid}/accept", headers=ME)


def test_accept_on_counsellor_plan_writes_choice_request_not_contract(world):
    before = world.plan().contract_sha256
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    r = accept(world, pid)
    assert r.status_code == 200 and r.json()["status"] == "requested"
    assert world.plan().contract_sha256 == before
    p = world.proposal(pid)
    assert p.status == "requested" and p.base_decision_version == 1
    [row] = world.requests()
    assert row.idempotency_key == f"choice_request:{pid}" and row.channel == "counsellor"
    req = ChoiceRequestV1.model_validate(row.payload)
    assert req.based_on_version == p.base_decision_version and req.proposal_id == pid
    assert req.journey_id == "j-sample-1" and req.student_ref == STUDENT
    assert [(c.programme_ref, c.rank) for c in req.programmes] == [(FIRST, 1), (THIRD, 2)]
    assert world.hooks == [f"choice_request:{pid}"]


def test_cancel_programme_request_drops_and_reranks(world):
    pid = world.propose(CancelProgramme(programme_ref=FIRST, reason=WHY))
    assert accept(world, pid).json()["status"] == "requested"
    [row] = world.requests()
    req = ChoiceRequestV1.model_validate(row.payload)
    assert [(c.programme_ref, c.rank) for c in req.programmes] == [(SECOND, 1)]
    assert world.overrides() == 0


def test_request_and_status_share_one_transaction(world, monkeypatch):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))

    def boom(*a, **k):
        raise RuntimeError("emit killed")

    monkeypatch.setattr(choice_requests, "emit", boom)
    with pytest.raises(RuntimeError):
        world.r.accept(STUDENT, pid)
    assert world.proposal(pid).status == "pending" and world.requests() == []


def test_accept_twice_is_stale(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    assert accept(world, pid).status_code == 200
    assert accept(world, pid).status_code == 409
    assert len(world.requests()) == 1


def test_mixed_proposal_applies_other_ops_now(world):
    # an add_task of a step the plan already has would be small; take any template the playbook offers and a swap
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY),
                        AddTask(template_key=_addable(world), programme_ref=None, reason=WHY))
    body = accept(world, pid).json()
    assert body["status"] == "requested" and body["revision"] is not None and body["revision"] > 1
    assert world.proposal(pid).revision == body["revision"]
    assert len(world.requests()) == 1
    assert [c["programme_ref"] for c in world.plan().contract["programmes"]] == [FIRST, SECOND]


def _addable(world) -> str:
    """A step template the plan does not have yet, found by trying: the compiler decides."""
    book = world.svc.plans._pinned(world.plan_id)
    have = {t.template_key for t in book.tasks}
    for t in book.tasks:
        cand = t.template_key
        ops = [AddTask(template_key=cand, programme_ref=None, reason=WHY)]
        try:
            kept, _ = world.r.check(world.plan_id, ops)
        except Exception:
            continue
        if kept:
            return cand
    raise AssertionError("no addable template")


def test_zero_places_is_refused_with_support_case(world):
    pid = world.propose(CancelProgramme(programme_ref=FIRST, reason=WHY))
    # the contract is cut to one place directly, so that dropping it would leave none
    with world.engine.begin() as conn:
        c = dict(world.plan().contract)
        c["programmes"] = [{"programme_ref": FIRST, "rank": 1}]
        conn.execute(update(P).where(P.c.id == world.plan_id).values(contract=c))
    ok = world.r._request_choice(world.r.proposals.get(pid), [CancelProgramme(programme_ref=FIRST, reason=WHY)])
    assert ok is None
    assert world.proposal(pid).status == "refused" and world.requests() == []
    with world.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.support_cases)).scalar() == 1


def swap_body(out, in_):
    return {"out": out, "in": in_}


def test_builder_swap_on_counsellor_plan_is_a_request(world):
    before = world.plan().contract_sha256
    r = world.client.post(f"/v1/os/plans/{world.plan_id}/swap", json=swap_body(SECOND, THIRD), headers=ME)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["state"] == "requested"
    p = world.proposal(body["proposal_id"])
    assert (p.source, p.status, p.big) == ("student", "requested", True)
    assert world.plan().contract_sha256 == before
    [row] = world.requests()
    assert row.idempotency_key == f"choice_request:{p.id}"
    assert world.hooks == [f"choice_request:{p.id}"]


def test_builder_remove_on_counsellor_plan_is_a_request(world):
    r = world.client.delete(f"/v1/os/plans/{world.plan_id}/programmes/{SECOND}", headers=ME)
    assert r.status_code == 202 and r.json()["state"] == "requested"
    req = ChoiceRequestV1.model_validate(world.requests()[0].payload)
    assert [(c.programme_ref, c.rank) for c in req.programmes] == [(FIRST, 1)]


def test_builder_remove_last_place_still_refused(world):
    with world.engine.begin() as conn:
        c = dict(world.plan().contract)
        c["programmes"] = [{"programme_ref": FIRST, "rank": 1}]
        conn.execute(update(P).where(P.c.id == world.plan_id).values(contract=c))
    r = world.client.delete(f"/v1/os/plans/{world.plan_id}/programmes/{FIRST}", headers=ME)
    assert r.status_code == 409 and world.requests() == []


def test_notify_called_after_commit_and_errors_swallowed(world):
    def bad(key):
        raise RuntimeError("secret detail")

    ports.configure(world.svc, choice_enabled=lambda: True, on_choice_request=bad)
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    assert accept(world, pid).status_code == 200
    assert world.proposal(pid).status == "requested" and len(world.requests()) == 1


def test_enabled_that_raises_reads_as_off(world):
    def bad():
        raise RuntimeError("x")

    choice_requests.configure(bad, None)
    assert choice_requests.enabled() is False


def test_status_note_hidden_until_approved(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    accept(world, pid)
    [p] = world.client.get("/v1/os/inbox", headers=ME).json()["proposals"]
    assert p["id"] == pid and p["status"] == "requested" and p["status_note"] is None
    assert p["request_outcome"] is None and p["reasons"] == [WHY]
    on = replace(world.svc.settings, rehearsal=True)
    assert choice_texts.note("requested", on) == yaml.safe_load(choice_texts.PATH.read_text())["requested"]
    assert yaml.safe_load(choice_texts.PATH.read_text())["approved"] is False
    assert choice_texts.note("requested", world.svc.settings) is None


def test_expired_request_with_outcome_is_listed(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    accept(world, pid)
    assert world.r.proposals.expire_requested(pid, "stale")
    [p] = world.client.get("/v1/os/inbox", headers=ME).json()["proposals"]
    assert (p["status"], p["request_outcome"]) == ("expired", "stale")


# ---- flags off: today's behaviour --------------------------------------------------------------------------------


def test_unconfigured_port_keeps_direct_edit(engine, clean, os_db):
    w = make_world(engine, os_db, enabled=False)
    try:
        pid = w.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
        r = accept(w, pid)
        assert r.status_code == 200 and r.json()["status"] == "accepted"
        assert w.proposal(pid).status == "accepted" and w.requests() == []
        assert [c["programme_ref"] for c in w.plan().contract["programmes"]] == [FIRST, THIRD]
    finally:
        ports.configure(None)


def test_module_off_no_choice_request_rows(engine, clean, os_db):
    w = make_world(engine, os_db, module=False)
    try:
        pid = w.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
        assert accept(w, pid).json()["status"] == "accepted"
        r = w.client.delete(f"/v1/os/plans/{w.plan_id}/programmes/{THIRD}", headers=ME)
        assert r.status_code == 200 and w.requests() == []
    finally:
        ports.configure(None)


def test_self_serve_plan_accept_unchanged(engine, clean, os_db):
    w = make_world(engine, os_db, source="self")
    try:
        with w.engine.begin() as conn:
            eid = events.record(conn, "pai", w.plan_id, "admission_rejected", {"programme_ref": FIRST}, "k1")
        pid = w.r.decide(w.plan_id, [eid], "rules", [CancelProgramme(programme_ref=FIRST, reason=WHY)]).proposal_id
        r = accept(w, pid)
        assert r.status_code == 200 and r.json()["status"] == "accepted"
        assert w.proposal(pid).base_decision_version is None and w.requests() == []
    finally:
        ports.configure(None)


def test_ports_configure_sets_and_defaults_the_gate(world):
    assert choice_requests.enabled() is True
    ports.configure(world.svc)  # no gate given: today's behaviour
    assert choice_requests.enabled() is False
    choice_requests.notify("choice_request:1")  # no hook: nothing happens
