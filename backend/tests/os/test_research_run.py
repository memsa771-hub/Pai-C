"""Slice 2 Task 6: the os.research workflow and the knowledge.research module (spec §4.6, S2-D2, S2-D3, S2-D10).

DBOS runs in this process (as in the dbos_worker fixture). The pages come from an httpx MockTransport and the
readings from a FunctionModel that answers per page URL and reading, so nothing leaves the machine.
"""

import re
import time
from datetime import date, datetime, timezone

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, insert, select

from app.os import models
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.compiler import CONFIRM_TYPE
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_profile_dir, load_seed
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.research.readings import build_readers
from app.os.knowledge.research.run import enqueue_research, register_research, research_workflow_id
from app.os.playbooks import load_playbook_dir
from app.os.runner import Module, default_registry, enqueue_pending
from app.os.service import PlanService
from app.os.settings import load_settings
from app.os.workers.manual import confirm_fact
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT

TENANT = "pai"
TODAY = date(2027, 2, 1)  # the golden student's compile date
PAGES = {
    "tu-chemnitz-embedded-systems": ("https://www.tu-chemnitz.test/es", "tu-chemnitz.test",
                                     "MSc Embedded Systems | TU Chemnitz"),
    "ovgu-eeit": ("https://www.ovgu.test/eeit", "ovgu.test",
                  "MSc Electrical Engineering and Information Technology | OVGU"),
    "btu-artificial-intelligence": ("https://www.b-tu.test/ai", "b-tu.test", "MSc Artificial Intelligence | BTU"),
}
DEADLINE = "Application deadline for the winter semester 2027/28: 1 July 2027."
ROUTE = "International applicants apply via uni-assist."
NO_TEST = "There is no admission test."
URL_RE = re.compile(r"<<<PAGE url=(\S+)>>>")


def page_html(title: str) -> str:
    return f"<html><head><title>{title}</title></head><body><p>{DEADLINE}</p><p>{ROUTE}</p><p>{NO_TEST}</p></body></html>"


def answer_for(url: str) -> dict:
    return {
        "deadline_close": {"value": "07-01", "quote": DEADLINE, "url": url, "cycle": "winter semester 2027/28"},
        "application_route": {"value": "uni_assist", "quote": ROUTE, "url": url},
        "admission_test": {"value": {"any_of": []}, "quote": NO_TEST, "url": url},
    }


class Ctx:
    """What a test drives: the DBOS client, kernel, service, and which readings answer."""

    def __init__(self, engine, client, kernel, service):
        self.engine, self.client, self.kernel, self.service = engine, client, kernel, service
        self.answering = {"A", "B", "C"}  # readings that return the page's facts; the others return nothing
        self.calls: list[str] = []


def _reading_of(messages) -> str:
    system = " ".join(p.content for m in messages for p in m.parts if p.part_kind == "system-prompt")
    return "A" if system.startswith("You extract") else "B" if system.startswith("You are checking") else "C"


@pytest.fixture
def research(os_db, engine, clean, monkeypatch):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
                              "OS_FETCH_HOST_INTERVAL_S": "0"})
    kernel = Kernel(engine, TENANT)
    service = PlanService(engine, settings, kernel, SqlKnowledge(engine, TENANT), load_playbook_dir(),
                          today=lambda: TODAY)
    store = ProgrammeStore(engine, TENANT)
    for ref, (url, domain, _) in PAGES.items():
        store.upsert(Programme(ref=ref, route_key="germany_master", university=ref.split("-")[0], name=ref,
                               aliases=(), start_urls=(url,), official_domains=(domain,)))
    titles = {url: title for url, _, title in PAGES.values()}
    with engine.begin() as conn:  # the programme names the pages use (the scope rule reads them)
        for ref, (_, _, title) in PAGES.items():
            name = title.split(" | ")[0].removeprefix("MSc ")
            conn.execute(models.programmes.update().where(models.programmes.c.ref == ref).values(name=name))

    def serve(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in titles:
            return httpx.Response(200, text=page_html(titles[url]), headers={"content-type": "text/html"})
        return httpx.Response(404, text="")

    ctx_holder: dict = {}

    def fn(messages, info: AgentInfo) -> ModelResponse:
        ctx: Ctx = ctx_holder["ctx"]
        reading = _reading_of(messages)
        ctx.calls.append(reading)
        prompt = " ".join(str(p.content) for m in messages for p in m.parts if p.part_kind == "user-prompt")
        url = URL_RE.search(prompt).group(1)
        args = answer_for(url) if reading in ctx.answering else {}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    gateway = PageGateway(engine, TENANT, settings, client=httpx.Client(transport=httpx.MockTransport(serve)))
    spec = load_agent_spec(AGENT_DIR / "research.v1.yaml")
    profiles = load_profile_dir()
    readers = {key: build_readers(FunctionModel(fn), p, spec) for key, p in profiles.items()}
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), kernel)
    register_research(engine, settings, kernel, service, gateway, readers, spec, profiles)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    ctx = Ctx(engine, client, kernel, service)
    ctx_holder["ctx"] = ctx
    try:
        yield ctx
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


# --- helpers -----------------------------------------------------------------------------------------------

T = models.tasks


def confirm_tasks(engine, plan_id=None) -> dict[str, dict]:
    q = select(T.c.instance_key, T.c.state, T.c.result).where(T.c.task_type == CONFIRM_TYPE)
    if plan_id is not None:
        q = q.where(T.c.plan_id == plan_id)
    with engine.connect() as conn:
        return {r.instance_key: {"state": r.state, "result": r.result} for r in conn.execute(q)}


def start_and_wait(ctx: Ctx, contract=TEST_STUDENT) -> int:
    """Seeds, starts the plan and runs its confirm tasks until they all wait for review."""
    if not count(ctx.engine, models.knowledge_facts):
        load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(ctx.engine, TENANT))
    plan_id = ctx.service.start_plan(contract).plan_id
    deadline = time.monotonic() + 40
    while True:
        enqueue_pending(ctx.engine, ctx.client, TENANT)
        states = {t["state"] for t in confirm_tasks(ctx.engine, plan_id).values()}
        if states and states <= {"waiting_review", "done"}:
            return plan_id
        if time.monotonic() > deadline:
            raise AssertionError(f"confirm tasks stuck in {states}")
        time.sleep(0.2)


def research_today(ctx: Ctx, day: date = TODAY) -> int:
    n = enqueue_research(ctx.engine, ctx.client, TENANT, day)
    for ref in PAGES:
        try:
            ctx.client.retrieve_workflow(research_workflow_id(TENANT, ref, 2027, day)).get_result()
        except Exception as e:  # noqa: BLE001  (a workflow that was never enqueued)
            if "not found" not in str(e).lower() and "NonExistent" not in type(e).__name__:
                raise
    return n


def count(engine, table) -> int:
    with engine.connect() as conn:  # always closed: an open transaction would block the next test's TRUNCATE
        return conn.execute(select(func.count()).select_from(table)).scalar()


def rows(engine, query) -> list:
    with engine.connect() as conn:
        return conn.execute(query).all()


def fact(engine, ref, field):
    F = models.knowledge_facts
    with engine.connect() as conn:
        return conn.execute(select(F).where(F.c.ref == ref, F.c.field == field, F.c.intake_year == 2027)).first()


def events(engine, kind):
    E = models.events
    with engine.connect() as conn:
        return conn.execute(select(E.c.payload).where(E.c.type == kind).order_by(E.c.id)).scalars().all()


def due(engine, plan_id, key):
    with engine.connect() as conn:
        return conn.execute(select(T.c.due_at).where(T.c.plan_id == plan_id, T.c.instance_key == key)).scalar()


def revision(engine, plan_id):
    with engine.connect() as conn:
        return conn.execute(select(models.plans.c.current_revision).where(models.plans.c.id == plan_id)).scalar()


# --- tests -------------------------------------------------------------------------------------------------


def test_registry_single_owner():
    reg = default_registry()
    assert reg.owner(CONFIRM_TYPE).name == "knowledge.research"
    assert "knowledge.manual" not in {m.name for m in reg.modules()}
    with pytest.raises(ValueError, match="already owned"):
        reg.register(Module(name="knowledge.manual", owns=frozenset({CONFIRM_TYPE}), handler=None))


def test_worker_registers_research_only_with_a_key(monkeypatch):
    from app.os.runner import worker

    settings = load_settings({"OS_DATABASE_URL": "postgresql://unused/x"})
    assert worker.register_research_if_configured(settings, engine=None, kernel=None) is False  # no key: admin path


def test_confirm_task_waits_for_research(research):
    plan_id = start_and_wait(research)
    tasks = confirm_tasks(research.engine, plan_id)
    assert tasks["confirm_fact@ovgu-eeit:application_route"]["result"]["waiting_for"] == "research"
    assert tasks["confirm_fact@ovgu-eeit:deadline_close"]["result"]["waiting_for"] == "research"
    # a route fact is not researched (S2-D1): an admin supplies it
    assert tasks["confirm_fact@germany_master:visa_target_date"]["result"]["waiting_for"] == "admin_fact_confirmation"


def test_confirmed_fact_completes_task_and_redates_plan(research):
    plan_id = start_and_wait(research)
    before_rev, before_due = revision(research.engine, plan_id), due(research.engine, plan_id, "uni_assist_apply@ovgu-eeit")
    assert research_today(research) == 3
    row = fact(research.engine, "ovgu-eeit", "deadline_close")
    assert (row.status, row.source, row.value) == ("confirmed", "research", {"date": "2027-07-01"})
    assert row.quote == DEADLINE and row.url == PAGES["ovgu-eeit"][0] and row.research_run_id is not None
    assert {e["reading"] for e in row.evidence} == {"A", "B"} and all(e["reasons"] == [] for e in row.evidence)
    assert fact(research.engine, "ovgu-eeit", "admission_test").value == []  # an empty list: no test step
    # every model request was a DBOS step of its research workflow (DBOSDurability), so a crash replays it
    from sqlalchemy import text

    with research.engine.connect() as conn:
        steps = conn.execute(text(
            f"SELECT o.workflow_uuid, o.function_name FROM {TEST_DBOS_SCHEMA}.operation_outputs o "
            f"WHERE o.function_name LIKE '%model.request%' AND o.workflow_uuid LIKE 'research:%'")).all()
    assert len(steps) == 6 and len({s.workflow_uuid for s in steps}) == 3  # A and B in each of the 3 runs
    tasks = confirm_tasks(research.engine, plan_id)
    assert tasks["confirm_fact@ovgu-eeit:deadline_close"]["state"] == "done"
    assert tasks["confirm_fact@ovgu-eeit:application_route"]["state"] == "done"
    assert tasks["confirm_fact@germany_master:visa_target_date"]["state"] == "waiting_review"
    assert revision(research.engine, plan_id) > before_rev
    assert due(research.engine, plan_id, "uni_assist_apply@ovgu-eeit") < before_due  # 1 July, not 15 July
    changed = [e for e in events(research.engine, "fact_changed") if e["ref"] == "ovgu-eeit"]
    assert {e["field"] for e in changed} >= {"deadline_close", "application_route"}
    runs = rows(research.engine, select(models.research_runs))
    assert len(runs) == 3 and {r.status for r in runs} == {"done"} and all(r.confirmed >= 3 for r in runs)
    agent_runs = rows(research.engine, select(models.agent_runs.c.research_run_id, models.agent_runs.c.reading))
    assert sorted(r.reading for r in agent_runs) == ["A", "A", "A", "B", "B", "B"]  # no C: every field has 0 or 2


def test_one_run_per_programme_per_day(research):
    start_and_wait(research)
    second = TEST_STUDENT.model_copy(update={"external_ref": "test-student-2", "student_ref": "test-student-2"})
    start_and_wait(research, second)  # two plans wait on the same programmes
    assert research_today(research) == 3
    calls = len(research.calls)
    assert research_today(research) == 0  # same day: nothing new
    assert len(research.calls) == calls
    assert count(research.engine, models.research_runs) == 3


def test_unconfirmed_waits_for_admin(research):
    research.answering = {"A"}  # one reading only: nothing can be confirmed
    plan_id = start_and_wait(research)
    research_today(research)
    row = fact(research.engine, "ovgu-eeit", "deadline_close")
    assert (row.status, row.source) == ("unconfirmed", "research")
    assert {e["reading"] for e in row.evidence} == {"A"}
    assert "C" in research.calls  # a field with one valid reading asks reading C (S2-D7)
    key = "confirm_fact@ovgu-eeit:deadline_close"
    assert confirm_tasks(research.engine, plan_id)[key]["state"] == "waiting_review"
    # the admin path still completes it
    confirm_fact(research.service, SqlKnowledge(research.engine, TENANT), research.kernel, row.id,
                 value={"date": "2027-07-01"}, quote=DEADLINE, url=PAGES["ovgu-eeit"][0], status="confirmed")
    assert confirm_tasks(research.engine, plan_id)[key]["state"] == "done"


def test_conflict_keeps_confirmed_value(research):
    plan_id = start_and_wait(research)
    seeded = fact(research.engine, "ovgu-eeit", "deadline_close")
    confirm_fact(research.service, SqlKnowledge(research.engine, TENANT), research.kernel, seeded.id,
                 value={"date": "2027-07-15"}, quote="15 July 2027", url=PAGES["ovgu-eeit"][0], status="confirmed")
    research_today(research)
    row = fact(research.engine, "ovgu-eeit", "deadline_close")
    assert row.status == "confirmed" and row.value == {"date": "2027-07-15"}  # not overwritten
    assert "2027-07-01" in (row.conflict_note or "")
    conflicts = [e for e in events(research.engine, "fact_conflict") if e["ref"] == "ovgu-eeit"]
    assert len(conflicts) == 1 and conflicts[0]["field"] == "deadline_close"
    assert confirm_tasks(research.engine, plan_id)["confirm_fact@ovgu-eeit:application_route"]["state"] == "done"


def test_budget_exceeded_skips_run(research):
    plan_id = start_and_wait(research)
    with research.engine.begin() as conn:
        run_id = conn.execute(insert(models.research_runs).values(
            tenant_id=TENANT, programme_ref="x", intake_year=2027, workflow_id="earlier", status="done")
            .returning(models.research_runs.c.id)).scalar()
        conn.execute(insert(models.agent_runs).values(
            tenant_id=TENANT, research_run_id=run_id, reading="A", agent="research", agent_version=1, model="m",
            cost_usd=20.0))
    research_today(research)
    with research.engine.connect() as conn:
        statuses = conn.execute(select(models.research_runs.c.status).where(
            models.research_runs.c.workflow_id != "earlier")).scalars().all()
    assert sorted(statuses) == ["skipped_budget"] * 3
    assert len(events(research.engine, "budget_exceeded")) == 3
    assert research.calls == []  # no reading ran
    assert fact(research.engine, "ovgu-eeit", "deadline_close").source == "seed"
    assert confirm_tasks(research.engine, plan_id)["confirm_fact@ovgu-eeit:deadline_close"]["state"] == "waiting_review"
