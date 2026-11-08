"""P2-T7: season monitoring, notice windows, the re-check marker, student notices and reports (R-27, R-28; rows 6.23,
6.24). Fictional `.test` sites served by the fixture server; fictional programmes. Verified facts only through review."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.api.queries import waiting_items
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.changes import after_fact_change
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.review import ReviewerStore, ReviewQueue
from app.os.knowledge.sources.snapshots import SnapshotStore
from app.os.monitor import run as monitor
from app.os.monitor.config import load_config, load_texts
from app.os.monitor.windows import active_windows, contains, window_ref
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from app.os.workers import confirm_fact
from app.os.workers.jobs import JOB_FACTORIES
from tests.os.registry.helpers import inst, olist, store
from tests.os.test_api import TOKEN, contract

FAKE = Path(__file__).parent / "playbooks"
HOST = "www.alpha-university.test"
PATH = "/admissions/notice"
URL = f"https://{HOST}{PATH}"
QUOTE = "Applications close on 1 August 2027"
AT = datetime(2027, 4, 1, tzinfo=UTC)
D1, D2, D3 = date(2027, 5, 2), date(2027, 5, 3), date(2027, 5, 4)
pytestmark = pytest.mark.req("R-27", "R-28")


def page(close="Applications close on 1 August 2027") -> str:
    """The fixture university's notice with one sentence changed (so the page does not shrink)."""
    return ("<html><body><h1>Admissions notice: fall 2027</h1><p>Applications for BS Computing open on 1 June 2027. "
            f"{close}.</p><p>Fee per semester: 1000 units.</p><p><a href='/admissions/apply'>How to apply</a></p>"
            "</body></html>")


class World:
    def __init__(self, engine, os_db, sites, reports=True):
        self.engine, self.sites = engine, sites
        settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true",
                                  **({"OS_REPORTS": "1"} if reports else {})})
        self.svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: D1)
        self.kb = SqlKnowledge(engine, "pai")
        self.queue = ReviewQueue(engine, "pai", self.kb, on_fact_change=lambda sc, ref, fld, fid, st, yr, done:
                                 self.changed(sc, ref, fld, fid, st, yr))
        self.snapshots = SnapshotStore(engine, "pai")
        self.gateway = PageGateway(engine, "pai", settings, client=sites.client(), sleep=lambda s: None)
        ProgrammeStore(engine, "pai").upsert(Programme(
            ref="p1", route_key="ireland_master", university="Alpha University", name="BS Computing", aliases=(),
            start_urls=(URL,), official_domains=("alpha-university.test",)))
        reg = store(engine)
        reg.record(olist(rows=1), cause="import")
        reg.record(inst("one", region="punjab"), cause="import")
        reg.link_programme("p1", institution_id="inst:one", region="punjab", family="university", cause="import")
        self.fact_id = self.kb.upsert("programme", "p1", "deadline_close", Fact(
            {"date": "2027-08-01"}, QUOTE, URL, AT, 2027, "confirmed", intake_term="winter"))
        self.window(status="confirmed")

    def window(self, opens="03-01", closes="09-30", status="confirmed") -> int:
        quote, url = ("Notices appear in this period", "https://lists.alpha.test/seasons") if status != "unconfirmed" \
            else ("", "")
        return self.kb.upsert("registry", window_ref("punjab", "university"), "notice_window", Fact(
            {"opens": opens, "closes": closes}, quote, url, AT, 2027, status, intake_term="winter"))

    def plan(self, student="stu-1") -> int:
        return self.svc.plans.start_plan(
            __import__("app.os.contracts.route_contract", fromlist=["RouteContract"]).RouteContract.model_validate(
                contract(student, external_ref=f"ext-{student}"))).plan_id

    def changed(self, scope, ref, field, fact_id, status, year) -> None:
        after_fact_change(self.svc.plans, self.svc.kernel, scope, ref, field, fact_id, status, year, complete=False)

    def run(self, today=D1, **kw) -> dict:
        return monitor.run(self.engine, "pai", today, datetime(today.year, today.month, today.day, 3, 30, tzinfo=UTC),
                           gateway=self.gateway, snapshots=self.snapshots, knowledge=self.kb, queue=self.queue,
                           after_change=self.changed, **kw)

    def task(self, plan_id, key="apply@p1"):
        with self.engine.connect() as conn:
            return conn.execute(select(models.tasks).where(models.tasks.c.plan_id == plan_id,
                                                           models.tasks.c.instance_key == key)).one()

    def fact(self):
        return self.kb.get(self.fact_id)[3]


@pytest.fixture
def w(engine, clean, os_db, fixture_sites):
    return World(engine, os_db, fixture_sites)


@pytest.fixture
def w_off(engine, clean, os_db, fixture_sites):
    return World(engine, os_db, fixture_sites, reports=False)


def items(w, kind):
    return w.queue.list_items(kind=kind)


# --- notice windows (P2-D21) ------------------------------------------------------------------------------------------

def test_a_window_may_wrap_the_year_and_a_bad_one_is_not_a_window():
    assert contains({"opens": "03-01", "closes": "09-30"}, date(2027, 5, 2)) is True
    assert contains({"opens": "03-01", "closes": "09-30"}, date(2027, 12, 1)) is False
    assert contains({"opens": "11-15", "closes": "02-10"}, date(2027, 12, 31)) is True
    assert contains({"opens": "11-15", "closes": "02-10"}, date(2027, 1, 5)) is True
    assert contains({"opens": "11-15", "closes": "02-10"}, date(2027, 6, 1)) is False
    for bad in (None, "03-01", {"opens": "3-1", "closes": "09-30"}, {"opens": "13-01", "closes": "09-30"},
                {"opens": "03-01"}, {"opens": "02-30", "closes": "09-30"}):
        assert contains(bad, date(2027, 5, 2)) is None


def test_only_a_confirmed_window_counts_and_a_season_is_never_invented(w):
    assert [(x.region, x.family, x.term, x.year) for x in active_windows(w.engine, "pai", D1)] == [
        ("punjab", "university", "winter", 2027)]
    assert active_windows(w.engine, "pai", date(2027, 12, 1)) == []  # off season
    w.kb.revise(w.window(), status="unconfirmed", cause="manual")  # (re-writing the same window returns its id)
    assert active_windows(w.engine, "pai", D1) == []  # an unconfirmed window decides nothing
    w.kb.upsert("registry", "badref", "notice_window", Fact({"opens": "01-01", "closes": "12-31"}, "q", "https://x.test/y",
                                                            AT, 2027, "confirmed"))
    assert active_windows(w.engine, "pai", D1) == []  # no region:family in the ref


# --- the proof for row 6.24 ---------------------------------------------------------------------------------------------

@pytest.mark.req("R-27")
def test_a_page_change_in_season_resets_the_fact_pauses_the_step_and_queues_the_item(w):
    plan = w.plan()
    assert w.task(plan).blocked_reason is None and not w.task(plan).provisional
    first = w.run(D1)
    assert (first["windows"], first["urls"], first["facts"], first["taken_back"]) == (1, 1, 1, 0)
    assert w.fact().status == "confirmed" and items(w, "change") == []
    # the official page changes: the deadline moved
    w.sites.set_page(HOST, PATH, page("Applications close on 15 August 2027"))
    second = w.run(D2)  # seen once: a temporary page problem must not cost a fact
    assert (second["taken_back"], second["seen_once"], second["page_changed"]) == (0, 1, 1)
    assert w.fact().status == "confirmed" and w.task(plan).blocked_reason is None and items(w, "change") == []
    third = w.run(D3)  # seen on a second, separate run
    assert third["taken_back"] == 1
    f = w.fact()
    assert (f.status, f.recheck) == ("unconfirmed", "monitor") and "changed" in f.conflict_note
    last = w.kb.revisions(w.fact_id)[-1]
    assert (last.cause, last.actor, last.before["status"], last.after["status"]) == ("monitor", "monitor", "confirmed",
                                                                                    "unconfirmed")
    step = w.task(plan)  # the step it dates waits (P2-D20)
    assert step.state == "blocked" and step.blocked_reason == "fact_rechecking:deadline_close"
    with w.engine.connect() as conn:  # the student's plan was revised through the kernel
        kinds = [r.type for r in conn.execute(select(models.events.c.type).where(models.events.c.plan_id == plan))]
    assert kinds.count("plan_revised") >= 1
    with w.engine.connect() as conn:  # and the student is told: the plan's "updated" notice and the bell event
        notices = conn.execute(select(models.tasks.c.title).where(models.tasks.c.plan_id == plan,
                                                                  models.tasks.c.template_key == "plan_updated")).all()
    assert [n.title for n in notices] == ["Your plan was updated"]
    [item] = items(w, "change")  # and the item is queued, with where to look
    assert (item.fact_id, item.payload["reason"], item.payload["url"]) == (w.fact_id, "quote_gone", URL)
    assert item.payload["snapshot_id"] and w.snapshots.get(item.payload["snapshot_id"]).text.count("15 August") == 1
    [waiting] = waiting_items(w.engine, "pai", "stu-1", w.svc.plans.playbooks)  # the inbox says why, in approved words
    assert waiting["waiting_for"] == load_texts()["fact_rechecking_waiting"]
    # a checker confirms it again from the new page: the step is free
    confirm_fact(w.svc.plans, w.kb, w.svc.kernel, w.fact_id, value={"date": "2027-08-15"},
                 quote="Applications close on 15 August 2027", url=URL, status="confirmed")
    assert w.fact().recheck is None and w.task(plan).blocked_reason is None and w.task(plan).state != "blocked"


def test_a_run_is_once_a_day_and_an_unchanged_page_changes_nothing(w):
    w.plan()
    assert w.run(D1)["taken_back"] == 0
    assert w.run(D1)["already_ran"] is True
    n = len(w.sites.requests)
    w.run(D1)
    assert len(w.sites.requests) == n  # the second call of the day read nothing
    with w.engine.connect() as conn:
        assert conn.execute(select(models.monitor_runs.c.finished_at)).scalar() is not None
    assert w.fact().status == "confirmed" and w.kb.revisions(w.fact_id)[-1].cause != "monitor"


def test_off_season_nothing_is_read(w):
    w.plan()
    counts = w.run(date(2027, 12, 1))
    assert counts["windows"] == 0 and counts["urls"] == 0
    assert not [r for r in w.sites.requests if r[0] == HOST]


def test_a_gone_page_counts_only_when_seen_twice_and_a_failing_page_never_does(w):
    w.plan()
    w.run(D1)
    w.sites.set_page(HOST, PATH, "server trouble", status=500)
    broken = w.run(D2)
    assert broken["unreadable"] == 1 and broken["taken_back"] == 0 and w.fact().status == "confirmed"
    w.sites.set_page(HOST, PATH, "not found", status=404)
    once = w.run(D3)
    assert (once["taken_back"], once["seen_once"]) == (0, 1) and w.fact().status == "confirmed"
    w.sites.set_page(HOST, PATH, page())
    back = w.run(date(2027, 5, 5))  # the page is back: what was seen once is forgotten
    assert back["taken_back"] == 0 and back["seen_once"] == 0
    w.sites.set_page(HOST, PATH, "not found", status=404)
    assert w.run(date(2027, 5, 6))["seen_once"] == 1  # counting starts again
    assert w.run(date(2027, 5, 7))["taken_back"] == 1
    assert items(w, "change")[0].payload["reason"] == "page_gone"


def test_a_verified_fact_is_taken_back_too_and_its_open_verify_item_is_voided(w):
    k = w.kb
    k.set_status(w.fact_id, "verified", cause="review", actor="tester")
    item, _ = w.queue.open_item("verify", dedupe_key="v", fact_id=w.fact_id)
    w.sites.set_page(HOST, PATH, page("Applications close on 9 September 2027"))
    w.plan()
    w.run(D1)
    assert w.run(D2)["taken_back"] == 1
    assert w.fact().status == "unconfirmed"
    assert w.queue.get_item(item).resolution == "void"


def test_the_monitor_only_looks_at_facts_of_the_windows_region_and_family(w):
    w.kb.upsert("programme", "p1", "fee_per_semester", Fact(1000, "Fee per semester: 1000 units", URL, AT, 2027, "confirmed",
                                                            intake_term="winter"))
    w.kb.upsert("programme", "p1", "fee_next", Fact(5, "q", "https://other.test/x", AT, 2026, "confirmed"))  # another year
    counts = w.run(D1)
    assert counts["facts"] == 2 and counts["urls"] == 1  # the deadline and the fee share one page; the 2026 fact is out


def test_the_job_is_registered_but_scheduled_only_with_the_flag(engine, clean, os_db):
    jobs = {name: cron for name, cron, _ in JOB_FACTORIES}
    assert jobs["monitor"] == "30 3 * * *"
    settings = load_settings({"OS_DATABASE_URL": os_db})
    assert settings.monitor is False
    factory = dict((n, f) for n, _, f in JOB_FACTORIES)["monitor"]
    assert factory(settings, engine, None, None) is None  # no job at all: nothing scheduled, nothing ticked
    assert load_settings({"OS_DATABASE_URL": os_db, "OS_MONITOR": "1"}).monitor is True


# --- reports (row 6.23) and the owner ruling of 2026-11-08 ---------------------------------------------------------------

def make_api(w):
    app = FastAPI()
    app.include_router(build_router(lambda: w.svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    return TestClient(app)


@pytest.fixture
def api(w):
    c = make_api(w)
    c.plan = w.plan("stu-1")
    c.plan2 = w.plan("stu-2")
    c.plan3 = w.plan("stu-3")
    return c


S1, S2, S3 = {"X-Test-Student": "stu-1"}, {"X-Test-Student": "stu-2"}, {"X-Test-Student": "stu-3"}


def report(api, w, headers=S1, reason="wrong_date", text=None, fid=None):
    return api.post(f"/v1/os/facts/{fid or w.fact_id}/report", headers=headers, json={"reason": reason, "text": text})


def blocked(w, plan) -> str | None:
    return w.task(plan).blocked_reason


@pytest.mark.req("R-28")
def test_a_report_shows_not_confirmed_to_everyone_but_only_the_reporters_steps_wait(w, api):
    r = report(api, w, text="My teacher says it moved to September.")
    assert r.status_code == 200 and r.json()["status"] == "received"
    f = w.fact()
    assert (f.status, f.recheck) == ("unconfirmed", "report")  # "not confirmed" on every screen at once
    assert "September" not in (f.conflict_note or "")  # the student's words never reach the fact
    assert w.kb.revisions(w.fact_id)[-1].cause == "report"
    assert blocked(w, api.plan) == "fact_rechecking:deadline_close" and w.task(api.plan).state == "blocked"
    for other in (api.plan2, api.plan3):  # the others keep running, on a date marked provisional
        assert blocked(w, other) is None and w.task(other).state != "blocked" and w.task(other).provisional
    [item] = items(w, "report")
    assert item.fact_id == w.fact_id and item.payload["reports"][0]["reason"] == "wrong_date"
    assert "September" in item.payload["reports"][0]["text"]  # only the review item holds the words
    with w.engine.connect() as conn:  # the reporter is told: the plan's "updated" notice and the revision
        notice = conn.execute(select(models.tasks.c.title).where(models.tasks.c.plan_id == api.plan,
                                                                 models.tasks.c.template_key == "plan_updated")).all()
    assert [n.title for n in notice] == ["Your plan was updated"]


@pytest.mark.req("R-28")
def test_three_different_students_make_it_everyones_wait_and_one_student_twice_does_not(w, api):
    report(api, w, S1)
    assert report(api, w, S1, reason="other").status_code == 200  # the same student again: still one reporter
    assert w.fact().recheck == "report" and blocked(w, api.plan2) is None
    report(api, w, S2)
    assert w.fact().recheck == "report" and blocked(w, api.plan2) == "fact_rechecking:deadline_close"  # the reporter
    assert blocked(w, api.plan3) is None
    report(api, w, S3)  # the third different student
    assert w.fact().recheck == "report_escalated"
    assert all(blocked(w, p) == "fact_rechecking:deadline_close" for p in (api.plan, api.plan2, api.plan3))
    assert len(items(w, "report")) == 1 and items(w, "report")[0].join_count == 3  # one item, joined each time


@pytest.mark.req("R-28")
def test_a_reviewer_who_agrees_makes_it_everyones_wait_and_asks_for_the_original(w, api):
    report(api, w, S1)
    reviewer, _ = ReviewerStore(w.engine, "pai").add("amina", "Amina", "checker")
    [item] = items(w, "report")
    out = w.queue.resolve(item.id, reviewer, "agrees", "the page does say September")
    assert out["resolution"] == "agrees"
    assert w.fact().recheck == "report_escalated" and blocked(w, api.plan3) == "fact_rechecking:deadline_close"
    [c] = items(w, "collect")
    assert c.fact_id == w.fact_id and c.payload["reason"] == "reported"


@pytest.mark.req("R-28")
def test_a_dismissed_report_puts_the_fact_back_and_the_step_runs_again(w, api):
    """The end-to-end recovery: report, dismiss, the step is ready again."""
    w.kb.set_status(w.fact_id, "verified", cause="review", actor="tester")
    report(api, w)
    assert w.fact().status == "unconfirmed" and blocked(w, api.plan) == "fact_rechecking:deadline_close"
    verify, _ = w.queue.open_item("verify", dedupe_key="v", fact_id=w.fact_id)
    reviewer, _ = ReviewerStore(w.engine, "pai").add("amina", "Amina", "checker")
    [item] = items(w, "report")
    with pytest.raises(Exception):  # a note is needed
        w.queue.resolve(item.id, reviewer, "dismissed", " ")
    out = w.queue.resolve(item.id, reviewer, "dismissed", "the page still says 1 August")
    assert (out["resolution"], out["fact_status"]) == ("stands", "verified")  # the status it had before
    f = w.fact()
    assert (f.status, f.recheck) == ("verified", None)
    last = w.kb.revisions(w.fact_id)[-1]
    assert (last.cause, last.actor) == ("review", "amina") and last.before["status"] == "unconfirmed"
    step = w.task(api.plan)
    assert step.blocked_reason is None and step.state != "blocked" and not step.provisional
    assert w.queue.get_item(verify).resolution == "void"


@pytest.mark.req("R-27")
def test_a_change_item_can_say_the_fact_stands(w):
    plan = w.plan()
    w.run(D1)
    w.sites.set_page(HOST, PATH, page("Applications close on 15 August 2027"))
    w.run(D2)
    w.run(D3)
    assert w.task(plan).blocked_reason == "fact_rechecking:deadline_close"
    [item] = items(w, "change")
    reviewer, _ = ReviewerStore(w.engine, "pai").add("amina", "Amina", "checker")
    assert w.queue.resolve(item.id, reviewer, "stands", "a typo on the page, fixed by the office")["fact_status"] == "confirmed"
    assert w.fact().recheck is None and w.task(plan).blocked_reason is None


def test_dismissing_a_report_closes_it_plainly_when_nothing_took_the_fact_back(w):
    w.kb.revise(w.fact_id, status="unconfirmed", conflict_note="never confirmed", cause="manual")  # no re-check marker
    item, _ = w.queue.open_item("report", dedupe_key="r", fact_id=w.fact_id)
    reviewer, _ = ReviewerStore(w.engine, "pai").add("amina", "Amina", "checker")
    out = w.queue.resolve(item, reviewer, "dismissed", "nothing to put back")
    assert out["resolution"] == "dismissed" and w.fact().status == "unconfirmed"


def test_a_new_round_of_reports_counts_its_own_reporters_only(w, api):
    report(api, w, S1)
    report(api, w, S2)
    reviewer, _ = ReviewerStore(w.engine, "pai").add("amina", "Amina", "checker")
    [first] = items(w, "report")
    w.queue.resolve(first.id, reviewer, "dismissed", "the page still says so")  # round one ends: the fact is back
    assert (w.fact().status, w.fact().recheck) == ("confirmed", None) and blocked(w, api.plan) is None
    report(api, w, S3)  # round two: one reporter, although three different students have reported over time
    assert w.fact().recheck == "report" and blocked(w, api.plan3) == "fact_rechecking:deadline_close"
    assert blocked(w, api.plan) is None and blocked(w, api.plan2) is None  # earlier, closed reports hold nothing
    report(api, w, S1)
    report(api, w, S2)  # three in this round
    assert w.fact().recheck == "report_escalated"


def test_a_fact_that_changed_after_it_was_taken_back_is_not_put_back(w):
    from app.os.knowledge.review import ReviewError

    w.plan()
    w.kb.revise(w.fact_id, status="unconfirmed", recheck="monitor", cause="monitor")
    item, _ = w.queue.open_item("change", dedupe_key="c", fact_id=w.fact_id)
    w.kb.revise(w.fact_id, value={"date": "2027-09-01"}, quote="Applications close on 1 September 2027", cause="research")
    reviewer, _ = ReviewerStore(w.engine, "pai").add("amina", "Amina", "checker")
    with pytest.raises(ReviewError) as e:
        w.queue.resolve(item, reviewer, "stands", "ok")
    assert e.value.status == 409 and w.fact().status == "unconfirmed"


def test_sync_opens_a_verify_item_for_every_fact_being_rechecked(w):
    w.kb.revise(w.fact_id, status="unconfirmed", recheck="monitor", cause="monitor")
    w.queue.sync()
    [v] = [i for i in items(w, "verify") if i.fact_id == w.fact_id]
    reviewer, _ = ReviewerStore(w.engine, "pai").add("amina", "Amina", "checker")
    w.queue.submit_review(v.id, reviewer, "check", "correct")  # the first positive check confirms it again
    assert (w.fact().status, w.fact().recheck) == ("confirmed", None)


def test_only_a_fact_the_students_plan_shows_can_be_reported(w, api):
    other = w.kb.upsert("programme", "p9", "deadline_close", Fact({"date": "2027-08-01"}, "q", "https://x.test/y", AT, 2027,
                                                                  "confirmed"))
    assert report(api, w, fid=other).status_code == 404
    assert api.post(f"/v1/os/facts/{w.fact_id}/report", headers={"X-Test-Student": "nobody"},
                    json={"reason": "other"}).status_code == 404  # no plan
    assert report(api, w, fid=9999).status_code == 404
    assert api.post(f"/v1/os/facts/{w.fact_id}/report", json={"reason": "other"}).status_code == 401
    assert w.fact().status == "confirmed"


def test_bad_reports_are_refused(w, api):
    url = f"/v1/os/facts/{w.fact_id}/report"
    assert api.post(url, headers=S1, json={"reason": "nonsense"}).status_code == 422
    assert api.post(url, headers=S1, json={"reason": "other", "text": "x" * 3000}).status_code == 422
    assert api.post(url, headers=S1, json={"reason": "other", "extra": 1}).status_code == 422
    assert w.fact().status == "confirmed" and items(w, "report") == []


def test_a_student_may_report_only_a_few_different_facts_a_day(w, api):
    cap = load_config().max_reported_facts_per_day
    ids = [w.kb.upsert("programme", "p1", f"field_{i}", Fact(i, "q", URL, AT, 2027, "confirmed", intake_term="winter"))
           for i in range(cap + 1)]
    for fid in ids[:cap]:
        assert report(api, w, fid=fid, reason="other").status_code == 200
    assert report(api, w, fid=ids[cap], reason="other").status_code == 429
    assert report(api, w, fid=ids[0], reason="other").status_code == 200  # the same fact again


def test_the_limit_holds_when_two_requests_arrive_at_once(w, api):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace

    from app.os.monitor.reports import ReportError, report_facts

    cfg = replace(load_config(), max_reported_facts_per_day=1)
    b = w.kb.upsert("programme", "p1", "fee_per_semester", Fact(1000, "Fee per semester: 1000 units", URL, AT, 2027,
                                                                "confirmed", intake_term="winter"))
    def go(fid):
        try:
            return report_facts(w.engine, "pai", "stu-1", [fid], "other", None, datetime.now(UTC), knowledge=w.kb,
                                queue=w.queue, config=cfg)["status"]
        except ReportError as e:
            return e.status
    with ThreadPoolExecutor(2) as pool:
        got = sorted(map(str, pool.map(go, [w.fact_id, b])))
    assert got == ["429", "received"]
    with w.engine.connect() as conn:
        assert len(conn.execute(select(models.fact_reports.c.fact_id).distinct()).all()) == 1


def test_the_report_link_reports_every_fact_behind_a_source_or_none_of_them(w, api):
    cap = load_config().max_reported_facts_per_day
    for i in range(cap):  # cap + 1 facts share the page: the batch is too big, so none of it is applied
        w.kb.upsert("programme", "p1", f"extra_{i}", Fact(i, "q", URL, AT, 2027, "confirmed", intake_term="winter"))
    r = api.post("/v1/os/sources/report", headers=S1, json={"url": URL, "reason": "page_changed"})
    assert r.status_code == 429
    with w.engine.connect() as conn:
        assert conn.execute(select(models.fact_reports.c.id)).all() == []
    assert w.fact().status == "confirmed" and items(w, "report") == []
    ok = api.post("/v1/os/sources/report", headers=S2, json={"url": "https://nowhere.test/", "reason": "other"})
    assert ok.status_code == 404


def test_a_source_report_of_a_few_facts_reports_them_all(w, api):
    w.kb.upsert("programme", "p1", "fee_per_semester", Fact(1000, "Fee per semester: 1000 units", URL, AT, 2027,
                                                            "confirmed", intake_term="winter"))
    assert api.post("/v1/os/sources/report", headers=S1, json={"url": URL, "reason": "page_changed"}).status_code == 200
    assert {i.field for i in items(w, "report")} == {"deadline_close", "fee_per_semester"}


def test_the_link_is_offered_only_under_pages_that_have_facts(w, api):
    assert api.get("/v1/os/report/sources", headers=S1).json() == {"urls": [URL]}
    assert api.get("/v1/os/report/sources", headers={"X-Test-Student": "nobody"}).json() == {"urls": []}


def test_the_report_texts_are_the_approved_ones(w, api):
    got = api.get("/v1/os/report/texts", headers=S1).json()
    assert [r["code"] for r in got["reasons"]] == list(load_config().report_reasons)
    assert got["texts"]["report_link"] == "Report as wrong" and got["reasons"][0]["label"] == "The date is wrong"
    assert api.get("/v1/os/report/texts").status_code == 401
    assert "standing approval" in (Path(__file__).parents[2] / "app/os/monitor/texts.yaml").read_text()


# --- the flags off ---------------------------------------------------------------------------------------------------------

def test_with_reports_off_the_routes_do_not_exist_and_nothing_is_marked(w_off):
    c = make_api(w_off)
    plan = w_off.plan("stu-1")
    h = {"X-Test-Student": "stu-1"}
    assert c.get("/v1/os/report/texts", headers=h).status_code == 404  # so the link hides
    assert c.get("/v1/os/report/sources", headers=h).status_code == 404
    assert c.post(f"/v1/os/facts/{w_off.fact_id}/report", headers=h, json={"reason": "other"}).status_code == 404
    assert c.post("/v1/os/sources/report", headers=h, json={"url": URL, "reason": "other"}).status_code == 404
    assert w_off.fact().status == "confirmed" and w_off.task(plan).blocked_reason is None
    assert load_settings({"OS_DATABASE_URL": "x"}).reports is False


def test_the_suspect_path_keeps_fact_missing_when_monitor_and_reports_are_off(w_off):
    from app.os.knowledge.sources.suspect import drop_domain_facts

    plan = w_off.plan()
    drop_domain_facts(w_off.engine, "pai", w_off.kb, HOST, w_off.changed)  # no marker given: today's behaviour
    assert w_off.fact().status == "unconfirmed" and w_off.fact().recheck is None
    assert w_off.task(plan).blocked_reason is None or w_off.task(plan).blocked_reason.startswith("fact_missing")
    assert not (w_off.task(plan).blocked_reason or "").startswith("fact_rechecking")


def test_drop_domain_facts_marks_the_facts_for_recheck_when_the_flags_are_on(w):
    from app.os.knowledge.sources.suspect import drop_domain_facts

    plan = w.plan()
    drop_domain_facts(w.engine, "pai", w.kb, HOST, w.changed, "monitor")
    assert w.fact().recheck == "monitor" and w.task(plan).blocked_reason == "fact_rechecking:deadline_close"


# --- sanity: a bad page changes nothing ---------------------------------------------------------------------------------------

def test_a_long_page_replaced_by_a_short_notice_is_a_change_after_the_failures_in_a_row(w):
    """The sanity guard delays a change, never hides it."""
    plan = w.plan()
    w.run(D1)
    good = w.snapshots.latest(URL)
    w.sites.set_page(HOST, PATH, "<html><body><p>Down for maintenance.</p></body></html>")
    first = w.run(D2)
    assert (first["unreadable"], first["seen_once"], first["taken_back"]) == (1, 1, 0)
    assert w.fact().status == "confirmed" and w.task(plan).blocked_reason is None and items(w, "change") == []
    assert w.snapshots.latest(URL).id == good.id  # the broken page is kept, flagged, and never "the last clean one"
    flagged = w.snapshots.latest(URL, clean_only=False)
    assert flagged.flagged == "sanity_shrunk" and flagged.id != good.id
    second = w.run(D3)  # the second failure in a row
    assert second["taken_back"] == 1
    f = w.fact()
    assert (f.status, f.recheck) == ("unconfirmed", "monitor")
    assert w.task(plan).blocked_reason == "fact_rechecking:deadline_close"  # the steps stop running on the old date
    [per_url] = [i for i in items(w, "change") if i.subject == URL]  # one item for the page, with the flagged snapshot
    assert per_url.payload["reason"] == "sanity_shrunk" and per_url.payload["snapshot_id"] == flagged.id
    assert w.snapshots.latest(URL).id == good.id
    assert w.run(date(2027, 5, 5))["taken_back"] == 0  # nothing monitored any more, no second item
    assert len([i for i in items(w, "change") if i.subject == URL]) == 1


def test_a_page_where_every_quote_changed_is_a_change_after_the_failures_in_a_row(w):
    w.kb.upsert("programme", "p1", "fee_per_semester", Fact(1000, "Fee per semester: 1000 units", URL, AT, 2027,
                                                            "confirmed", intake_term="winter"))
    plan = w.plan()
    w.run(D1)
    other = page("Applications close on 15 August 2027").replace("Fee per semester: 1000 units", "Fee per semester: 1200 units")
    w.sites.set_page(HOST, PATH, other)
    first = w.run(D2)
    assert (first["unreadable"], first["seen_once"], first["taken_back"]) == (1, 2, 0)
    assert w.fact().status == "confirmed"
    second = w.run(D3)
    assert second["taken_back"] == 2
    assert w.fact().recheck == "monitor" and w.task(plan).blocked_reason == "fact_rechecking:deadline_close"
    [per_url] = [i for i in items(w, "change") if i.subject == URL]
    assert per_url.payload["reason"] == "sanity_no_quote" and sorted(per_url.payload["facts"]) != []
    assert w.snapshots.latest(URL, clean_only=False).flagged == "sanity_no_quote"


def test_a_page_that_passes_again_forgets_the_failures(w):
    w.plan()
    w.run(D1)
    w.sites.set_page(HOST, PATH, "<html><body><p>Down for maintenance.</p></body></html>")
    assert w.run(D2)["seen_once"] == 1
    w.sites.set_page(HOST, PATH, page())
    assert w.run(D3)["seen_once"] == 0  # a good page: counting starts again
    w.sites.set_page(HOST, PATH, "<html><body><p>Down for maintenance.</p></body></html>")
    assert w.run(date(2027, 5, 5))["taken_back"] == 0  # one failure again, not two in a row


def test_the_sanity_settings_are_in_config():
    cfg = load_config()
    assert (cfg.seen_runs_needed, cfg.sanity_no_match_min_facts, cfg.sanity_max_shrink_percent,
            cfg.sanity_failures_needed) == (2, 2, 60, 2)


# --- runs: one at a time, and a cut-off run is finished ---------------------------------------------------------------------

def test_a_run_another_worker_holds_is_not_run_twice_and_the_retry_tick_finishes_a_cut_off_run(w):
    """The day's lock is a session advisory lock on an idle connection: no transaction stays open during the run."""
    from sqlalchemy import insert as sql_insert

    w.plan()
    assert w.run(D1, only_unfinished=True) == {"nothing_to_finish": True}  # no run today: the retry does nothing
    with w.engine.begin() as conn:  # a run that started and was cut off
        conn.execute(sql_insert(models.monitor_runs).values(tenant_id="pai", run_date=D1, started_at=AT))
    from sqlalchemy import func

    with w.engine.connect() as holder:  # another worker is running it
        holder.execute(select(func.pg_advisory_lock(monitor.lock_key("pai", D1))))
        holder.commit()
        assert w.run(D1) == {"locked": True}
        assert w.run(D1, only_unfinished=True) == {"locked": True}
        holder.execute(select(func.pg_advisory_unlock(monitor.lock_key("pai", D1))))
        holder.commit()
    done = w.run(D1, only_unfinished=True)  # the lock is gone: the retry tick finishes it
    assert done["urls"] == 1 and "already_ran" not in done
    assert w.run(D1, only_unfinished=True)["already_ran"] is True  # and then does nothing


def test_a_rechecked_fact_that_is_confirmed_again_loses_the_marker_whatever_path_confirms_it(w):
    for how in ("confirm", "upsert", "set_status", "revise"):
        w.kb.revise(w.fact_id, status="unconfirmed", recheck="monitor", cause="monitor")
        assert w.fact().recheck == "monitor"
        if how == "confirm":
            w.kb.confirm(w.fact_id, value={"date": "2027-08-01"}, quote=QUOTE, url=URL, status="confirmed")
        elif how == "upsert":
            w.kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-08-01"}, QUOTE, URL, AT, 2027,
                                                                  "confirmed", intake_term="winter"))
        elif how == "set_status":
            w.kb.set_status(w.fact_id, "confirmed", cause="manual")
        else:
            w.kb.revise(w.fact_id, status="confirmed", cause="manual")
        assert (w.fact().status, w.fact().recheck) == ("confirmed", None), how


def test_only_a_high_stakes_fact_under_recheck_blocks_a_step(w):
    plan = w.plan()
    w.kb.revise(w.fact_id, status="unconfirmed", recheck="monitor", cause="monitor")
    w.changed("programme", "p1", "deadline_close", w.fact_id, "unconfirmed", 2027)
    assert w.task(plan).blocked_reason == "fact_rechecking:deadline_close"
    w.kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-08-01"}, QUOTE, URL, AT, 2027, "unconfirmed",
                                                          intake_term="winter", fact_class="application_route",
                                                          recheck="monitor"))
    w.changed("programme", "p1", "deadline_close", w.fact_id, "unconfirmed", 2027)
    assert w.task(plan).blocked_reason is None  # not high-stakes: the step runs on a provisional date, as before


# --- the migration --------------------------------------------------------------------------------------------------------

def test_os_0030_goes_back_and_refuses_to_lose_records(engine, clean, os_db):
    from tests.os.conftest import run_alembic

    kb = SqlKnowledge(engine, "pai")
    fid = kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-08-01"}, QUOTE, URL, AT, 2027, "confirmed"))
    kb.revise(fid, status="unconfirmed", recheck="monitor", cause="monitor")
    engine.dispose()
    with pytest.raises(Exception):  # a fact is being re-checked: nothing is thrown away silently
        run_alembic(["downgrade", "os_0029"], os_db)
    from tests.os.conftest import truncate_os_tables
    from sqlalchemy import create_engine

    eng = create_engine(os_db)
    try:
        truncate_os_tables(eng)
    finally:
        eng.dispose()
    run_alembic(["downgrade", "os_0029"], os_db)
    run_alembic(["upgrade", "os@head"], os_db)
