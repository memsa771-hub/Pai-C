"""Slice 8 gate (spec §8): a fictional Counsellor decision goes all the way through with the module on, and
standalone PAI OS behaves exactly as in Slice 7 with the module off (as os_0013 leaves it). DBOS runs in this
process."""

import json
import time
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select

from app.os import models, ports
from app.os.adapters.counsellor.run import register_intake, run_intake_job
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.replan import replanner_for
from app.os.ports import escalation as os_escalation
from app.os.ports import plan_query, plan_source
from app.os.replan import events
from app.os.replan.apply import BROKEN_REASON
from app.os.replan.store import SupportStore
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT

SAMPLES = Path(__file__).resolve().parents[2] / "app" / "os" / "contracts" / "samples"


def sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text())


@pytest.fixture
def gate(os_db, engine, clean):
    from dbos import DBOS, DBOSClient

    from app.os.api.services import make_services
    from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
    from app.os.knowledge.programmes import PROGRAMME_SEED, ProgrammeStore, load_programme_seed
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow
    from app.os.settings import load_settings

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    svc = make_services(settings, engine=engine, today=lambda: date(2027, 1, 20))
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    load_programme_seed(PROGRAMME_SEED, ProgrammeStore(engine, "pai"))
    with engine.begin() as conn:  # the row as os_0013 leaves it (clean empties the table)
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=False))
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), svc.kernel)
    register_intake(svc)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    ports.configure(svc)
    try:
        yield svc, client
    finally:
        ports.configure(None)
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def switch(engine, on: bool) -> None:
    with engine.begin() as conn:
        conn.execute(models.modules.update().where(models.modules.c.module == "counsellor").values(enabled=on))


def test_end_to_end_module_on(gate):
    svc, client = gate
    switch(svc.engine, True)
    export = sample("export_valid_de.json")
    assert plan_source.submit_counsellor_decision(export) == "stored"
    store, end = IntakeStore(svc.engine, "pai"), time.monotonic() + 60
    while store.get("d-sample-1").status == "pending":
        assert time.monotonic() < end, "the decision was not planned in time"
        run_intake_job(svc.engine, "pai", client)  # the worker's one-minute job
        time.sleep(1)
    intake = store.get("d-sample-1")
    assert (intake.status, intake.reason) == ("planned", None)
    summary = plan_query.plan_summary("ws-sample-1")  # the Counsellor's Plan screen
    assert (summary.plan_id, summary.route.destination_country, summary.state) == (intake.plan_id, "DE",
                                                                                   "needs_student")
    with svc.engine.begin() as conn:  # the route stops holding (Slice 7's route_invalid)
        eid = events.record(conn, "pai", intake.plan_id, "route_invalid", {}, "gate")
    case_id = replanner_for(svc).support(intake.plan_id, [eid], BROKEN_REASON)
    (sent,) = os_escalation.pending_counsellor_escalations()
    assert (sent.key, sent.case_id, sent.journey_id, sent.student_ref, sent.reason) == (
        f"escalation:{case_id}", case_id, "j-sample-1", "ws-sample-1", "not_eligible")
    assert plan_query.plan_summary("ws-sample-1").support_case_open is True
    os_escalation.mark_counsellor_delivery(sent.key, "sent")  # the glue delivered it
    assert os_escalation.pending_counsellor_escalations() == []


def test_standalone_suite_module_off(gate):
    svc, client = gate
    plan_id = svc.plans.start_plan(TEST_STUDENT).plan_id  # self-serve, as in Slice 7
    with svc.engine.begin() as conn:
        eid = events.record(conn, "pai", plan_id, "route_invalid", {}, "gate")
    case = SupportStore(svc.engine, "pai").get(replanner_for(svc).support(plan_id, [eid], BROKEN_REASON))
    assert (case.status, case.counsellor_status) == ("open", None)
    assert plan_source.submit_counsellor_decision(sample("export_valid_de.json")) == "module_off"
    assert run_intake_job(svc.engine, "pai", client) == 0  # off: the stored decision waits
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.outbox).where(
            models.outbox.c.channel == "counsellor")).scalar() == 0
        assert conn.execute(select(models.counsellor_intake.c.status)).scalars().all() == ["pending"]
        assert conn.execute(select(func.count()).select_from(models.counsellor_sweep)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(models.plans).where(
            models.plans.c.source == "counsellor")).scalar() == 0
    assert plan_query.plan_summary(TEST_STUDENT.student_ref).plan_id == plan_id  # answers even while off
