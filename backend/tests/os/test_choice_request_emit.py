"""P1-T6 Task 2: on a Counsellor plan an accepted choice change (and the builder's swap or remove) becomes a
choice_request, written in the same transaction as the proposal's new status `requested`; the contract is not touched
(R-07, rows 6.5 and 6.6). With the module or the host part off, today's paths run unchanged. Fictional data."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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


_TEXTS = choice_texts._load(choice_texts.PATH)[1]


def _unapproved(path=choice_texts.PATH):
    """The texts as they would load from a file still stored `approved: false`."""
    return False, _TEXTS


def test_status_note_hidden_until_approved(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    accept(world, pid)
    with patch.object(choice_texts, "_load", _unapproved):
        [p] = world.client.get("/v1/os/inbox", headers=ME).json()["proposals"]
        assert p["id"] == pid and p["status"] == "requested" and "status_note" not in p
        assert "request_outcome" not in p and p["reasons"] == [WHY]
        on = replace(world.svc.settings, rehearsal=True)
        assert choice_texts.note("requested", on) == yaml.safe_load(choice_texts.PATH.read_text())["requested"]
        assert choice_texts.note("requested", world.svc.settings) is None
    assert choice_texts.PATH.parent.name == "texts"


def test_texts_are_approved_by_the_owner_and_shown(world):
    assert yaml.safe_load(choice_texts.PATH.read_text())["approved"] is True  # approved in chat, 2026-11-06
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    accept(world, pid)
    [p] = world.client.get("/v1/os/inbox", headers=ME).json()["proposals"]
    assert p["status_note"] == yaml.safe_load(choice_texts.PATH.read_text())["requested"]


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


# ---- fix round 1 --------------------------------------------------------------------------------------------------


def student_proposals_count(w) -> int:
    with w.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(PR).where(PR.c.source == "student")).scalar()


def test_builder_double_call_is_one_request(world):
    first = world.client.post(f"/v1/os/plans/{world.plan_id}/swap", json=swap_body(SECOND, THIRD), headers=ME)
    second = world.client.post(f"/v1/os/plans/{world.plan_id}/swap", json=swap_body(SECOND, THIRD), headers=ME)
    assert first.status_code == 202
    assert second.status_code == 409 and second.json()["detail"] == "request_open"
    assert student_proposals_count(world) == 1 and len(world.requests()) == 1


def test_builder_daily_limit_counts_requests(world):
    for n in range(3):  # each is answered (the Counsellor's answer expires it), so the next may be asked
        r = world.client.post(f"/v1/os/plans/{world.plan_id}/swap", json=swap_body(SECOND, THIRD), headers=ME)
        assert r.status_code == 202, (n, r.text)
        assert world.r.proposals.expire_requested(r.json()["proposal_id"], "stale")
    fourth = world.client.post(f"/v1/os/plans/{world.plan_id}/swap", json=swap_body(SECOND, THIRD), headers=ME)
    assert fourth.status_code == 409 and "a day" in fourth.json()["detail"]
    assert student_proposals_count(world) == 3


def test_expire_due_never_overwrites_requested(world, monkeypatch):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    with world.engine.begin() as conn:
        conn.execute(update(PR).where(PR.c.id == pid).values(expires_at=date(2020, 1, 1)))
    real = world.r.proposals.expire_if_pending

    def race(proposal_id):  # the student's accept lands between the select and the update
        with world.engine.begin() as conn:  # (the student's answer is on time: it found a live suggestion)
            conn.execute(update(PR).where(PR.c.id == proposal_id).values(
                expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        assert accept(world, proposal_id).json()["status"] == "requested"
        return real(proposal_id)

    monkeypatch.setattr(world.r.proposals, "expire_if_pending", race)
    assert world.r.expire_due(datetime.now(timezone.utc)) == 0
    assert world.proposal(pid).status == "requested"


def test_expire_due_still_expires_pending(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    with world.engine.begin() as conn:
        conn.execute(update(PR).where(PR.c.id == pid).values(expires_at=date(2020, 1, 1)))
    assert world.r.expire_due(datetime.now(timezone.utc)) == 1
    assert world.proposal(pid).status == "expired"


def test_flags_off_proposal_body_has_todays_keys(engine, clean, os_db):
    w = make_world(engine, os_db, enabled=False)
    try:
        w.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
        [p] = w.client.get("/v1/os/inbox", headers=ME).json()["proposals"]
        assert set(p) == {"id", "plan_id", "status", "big", "source", "ops", "reasons", "revision", "expires_at",
                          "created_at", "answered_at"}
        accept(w, p["id"])
        [c] = w.client.get(f"/v1/os/plans/{w.plan_id}/changes", headers=ME).json()["changes"]
        assert "status_note" not in c and "request_outcome" not in c
    finally:
        ports.configure(None)


def test_bad_places_refuse_cleanly(world, monkeypatch):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    from pydantic import ValidationError

    def bad(*a, **k):
        ChoiceRequestV1.model_validate({})  # raises ValidationError

    monkeypatch.setattr(choice_requests, "emit", bad)
    r = accept(world, pid)
    assert r.status_code == 409
    assert world.proposal(pid).status == "pending" and world.requests() == []
    assert ValidationError  # noqa


def test_too_many_places_refused_before_anything_applies(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    with world.engine.begin() as conn:  # a contract of six places cannot go in a request (at most five)
        c = dict(world.plan().contract)
        c["programmes"] = [{"programme_ref": f"x{i}", "rank": i} for i in range(1, 7)]
        c["programmes"][0]["programme_ref"] = SECOND
        conn.execute(update(P).where(P.c.id == world.plan_id).values(contract=c))
    r = accept(world, pid)
    assert r.status_code == 409 and world.proposal(pid).status == "pending" and world.requests() == []


def test_emit_failure_after_other_ops_then_retry_opens_no_second_case(world, monkeypatch):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY),
                        AddTask(template_key=_addable(world), programme_ref=None, reason=WHY))
    real = choice_requests.emit
    monkeypatch.setattr(choice_requests, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        world.r.accept(STUDENT, pid)
    assert world.proposal(pid).status == "pending"
    monkeypatch.setattr(choice_requests, "emit", real)
    assert accept(world, pid).json()["status"] == "requested"
    with world.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.support_cases)).scalar() == 0
        causes = conn.execute(select(models.plan_revisions.c.cause).where(
            models.plan_revisions.c.cause == f"replan:{pid}")).scalars().all()
    assert len(causes) == 1 and len(world.requests()) == 1


def test_places_exclude_programmes_cancelled_by_override(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    world.r.overrides.add(world.plan_id, pid, "cancel_programme", FIRST, {})
    assert accept(world, pid).json()["status"] == "requested"
    req = ChoiceRequestV1.model_validate(world.requests()[0].payload)
    assert [(c.programme_ref, c.rank) for c in req.programmes] == [(THIRD, 1)]


def test_zero_places_through_the_route(world, monkeypatch):
    pid = world.propose(CancelProgramme(programme_ref=FIRST, reason=WHY))
    with world.engine.begin() as conn:
        c = dict(world.plan().contract)
        c["programmes"] = [{"programme_ref": FIRST, "rank": 1}]
        conn.execute(update(P).where(P.c.id == world.plan_id).values(contract=c))
    # The check stub makes the zero-places branch reachable: the real checks refuse dropping the last place earlier.
    # The branch itself is a defensive R-22 guard (dropping every place is an escalation, never a choice request).
    monkeypatch.setattr(Replanner, "check", lambda self, plan_id, ops: (ops, []))  # the plan checks are not the subject
    r = accept(world, pid)
    assert r.status_code == 200 and r.json()["status"] == "refused"
    assert world.requests() == [] and world.proposal(pid).status == "refused"
    assert accept(world, pid).status_code == 409  # no second case
    with world.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.support_cases)).scalar() == 1


def test_builder_places_exclude_programmes_cancelled_by_override(world):
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    world.r.overrides.add(world.plan_id, pid, "cancel_programme", FIRST, {})  # an earlier proposal dropped FIRST
    r = world.client.post(f"/v1/os/plans/{world.plan_id}/swap", json=swap_body(SECOND, THIRD), headers=ME)
    assert r.status_code == 202, r.text
    req = ChoiceRequestV1.model_validate(world.requests()[0].payload)
    assert [(c.programme_ref, c.rank) for c in req.programmes] == [(THIRD, 1)]


def test_open_builder_request_makes_a_pending_accept_409(world):
    """Carried from the Task 2 review: the accept path refuses a choice change while the plan already has a request
    with the Counsellor, as the builder does (`request_open`), and writes no second outbox row."""
    pid = world.propose(SwapProgramme(out_ref=SECOND, in_ref=THIRD, reason=WHY))
    first = world.client.delete(f"/v1/os/plans/{world.plan_id}/programmes/{SECOND}", headers=ME)
    assert first.status_code == 202
    r = accept(world, pid)
    assert r.status_code == 409 and "request_open" in r.text
    assert world.proposal(pid).status == "pending" and len(world.requests()) == 1


def test_non_choice_proposal_still_accepts_while_a_request_is_open(world):
    """The request_open guard is for choice-changing accepts only: a proposal with no swap or removal still applies."""
    template = _addable(world)
    first = world.propose(CancelProgramme(programme_ref=FIRST, reason=WHY))
    assert accept(world, first).json()["status"] == "requested"
    store = world.r.proposals
    pid = store.create(world.plan_id, [], "rules", [AddTask(template_key=template, programme_ref=None,
                                                            reason=WHY).model_dump(mode="json")], [], True, None)
    r = accept(world, pid)
    assert r.status_code == 200 and r.json()["status"] == "accepted", r.text
    assert len(world.requests()) == 1 and world.proposal(first).status == "requested"
