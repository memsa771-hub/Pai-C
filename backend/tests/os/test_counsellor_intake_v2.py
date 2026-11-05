"""P1-T2 Task 4: the OS stores each decision version, applies only newer ones, and a withdrawn version closes the
plan (R-02, R-06). Fictional v2 exports from app/os/contracts/samples/v2; the Germany playbook and the fake routes."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.os import models, ports
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.services import make_services
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.knowledge.programmes import PROGRAMME_SEED, Programme, ProgrammeStore, load_programme_seed
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.ports import plan_source
from app.os.settings import load_settings
from app.os.workers.reminders import run_reminders

pytestmark = [pytest.mark.req("R-02"), pytest.mark.req("R-06")]

SAMPLES = Path(__file__).resolve().parents[2] / "app" / "os" / "contracts" / "samples"
FAKE = Path(__file__).parent / "playbooks"
P, T, R = models.plans, models.tasks, models.plan_revisions
OPEN_STATES = ("pending", "ready", "running", "waiting_student", "waiting_review", "failed", "blocked")
NEW_PLACES = [{"programme_ref": "ovgu-eeit", "rank": 1}, {"programme_ref": "btu-artificial-intelligence", "rank": 2}]


@pytest.fixture
def svc(engine, clean, os_db):
    books = load_playbook_dir(FAKE) | load_playbook_dir()
    s = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine, playbooks=books,
                      today=lambda: date(2027, 1, 20))
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    store = ProgrammeStore(engine, "pai")
    load_programme_seed(PROGRAMME_SEED, store)
    for ref, route in (("ie-p1", "ireland_master"), ("ie-p2", "ireland_master"), ("pk-p1", "pakistan_bs")):
        store.upsert(Programme(ref=ref, route_key=route, university="University", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://example.org/{ref}",), official_domains=("example.org",)))
    return s


def v1(**over) -> dict:
    return {**json.loads((SAMPLES / "export_valid_de.json").read_text()), **over}


def v2(name: str = "decision_chosen_de.json", **over) -> dict:
    return {**json.loads((SAMPLES / "v2" / name).read_text()), **over}


def chosen(n: int, **over) -> dict:
    return v2(decision_id=f"d-v{n}", decision_version=n, chosen_at=f"2027-01-{10 + n:02d}T09:00:00+05:00", **over)


def withdrawn(n: int) -> dict:
    return v2("decision_withdrawn_de.json", decision_id=f"d-v{n}", decision_version=n,
              chosen_at=f"2027-01-{10 + n:02d}T09:00:00+05:00")


def run(svc, export: dict):
    store = IntakeStore(svc.engine, "pai")
    store.add(export, "0" * 64)
    return process(svc, store.get(export["decision_id"]))


def plan_row(svc, plan_id: int):
    with svc.engine.connect() as conn:
        return conn.execute(select(P).where(P.c.id == plan_id)).one()


def states(svc, plan_id: int) -> set[str]:
    with svc.engine.connect() as conn:
        return set(conn.execute(select(T.c.state).where(T.c.plan_id == plan_id)).scalars())


def test_v2_choose_plans_then_newer_revises(svc):
    first = run(svc, v1())
    assert first.status == "planned"
    second = run(svc, chosen(2, programmes=NEW_PLACES))
    assert (second.status, second.plan_id) == ("revised", first.plan_id)
    assert [p["programme_ref"] for p in plan_row(svc, first.plan_id).contract["programmes"]] == [
        "ovgu-eeit", "btu-artificial-intelligence"]
    assert plan_row(svc, first.plan_id).contract["contract_version"] == "1"  # D-b: the engine takes v1
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(P)).scalar() == 1


def test_v2_chosen_alone_plans(svc):
    r = run(svc, chosen(1))
    assert (r.status, r.reason) == ("planned", None)
    assert plan_row(svc, r.plan_id).external_ref == "j-sample-1:DE:master"


def test_older_version_is_stale(svc):
    third = run(svc, chosen(3, programmes=NEW_PLACES))
    assert third.status == "planned"
    before = plan_row(svc, third.plan_id).contract
    store = IntakeStore(svc.engine, "pai")
    store.finish(store.get("d-v3").id, third.status, None, third.plan_id)
    r = run(svc, chosen(2))
    assert (r.status, r.plan_id) == ("stale", None)
    assert plan_row(svc, third.plan_id).contract == before
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(R).where(R.c.plan_id == third.plan_id)).scalar() == 1


def test_any_stored_newer_version_makes_older_stale(svc):
    """Rule change (final review I1, R-02): a newer version stored for the student, even one still pending, makes an
    older one stale. The newer one is processed anyway, so the older one is never applied."""
    store = IntakeStore(svc.engine, "pai")
    store.add(chosen(3), "0" * 64)
    assert run(svc, chosen(2)).status == "stale"
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(P)).scalar() == 0


def test_both_pending_older_first_is_stale_newer_plans(svc):
    store = IntakeStore(svc.engine, "pai")
    store.add(chosen(1), "0" * 64)
    store.add(chosen(2, programmes=NEW_PLACES), "0" * 64)
    first = process(svc, store.get("d-v1"))
    assert (first.status, first.plan_id) == ("stale", None)
    store.finish(store.get("d-v1").id, first.status, first.reason, first.plan_id)
    second = process(svc, store.get("d-v2"))
    assert second.status == "planned"
    assert [p["programme_ref"] for p in plan_row(svc, second.plan_id).contract["programmes"]] == [
        "ovgu-eeit", "btu-artificial-intelligence"]


def test_late_chosen_after_processed_withdrawal_is_stale(svc):
    """The reviewer's case: v2 withdrawn is processed, then a late v1 arrives. It is stale; the plan stays closed."""
    store = IntakeStore(svc.engine, "pai")
    first = run(svc, v1())
    gone = run(svc, withdrawn(2))
    store.finish(store.get("d-v2").id, gone.status, gone.reason, gone.plan_id)
    late = run(svc, chosen(1))
    assert (late.status, late.plan_id) == ("stale", None)
    assert plan_row(svc, first.plan_id).status == "closed"
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(P).where(P.c.status != "closed")).scalar() == 0


def test_newer_version_stored_mid_process_makes_repeat_stale(svc):
    """v2 processed but not finished, then v1 arrives late: v1 is stale and changes nothing."""
    r = run(svc, chosen(2, programmes=NEW_PLACES))
    assert r.status == "planned"
    before = plan_row(svc, r.plan_id).contract
    late = run(svc, chosen(1))
    assert late.status == "stale"
    assert plan_row(svc, r.plan_id).contract == before


def test_stale_is_stored_as_status(svc):
    store = IntakeStore(svc.engine, "pai")
    r = run(svc, chosen(2))
    store.finish(store.get("d-v2").id, r.status, r.reason, r.plan_id)
    stale = run(svc, chosen(1))
    store.finish(store.get("d-v1").id, stale.status, stale.reason, stale.plan_id)
    assert store.get("d-v1").status == "stale"


def test_repeat_delivery_is_duplicate(svc):
    ports.configure(svc)
    try:
        with svc.engine.begin() as conn:
            conn.execute(models.modules.insert().values(module="counsellor", tenant_id="pai", enabled=True))
        assert plan_source.submit_decision(chosen(1)) == "stored"
        assert plan_source.submit_decision(chosen(1)) == "duplicate"
        with svc.engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(models.counsellor_intake)).scalar() == 1
        got = IntakeStore(svc.engine, "pai").get("d-v1")
        assert (got.decision_version, got.decision_status) == (1, "chosen")
        assert plan_source.latest_version("ws-sample-1") == 1
        assert plan_source.latest_version("nobody") is None
        plan_source.submit_decision(chosen(3))
        plan_source.submit_decision(chosen(2))
        assert plan_source.latest_version("ws-sample-1") == 3
    finally:
        ports.configure(None)


def test_submit_decision_needs_version_and_status(svc):
    ports.configure(svc)
    try:
        for key in ("decision_version", "status"):
            export = chosen(1)
            del export[key]
            with pytest.raises(ValueError, match=key):
                plan_source.submit_decision(export)
        with svc.engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(models.counsellor_intake)).scalar() == 0
    finally:
        ports.configure(None)


def test_pending_orders_by_version_nulls_first(svc):
    store = IntakeStore(svc.engine, "pai")
    store.add(chosen(3), "0" * 64)
    store.add(chosen(2), "0" * 64)
    store.add(v1(decision_id="d-old", chosen_at="2027-01-30T09:00:00+05:00"), "0" * 64)
    assert [i.decision_id for i in store.pending()] == ["d-old", "d-v2", "d-v3"]


def test_withdrawn_closes_the_plan(svc):
    first = run(svc, v1())
    r = run(svc, withdrawn(2))
    assert (r.status, r.plan_id) == ("withdrawn", first.plan_id)
    assert plan_row(svc, first.plan_id).status == "closed"
    assert not states(svc, first.plan_id) & set(OPEN_STATES)
    with svc.engine.connect() as conn:
        last = conn.execute(select(R.c.cause).where(R.c.plan_id == first.plan_id).order_by(R.c.number.desc())).first()
    assert last.cause == "withdrawn:d-v2"
    now = datetime(2027, 3, 1, tzinfo=timezone.utc)
    assert run_reminders(svc.engine, Outbox(svc.engine, "pai"), now, "pai") == 0
    store = IntakeStore(svc.engine, "pai")
    again = process(svc, store.get("d-v2"))  # a repeat changes nothing more
    assert again.status == "withdrawn"
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(R).where(R.c.cause == "withdrawn:d-v2")).scalar() == 1


def test_withdrawn_without_a_plan(svc):
    r = run(svc, withdrawn(2))
    assert (r.status, r.plan_id) == ("withdrawn", None)


def test_choose_after_withdraw_same_route(svc):
    first = run(svc, v1())
    run(svc, withdrawn(2))
    store = IntakeStore(svc.engine, "pai")
    store.finish(store.get("d-v2").id, "withdrawn", None, first.plan_id)
    r = run(svc, chosen(3))
    assert (r.status, r.reason, r.plan_id) == ("refused", "plan_closed", first.plan_id)  # D-e: a person decides
    assert plan_row(svc, first.plan_id).status == "closed"


def test_intermediate_refused_until_t5(svc):
    export = chosen(1, origin_country="PK", destination_country="PK", level="intermediate",
                    programmes=[{"programme_ref": "pk-p1", "rank": 1}])
    r = run(svc, export)
    assert (r.status, r.reason, r.plan_id) == ("refused", "route_not_supported", None)
    ports.configure(svc)
    try:
        assert plan_source.supports("PK", "PK", "intermediate") is False
        assert plan_source.supports("PK", "DE", "master") is True
        assert plan_source.supports("PK", "IE", "master") is True
        assert plan_source.supports("PK", "FR", "master") is False
    finally:
        ports.configure(None)


def test_unsupported_v2_without_a_plan_plans_nothing(svc):
    """Row 6.14: the OS does nothing for a route it cannot run (no plan, no refusal sent to the Counsellor)."""
    r = run(svc, v2("decision_unsupported_pk_inter.json"))
    assert (r.status, r.reason, r.plan_id) == ("unsupported", None, None)
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(P)).scalar() == 0


def test_move_to_unsupported_route_closes_the_old_plan(svc):
    """Final review I3 (rows 6.3 and 6.14): a planned, supported route changed to one the OS cannot run closes the
    old plan, and its reminders stop."""
    store = IntakeStore(svc.engine, "pai")
    first = run(svc, chosen(1))
    store.finish(store.get("d-v1").id, first.status, first.reason, first.plan_id)
    moved = v2("decision_unsupported_pk_inter.json", decision_id="d-v2", decision_version=2,
               chosen_at="2027-01-12T09:00:00+05:00")
    r = run(svc, moved)
    assert (r.status, r.reason, r.plan_id) == ("unsupported", None, first.plan_id)
    assert plan_row(svc, first.plan_id).status == "closed"
    assert not states(svc, first.plan_id) & set(OPEN_STATES)
    with svc.engine.connect() as conn:
        last = conn.execute(select(R.c.cause).where(R.c.plan_id == first.plan_id).order_by(R.c.number.desc())).first()
    assert last.cause == "unsupported:d-v2"
    assert run_reminders(svc.engine, Outbox(svc.engine, "pai"), datetime(2027, 3, 1, tzinfo=timezone.utc), "pai") == 0
    store.finish(store.get("d-v2").id, r.status, r.reason, r.plan_id)
    assert store.get("d-v2").status == "unsupported"  # the status check accepts it
    again = process(svc, store.get("d-v2"))  # a repeat changes nothing more
    assert again.status == "unsupported"
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(R).where(R.c.cause == "unsupported:d-v2")).scalar() == 1


def test_invalid_v2_is_invalid_export(svc):
    r = run(svc, chosen(1, status="paused"))
    assert (r.status, r.reason) == ("refused", "invalid_export")


def test_v2_not_authorized(svc):
    r = run(svc, chosen(1, authorized_at=None))
    assert (r.status, r.reason) == ("refused", "not_authorized")

