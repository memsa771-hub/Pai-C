"""P1-T5 Task 1: the OS builds plan_view.v1 from the plan tables, through the Counsellor intake (R-04, R-44, D-s).
Fictional data: the Germany playbook and the fake routes; plan rows are the tests' own writes where a state needs one."""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, update

from app.os import models, ports
from app.os.adapters.counsellor.store import IntakeStore
from app.os.contracts.plan_view import PlanViewV1
from app.os.playbooks import load_playbook_dir
from app.os.plan_view import build_plan_view
from app.os.ports import plan_query
from test_counsellor_intake_v2 import chosen, run, svc, v1, withdrawn  # noqa: F401
from test_plan_summary import CONTRACT, STUDENT, plan, task

pytestmark = [pytest.mark.req("R-04"), pytest.mark.req("R-44")]

BOOKS = load_playbook_dir()
AT = datetime(2027, 1, 12, 9, tzinfo=timezone.utc)


class _Svc:  # what the builder needs of the services
    def __init__(self, engine, books=None, tenant="pai"):
        self.engine = engine
        self.settings = type("S", (), {"tenant_id": tenant})()
        self.plans = type("P", (), {"playbooks": BOOKS if books is None else books})()


def decision(engine, status: str, plan_id: int | None, version: int | None = 1, n: int = 1, **export):
    """Stores one intake row for STUDENT with the given outcome."""
    store = IntakeStore(engine, "pai")
    body = {"decision_id": f"d-{n}", "student_ref": STUDENT, "journey_id": "j-1", "chosen_at": AT.isoformat(),
            "decision_version": version, "status": "chosen", "authorized_at": AT.isoformat(), **export}
    store.add(body, "0" * 64)
    if status != "pending":
        store.finish(store.get(f"d-{n}").id, status, None, plan_id)


def view(engine) -> PlanViewV1:
    v = build_plan_view(_Svc(engine), STUDENT)
    assert PlanViewV1.model_validate(v.model_dump(mode="json", by_alias=True)) == v
    return v


@pytest.mark.parametrize("status,paused,waiting,state", [
    ("done", False, False, "finished"), ("closed", False, False, "stopped"), ("paused", False, False, "paused"),
    ("active", False, False, "active"), ("at_risk", False, False, "active"),
    ("active", False, True, "needs_student"), ("at_risk", False, True, "needs_student"),
    ("active", True, False, "active")])  # changes_paused is not a paused plan
def test_plan_status_maps_to_state(engine, clean, status, paused, waiting, state):
    p = plan(engine, status=status, paused=paused)
    task(engine, p, "a", "running")
    if waiting:
        task(engine, p, "b", "waiting_student", kind="student")
    decision(engine, "planned", p)
    v = view(engine)
    assert (v.state, v.plan_id, v.revision) == (state, p, 1)


def test_pending_proposal_needs_student(engine, clean):
    p = plan(engine)
    task(engine, p, "a", "running")
    with engine.begin() as conn:
        conn.execute(insert(models.proposals).values(tenant_id="pai", plan_id=p, source="rules", status="pending"))
        conn.execute(insert(models.proposals).values(tenant_id="pai", plan_id=p, source="rules", status="expired"))
    decision(engine, "planned", p)
    v = view(engine)
    assert (v.state, v.proposals_waiting) == ("needs_student", 1)


@pytest.mark.parametrize("intake,state", [
    ("planned", "active"), ("revised", "active"), ("replaced", "active"), ("paused", "active"),
    ("withdrawn", "stopped"), ("unsupported", "stopped"),
    ("pending", "empty"), ("held", "empty"), ("refused", "empty"), ("stale", "empty")])
def test_intake_status_selects_the_plan(engine, clean, intake, state):
    p = plan(engine, status="closed" if state == "stopped" else "active")
    task(engine, p, "a", "running")
    decision(engine, intake, p)
    v = view(engine)
    assert v.state == state
    assert (v.plan_id is None) == (state == "empty")


def test_no_decision_is_empty(engine, clean):
    plan(engine)  # a plan nobody chose through the Counsellor
    v = view(engine)
    assert (v.state, v.plan_id, v.steps, v.decision_version, v.consent) == ("empty", None, [], None, None)


@pytest.mark.parametrize("newer", ["pending", "held", "refused", "stale"])
def test_newer_unapplied_decision_does_not_hide_the_applied_plan(engine, clean, newer):
    """Replaces test_not_yet_applied_decision_is_empty (controller ruling, fix round 1): the lag shows in
    decision_version, the plan stays."""
    p = plan(engine)
    task(engine, p, "a", "running")
    decision(engine, "planned", p, version=1, n=1)
    decision(engine, newer, None, version=2, n=2)
    v = view(engine)
    assert (v.state, v.plan_id, v.decision_version) == ("active", p, 1)


def test_only_a_pending_decision_is_empty(engine, clean):
    plan(engine)
    decision(engine, "pending", None, version=1)
    assert view(engine).state == "empty"


def test_withdrawn_row_with_open_plan_is_stopped(engine, clean):
    p = plan(engine)  # still active
    task(engine, p, "a", "running")
    decision(engine, "withdrawn", p)
    v = view(engine)
    assert (v.state, v.state_reason) == ("stopped", "withdrawn")


def test_self_serve_plan_is_not_used_for_a_decision(engine, clean):
    mine = plan(engine, source="self_serve", ref="s-1:DE:master")
    task(engine, mine, "own", "running")
    counsellor = plan(engine, ref="j-1:IE:master")
    task(engine, counsellor, "theirs", "running")
    decision(engine, "planned", counsellor)
    v = view(engine)
    assert v.plan_id == counsellor and [s.instance_key for s in v.steps] == ["theirs"]
    with engine.begin() as conn:
        conn.execute(models.counsellor_intake.delete())
    assert view(engine).state == "empty"  # the self-serve plan alone never appears


def test_decision_version_is_the_newest_applied_to_the_plan(engine, clean):
    p = plan(engine)
    task(engine, p, "a", "running")
    decision(engine, "planned", p, version=1, n=1)
    decision(engine, "revised", p, version=3, n=3)
    decision(engine, "stale", p, version=2, n=2)
    decision(engine, "refused", None, version=4, n=4)
    assert view(engine).decision_version == 3


def test_v1_decision_has_no_version(engine, clean):
    p = plan(engine)
    task(engine, p, "a", "running")
    decision(engine, "planned", p, version=None)
    assert view(engine).decision_version is None


def test_notice_and_renamed_tasks_are_excluded(engine, clean):
    p = plan(engine)
    task(engine, p, "apply", "running")
    task(engine, p, "plan_updated@r2", "waiting_student", kind="student")
    task(engine, p, "old#c2", "cancelled")
    task(engine, p, "again#d3", "done")
    decision(engine, "planned", p)
    v = view(engine)
    assert [s.instance_key for s in v.steps] == ["apply"]
    assert v.state == "active"  # the notice does not make the plan wait for the student


def test_step_fields_edges_and_blocked_reason(engine, clean):
    p = plan(engine)
    task(engine, p, "docs", "done", kind="student")
    task(engine, p, "apply@prog", "blocked", blocked="fact_missing:fee", programme="prog")
    task(engine, p, "free", "blocked", blocked="Free text with spaces")
    task(engine, p, "plan_updated@r2", "pending")
    with engine.begin() as conn:
        ids = dict(conn.execute(models.tasks.select().with_only_columns(
            models.tasks.c.instance_key, models.tasks.c.id)).all())
        for a, b in (("docs", "apply@prog"), ("plan_updated@r2", "apply@prog"), ("docs", "free")):
            conn.execute(insert(models.task_edges).values(tenant_id="pai", plan_id=p, from_task=ids[a], to_task=ids[b],
                                                          hard=True))
    decision(engine, "planned", p)
    by = {s.instance_key: s for s in view(engine).steps}
    assert by["docs"].owner == "student" and by["docs"].inbox_kind == "act" and by["docs"].depends_on == []
    assert by["apply@prog"].depends_on == ["docs"]  # the hidden notice is not a dependency
    assert (by["apply@prog"].blocked_reason, by["apply@prog"].programme_ref) == ("fact_missing", "prog")
    assert by["free"].blocked_reason == "blocked"
    assert by["apply@prog"].owner == "pai" and by["apply@prog"].needs == []


def test_closed_state_reason_is_the_cause_word(engine, clean):
    p = plan(engine, status="closed")
    with engine.begin() as conn:
        conn.execute(update(models.plans).where(models.plans.c.id == p).values(current_revision=2))
        conn.execute(insert(models.plan_revisions).values(tenant_id="pai", plan_id=p, number=2,
                                                          cause="withdrawn:d-2", diff={"cancelled": ["a"]}))
    decision(engine, "withdrawn", p, version=2)
    v = view(engine)
    assert (v.state, v.state_reason, v.revision, v.decision_version) == ("stopped", "withdrawn", 2, 2)


def test_paused_reason_comes_from_the_event(engine, clean):
    p = plan(engine, status="paused")
    with engine.begin() as conn:
        conn.execute(insert(models.events).values(tenant_id="pai", plan_id=p, type="plan_paused",
                                                  payload={"reason": "old_reason"}))
        conn.execute(insert(models.events).values(tenant_id="pai", plan_id=p, type="plan_paused",
                                                  payload={"reason": "consent_missing"}))
    decision(engine, "paused", p)
    v = view(engine)
    assert (v.state, v.state_reason) == ("paused", "consent_missing")


def test_changes_list_a_revision(engine, clean):
    p = plan(engine)
    task(engine, p, "a", "running")
    with engine.begin() as conn:
        conn.execute(update(models.plans).where(models.plans.c.id == p).values(current_revision=2))
        conn.execute(insert(models.plan_revisions).values(tenant_id="pai", plan_id=p, number=1, cause="created",
                                                          diff={"added": ["a"]}))
        conn.execute(insert(models.plan_revisions).values(
            tenant_id="pai", plan_id=p, number=2, cause="replan:7", created_at=AT,
            diff={"added": ["n", "plan_updated@r2"], "removed": ["old"], "changed": ["a"], "skipped_started": ["s"]}))
    decision(engine, "revised", p)
    v = view(engine)
    assert [(c.revision, c.cause, c.kind, c.instance_key) for c in v.changes] == [
        (2, "replan", "added", "n"), (2, "replan", "removed", "old"), (2, "replan", "revised", "a")]
    assert v.changes[0].at == AT


@pytest.mark.parametrize("export,expected", [
    ({}, ("given", "not_needed")),
    ({"authorized_at": None}, ("missing", "not_needed")),
    ({"guardian_required": True, "guardian_authorized_at": None}, ("given", "missing")),
    ({"guardian_required": True, "guardian_authorized_at": AT.isoformat()}, ("given", "given"))])
def test_consent_comes_from_the_intake_export(engine, clean, export, expected):
    p = plan(engine)
    task(engine, p, "a", "running")
    decision(engine, "planned", p, **export)
    c = view(engine).consent
    assert (c.student, c.guardian) == expected


@pytest.mark.req("R-51")
def test_pages_come_from_the_playbook_requests_and_documents_are_empty(engine, clean):
    """Changed on purpose (D-z6): `pages` was always []; it is now the pinned playbook version's page keys."""
    p = plan(engine)
    with engine.begin() as conn:
        conn.execute(insert(models.playbook_pins).values(tenant_id="pai", plan_id=p, playbook_key="germany_master",
                                                         version=1))
    decision(engine, "planned", p)
    v = view(engine)
    assert v.pages == ["start", "inbox", "documents", "programmes", "statements", "pack", "visa"]
    assert (v.requests, v.documents_needed) == ([], [])


def test_pages_follow_the_pinned_version_and_are_empty_without_a_playbook(engine, clean):
    p = plan(engine)
    with engine.begin() as conn:
        conn.execute(insert(models.playbook_pins).values(tenant_id="pai", plan_id=p, playbook_key="germany_master",
                                                         version=7))
    decision(engine, "planned", p)
    assert view(engine).pages == []  # that version is not loaded: nothing is invented


@pytest.mark.req("R-51")
def test_empty_view_has_no_pages(engine, clean):
    v = view(engine)
    assert (v.state, v.pages) == ("empty", [])


def test_real_flow_through_the_port(svc):
    """A real Germany plan from a v1 and a v2 decision, read through PlanQuery, then a withdrawal."""
    first = run(svc, v1())
    store = IntakeStore(svc.engine, "pai")
    store.finish(store.get(v1()["decision_id"]).id, first.status, first.reason, first.plan_id)
    student = v1()["student_ref"]
    ports.configure(svc)
    try:
        v = plan_query.plan_view(student)
        assert v.state in ("active", "needs_student") and v.plan_id == first.plan_id and v.steps
        assert (v.route.route_key, v.route.destination_country, v.route.level) == ("germany_master", "DE", "master")
        assert v.consent.student == "given" and v.decision_version is None
        assert PlanViewV1.model_validate(json.loads(v.model_dump_json(by_alias=True))) == v
        w = run(svc, withdrawn(2))
        store.finish(store.get("d-v2").id, w.status, w.reason, w.plan_id)
        v = plan_query.plan_view(student)
        assert (v.state, v.state_reason, v.decision_version) == ("stopped", "withdrawn", 2)
    finally:
        ports.configure(None)


def test_unknown_student_is_empty_through_the_port(svc):
    ports.configure(svc)
    try:
        assert plan_query.plan_view("nobody").state == "empty"
    finally:
        ports.configure(None)


def test_route_key_from_the_newest_pin(engine, clean):
    p = plan(engine)
    with engine.begin() as conn:
        conn.execute(insert(models.playbook_pins).values(tenant_id="pai", plan_id=p, playbook_key="germany_master",
                                                         version=1))
    decision(engine, "planned", p)
    assert view(engine).route.route_key == "germany_master"


def test_no_pin_derives_the_key_from_the_playbooks(engine, clean):
    p = plan(engine)
    decision(engine, "planned", p)
    v = build_plan_view(_Svc(engine), STUDENT)
    assert v.route.route_key == "germany_master"


def test_no_pin_and_no_playbook_is_an_error(engine, clean):
    p = plan(engine)
    decision(engine, "planned", p)
    with pytest.raises(ValueError, match="no playbook pin"):
        build_plan_view(_Svc(engine, {}), STUDENT)


def test_other_students_are_never_returned(engine, clean):
    mine = plan(engine)
    task(engine, mine, "a", "running")
    decision(engine, "planned", mine, n=1)
    other = plan(engine, ref="j-9:DE:master")
    with engine.begin() as conn:
        conn.execute(update(models.plans).where(models.plans.c.id == other).values(student_ref="ws-other"))
    decision(engine, "planned", other, n=2, student_ref="ws-other")
    assert view(engine).plan_id == mine
    assert build_plan_view(_Svc(engine), "ws-other").plan_id == other
    assert build_plan_view(_Svc(engine), "ws-nobody").state == "empty"


def test_other_tenants_are_never_returned(engine, clean):
    """A full plan, task, revision, intake row and closed plan of the same student_ref under tenant `other`."""
    with engine.begin() as conn:
        o = conn.execute(insert(models.plans).values(
            tenant_id="other", source="counsellor", external_ref="j-1:DE:master", student_ref=STUDENT,
            contract=CONTRACT, contract_sha256="0" * 64, status="closed", current_revision=2
        ).returning(models.plans.c.id)).scalar_one()
        conn.execute(insert(models.plan_revisions).values(tenant_id="other", plan_id=o, number=2,
                                                          cause="leaked:x", diff={"added": ["leak"]}))
        conn.execute(insert(models.counsellor_intake).values(
            tenant_id="other", decision_id="d-o", student_ref=STUDENT, journey_id="j-1", export={}, export_sha256="0",
            chosen_at=AT, status="withdrawn", plan_id=o, decision_version=5))
    task(engine, o, "leak", "running")
    assert build_plan_view(_Svc(engine, tenant="pai"), STUDENT).state == "empty"
    assert build_plan_view(_Svc(engine, tenant="other"), STUDENT).plan_id == o
    # the same plan id reached through a pai intake row must not show other tenant data
    decision(engine, "planned", o)
    v = view(engine)
    assert v.plan_id is None and v.steps == [] and v.changes == []


def test_stopped_by_decision_never_shows_the_pause_reason(engine, clean):
    p = plan(engine, status="paused")
    with engine.begin() as conn:
        conn.execute(insert(models.events).values(tenant_id="pai", plan_id=p, type="plan_paused",
                                                  payload={"reason": "consent_missing"}))
    decision(engine, "withdrawn", p, version=2)
    v = view(engine)
    assert (v.state, v.state_reason) == ("stopped", "withdrawn")


def test_unsupported_row_with_open_plan_is_stopped(engine, clean):
    p = plan(engine)
    task(engine, p, "a", "running")
    decision(engine, "unsupported", p)
    v = view(engine)
    assert (v.state, v.state_reason) == ("stopped", "unsupported")


def test_contract_without_its_route_is_a_clear_error(engine, clean):
    p = plan(engine)
    with engine.begin() as conn:
        conn.execute(update(models.plans).where(models.plans.c.id == p).values(contract={"level": "master"}))
    decision(engine, "planned", p)
    with pytest.raises(ValueError, match="contract without its route"):
        view(engine)


def test_pin_with_the_highest_version_wins(engine, clean):
    """os_playbook_pins is unique per plan_id, so two pins cannot be stored; the ordering (version, then id, newest
    first) is defensive. This checks the single stored pin is the one used."""
    p = plan(engine)
    with engine.begin() as conn:
        conn.execute(insert(models.playbook_pins).values(tenant_id="pai", plan_id=p, playbook_key="pin_key",
                                                         version=2))
    decision(engine, "planned", p)
    assert view(engine).route.route_key == "pin_key"


@pytest.mark.req("R-41")
def test_intermediate_plan_builds_a_view(svc):
    from test_counsellor_intake_v2 import inter
    export = inter(1)
    r = run(svc, export)
    store = IntakeStore(svc.engine, "pai")
    store.finish(store.get(export["decision_id"]).id, r.status, r.reason, r.plan_id)
    ports.configure(svc)
    try:
        v = plan_query.plan_view(export["student_ref"])
        assert v.plan_id == r.plan_id and v.steps
        assert (v.route.route_key, v.route.level) == ("pakistan_inter", "intermediate")
    finally:
        ports.configure(None)


# --- P1-T7 Task 4 (D-y14, R-16): documents_needed from the route's pack checklist -----------------------------------


class _PackSvc(_Svc):
    def __init__(self, engine, pack_configs):
        super().__init__(engine)
        self.pack_configs = pack_configs


def test_documents_needed_from_pack_checklist(engine, clean):
    from app.os.documents.store import DocumentStore
    from app.os.packs.config import load_pack_configs
    from app.os.ports import document_files
    from test_api_documents import TRANSCRIPT, TYPES, simulate_read

    configs = load_pack_configs()
    p = plan(engine)
    decision(engine, "planned", p)
    wanted = [i.ref for i in configs["germany_master"].checklist if i.kind == "document"]
    assert "transcript" in wanted and "ielts_trf" in wanted
    store = DocumentStore(engine, "pai")

    def need():
        v = build_plan_view(_PackSvc(engine, configs), STUDENT)
        assert PlanViewV1.model_validate(v.model_dump(mode="json", by_alias=True)) == v
        return {n.doc_type: n.status for n in v.documents_needed}

    try:
        assert need() == {}  # the port is off: today's empty list
        document_files.configure(enabled=lambda: True)
        assert need() == {ref: "missing" for ref in wanted}
        assert [n.doc_type for n in build_plan_view(_PackSvc(engine, configs), STUDENT).documents_needed] == wanted
        d = store.create(STUDENT, "transcript", TYPES["transcript"].version, "t.pdf", "application/pdf", b"%PDF-1 a")
        assert need()["transcript"] == "uploaded"
        for status in ("reading", "read", "needs_student"):
            store.set_status(d, status)
            assert need()["transcript"] == "uploaded"
        store.set_status(d, "failed")
        assert need()["transcript"] == "missing"
        simulate_read(engine, d, "transcript", TRANSCRIPT)
        store.confirm(d, {f.name: TRANSCRIPT.get(f.name) for f in TYPES["transcript"].fields})
        assert need()["transcript"] == "confirmed" and need()["ielts_trf"] == "missing"
        store.delete(d)
        assert need()["transcript"] == "missing"  # a deleted document is not a document
        # a route with no pack config, and a service without any
        assert build_plan_view(_PackSvc(engine, {}), STUDENT).documents_needed == []
        assert build_plan_view(_Svc(engine), STUDENT).documents_needed == []
    finally:
        document_files.configure()


# --- P1-T8 Task 3: the plan's requests and what each step needs (R-17, R-19) ------------------------------------------

@pytest.mark.req("R-17")
def test_plan_view_lists_requests_and_step_needs(engine, clean):
    from dataclasses import replace
    from datetime import date

    from app.os.compiler import compile_plan
    from app.os.requests.state import StudentState
    from tests.os.kernel_helpers import kernel
    from tests.os.test_compile_needs import BOOKS, INTER1, INTER2, OBTAINED, TOTAL, contract, merit

    who = contract().model_copy(update={"student_ref": STUDENT})
    k = kernel(engine)
    today = date(2027, 3, 1)
    ref = k.create_plan(who, compile_plan(who, INTER2, {}, merit(), today, student=StudentState()))
    decision(engine, "planned", ref.plan_id)
    svc = _Svc(engine, books=BOOKS)

    v = build_plan_view(svc, STUDENT)
    assert PlanViewV1.model_validate(v.model_dump(mode="json", by_alias=True)) == v
    steps = {s.instance_key: s for s in v.steps}
    form = steps["admission_form"]  # a playbook step: its needs come from the pinned book
    assert [(n.kind, n.ref, n.evidence) for n in form.needs] == [
        ("fact", OBTAINED, "stated"), ("fact", TOTAL, "stated")]
    assert form.blocked_reason == "awaiting_fact" and form.status == "blocked"
    assert [(n.ref, n.evidence) for n in steps["merit_list@p1"].needs] == [(OBTAINED, "shown")]
    asked = steps[f"provide@fact:{OBTAINED}:stated"]  # a generated step: its need comes from its key
    assert [(n.kind, n.ref, n.evidence) for n in asked.needs] == [("fact", OBTAINED, "stated")]
    assert (asked.status, asked.owner, asked.inbox_kind) == ("waiting_student", "student", "provide")
    assert sorted((r.need.ref, r.need.evidence, r.status) for r in v.requests) == [
        (OBTAINED, "stated", "open"), (TOTAL, "stated", "open")]
    due = {r.need.ref: (r.due_at, r.due_tz) for r in v.requests}
    assert due[OBTAINED] == (asked.due_at, asked.due_tz) and asked.due_at is not None  # the step's date and zone

    # the student types the marks: that request is answered, the mark sheet is asked next
    typed = StudentState(facts={OBTAINED: "stated", TOTAL: "stated"})
    k.revise(ref.plan_id, "student_fact_changed", compile_plan(who, INTER2, {}, merit(), today, student=typed))
    v = build_plan_view(svc, STUDENT)
    got = sorted((r.need.ref, r.need.evidence, r.status) for r in v.requests)
    assert got == [(OBTAINED, "shown", "open"), (OBTAINED, "stated", "answered"), (TOTAL, "stated", "answered")]
    assert not [s for s in v.steps if "#" in s.instance_key]  # the finished request step is history, not a step

    # a plan on the book without needs: no needs, no requests
    plan_v1 = k.create_plan(who.model_copy(update={"external_ref": "ext-v1"}), compile_plan(
        who.model_copy(update={"external_ref": "ext-v1"}), INTER1, {}, merit(), today))
    decision(engine, "planned", plan_v1.plan_id, version=2, n=2)
    old = build_plan_view(svc, STUDENT)
    assert old.plan_id == plan_v1.plan_id and old.requests == [] and all(s.needs == [] for s in old.steps)


@pytest.mark.req("R-17")
def test_result_expected_step_shows_no_need_and_no_request(engine, clean):
    from datetime import date

    from app.os.compiler import compile_plan
    from app.os.requests.state import StudentState
    from tests.os.kernel_helpers import kernel
    from tests.os.test_compile_needs import BOOKS, CALENDAR, INTER2, OBTAINED, contract, merit

    who = contract().model_copy(update={"student_ref": STUDENT})
    ref = kernel(engine).create_plan(who, compile_plan(who, INTER2, CALENDAR, merit(), date(2027, 3, 1),
                                                       student=StudentState()))
    decision(engine, "planned", ref.plan_id)
    v = build_plan_view(_Svc(engine, books=BOOKS), STUDENT)
    waits = next(s for s in v.steps if s.template_key == "result_expected")
    assert waits.needs == [] and waits.blocked_reason == "result_expected"
    assert [r.need.ref for r in v.requests].count(OBTAINED) == 1  # the provide step behind it is the request
