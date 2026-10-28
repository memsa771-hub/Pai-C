"""Slice 9a Task 11 (batch A): the rehearsal fix pass, backend. One test (or a few) per fixed failure, and the four old
deferred minors of Slice 7 (spec S9-D10). Fictional data only."""
# ruff: noqa: F811  (`api` is a fixture imported from test_api_replan, so test arguments of that name redefine it)

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

from app.os import clock, models
from app.os.compiler import CONFIRM_TYPE
from app.os.kernel import Outcome
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

    def row(state, ref="gone", kind="work", protected=False):
        return {"state": state, "kind": kind, "protected": protected, "skipped_draft": None, "task_type": "x",
                "programme_ref": ref}

    stored = {"review": row("waiting_review"), "running": row("running"), "input": row("waiting_student"),
              "kept": row("pending", protected=True), "inbox": row("waiting_student", kind="student"),
              "route_check": row("waiting_review", ref=None), "stays_check": row("waiting_review", ref="stays")}
    d = diff(stored, {"live@stays": SimpleNamespace(programme_ref="stays")}, {})
    assert sorted(d.removed) == ["inbox", "review"]
    assert sorted(d.skipped_started) == ["input", "route_check", "running", "stays_check"]
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


def _row(key: str, state: str, kind: str = "student", protected: bool = False) -> TaskRow:
    return TaskRow(key, key.split("@")[0], P1, state, kind, False, protected, None, None, 1, ())


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
    checking = _rejected(_row(f"a@{P1}", "pending"), _row(f"confirm_fact@{P1}:x", "waiting_review", kind="work"))
    assert checking == R  # a fact check waiting for research goes with the programme (F2)


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
