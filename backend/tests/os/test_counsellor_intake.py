"""Slice 8 Task 4: a Counsellor decision becomes a plan (spec §2.3, S8-D7, S8-D8, S8-D10, S8-D11). Fictional
exports from app/os/contracts/samples; the Germany playbook and the fake routes."""

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.os import models
from app.os.adapters.counsellor.intake import REFUSALS, process
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api.services import make_services
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.knowledge.programmes import PROGRAMME_SEED, Programme, ProgrammeStore, load_programme_seed
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from tests.os.test_golden import TEST_STUDENT

SAMPLES = Path(__file__).resolve().parents[2] / "app" / "os" / "contracts" / "samples"
FAKE = Path(__file__).parent / "playbooks"
P, T, R, C = models.plans, models.tasks, models.plan_revisions, models.support_cases
OPEN_STATES = ("pending", "ready", "running", "waiting_student", "waiting_review", "failed", "blocked")


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


def sample(name: str, **over) -> dict:
    return {**json.loads((SAMPLES / name).read_text()), **over}


def run(svc, export: dict):
    store = IntakeStore(svc.engine, "pai")
    store.add(export, "0" * 64)
    return process(svc, store.get(export["decision_id"]))


def plan_row(svc, plan_id: int):
    with svc.engine.connect() as conn:
        return conn.execute(select(P).where(P.c.id == plan_id)).one()


def task_states(svc, plan_id: int) -> dict[str, str]:
    with svc.engine.connect() as conn:
        return dict(conn.execute(select(T.c.instance_key, T.c.state).where(T.c.plan_id == plan_id)).all())


def cases(svc, plan_id: int) -> list:
    with svc.engine.connect() as conn:
        return conn.execute(select(C).where(C.c.plan_id == plan_id)).all()


def test_refusal_reasons_exact():
    assert REFUSALS == ("not_authorized", "invalid_export", "route_not_supported", "unknown_programme",
                        "self_serve_plan_open", "plan_closed")


def test_valid_export_starts_plan(svc):
    r = run(svc, sample("export_valid_de.json"))
    assert (r.status, r.reason) == ("planned", None)
    row = plan_row(svc, r.plan_id)
    assert (row.source, row.external_ref, row.student_ref, row.status) == (
        "counsellor", "j-sample-1:DE:master", "ws-sample-1", "active")
    assert row.contract["programmes"][0]["programme_ref"] == "tu-chemnitz-embedded-systems"
    assert IntakeStore(svc.engine, "pai").get("d-sample-1").counsellor_status is None


def test_same_route_is_revision_keeps_done_tasks(svc):
    first = run(svc, sample("export_valid_de.json"))
    with svc.engine.connect() as conn:
        task = conn.execute(select(T).where(T.c.plan_id == first.plan_id, T.c.state == "waiting_student",
                                            T.c.programme_ref.is_(None)).order_by(T.c.id)).first()
    assert svc.kernel.complete_student_task(task.id, "ws-sample-1", {})
    r = run(svc, sample("export_same_route_new_places.json"))
    assert (r.status, r.plan_id) == ("revised", first.plan_id)  # the same plan, never a second one
    with svc.engine.connect() as conn:
        assert conn.execute(select(T.c.state).where(T.c.id == task.id)).scalar_one() == "done"
        assert conn.execute(select(func.count()).select_from(P)).scalar() == 1
        causes = conn.execute(select(R.c.cause).where(R.c.plan_id == first.plan_id)).scalars().all()
    assert "counsellor:d-sample-2" in causes
    refs = [p["programme_ref"] for p in plan_row(svc, first.plan_id).contract["programmes"]]
    assert refs == ["ovgu-eeit", "btu-artificial-intelligence"]


def test_new_country_closes_old_plan_and_starts_new(svc):
    old = run(svc, sample("export_valid_de.json"))
    r = run(svc, sample("export_new_country.json"))
    assert r.status == "replaced" and r.plan_id != old.plan_id
    assert plan_row(svc, r.plan_id).external_ref == "j-sample-1:IE:master"
    assert plan_row(svc, old.plan_id).status == "closed"
    assert not set(task_states(svc, old.plan_id).values()) & set(OPEN_STATES)  # every open task cancelled
    with svc.engine.connect() as conn:
        last = conn.execute(select(R.c.cause).where(R.c.plan_id == old.plan_id).order_by(R.c.number.desc())).first()
    assert last.cause == f"superseded:{r.plan_id}"


def test_route_closed_refused_plan_closed(svc):
    old = run(svc, sample("export_valid_de.json"))
    run(svc, sample("export_new_country.json"))
    r = run(svc, sample("export_valid_de.json", decision_id="d-sample-7", chosen_at="2027-01-20T09:00:00+05:00"))
    assert (r.status, r.reason, r.plan_id) == ("refused", "plan_closed", old.plan_id)
    assert plan_row(svc, old.plan_id).status == "closed"  # a closed plan is never reopened
    assert [c.status for c in cases(svc, old.plan_id)] == ["open"]


def test_not_authorized(svc):
    r = run(svc, sample("export_not_authorized.json"))
    assert (r.status, r.reason, r.plan_id) == ("refused", "not_authorized", None)


def test_invalid_export(svc):
    r = run(svc, sample("export_valid_de.json", level="degree"))
    assert (r.status, r.reason, r.plan_id) == ("refused", "invalid_export", None)


def test_route_not_supported_pk_pk(svc):
    r = run(svc, sample("export_pk_pk.json"))
    assert (r.status, r.reason, r.plan_id) == ("refused", "route_not_supported", None)


def test_unknown_programme(svc):
    r = run(svc, sample("export_unknown_programme.json"))
    assert (r.status, r.reason, r.plan_id) == ("refused", "unknown_programme", None)
    other_route = sample("export_valid_de.json", decision_id="d-x", programmes=[{"programme_ref": "ie-p1", "rank": 1}])
    assert run(svc, other_route).reason == "unknown_programme"  # a place of another route is unknown here too


def test_self_serve_plan_open_refused_with_case(svc):
    own = svc.plans.start_plan(TEST_STUDENT.model_copy(update={"student_ref": "ws-sample-1"})).plan_id
    export = sample("export_valid_de.json")
    r = run(svc, export)
    assert (r.status, r.reason, r.plan_id) == ("refused", "self_serve_plan_open", own)
    assert process(svc, IntakeStore(svc.engine, "pai").get("d-sample-1")).reason == "self_serve_plan_open"  # repeat
    assert [c.status for c in cases(svc, own)] == ["open"]  # one case, however often it runs (invariant 8)
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(P).where(P.c.source == "counsellor")).scalar() == 0


def test_first_four_refusals_marked_for_counsellor(svc):
    store = IntakeStore(svc.engine, "pai")
    for name in ("export_not_authorized.json", "export_unknown_programme.json", "export_pk_pk.json"):
        run(svc, sample(name))
    run(svc, sample("export_valid_de.json", decision_id="d-bad", level="degree", journey_id="j-bad"))  # own journey:
    # the samples above are newer decisions on j-sample-1, which would make it outdated (final review I3)
    for decision in ("d-sample-4", "d-sample-5", "d-sample-6", "d-bad"):
        assert store.get(decision).counsellor_status == "pending"  # Task 7 sends them by journey as `other`
    svc.plans.start_plan(TEST_STUDENT.model_copy(update={"student_ref": "ws-sample-1"}))
    run(svc, sample("export_valid_de.json"))
    assert store.get("d-sample-1").counsellor_status is None  # self_serve_plan_open: a support case instead


@pytest.mark.parametrize("dest,level,ref,route", [("IE", "master", "ie-p1", "ireland_master"),
                                                   ("PK", "bachelor", "pk-p1", "pakistan_bs")])
def test_fake_routes_plan_unchanged(svc, dest, level, ref, route):
    export = sample("export_valid_de.json", destination_country=dest, level=level,
                    programmes=[{"programme_ref": ref, "rank": 1}])
    r = run(svc, export)
    assert r.status == "planned"
    contract = type(TEST_STUDENT).model_validate({
        **TEST_STUDENT.model_dump(mode="json"), "student_ref": "other", "external_ref": "other", "level": level,
        "destination_country": dest, "programmes": [{"programme_ref": ref, "rank": 1}]})
    own = svc.plans.start_plan(contract).plan_id
    with svc.engine.connect() as conn:
        pins = dict(conn.execute(select(models.playbook_pins.c.plan_id, models.playbook_pins.c.playbook_key)).all())
    assert pins[r.plan_id] == pins[own] == route
    assert task_states(svc, r.plan_id) == task_states(svc, own)


def test_close_plan_repeat_is_noop(svc):
    r = run(svc, sample("export_valid_de.json"))
    first = svc.kernel.close_plan(r.plan_id, "superseded:999")
    assert svc.kernel.close_plan(r.plan_id, "superseded:999") == first
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(R).where(R.c.plan_id == r.plan_id,
                                                                      R.c.cause == "superseded:999")).scalar() == 1
