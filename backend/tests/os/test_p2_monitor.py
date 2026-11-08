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
from app.os.knowledge.review import ReviewQueue
from app.os.knowledge.sources.snapshots import SnapshotStore
from app.os.monitor import run as monitor
from app.os.monitor.config import load_config, load_texts
from app.os.monitor.windows import active_windows, contains, window_ref
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from app.os.workers import confirm_fact
from app.os.workers.jobs import JOB_FACTORIES
from tests.os.registry.helpers import inst, olist, store
from tests.os.test_api import ADMIN, TOKEN, contract

FAKE = Path(__file__).parent / "playbooks"
HOST = "www.alpha-university.test"
PATH = "/admissions/notice"
URL = f"https://{HOST}{PATH}"
QUOTE = "Applications close on 1 August 2027"
AT = datetime(2027, 4, 1, tzinfo=UTC)
D1, D2 = date(2027, 5, 2), date(2027, 5, 3)
pytestmark = pytest.mark.req("R-27", "R-28")


class World:
    def __init__(self, engine, os_db, sites):
        self.engine, self.sites = engine, sites
        settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
        self.svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: D1)
        self.kb = SqlKnowledge(engine, "pai")
        self.queue = ReviewQueue(engine, "pai", self.kb)
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
                contract(student))).plan_id

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
    w.sites.set_page(HOST, PATH, "<html><body><p>Applications close on 15 August 2027.</p></body></html>")
    second = w.run(D2)
    assert (second["taken_back"], second["page_changed"]) == (1, 1)
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


def test_a_gone_page_takes_its_facts_back_but_a_failing_page_does_not(w):
    w.plan()
    w.run(D1)
    w.sites.set_page(HOST, PATH, "server trouble", status=500)
    broken = w.run(D2)
    assert broken["unreadable"] == 1 and broken["taken_back"] == 0 and w.fact().status == "confirmed"
    w.sites.set_page(HOST, PATH, "not found", status=404)
    gone = w.run(date(2027, 5, 4))
    assert gone["taken_back"] == 1
    assert items(w, "change")[0].payload["reason"] == "page_gone"


def test_a_verified_fact_is_taken_back_too_and_its_open_verify_item_is_voided(w):
    k = w.kb
    k.set_status(w.fact_id, "verified", cause="review", actor="tester")
    item, _ = w.queue.open_item("verify", dedupe_key="v", fact_id=w.fact_id)
    w.sites.set_page(HOST, PATH, "<p>Applications close on 9 September 2027</p>")
    w.plan()
    assert w.run(D1)["taken_back"] == 1
    assert w.fact().status == "unconfirmed"
    assert w.queue.get_item(item).resolution == "void"


def test_the_monitor_only_looks_at_facts_of_the_windows_region_and_family(w):
    w.kb.upsert("programme", "p1", "fee_per_semester", Fact(1000, "Fee per semester: 1000 units", URL, AT, 2027, "confirmed",
                                                            intake_term="winter"))
    w.kb.upsert("programme", "p1", "fee_next", Fact(5, "q", "https://other.test/x", AT, 2026, "confirmed"))  # another year
    counts = w.run(D1)
    assert counts["facts"] == 2 and counts["urls"] == 1  # the deadline and the fee share one page; the 2026 fact is out


def test_the_job_is_registered_and_does_nothing_without_the_flag(engine, clean, os_db):
    jobs = {name: cron for name, cron, _ in JOB_FACTORIES}
    assert jobs["monitor"] == "30 3 * * *"
    settings = load_settings({"OS_DATABASE_URL": os_db})
    assert settings.monitor is False
    factory = dict((n, f) for n, _, f in JOB_FACTORIES)["monitor"]
    assert factory(settings, engine, None, None)() is None
    assert load_settings({"OS_DATABASE_URL": os_db, "OS_MONITOR": "1"}).monitor is True


# --- reports (row 6.23) -----------------------------------------------------------------------------------------------------

@pytest.fixture
def api(w):
    app = FastAPI()
    app.include_router(build_router(lambda: w.svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.plan = w.plan()
    return c


S1, S2 = {"X-Test-Student": "stu-1"}, {"X-Test-Student": "stu-2"}


@pytest.mark.req("R-28")
def test_a_student_report_resets_the_fact_pauses_the_step_and_queues_the_item(w, api):
    r = api.post(f"/v1/os/facts/{w.fact_id}/report", headers=S1,
                 json={"reason": "wrong_date", "text": "My teacher says it moved to September."})
    assert r.status_code == 200 and r.json()["status"] == "received"
    f = w.fact()
    assert (f.status, f.recheck) == ("unconfirmed", "report")
    assert "September" not in (f.conflict_note or "")  # the student's words never reach the fact
    assert w.kb.revisions(w.fact_id)[-1].cause == "report"
    step = w.task(api.plan)
    assert step.state == "blocked" and step.blocked_reason == "fact_rechecking:deadline_close"
    [item] = items(w, "report")
    assert item.fact_id == w.fact_id and item.payload["reports"][0]["reason"] == "wrong_date"
    assert "September" in item.payload["reports"][0]["text"]  # only the review item holds them
    # the same fact reported again joins the open item
    again = api.post(f"/v1/os/facts/{w.fact_id}/report", headers=S1, json={"reason": "other"})
    assert again.status_code == 200 and len(items(w, "report")) == 1
    assert items(w, "report")[0].join_count == 1 and len(items(w, "report")[0].payload["reports"]) == 2


def test_only_a_fact_the_students_plan_shows_can_be_reported(w, api):
    other = w.kb.upsert("programme", "p9", "deadline_close", Fact({"date": "2027-08-01"}, "q", "https://x.test/y", AT, 2027,
                                                                  "confirmed"))
    assert api.post(f"/v1/os/facts/{other}/report", headers=S1, json={"reason": "other"}).status_code == 404
    assert api.post(f"/v1/os/facts/{w.fact_id}/report", headers=S2, json={"reason": "other"}).status_code == 404  # no plan
    assert api.post("/v1/os/facts/9999/report", headers=S1, json={"reason": "other"}).status_code == 404
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
        assert api.post(f"/v1/os/facts/{fid}/report", headers=S1, json={"reason": "other"}).status_code == 200
    assert api.post(f"/v1/os/facts/{ids[cap]}/report", headers=S1, json={"reason": "other"}).status_code == 429
    assert api.post(f"/v1/os/facts/{ids[0]}/report", headers=S1, json={"reason": "other"}).status_code == 200  # same fact


def test_the_report_link_reports_every_fact_behind_a_source(w, api):
    w.kb.upsert("programme", "p1", "fee_per_semester", Fact(1000, "Fee per semester: 1000 units", URL, AT, 2027,
                                                            "confirmed", intake_term="winter"))
    r = api.post("/v1/os/sources/report", headers=S1, json={"url": URL, "reason": "page_changed"})
    assert r.status_code == 200
    assert {i.field for i in items(w, "report")} == {"deadline_close", "fee_per_semester"}
    assert api.post("/v1/os/sources/report", headers=S1, json={"url": "https://nowhere.test/", "reason": "other"}).status_code == 404


def test_the_report_texts_are_the_approved_ones(w, api):
    got = api.get("/v1/os/report/texts", headers=S1).json()
    assert [r["code"] for r in got["reasons"]] == list(load_config().report_reasons)
    assert got["texts"]["report_link"] == "Report as wrong" and got["reasons"][0]["label"] == "The date is wrong"
    assert api.get("/v1/os/report/texts").status_code == 401


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


def test_drop_domain_facts_marks_the_facts_for_recheck_too(w):
    from app.os.knowledge.sources.suspect import drop_domain_facts

    plan = w.plan()
    drop_domain_facts(w.engine, "pai", w.kb, HOST, w.changed)
    assert w.fact().recheck == "monitor" and w.task(plan).blocked_reason == "fact_rechecking:deadline_close"


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
