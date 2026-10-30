"""Slice 8 Task 5: the `counsellor.intake` workflow and its one-minute job (spec §2.3, S8-D2, S8-D9), with DBOS in
this process. Fictional exports from app/os/contracts/samples."""

import time
from datetime import date

import pytest
from sqlalchemy import insert, select

from app.os import models
from app.os.adapters.counsellor.run import intake_workflow_id, register_intake, run_intake_job
from app.os.adapters.counsellor.store import IntakeStore
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_counsellor_intake import FAKE, sample
from tests.os.test_counsellor_submit import switch_on

P = models.plans


@pytest.fixture
def worker(os_db, engine, clean):
    from dbos import DBOS, DBOSClient

    from app.os.api.services import make_services
    from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
    from app.os.knowledge.programmes import PROGRAMME_SEED, Programme, ProgrammeStore, load_programme_seed
    from app.os.playbooks import load_playbook_dir
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow
    from app.os.settings import load_settings

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE) | load_playbook_dir(),
                        today=lambda: date(2027, 1, 20))
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    store = ProgrammeStore(engine, "pai")
    load_programme_seed(PROGRAMME_SEED, store)
    for ref in ("ie-p1", "ie-p2"):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="University", name=ref, aliases=(),
                               start_urls=(f"https://example.org/{ref}",), official_domains=("example.org",)))
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), svc.kernel)
    register_intake(svc)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    try:
        yield engine, client
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def add(engine, export: dict) -> None:
    IntakeStore(engine, "pai").add(export, "0" * 64)


def drain(engine, client, decisions: list[str], timeout: float = 60) -> dict:
    """Runs the job each second, as the schedule would, until every decision is processed."""
    store, end = IntakeStore(engine, "pai"), time.monotonic() + timeout
    while time.monotonic() < end:
        run_intake_job(engine, "pai", client)
        got = {d: store.get(d) for d in decisions}
        if all(i.status != "pending" for i in got.values()):
            return got
        time.sleep(1)
    raise AssertionError(f"still pending: {[d for d, i in got.items() if i.status == 'pending']}")


def test_workflow_id():
    assert intake_workflow_id("pai", "d-1") == "counsellor:pai:d-1"


def test_job_enqueues_each_once(worker):
    engine, client = worker
    switch_on(engine)
    add(engine, sample("export_valid_de.json"))
    add(engine, sample("export_valid_de.json", decision_id="d-b", student_ref="ws-sample-2", journey_id="j-b"))
    assert run_intake_job(engine, "pai", client) == 2
    assert run_intake_job(engine, "pai", client) <= 2  # the same workflow IDs again: DBOS runs each once
    got = drain(engine, client, ["d-sample-1", "d-b"])
    assert {i.status for i in got.values()} == {"planned"} and all(i.processed_at for i in got.values())
    with engine.connect() as conn:
        assert conn.execute(select(P.c.student_ref).where(P.c.source == "counsellor").order_by(P.c.student_ref)
                            ).scalars().all() == ["ws-sample-1", "ws-sample-2"]
        revisions = conn.execute(select(models.plan_revisions.c.cause)).scalars().all()
    assert revisions == ["created", "created"]  # nothing ran twice
    assert run_intake_job(engine, "pai", client) == 0  # nothing pending


def test_pending_in_order_after_switch_on(worker):
    engine, client = worker
    add(engine, sample("export_new_country.json"))  # chosen last: the plan that must remain (review focus 3)
    add(engine, sample("export_same_route_new_places.json"))
    add(engine, sample("export_valid_de.json"))  # chosen first, stored last
    assert run_intake_job(engine, "pai", client) == 0  # module off: they wait
    switch_on(engine)
    got = drain(engine, client, ["d-sample-1", "d-sample-2", "d-sample-3"])
    assert [got[d].status for d in ("d-sample-1", "d-sample-2", "d-sample-3")] == ["planned", "revised", "replaced"]
    with engine.connect() as conn:
        open_plans = conn.execute(select(P.c.external_ref).where(P.c.status != "closed")).scalars().all()
    assert open_plans == ["j-sample-1:IE:master"]


def test_refusal_is_recorded(worker):
    engine, client = worker
    switch_on(engine)
    add(engine, sample("export_pk_pk.json"))
    got = drain(engine, client, ["d-sample-6"])["d-sample-6"]
    assert (got.status, got.reason, got.counsellor_status) == ("refused", "route_not_supported", "pending")
