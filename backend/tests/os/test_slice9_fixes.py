"""Slice 9a Task 11 (batch A): the rehearsal fix pass, backend. One test (or a few) per fixed failure, and the four old
deferred minors of Slice 7 (spec S9-D10). Fictional data only."""
# ruff: noqa: F811  (`api` is a fixture imported from test_api_replan, so test arguments of that name redefine it)

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

from app.os import clock, models
from app.os.compiler import CONFIRM_TYPE
from app.os.kernel import IllegalTransition, Outcome
from app.os.knowledge.research.run import enqueue_research
from app.os.replan import events
from app.os.replan.checks import task_rows
from app.os.replan.config import ReplanConfig
from app.os.replan.ops import CancelProgramme, Reprioritise, TaskRow
from app.os.replan.rules import PlanState, rules_for
from app.os.replan.store import ProposalStore, SupportStore
from tests.os.conftest import truncate_os_tables
from tests.os.test_api_replan import (  # noqa: F401  (api and real_clock are fixtures)
    ME,
    P1,
    R,
    api,
    propose,
)
from tests.os.test_golden import TEST_STUDENT
from tests.os.test_rehearsal_mode import (  # noqa: F401
    ADMIN,
    BASE,
    DAY,
    FakeClient,
    _app,
    _near,
    _settings,
    real_clock,
)

T = models.tasks


# ---- item 1: the rehearsal start date ------------------------------------------------------------------------------

def _start(web, day: date):
    return web.post(f"{BASE}/start", json={"date": day.isoformat()}, headers=ADMIN)


@pytest.mark.parametrize("shift", [-200, 45])
def test_rehearsal_start_sets_today(engine, clean, os_db, shift):
    """In the past (a negative offset) and in the future: the shared clock then reads exactly that day."""
    day = datetime.now(timezone.utc).date() + timedelta(days=shift)
    web = _app(engine, _settings(os_db, True), FakeClient())
    r = _start(web, day)
    assert r.status_code == 200, r.text
    assert clock.today() == day
    assert r.json()["offset_days"] == shift
    assert datetime.fromisoformat(r.json()["now"]).date() == day


def test_rehearsal_start_only_once(engine, clean, os_db):
    """Time never goes back once set: a second start is refused, and so is a start after an advance."""
    web = _app(engine, _settings(os_db, True), FakeClient())
    day = date(2026, 12, 1)
    assert _start(web, day).status_code == 200
    again = _start(web, day - timedelta(days=10))
    assert again.status_code == 409
    assert clock.today() == day
    truncate_os_tables(engine)  # a clean clock again, then moved by an advance first
    assert web.post(f"{BASE}/advance", json={"days": 1}, headers=ADMIN).status_code == 200
    assert _start(web, day).status_code == 409


def test_rehearsal_start_404_when_off(engine, clean, os_db):
    web = _app(engine, _settings(os_db, False), FakeClient())
    assert _start(web, date(2026, 12, 1)).status_code == 404


def test_rehearsal_start_needs_admin(engine, clean, os_db):
    web = _app(engine, _settings(os_db, True), FakeClient())
    r = web.post(f"{BASE}/start", json={"date": "2026-12-01"}, headers={"X-OS-Admin-Token": "wrong"})
    assert r.status_code in (401, 403)


def test_advance_stays_forward_only_after_a_past_start(engine, clean, os_db):
    web = _app(engine, _settings(os_db, True), FakeClient())
    day = datetime.now(timezone.utc).date() - timedelta(days=90)
    assert _start(web, day).status_code == 200
    assert web.post(f"{BASE}/advance", json={"days": 0}, headers=ADMIN).status_code == 422
    assert web.post(f"{BASE}/advance", json={"days": -5}, headers=ADMIN).status_code == 422
    r = web.post(f"{BASE}/advance", json={"days": 3}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["offset_days"] == -87
    assert clock.today() == day + timedelta(days=3)


def test_clock_reads_a_negative_offset(engine, clean, os_db):
    from app.os.rehearsal.store import ClockStore, install_clock

    with engine.begin() as conn:
        conn.execute(insert(models.rehearsal_clock).values(tenant_id="pai", offset_seconds=-30 * 86400))
    assert ClockStore(engine, "pai").offset() == -30 * DAY
    install_clock(_settings(os_db, True), engine)
    assert _near(clock.now(), datetime.now(timezone.utc) - 30 * DAY)


def test_rehearsal_start_refused_once_plans_exist(engine, clean, os_db):
    """A rehearsal clock that never moved, on a database where plans already ran at real time: a start on a past day
    would send time back behind their stored timestamps, so it is refused (409) and nothing is written."""
    with engine.begin() as conn:
        conn.execute(insert(models.plans).values(tenant_id="pai", source="self_serve", external_ref="x", student_ref="stu-x", contract={},
                                                 contract_sha256="0" * 64, status="active"))
    web = _app(engine, _settings(os_db, True), FakeClient())
    r = _start(web, date(2026, 12, 1))
    assert r.status_code == 409
    with engine.connect() as conn:
        assert conn.execute(select(models.rehearsal_clock)).all() == []
    with engine.begin() as conn:  # another tenant's plans do not count
        conn.execute(models.plans.update().values(tenant_id="other"))
    assert _start(web, date(2026, 12, 1)).status_code == 200


def test_leftover_negative_offset_ignored_when_off(engine, clean, os_db):
    """Review Focus 1: rehearsal off, a leftover negative offset row: real time, and every rehearsal call is 404."""
    from app.os.rehearsal.store import install_clock

    with engine.begin() as conn:
        conn.execute(insert(models.rehearsal_clock).values(tenant_id="pai", offset_seconds=-90 * 86400))
    install_clock(_settings(os_db, False), engine)
    assert _near(clock.now(), datetime.now(timezone.utc))
    web = _app(engine, _settings(os_db, False), FakeClient())
    assert _near(clock.now(), datetime.now(timezone.utc))
    assert _start(web, date(2026, 12, 1)).status_code == 404
    assert web.post(f"{BASE}/advance", json={"days": 1}, headers=ADMIN).status_code == 404
    assert web.post(f"{BASE}/tick", headers=ADMIN).status_code == 404


def test_migration_down_clamps_a_negative_offset(os_db, engine, clean):
    from sqlalchemy import text

    from tests.os.conftest import run_alembic

    with engine.begin() as conn:
        conn.execute(insert(models.rehearsal_clock).values(tenant_id="pai", offset_seconds=-5 * 86400))
        conn.execute(insert(models.rehearsal_clock).values(tenant_id="other", offset_seconds=7 * 86400))
    engine.dispose()
    run_alembic(["downgrade", "os_0016"], os_db)
    try:
        with engine.connect() as conn:
            got = dict(conn.execute(text("SELECT tenant_id, offset_seconds FROM os.os_rehearsal_clock")).all())
        assert got == {"pai": 0, "other": 7 * 86400}
    finally:
        engine.dispose()
        run_alembic(["upgrade", "os@head"], os_db)


# ---- item 3 (F2): a removed programme's fact checks stop ---------------------------------------------------------

def _to_review(api, ref: str) -> list[str]:
    """What the runner does for each of the programme's fact checks: it runs and waits for research."""
    k = api.svc.kernel
    with api.engine.connect() as conn:
        rows = conn.execute(select(T).where(T.c.plan_id == api.plan_id, T.c.task_type == CONFIRM_TYPE,
                                            T.c.programme_ref == ref)).all()
    for row in rows:
        assert k.mark_running(row.id, row.attempt)
        k.apply_result(row.id, row.attempt, Outcome("needs_review", {"waiting_for": "research", "programme": ref}))
    return sorted(r.instance_key for r in rows)


def test_removed_programme_stops_its_fact_checks(api):
    """S3 (F2 `left_open:S3:removed_programme`): accepting the removal of a programme whose fact checks wait for
    research cancels them; the revision lists them as removed, and no research is started for it afterwards."""
    keys = _to_review(api, P1)
    assert keys, "the seeded facts are unconfirmed, so the plan checks them"
    assert _to_review(api, "ovgu-eeit")  # a programme that stays
    pid = propose(api)
    r = api.post(f"/v1/os/proposals/{pid}/accept", headers=ME)
    assert r.status_code == 200, r.text
    with api.engine.connect() as conn:
        left = conn.execute(select(T.c.instance_key, T.c.state).where(
            T.c.plan_id == api.plan_id, T.c.programme_ref == P1, T.c.state.not_in(("cancelled", "done", "skipped")))
        ).all()
        diff = conn.execute(select(models.plan_revisions.c.diff).where(
            models.plan_revisions.c.plan_id == api.plan_id, models.plan_revisions.c.cause == f"replan:{pid}")
        ).scalar_one()
    assert left == []
    assert set(keys) <= set(diff["removed"]) and not set(keys) & set(diff["skipped_started"])
    client = FakeClient()
    enqueue_research(api.engine, client, "pai", date(2027, 2, 1))
    assert {o["workflow_id"].split(":")[2] for o in client.enqueued} == {"ovgu-eeit"}  # the one that stays only


def test_only_review_waits_are_removed_with_their_programme():
    """The rule stays narrow: only a step waiting for a review (research or an admin) whose programme left the plan
    goes; a running step, a work step waiting for the student's input and a protected step are kept and reported, and
    a check of a programme that stays (dropped because its fact was just confirmed) waits to be completed."""
    from app.os.kernel import diff

    def row(state, ref="gone", kind="work", protected=False, task_type=CONFIRM_TYPE):
        return {"state": state, "kind": kind, "protected": protected, "skipped_draft": None, "task_type": task_type,
                "programme_ref": ref}

    stored = {"review": row("waiting_review"), "running": row("running"), "input": row("waiting_student"),
              "kept": row("pending", protected=True), "inbox": row("waiting_student", kind="student"),
              "route_check": row("waiting_review", ref=None), "stays_check": row("waiting_review", ref="stays"),
              "other_review": row("waiting_review", task_type="some.module_review")}
    d = diff(stored, {"live@stays": SimpleNamespace(programme_ref="stays")}, {})
    assert sorted(d.removed) == ["inbox", "review"]
    # a work step of another module waiting for a review is not a fact check: it is kept and reported, not cancelled
    assert sorted(d.skipped_started) == ["input", "other_review", "route_check", "running", "stays_check"]
    assert d.kept_protected == ["kept"]


# ---- item 4: the four old minors (S9-D10) ------------------------------------------------------------------------

def _revision(api) -> int:
    with api.engine.connect() as conn:
        return conn.execute(select(models.plans.c.current_revision).where(models.plans.c.id == api.plan_id)).scalar()


def test_accept_refused_while_paused(api):
    """Slice 7 #1: while a person checks the plan (changes paused), the student cannot accept a suggestion."""
    pid = propose(api)
    api.svc.kernel.set_changes_paused(api.plan_id, True)
    before = _revision(api)
    r = api.post(f"/v1/os/proposals/{pid}/accept", headers=ME)
    assert r.status_code == 409 and "paused" in r.json()["detail"]
    assert ProposalStore(api.engine, "pai").get(pid).status == "pending"
    assert _revision(api) == before
    api.svc.kernel.set_changes_paused(api.plan_id, False)
    assert api.post(f"/v1/os/proposals/{pid}/accept", headers=ME).status_code == 200


def test_empty_supervisor_answer_escalates(os_db, engine, clean, monkeypatch):
    """Slice 7 #5: a Supervisor answer with no operations opens a support case instead of closing the event."""
    from dbos import DBOS

    from tests.os import test_replan_run as rr

    monkeypatch.setattr(rr, "SUPERVISOR_OPS", {"ops": [], "summary": "Nothing to do."})
    ctx, client = rr.make(os_db, engine)
    try:
        eid = ctx.event("escalate", instance_key="travel_insurance")
        got = ctx.run(eid)
        assert got["status"] == "support", got
        [case] = SupportStore(engine, "pai").list("open")
        assert case.plan_id == ctx.plan_id and case.event_ids == [eid]
        assert [p.status for p in ProposalStore(engine, "pai").for_plan(ctx.plan_id)] == []
        assert events.pending(engine, "pai") == []
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def _row(key: str, state: str, kind: str = "student", protected: bool = False, task_type: str = "x") -> TaskRow:
    return TaskRow(key, key.split("@")[0], P1, state, kind, False, protected, None, None, 1, (), task_type)


def _rejected(*rows: TaskRow):
    state = PlanState(1, "route", [P1, "other"], {r.instance_key: r for r in rows})
    e = events.Event(1, 1, None, "admission_rejected", {"programme_ref": P1})
    [op] = rules_for(e, state, ReplanConfig())
    assert isinstance(op, CancelProgramme)
    return op.reason


def test_cancel_programme_wording_when_steps_kept():
    """Slice 7 #6: the reason no longer says every remaining step is removed when a started or protected one stays."""
    plain = _rejected(_row(f"a@{P1}", "waiting_student"), _row(f"b@{P1}", "pending"))
    assert plain == R
    started = _rejected(_row(f"a@{P1}", "waiting_student"), _row(f"m@{P1}", "running", kind="work"))
    protected = _rejected(_row(f"a@{P1}", "waiting_student"), _row(f"p@{P1}", "pending", protected=True))
    for reason in (started, protected):
        assert "remaining steps are removed" not in reason
        assert "kept" in reason
    finished = _rejected(_row(f"a@{P1}", "pending"), _row(f"d@{P1}", "done", kind="work"))
    assert finished == R  # a finished step is history, not "kept"
    checking = _rejected(_row(f"a@{P1}", "pending"),
                         _row(f"confirm_fact@{P1}:x", "waiting_review", kind="work", task_type=CONFIRM_TYPE))
    assert checking == R  # a fact check waiting for research goes with the programme (F2)
    other = _rejected(_row(f"a@{P1}", "pending"), _row(f"m@{P1}", "waiting_review", kind="work"))
    assert "kept" in other  # another module's step waiting for a review stays, and the text says so


def test_no_empty_what_changed_entry(api):
    """Slice 7 #7: a small change that turned out to change nothing in the plan adds no "What changed" entry."""
    rows = task_rows(api.engine, "pai", api.plan_id)
    pair = next(((d, k) for k, t in rows.items() for d, _ in t.depends_on
                 if t.kind == "student" and t.state in ("pending", "ready", "blocked", "waiting_student")
                 and rows[d].kind == "student" and rows[d].state in ("pending", "ready", "blocked", "waiting_student")
                 and not t.critical and not rows[d].critical), None)
    assert pair is not None, "the plan has a student step that already waits for another"
    first, then = pair  # `then` already waits for `first`: putting `first` before it changes nothing
    with api.engine.begin() as conn:
        eid = events.record(conn, "pai", api.plan_id, "deadline_at_risk", {"instance_key": then}, "k-noop")
    before = _revision(api)
    d = api.r.decide(api.plan_id, [eid], "rules", [Reprioritise(instance_key=first, before=then, reason="Order.")])
    assert d.status == "applied"
    assert _revision(api) == before  # no revision made
    assert ProposalStore(api.engine, "pai").get(d.proposal_id).revision is None
    body = api.get(f"/v1/os/plans/{api.plan_id}/changes", headers=ME).json()
    assert body["changes"] == []


# ---- polish: a fact check cancelled meanwhile is not completed ----------------------------------------------------

def test_fact_change_skips_a_check_cancelled_meanwhile(engine, clean, monkeypatch):
    """The research run lists the checks waiting for a fact, then completes them. A check the kernel cancelled in
    between (its programme left the plan, F2) is skipped, not an IllegalTransition that fails the step."""
    from app.os.knowledge import Fact
    from app.os.knowledge.changes import after_fact_change
    from tests.os.kernel_helpers import contract
    from tests.os.test_freshness import to_review
    from tests.os.test_workers import seed_deadline, service, task

    svc, kb, kernel = service(engine)
    fid = seed_deadline(kb, status="unconfirmed")
    ref = svc.start_plan(contract())
    key = "confirm_fact@p1:deadline_close"
    to_review(kernel, task(engine, ref.plan_id, key))
    real = kernel.complete_review

    def cancelled_first(task_id, result, **kw):  # the kernel's cancel lands between the listing and the completion
        with engine.begin() as conn:
            conn.execute(T.update().where(T.c.id == task_id).values(state="cancelled"))
        return real(task_id, result, **kw)

    monkeypatch.setattr(kernel, "complete_review", cancelled_first)
    kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-07-15"}, "Deadline", "https://uni.example/apply",
                                                       datetime(2026, 10, 17, tzinfo=timezone.utc), 2027, "confirmed"))
    after_fact_change(svc, kernel, "programme", "p1", "deadline_close", fid, "confirmed", 2027)
    with engine.connect() as conn:
        assert conn.execute(select(T.c.state).where(T.c.plan_id == ref.plan_id, T.c.instance_key.like(f"{key}%"))
                            ).scalars().all() == ["cancelled"]


def test_complete_review_if_waiting_skips_a_finished_check(engine, clean):
    """The kernel's own state check: a check no longer waiting for review is left as it is."""
    from tests.os.kernel_helpers import contract
    from tests.os.test_freshness import to_review
    from tests.os.test_workers import seed_deadline, service, task

    svc, kb, kernel = service(engine)
    seed_deadline(kb, status="unconfirmed")
    ref = svc.start_plan(contract())
    row = task(engine, ref.plan_id, "confirm_fact@p1:deadline_close")
    to_review(kernel, row)
    with engine.begin() as conn:
        conn.execute(T.update().where(T.c.id == row.id).values(state="cancelled"))
    assert kernel.complete_review(row.id, {}, only_if_waiting=True) is False
    with pytest.raises(IllegalTransition):  # the default stays strict for the admin API
        kernel.complete_review(row.id, {})


# ==== batch B: the student's screens ================================================================================
# The API half of the screen fixes: what the pages need to name programmes, to leave a removed programme out, to ask
# which admission the visa file is for, and to say what a plan update changed. Fictional data only.

NOTICE = "plan_updated@"
TEST_REF = TEST_STUDENT.student_ref


def _waiting(api, ref: str) -> int:
    """A student step of this programme put in the inbox (the kernel's write, simulated)."""
    with api.engine.begin() as conn:
        row = conn.execute(select(T.c.id).where(T.c.plan_id == api.plan_id, T.c.kind == "student",
                                                T.c.programme_ref == ref).order_by(T.c.id).limit(1)).first()
        conn.execute(T.update().where(T.c.id == row.id).values(state="waiting_student"))
    return row.id


def test_inbox_items_carry_programme_name(api):
    """`walk:S3:admission_card_unnamed`, `walk:S1:inbox_programme_unnamed`: every per-programme inbox item carries the
    programme's name and university from the programme store, so two cards of two programmes can be told apart."""
    from app.os.knowledge.programmes import Programme, ProgrammeStore

    ProgrammeStore(api.engine, "pai").upsert(Programme(
        ref=P1, route_key="germany_master", university="Uni Sample", name="MSc Example", aliases=(),
        start_urls=("https://uni.example/p1",), official_domains=("uni.example",)))
    tid = _waiting(api, P1)
    other = _waiting(api, "ovgu-eeit")  # not in the programme store: no name, the page words the step without one
    items = {i["id"]: i for i in api.get("/v1/os/inbox", headers=ME).json()["items"]}
    assert (items[tid]["programme_name"], items[tid]["university"]) == ("MSc Example", "Uni Sample")
    assert items[other]["programme_name"] is None
    assert all(i["programme_name"] is None for i in items.values() if i["programme_ref"] is None)


def test_removed_programme_left_out_of_the_students_pages(api):
    """`walk:S3:removed_programme_still_shown`: once the removal is accepted, the programme is no longer one of the
    plan's programmes for the pages (programme facts; and packs, visa choices and statements, which all read
    `student_plan`)."""
    from app.os.api import self_serve

    assert P1 in self_serve.student_plan(api.svc.plans, TEST_REF).programmes
    pid = propose(api)
    assert api.post(f"/v1/os/proposals/{pid}/accept", headers=ME).status_code == 200
    plan = self_serve.student_plan(api.svc.plans, TEST_REF)
    assert P1 not in plan.programmes and plan.programmes
    refs = [p["ref"] for p in api.get("/v1/os/programmes", headers=ME).json()["programmes"]]
    assert P1 not in refs and refs


def test_changes_still_name_a_removed_programme(api):
    """With the removed programme gone from the programmes page, "What changed" and the plan update still name it:
    the changes carry the names of every programme the plan had, and each notice change its programme's name."""
    from app.os.knowledge.programmes import Programme, ProgrammeStore

    ProgrammeStore(api.engine, "pai").upsert(Programme(
        ref=P1, route_key="germany_master", university="Uni Sample", name="MSc Example", aliases=(),
        start_urls=("https://uni.example/p1",), official_domains=("uni.example",)))
    pid = propose(api)
    assert api.post(f"/v1/os/proposals/{pid}/accept", headers=ME).status_code == 200
    assert api.get("/v1/os/changes", headers=ME).json()["names"][P1] == "MSc Example"
    [notice] = [i for i in api.get("/v1/os/inbox", headers=ME).json()["items"] if i["instance_key"].startswith(NOTICE)]
    assert {c["programme_name"] for c in notice["changes"] if c["programme_ref"] == P1} == {"MSc Example"}


def test_plan_update_notice_says_what_changed(api):
    """`walk:S1:plan_updated_notice_empty`: the "Your plan was updated" item says which of the student's steps were
    added, removed or changed; one whose revision changed none of the student's steps leaves the inbox."""
    pid = propose(api)
    assert api.post(f"/v1/os/proposals/{pid}/accept", headers=ME).status_code == 200
    items = api.get("/v1/os/inbox", headers=ME).json()["items"]
    [notice] = [i for i in items if i["instance_key"].startswith(NOTICE)]
    assert notice["changes"], "the removal removed some of the student's steps"
    removed = [c for c in notice["changes"] if c["change"] == "removed"]
    assert removed and all(c["title"] and c["programme_ref"] == P1 for c in removed)
    assert {c["change"] for c in notice["changes"]} <= {"added", "removed", "changed", "kept"}
    assert all(c["title"] for c in notice["changes"])
    assert all(i["changes"] == [] for i in items if not i["instance_key"].startswith(NOTICE))
    # a revision that changed only work steps (the kernel's write, simulated): nothing to tell the student
    with api.engine.begin() as conn:
        work = conn.execute(select(T.c.instance_key).where(T.c.plan_id == api.plan_id, T.c.kind == "work")
                            .limit(1)).scalar_one()
        conn.execute(insert(models.plan_revisions).values(tenant_id="pai", plan_id=api.plan_id, number=90,
                                                          cause="fact:x", diff={"added": [], "removed": [],
                                                                                "changed": [work]}))
        nid = conn.execute(insert(T).values(
            tenant_id="pai", plan_id=api.plan_id, instance_key=f"{NOTICE}r90", template_key="plan_updated",
            task_type="student.act", kind="student", inbox_kind="act", title="Your plan was updated",
            state="waiting_student", due_tz="UTC", playbook_version=1, result={"revision": 90, "cause": "fact:x"})
        ).inserted_primary_key[0]
    assert nid not in {i["id"] for i in api.get("/v1/os/inbox", headers=ME).json()["items"]}
    with api.engine.connect() as conn:
        assert conn.execute(select(T.c.state).where(T.c.id == nid)).scalar_one() == "done"


def test_statement_programmes_named(engine, clean, os_db):
    """`walk:S1:statement_programmes_raw_refs`: the statements page's programmes carry name and university."""
    from tests.os import test_api_statements as st

    web = st.api.__wrapped__(engine, clean, os_db)
    st.start(web)
    progs = web.get(f"{st.P}/statements", headers=st.me()).json()["programmes"]
    assert [(p["programme_ref"], p["name"], p["university"]) for p in progs] == [
        ("p1", "Programme p1", "Uni X"), ("p2", "Programme p2", "Uni X")]


def test_how_to_apply_names_the_programme():
    """`walk:S1:visa_how_to_apply_programme_text`: without a confirmed application route the one step names the
    programme and its university, and on the visa file it says the visa steps wait for that route."""
    from dataclasses import replace as dc_replace

    from app.os.packs.instructions import instructions
    from tests.os.test_pack_rules import inputs

    named = {"name": "MSc Example", "university": "Uni Sample"}
    [step] = instructions(inputs(facts={}), "p1", **named)[1]
    assert "MSc Example" in step.text and "Uni Sample" in step.text
    assert "this programme" not in step.text and "the university" not in step.text
    [visa] = instructions(dc_replace(inputs(facts={}), kind="visa"), "p1", **named)[1]
    assert "visa" in visa.text and "MSc Example" in visa.text and "Uni Sample" in visa.text
    assert "not confirmed yet" in instructions(inputs(facts={}), "p1")[1][0].text  # no name: still says so


def test_document_fields_have_plain_labels():
    """`walk:S1:documents_read_needs_tap`: a technical field name ("Mrz line1") has a plain label in its document
    type, and the documents API sends each field's label (None: the page words the name)."""
    from app.os.api.queries import document_out
    from app.os.documents.types import load_document_types

    types = load_document_types()
    labels = {f.name: f.label for t in types.values() for f in t.fields}
    for name in ("mrz_line1", "mrz_line2", "trf_number", "cefr", "min_pass", "scale_best"):
        assert labels[name], name
    assert "mrz" not in labels["mrz_line1"].lower()
    store = SimpleNamespace(fields=lambda _id: [
        {"field": f, "value_read": "x", "check": "ok", "reasons": [], "value_confirmed": None}
        for f in ("mrz_line1", "surname")])
    d = SimpleNamespace(id=1, doc_type="passport", filename="p.pdf", status="read", detected_type=None, pages=1,
                        error=None, created_at=None, read_at=None, confirmed_at=None)
    out = {f["field"]: f["label"] for f in document_out(store, d, [], types)["fields"]}
    assert out == {"mrz_line1": labels["mrz_line1"], "surname": labels["surname"]}


def test_visa_with_two_admissions_asks_first(engine, clean, os_db):
    """`walk:S1:visa_admitted_label_one_only`: with two admissions every admitted programme is listed, nothing is
    chosen for the student and nothing is built until they choose; with one admission it is still pre-selected."""
    from tests.os import test_api_visa as va

    gen = va.api.__wrapped__(engine, clean, os_db)
    web = next(gen)
    try:
        va.admitted(web, va.PROG)
        va.admitted(web, va.OTHER_PROG)
        body = web.get(va.V, headers=va.ME).json()
        assert body["status"] == "no_choice" and body["programme_ref"] is None
        assert body["choice"]["preselected"] is None
        assert set(body["choice"]["admitted"]) == {va.PROG, va.OTHER_PROG}
        assert web.post(f"{va.V}/build", headers=va.ME).status_code == 409
        assert not web.ctx.client.list_workflows(workflow_id_prefix="visa:", load_input=False, load_output=False)
        assert web.put(f"{va.V}/choice", headers=va.ME, json={"programme_ref": va.PROG}).status_code == 200
        body = va.settled(web)
        assert body["programme_ref"] == va.PROG and body["status"] != "no_choice"
    finally:
        next(gen, None)


# ---- batch C: F1, the visa date from the semester start ------------------------------------------------------------

VISA_NOTE = "Apply by {}: 6 weeks before your semester starts on {}. A visa usually takes about 90 days."
WAITING = "Waiting for your programme's semester start date"


def _semester_start(svc, ref: str, day: str) -> None:
    """A fictional semester start, as research or an admin would store it (confirmed, with its page and quote)."""
    from app.os.knowledge import SqlKnowledge
    from app.os.workers.manual import supply_fact

    supply_fact(svc.plans, SqlKnowledge(svc.engine, "pai"), svc.kernel, scope="programme", ref=ref,
                field="semester_start", intake_year=2027, value={"date": day},
                quote=f"Lectures start on {day}", url=f"https://uni.example/{ref}/dates", status="confirmed")


def _visa_step(engine, plan_id: int):
    with engine.connect() as conn:
        return conn.execute(select(T).where(T.c.plan_id == plan_id, T.c.instance_key == "visa_apply")).one()


def _visa_due(day: str) -> datetime:
    from app.os.compiler import end_of_day

    return end_of_day(date.fromisoformat(day), "Europe/Berlin") - timedelta(days=42)


def test_visa_date_follows_the_visa_programme(engine, clean, os_db):
    """F1 (`fact_missing:visa_target_date`): the visa step's date is 6 weeks before the semester start of the
    programme the visa file is for, cites that programme's page with a plain note, and moves when that programme
    changes: before any admission the earliest start (provisional), then the one admitted programme, then, with two
    admissions, the one the student chooses."""
    from tests.os import test_api_visa as va

    gen = va.api.__wrapped__(engine, clean, os_db)
    web = next(gen)
    try:
        uni_one, uni_two, uni_three = va.OTHER_PROG, va.PROG, "btu-artificial-intelligence"
        for ref, day in ((uni_one, "2027-10-01"), (uni_two, "2027-10-15"), (uni_three, "2027-09-15")):
            _semester_start(web.svc, ref, day)
        step = _visa_step(engine, web.plan_id)
        assert step.blocked_reason is None and step.provisional
        assert step.due_at == _visa_due("2027-09-15")
        with engine.begin() as conn:  # the admission step waits for the student (the kernel's write, simulated)
            tid = conn.execute(select(T.c.id).where(T.c.plan_id == web.plan_id,
                                                    T.c.instance_key == f"admission_result@{uni_one}")).scalar_one()
            conn.execute(T.update().where(T.c.id == tid).values(state="waiting_student"))
        r = web.post(f"/v1/os/inbox/{tid}/complete", headers=va.ME, json={"payload": {"choice": "admitted"}})
        assert r.status_code == 200, r.text
        step = _visa_step(engine, web.plan_id)
        assert step.due_at == _visa_due("2027-10-01") and not step.provisional
        assert step.citations[0] == {"source": "fact:semester_start", "url": f"https://uni.example/{uni_one}/dates",
                                     "note": VISA_NOTE.format("20 August 2027", "1 October 2027")}
        assert ["programme", uni_one, "semester_start"] in step.fact_refs
        va.admitted(web, uni_two)  # a second admission: the student chooses which one the visa is for
        assert web.put(f"{va.V}/choice", headers=va.ME, json={"programme_ref": uni_two}).status_code == 200
        step = _visa_step(engine, web.plan_id)
        assert step.due_at == _visa_due("2027-10-15")
        assert step.citations[0]["note"] == VISA_NOTE.format("3 September 2027", "15 October 2027")
    finally:
        next(gen, None)


def test_inbox_says_what_a_blocked_step_waits_for(api):
    """`walk:S1:nothing_to_do_while_blocked`: the visa step blocked on its semester start is listed (state
    `blocked`, nothing to tap) with what it waits for, in the playbook's words, instead of an empty inbox."""
    step = _visa_step(api.engine, api.plan_id)
    assert (step.state, step.blocked_reason) == ("blocked", "fact_missing:semester_start")
    items = api.get("/v1/os/inbox", headers=ME).json()["items"]
    [visa] = [i for i in items if i["instance_key"] == "visa_apply"]
    assert visa["state"] == "blocked" and visa["waiting_for"] == WAITING
    assert all(i["state"] in ("waiting_student", "blocked") for i in items)
    assert all(i["waiting_for"] is None for i in items if i["state"] == "waiting_student")
    assert api.post(f"/v1/os/inbox/{visa['id']}/complete", headers=ME, json={"payload": {}}).status_code == 409


def test_closed_notice_keeps_its_revision(api):
    """Review follow-up (batch B): an empty plan-update notice is closed with a result that keeps its revision and
    cause, so the link to the revision is not lost."""
    with api.engine.begin() as conn:
        conn.execute(insert(models.plan_revisions).values(tenant_id="pai", plan_id=api.plan_id, number=91,
                                                          cause="fact:y", diff={"added": [], "removed": [],
                                                                                "changed": []}))
        nid = conn.execute(insert(T).values(
            tenant_id="pai", plan_id=api.plan_id, instance_key=f"{NOTICE}r91", template_key="plan_updated",
            task_type="student.act", kind="student", inbox_kind="act", title="Your plan was updated",
            state="waiting_student", due_tz="UTC", playbook_version=1, result={"revision": 91, "cause": "fact:y"})
        ).inserted_primary_key[0]
    api.get("/v1/os/inbox", headers=ME)
    with api.engine.connect() as conn:
        row = conn.execute(select(T.c.state, T.c.result).where(T.c.id == nid)).one()
    assert row.state == "done"
    assert row.result == {"closed": "no_student_changes", "revision": 91, "cause": "fact:y"}


# ---- batch C fix round 1 -------------------------------------------------------------------------------------------

def test_provisional_visa_date_leaves_out_rejections(engine, clean, os_db):
    """With no visa programme yet, a programme that said "not admitted" (still in the plan until its removal is
    accepted) is never the date's source; once one admitted, only admitted programmes are."""
    from tests.os import test_api_visa as va

    gen = va.api.__wrapped__(engine, clean, os_db)
    web = next(gen)
    try:
        first, second, third = va.OTHER_PROG, va.PROG, "btu-artificial-intelligence"
        for ref, day in ((first, "2027-10-01"), (second, "2027-10-15"), (third, "2027-09-15")):
            _semester_start(web.svc, ref, day)
        assert _visa_step(engine, web.plan_id).due_at == _visa_due("2027-09-15")
        with engine.begin() as conn:  # the student's answer, as the kernel stores it (simulated)
            conn.execute(T.update().where(T.c.plan_id == web.plan_id,
                                          T.c.instance_key == f"admission_result@{third}")
                         .values(state="done", result={"choice": "rejected"}))
        web.svc.plans.recompile(web.plan_id, "test")
        step = _visa_step(engine, web.plan_id)
        assert step.due_at == _visa_due("2027-10-01") and step.provisional
        assert "earliest semester start of your programmes (1 October 2027)" in step.citations[0]["note"]
    finally:
        next(gen, None)
