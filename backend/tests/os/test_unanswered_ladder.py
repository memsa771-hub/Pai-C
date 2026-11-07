"""P1-T8 Task 5 (R-22): a request the student leaves unanswered goes up the ladder, in order, and never silently.

1. reminders on the cadence, 2. the deadline at risk nudges the request first, 3. a proposal to swap or drop the places
that wait for it, 4. a support case for a person. Real services, kernel, reminders and the os.replan workflow (DBOS in
this process) on Postgres; the Vault answers from a dict. Fictional routes, programmes and students. The student's
"close match" list is fixed by the test: how matches are found has its own tests."""

import types as pytypes
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import insert, select

from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.api import make_services
from app.os.contracts.route_contract import RouteContract
from app.os.knowledge import Fact, SqlKnowledge
from app.os.outbox import Outbox
from app.os.playbooks import Playbook
from app.os.replan import events
from app.os.replan.apply import ProposalStale, Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.run import generation, register_replan, replan_workflow_id, run_replan_job
from app.os.replan.store import SupportStore
from app.os.requests import texts
from app.os.settings import load_settings
from app.os.workers import deadline_engine, run_reminders
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_api import TEST_TERMS, TOKEN
from tests.os.test_api_documents import FakeClient
from tests.os.test_compile_needs import BOOKS
from tests.os.test_needs_gate import facts_of

pytestmark = pytest.mark.req("R-22")

TENANT, STUDENT = "pai", "stu-1"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
NEEDS = Path(__file__).parent / "playbooks" / "needs"
IELTS = "test.ielts.score"
ENGLISH_ASK = f"provide@fact:{IELTS}:shown"
MARKS_ASK = "provide@fact:education.intermediate.marks_obtained:stated"
DUE_PAST = datetime(2027, 7, 20, 8, tzinfo=timezone.utc)  # after every date of the test routes
T, EV, O = models.tasks, models.events, models.outbox


def ireland(*, needs_on: str) -> Playbook:
    """The fake Ireland v2 playbook with the needs on one step only. The English step is dated like `apply`, so its
    request has a due date (the shipped fake file leaves it undated). `needs_on` is `english_proof` or `visa`."""
    data = yaml.safe_load((NEEDS / "ireland_master.v2.yaml").read_text(encoding="utf-8"))
    for task in data["tasks"]:
        task.pop("needs", None)
        if task["template_key"] == "english_proof":
            task["anchor"] = {"fact": "deadline_close"}
        if task["template_key"] == needs_on:
            task["needs"] = [{"fact": IELTS, "evidence": "shown"}]
    data["asks"] = {IELTS: data["asks"][IELTS]}
    if needs_on == "visa":  # a route-level step that needs it; the visa is dated back from the deadline too
        for task in data["tasks"]:
            if task["template_key"] == "visa":
                task["depends_on"] = [{"key": "apply"}]
    return Playbook.model_validate(data)


def contract(student=STUDENT, level="master", refs=("ie-p1", "ie-p2", "ie-p3"), source="counsellor") -> RouteContract:
    dest, origin = ("IE", "PK") if level == "master" else ("PK", "PK")
    return RouteContract.model_validate({
        "contract_version": "1", "source": source,
        "external_ref": f"j-1:{dest}:{level}" if source == "counsellor" else f"self:{student}",
        "student_ref": student, "origin_country": origin, "destination_country": dest, "level": level,
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


def fact(value) -> Fact:
    return Fact(value, "q", "https://uni.example/x", CHECKED, 2027, "confirmed")


class Box:
    today = date(2027, 3, 1)
    now = datetime(2027, 3, 1, 8, tzinfo=timezone.utc)


def build(engine, os_db, monkeypatch, books, seed, suggestions=None):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true", "OS_ADMIN_TOKEN": TOKEN,
                              "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    box = Box()
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: box.today,
                        dbos_client=lambda: FakeClient(), terms_dir=TEST_TERMS)
    kb = SqlKnowledge(engine, TENANT)
    seed(kb)
    vault = {STUDENT: facts_of(STUDENT, 1)}
    hooks: list[str] = []
    ports.configure(svc, student_facts=lambda ref: vault.get(ref), choice_enabled=lambda: True,
                    on_choice_request=hooks.append)
    manifest.set_enabled(engine, TENANT, True)
    replanner = Replanner(engine, svc.plans, load_replan_configs(), Outbox(engine, TENANT), clock=lambda: box.now,
                          escalations=svc.escalations)
    matches = suggestions or {}
    monkeypatch.setattr(Replanner, "_suggestions", lambda self, contract, book, ref: list(matches.get(ref, [])))
    return pytypes.SimpleNamespace(svc=svc, engine=engine, kb=kb, vault=vault, box=box, replanner=replanner,
                                   settings=settings, hooks=hooks, os_db=os_db)


def seed_ireland(kb):
    for ref in ("ie-p1", "ie-p2", "ie-p3", "ie-p4"):
        kb.upsert("programme", ref, "deadline_close", fact({"date": "2027-07-15"}), "manual")
    for ref in ("ie-p1", "ie-p2"):
        kb.upsert("programme", ref, "english_requirement", fact({"ielts": 6.5}), "manual")
    for ref in ("ie-p3", "ie-p4"):
        kb.upsert("programme", ref, "english_requirement", fact(False), "manual")  # no English score asked here


def seed_inter(kb):
    for ref in ("pk-p1", "pk-p2"):
        kb.upsert("programme", ref, "merit_list_date", fact({"date": "2027-08-15"}), "manual")


@pytest.fixture
def world(engine, clean, os_db, monkeypatch):
    """The fake Ireland route; the English score is asked of ie-p1 and ie-p2 only; ie-p4 is the close match of ie-p1."""
    books = {**BOOKS, ("ireland_master", 2): ireland(needs_on="english_proof")}
    w = build(engine, os_db, monkeypatch, books, seed_ireland, {"ie-p1": ["ie-p4"], "ie-p2": []})
    try:
        yield w
    finally:
        ports.configure(None)


@pytest.fixture
def route_world(engine, clean, os_db, monkeypatch):
    """The fake bachelor route: its entry test is a route-level step that needs the intermediate marks."""
    w = build(engine, os_db, monkeypatch, BOOKS, seed_inter)
    try:
        yield w
    finally:
        ports.configure(None)


@pytest.fixture
def live(world):
    """The os.replan workflow running in this process (DBOS), as the worker runs it."""
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(world.os_db)
    DBOS(config=dbos_config(world.settings, "test-w0"))
    register_workflow(world.engine, world.settings, default_registry(), world.svc.kernel)
    register_replan(world.engine, world.settings, world.replanner, None)
    launch()
    world.client = DBOSClient(system_database_url=world.os_db, dbos_system_schema=TEST_DBOS_SCHEMA,
                              application_name=APP_NAME)
    try:
        yield world
    finally:
        world.client.destroy()
        DBOS.destroy(destroy_registry=True)


@pytest.fixture
def route_live(route_world):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    w = route_world
    reset_dbos_schema(w.os_db)
    DBOS(config=dbos_config(w.settings, "test-w0"))
    register_workflow(w.engine, w.settings, default_registry(), w.svc.kernel)
    register_replan(w.engine, w.settings, w.replanner, None)
    launch()
    w.client = DBOSClient(system_database_url=w.os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    try:
        yield w
    finally:
        w.client.destroy()
        DBOS.destroy(destroy_registry=True)


# --- helpers ------------------------------------------------------------------------------------------------------

def start(w, **kw) -> int:
    c = contract(**kw)
    plan_id = w.svc.plans.start_plan(c).plan_id
    if c.source == "counsellor":  # the decision the plan was made from, so a choice change can name its version
        with w.engine.begin() as conn:
            conn.execute(insert(models.counsellor_intake).values(
                tenant_id=TENANT, decision_id=f"d-{plan_id}", student_ref=c.student_ref, journey_id="j-1", export={},
                export_sha256="0" * 64, chosen_at="2027-01-10T09:00:00+05:00", status="planned", plan_id=plan_id,
                decision_version=1))
    return plan_id


def task(w, plan_id, key):
    with w.engine.connect() as conn:
        return conn.execute(select(T).where(T.c.plan_id == plan_id, T.c.instance_key == key)).one()


def keys_of(w, plan_id) -> dict[str, str]:
    with w.engine.connect() as conn:
        return {t.instance_key: t.state for t in conn.execute(select(T).where(T.c.plan_id == plan_id))}


def sweep(w, now: datetime) -> dict[int, dict]:
    """One hourly reminders run and one replan job at `now`, then the workflows the job queued run to the end. Returns
    each one's result by event id."""
    w.box.now = now
    run_reminders(w.engine, Outbox(w.engine, TENANT), now, TENANT)
    queued = [(e.plan_id, e.id) for e in events.pending(w.engine, TENANT)
              if not w.replanner.plans.kernel.changes_paused(e.plan_id)]
    assert run_replan_job(w.replanner, w.client, now) == len(queued)
    return {i: w.client.retrieve_workflow(replan_workflow_id(TENANT, p, i, generation(w.engine, TENANT, p))).get_result()
            for p, i in queued}


def pending_proposals(w, plan_id):
    return [p for p in w.replanner.proposals.for_plan(plan_id) if p.status == "pending"]


def event_of(w, plan_id, type_, key=None):
    with w.engine.connect() as conn:
        found = [e for e in conn.execute(select(EV).where(EV.c.plan_id == plan_id, EV.c.type == type_).order_by(EV.c.id))
                 if key is None or e.payload.get("instance_key") == key]
    assert found, f"no {type_} event for {key}"
    return found[0]


def reminder_keys(w, task_id) -> list[str]:
    with w.engine.connect() as conn:
        return [k for k in conn.execute(select(O.c.idempotency_key).where(
            O.c.idempotency_key.like(f"reminder:{task_id}:%")).order_by(O.c.id)).scalars()]


# --- rung 1: reminders --------------------------------------------------------------------------------------------

def test_request_step_gets_reminders_on_the_cadence(world):
    plan_id = start(world, source="self_serve")
    step = task(world, plan_id, ENGLISH_ASK)
    assert step.state == "waiting_student" and step.due_at is not None
    box = Outbox(world.engine, TENANT)

    def stage(first: date, days: int) -> list[str]:
        """Runs the day's recompile and reminders, twice a day, for `days` days; returns the slots that were new."""
        before = len(reminder_keys(world, step.id))
        for n in range(days):
            world.box.today = first + timedelta(days=n)
            deadline_engine.run(world.svc.plans, world.engine)
            for hour in (8, 20):
                now = datetime.combine(world.box.today, datetime.min.time(), timezone.utc) + timedelta(hours=hour)
                run_reminders(world.engine, box, now, TENANT)
        return [k.split(":", 2)[2] for k in reminder_keys(world, step.id)[before:]]

    due = step.due_at.date()
    weekly = stage(due - timedelta(days=60), 15)  # far from the date: one a week
    assert len(weekly) == len({s for s in weekly}) and 2 <= len(weekly) <= 3 and {s.split(":")[0] for s in weekly} == {"w"}
    every3 = stage(due - timedelta(days=13), 6)  # a week or two out: every third day
    assert 2 <= len(every3) <= 3 and {s.split(":")[0] for s in every3} == {"d3"}
    daily = stage(due - timedelta(days=5), 3)  # under a week: one a day, two runs a day add nothing
    assert len(daily) == 3 and {s.split(":")[0] for s in daily} == {"d"}
    assert len(set(daily)) == 3


def test_overdue_request_step_records_document_missing_once(world):
    plan_id = start(world, source="self_serve")
    step = task(world, plan_id, ENGLISH_ASK)
    box = Outbox(world.engine, TENANT)
    run_reminders(world.engine, box, step.due_at - timedelta(days=2), TENANT)
    with world.engine.connect() as conn:
        assert conn.execute(select(EV).where(EV.c.type == "document_missing")).first() is None  # not late yet
    run_reminders(world.engine, box, DUE_PAST, TENANT)
    run_reminders(world.engine, box, DUE_PAST + timedelta(days=1), TENANT)
    with world.engine.connect() as conn:
        found = conn.execute(select(EV).where(EV.c.type == "document_missing", EV.c.plan_id == plan_id)).all()
    assert [e.payload["instance_key"] for e in found] == [ENGLISH_ASK]  # one event for the step and its date


def test_overdue_which_is_right_enters_the_ladder(world, monkeypatch):
    from app.os.requests import state
    from app.os.requests.state import QuestionRef, StudentState

    plan_id = start(world, source="self_serve")
    # the Vault doubts the English score: the step that asks for it becomes a question
    asked = StudentState(questions={f"fact:{IELTS}": QuestionRef("vault", "profile_issue:1")})
    monkeypatch.setattr(state, "build", lambda svc, student: asked)
    assert world.svc.plans.recompile(plan_id, "student_fact_changed") is not None
    doubt = f"which_is_right@fact:{IELTS}:shown"
    step = task(world, plan_id, doubt)
    assert (step.state, step.inbox_kind) == ("waiting_student", "choose") and step.due_at is not None
    run_reminders(world.engine, Outbox(world.engine, TENANT), DUE_PAST, TENANT)
    assert event_of(world, plan_id, "document_missing", doubt).task_id == step.id


# --- rung 2: the deadline at risk ---------------------------------------------------------------------------------

def test_blocked_step_at_risk_nudges_the_request_first(live):
    plan_id = start(live)  # a Counsellor plan, so the Counsellor is told too
    live.box.today = date(2027, 7, 14)  # a day before the deadline: the request is already late
    deadline_engine.run(live.svc.plans, live.engine)
    risky = event_of(live, plan_id, "deadline_at_risk", "english_proof@ie-p1")  # the step that waits for the score
    sweep(live, datetime(2027, 7, 14, 9, tzinfo=timezone.utc))
    proposal = live.replanner.proposals.for_event(risky.id)
    assert proposal.status == "applied" and not proposal.big
    assert [(o["op"], o["instance_key"]) for o in proposal.ops] == [("reprioritise", ENGLISH_ASK),
                                                                    ("request_from_student", ENGLISH_ASK)]
    with live.engine.connect() as conn:
        told = [r.payload for r in conn.execute(select(O).where(O.c.template == "os_event"))]
        nudged = [r.payload for r in conn.execute(select(O).where(O.c.template == "replan_request"))]
    assert any(p["kind"] == "deadline_at_risk" and p["plan_id"] == plan_id for p in told)
    asked = {p["instance_key"] for p in nudged}
    assert ENGLISH_ASK in asked and "english_proof@ie-p1" not in asked  # the student is asked for the score, not for the step


# --- rung 3: a proposal to swap or drop ---------------------------------------------------------------------------

def test_overdue_request_on_some_places_proposes_swap_or_drop(live):
    plan_id = start(live)
    before = live.svc.plans._contract(plan_id)[1]
    results = sweep(live, DUE_PAST)
    missing = event_of(live, plan_id, "document_missing", ENGLISH_ASK)
    assert results[missing.id]["status"] == "pending"
    (proposal,) = pending_proposals(live, plan_id)
    assert proposal.big and [(o["op"], o.get("out_ref") or o["programme_ref"]) for o in proposal.ops] == [
        ("swap_programme", "ie-p1"), ("cancel_programme", "ie-p2")]  # ie-p3 asks nothing of the student
    swap, drop = proposal.ops
    assert swap["in_ref"] == "ie-p4" and swap["reason"] == texts.text("unanswered_swap")
    assert drop["reason"] == texts.text("unanswered_drop")
    assert proposal.event_ids == [missing.id]
    assert SupportStore(live.engine, TENANT).for_event(missing.id) is None  # a person is called only after the proposal
    assert live.svc.plans._contract(plan_id)[1] == before  # nothing changes until the student accepts


def test_the_same_places_are_not_proposed_twice(live):
    plan_id = start(live)
    sweep(live, DUE_PAST)
    other = live.replanner.proposals.for_plan(plan_id)
    assert len(other) == 1
    assert live.replanner.held(plan_id) == ("ie-p1", "ie-p2")


def test_ladder_never_leaves_fewer_than_min_programmes(live):
    plan_id = start(live, refs=("ie-p1", "ie-p2"))  # both places ask for the English score
    sweep(live, DUE_PAST)
    assert pending_proposals(live, plan_id) == []  # no removal is offered: it would leave nothing
    case = SupportStore(live.engine, TENANT).for_event(event_of(live, plan_id, "document_missing", ENGLISH_ASK).id)
    assert case is not None and case.reason == texts.text("unanswered_all")


def test_counsellor_plan_drop_becomes_a_choice_request(live):
    plan_id = start(live)
    sweep(live, DUE_PAST)
    (proposal,) = pending_proposals(live, plan_id)
    before = live.svc.plans._contract(plan_id)[1]
    live.replanner.accept(STUDENT, proposal.id)
    assert live.replanner.proposals.get(proposal.id).status == "requested"  # the Counsellor decides (T6, D-x2)
    assert live.svc.plans._contract(plan_id)[1] == before
    with live.engine.connect() as conn:
        (row,) = conn.execute(select(O).where(O.c.template == "choice_request")).all()
    assert row.idempotency_key == f"choice_request:{proposal.id}" and row.channel == "counsellor"
    assert [(c["programme_ref"], c["rank"]) for c in row.payload["programmes"]] == [("ie-p4", 1), ("ie-p3", 2)]


def test_a_self_serve_drop_changes_the_plan_when_accepted(live):
    plan_id = start(live, source="self_serve")
    sweep(live, DUE_PAST)
    (proposal,) = pending_proposals(live, plan_id)
    live.replanner.accept(STUDENT, proposal.id)
    refs = [p.programme_ref for p in live.svc.plans._contract(plan_id)[0].programmes]
    assert refs == ["ie-p4", "ie-p2", "ie-p3"]  # ie-p1 swapped for its close match...
    assert live.replanner.overrides.cancelled(plan_id) == {"ie-p2"}  # ...and ie-p2 taken out of the plan
    assert not [k for k in keys_of(live, plan_id) if k.endswith("@ie-p2") and "#" not in k]


# --- rung 4: a support case ---------------------------------------------------------------------------------------

def test_overdue_request_on_every_place_escalates_blocking_gap(route_live):
    w = route_live
    plan_id = w.svc.plans.start_plan(contract(level="bachelor", refs=("pk-p1", "pk-p2"), source="counsellor")).plan_id
    with w.engine.begin() as conn:
        conn.execute(insert(models.counsellor_intake).values(
            tenant_id=TENANT, decision_id="d-1", student_ref=STUDENT, journey_id="j-1", export={},
            export_sha256="0" * 64, chosen_at="2027-01-10T09:00:00+05:00", status="planned", plan_id=plan_id,
            decision_version=1))
    results = sweep(w, datetime(2027, 9, 1, 8, tzinfo=timezone.utc))  # after the merit list of the fake route
    missing = event_of(w, plan_id, "document_missing", MARKS_ASK)  # the entry test is route-level
    assert results[missing.id]["status"] == "applied"
    case = SupportStore(w.engine, TENANT).for_event(missing.id)
    assert case is not None and case.reason == texts.text("unanswered_all") and case.plan_id == plan_id
    with w.engine.connect() as conn:
        sent = [r.payload for r in conn.execute(select(O).where(O.c.channel == "counsellor", O.c.template == "escalation"))]
    assert [(p["reason"], p["case_id"]) for p in sent if p["case_id"] == case.id] == [("blocking_gap", case.id)]
    assert pending_proposals(w, plan_id) == []  # no swap or removal: the Counsellor looks, the student is not sent back


# --- never silent -------------------------------------------------------------------------------------------------

def never_silent(w, plan_id, now) -> int:
    """Every open request step of the plan whose date has passed has a proposal that asks the student, or a support
    case, naming its event. A bare reminder or nudge does not count. Returns how many steps it checked."""
    proposals, cases, checked = w.replanner.proposals, SupportStore(w.engine, TENANT), 0
    for key, state in keys_of(w, plan_id).items():
        if not key.startswith(("provide@", "which_is_right@")) or state in ("done", "cancelled", "skipped"):
            continue
        step = task(w, plan_id, key)
        if step.due_at is None or step.due_at >= now:
            continue
        ev = event_of(w, plan_id, "document_missing", key)
        proposal, case = proposals.for_event(ev.id), cases.for_event(ev.id)
        assert case is not None or (proposal is not None and proposal.big and proposal.status == "pending"), key
        checked += 1
    return checked


def test_plan_never_fails_silently(live):
    plan_id = start(live, source="self_serve")
    sweep(live, DUE_PAST)
    assert never_silent(live, plan_id, DUE_PAST) == 1


def test_plan_never_fails_silently_on_a_route_level_request(route_live):
    w = route_live
    plan_id = w.svc.plans.start_plan(contract(level="bachelor", refs=("pk-p1", "pk-p2"), source="self_serve")).plan_id
    now = datetime(2027, 9, 1, 8, tzinfo=timezone.utc)
    sweep(w, now)
    assert never_silent(w, plan_id, now) == 2  # the marks and the certificate


# --- an answer after the proposal ---------------------------------------------------------------------------------

def test_answer_after_proposal_leaves_the_proposal_to_the_student(live):
    plan_id = start(live, source="self_serve")
    sweep(live, DUE_PAST)
    (proposal,) = pending_proposals(live, plan_id)
    # the student gives the score at last: the request is answered, the steps that waited for it unblock
    live.vault[STUDENT] = facts_of(STUDENT, 2, test__ielts__score=(7.0, "confirmed"))
    assert live.svc.plans.recompile(plan_id, "student_fact_changed") is not None
    assert ENGLISH_ASK not in keys_of(live, plan_id)
    assert [s for k, s in keys_of(live, plan_id).items() if k.startswith(ENGLISH_ASK)] == ["done"]
    assert task(live, plan_id, "english_proof@ie-p1").state != "blocked"
    assert live.replanner.proposals.get(proposal.id).status == "pending"  # still the student's to answer
    with live.engine.connect() as conn:
        assert conn.execute(select(models.proposals.c.status).where(models.proposals.c.id == proposal.id)).scalar() == "pending"
    live.replanner.proposals.set_status(proposal.id, "declined")  # the student says no: nothing is removed
    assert [p.programme_ref for p in live.svc.plans._contract(plan_id)[0].programmes] == ["ie-p1", "ie-p2", "ie-p3"]
    with pytest.raises(ProposalStale):
        live.replanner.accept(STUDENT, proposal.id)
