"""P1-T2 Task 6 (R-12): a failure at any step of the Counsellor -> PAI OS hand-off loses nothing and duplicates
nothing. The app side is a real Counsellor session (SQLite) and the bridge; the OS side is the real PlanSource and
intake store on Postgres. Kill points: (a) before the commit, (b) after the commit but before any delivery,
(c) PAI OS took the decision but the `delivered` mark was lost, (d) the OS worker died mid-`process`.
Fictional student and programmes only."""

import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from dbos import DBOSClient
from sqlalchemy import func, insert, select, text

from app import pai_os_bridge as bridge
from app.config import config
from app.models import OsOutbox, RouteDecision
from app.os import models, ports
from app.os.adapters.counsellor.run import enqueue_intake
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.services import make_services
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.knowledge.programmes import PROGRAMME_SEED, ProgrammeStore, load_programme_seed
from app.os.ports import plan_source
from app.os.runner import APP_NAME
from app.os.settings import load_settings
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap.decisions import RouteDecisionService
from app.routers import roadmap
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_crash import Pool, _wait_queue
from tests.os.test_crash_counsellor_intake import TIMEOUT_S, _finish_waiting
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = [pytest.mark.req("R-12"), pytest.mark.chaos]

DETAILS = ChoiceDetails(origin_country="PK", destination_country="DE", level="master",
                        places=(("tu-chemnitz-embedded-systems", 1), ("ovgu-eeit", 2)), intake=("winter", 2027),
                       authorized_at=datetime(2027, 1, 10, 4, 0, 5, tzinfo=timezone.utc))


@pytest.fixture
def real_os(os_db, engine, clean):
    """The real OS services behind the ports, the Counsellor module on, the Germany seed loaded."""
    svc = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine, today=lambda: date(2027, 1, 20))
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    load_programme_seed(PROGRAMME_SEED, ProgrammeStore(engine, "pai"))
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    ports.configure(svc)
    try:
        yield svc
    finally:
        ports.configure(None)


@contextmanager
def handoff_on():
    with patch.object(config, "CONNECT_HANDOFF", True, create=True):
        yield


def intake_rows(engine) -> list:
    with engine.connect() as conn:
        return conn.execute(select(models.counsellor_intake.c.decision_id, models.counsellor_intake.c.status)).all()


def plan_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.plans)).scalar_one()


def outbox_rows(db, ws) -> list:
    db.expire_all()
    return list(db.scalars(select(OsOutbox).where(OsOutbox.workspace_id == ws).order_by(OsOutbox.key)))


def decision_rows(db, ws) -> list:
    db.expire_all()
    return list(db.scalars(select(RouteDecision).where(RouteDecision.workspace_id == ws)))


@pytest.fixture
def spy(monkeypatch):
    """Records what PAI OS answers to each submit, passing the real call through."""
    answers = []
    real = plan_source.submit_decision

    def submit(export):
        answers.append(real(export))
        return answers[-1]

    monkeypatch.setattr(plan_source, "submit_decision", submit)
    return answers


@pytest.mark.asyncio
async def test_a_failure_before_the_commit_loses_and_sends_nothing(real_os, engine, spy):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id

        def action():
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            raise RuntimeError("the request died before the commit")

        with handoff_on():
            with pytest.raises(RuntimeError):
                roadmap._write(action, db, ws)
            db.rollback()  # what the request's session does when the request ends in an error
            assert bridge.sweep_once(db)["submitted"] == 0
        assert decision_rows(db, ws) == [] and outbox_rows(db, ws) == []
        assert intake_rows(engine) == [] and spy == []


@pytest.mark.asyncio
async def test_a_commit_without_delivery_is_delivered_by_the_sweep_once(real_os, engine, spy):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with handoff_on():
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()  # the process stops here: deliver_pending never ran
            (row,) = outbox_rows(db, ws)
            assert row.status == "pending" and intake_rows(engine) == []
            assert bridge.sweep_once(db)["submitted"] == 1
            assert bridge.sweep_once(db)["submitted"] == 0  # a second sweep finds nothing to do
        (row,) = outbox_rows(db, ws)
        assert row.status == "delivered" and spy == ["stored"]
        assert intake_rows(engine) == [(row.payload["decision_id"], "pending")]


@pytest.mark.asyncio
async def test_a_lost_delivered_mark_is_a_duplicate_not_a_second_decision(real_os, engine, spy):
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with handoff_on():
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            with patch.object(db, "commit", side_effect=RuntimeError("the mark could not be saved")):
                with pytest.raises(RuntimeError):
                    bridge.deliver_pending(db, ws)  # PAI OS took the decision; the mark did not reach the database
            db.rollback()
            (row,) = outbox_rows(db, ws)
            assert spy == ["stored"] and row.status == "pending" and len(intake_rows(engine)) == 1
            assert bridge.sweep_once(db)["submitted"] == 1
        (row,) = outbox_rows(db, ws)
        assert spy == ["stored", "duplicate"] and row.status == "delivered"
        assert intake_rows(engine) == [(row.payload["decision_id"], "pending")]
        assert plan_count(engine) == 0


@pytest.mark.asyncio
async def test_a_worker_killed_mid_process_leaves_one_plan(real_os, os_db, engine, tmp_path, spy):
    reset_dbos_schema(os_db)
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        ws = student.workspace_id
        with handoff_on():
            RouteDecisionService(db).choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            assert bridge.deliver_pending(db, ws)["delivered"] == 1
        (row,) = outbox_rows(db, ws)
        decision_id = row.payload["decision_id"]
        store = IntakeStore(engine, "pai")
        pool, client, held = Pool(os_db, tmp_path), None, None
        try:
            pool.start(0)
            client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA,
                                application_name=APP_NAME)
            _wait_queue(client, pool)
            held = engine.connect()  # holds the intake row: `process` runs, `finish` waits on it
            held.execute(select(models.counsellor_intake).where(
                models.counsellor_intake.c.decision_id == decision_id).with_for_update())
            enqueue_intake(client, "pai", decision_id)
            deadline = time.monotonic() + TIMEOUT_S
            while not _finish_waiting(engine):
                assert time.monotonic() < deadline, f"finish never waited (logs: {tmp_path})"
                time.sleep(0.2)
            assert plan_count(engine) == 1  # `process` is done, the row is still pending
            pool.kill(0)
            held.rollback()
            held.close()
            held = None
            pool.start(0)
            while store.get(decision_id).status == "pending":
                assert time.monotonic() < deadline, f"not finished after the restart (logs: {tmp_path})"
                time.sleep(0.5)
        finally:
            if held is not None:
                held.close()
            pool.stop_all()
            if client is not None:
                client.destroy()
        with handoff_on():  # a later sweep re-sends nothing new and plans nothing twice
            bridge.sweep_once(db)
        with engine.connect() as conn:
            plans = conn.execute(select(models.plans.c.id)).scalars().all()
            causes = conn.execute(select(models.plan_revisions.c.cause)).scalars().all()
        got = store.get(decision_id)
        assert (got.status, got.plan_id) == ("planned", plans[0]) and len(plans) == 1
        assert causes == ["created"] and len(intake_rows(engine)) == 1
