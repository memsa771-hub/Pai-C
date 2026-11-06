"""P1-T9 Task 2 (R-51, R-53, R-54): `GET /v1/os/plan` gives the student's plan pages, route and the date each source
was checked. Pages and words come from the playbooks (Germany, and the fake routes); fictional students and facts."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.os import ports
from app.os.ports import my_plan as my_plan_port
from app.os.adapters.counsellor.store import IntakeStore
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.contracts.route_contract import RouteContract
from app.os.knowledge import Fact, SqlKnowledge
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings

pytestmark = [pytest.mark.req("R-51"), pytest.mark.req("R-53"), pytest.mark.req("R-54")]

FAKE = Path(__file__).parent / "playbooks"
P = "/v1/os"
AT = datetime(2027, 1, 12, 9, tzinfo=timezone.utc)
WINTER = {"term": "winter", "year": 2027}
EMPTY = {"state": "empty", "source": None, "plan_id": None, "route_key": None, "abroad": None, "pages": [],
         "sources": {}}


def me(student="stu-1") -> dict:
    return {"X-Test-Student": student}


def make_api(engine, os_db, on=True):
    my_plan_port.configure((lambda: True) if on else None)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": "t", "OS_ENABLED": "true"})
    books = load_playbook_dir(FAKE) | load_playbook_dir(PLAYBOOK_DIR)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1))
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.svc, c.books = svc, books
    return c


@pytest.fixture
def api(engine, clean, os_db):
    c = make_api(engine, os_db)
    try:
        yield c
    finally:
        my_plan_port.configure(None)


def contract(student, origin, destination, level, source, refs=("p1",)):
    return RouteContract.model_validate({
        "contract_version": "1", "source": source, "external_ref": f"{source}:{student}:{destination}:{level}",
        "student_ref": student, "origin_country": origin, "destination_country": destination, "level": level,
        "target_intake": WINTER, "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


def counsellor_plan(api, student, refs=("ovgu-eeit",), n=1):
    plan_id = api.svc.plans.start_plan(contract(student, "PK", "DE", "master", "counsellor", refs)).plan_id
    store = IntakeStore(api.svc.engine, "pai")
    store.add({"decision_id": f"d-{student}-{n}", "student_ref": student, "journey_id": "j-1",
               "chosen_at": AT.isoformat(), "decision_version": n, "status": "chosen",
               "authorized_at": AT.isoformat()}, "0" * 64)
    store.finish(store.get(f"d-{student}-{n}").id, "planned", None, plan_id)
    return plan_id


def self_plan(api, student, origin, destination, level, refs=("p1",)):
    return api.svc.plans.start_plan(contract(student, origin, destination, level, "self_serve", refs)).plan_id


def get(api, student="stu-1"):
    r = api.get(f"{P}/plan", headers=me(student))
    assert r.status_code == 200, r.text
    return r.json()


def fact(api, scope, ref, field, url, day, status="confirmed", year=2027):
    api.svc.knowledge.upsert(scope, ref, field, Fact("v", "q", url, day, year, status), "manual")


def test_plan_empty_before_a_choice(api):  # R-53
    assert get(api) == EMPTY


def test_counsellor_plan_pages_and_route(api):  # R-51
    plan_id = counsellor_plan(api, "stu-1")
    got = get(api)
    assert (got["state"], got["source"], got["plan_id"], got["route_key"], got["abroad"]) == (
        "needs_student", "counsellor", plan_id, "germany_master", True)
    book = api.books[("germany_master", 1)]
    assert [p["key"] for p in got["pages"]] == ["start", "inbox", "documents", "programmes", "statements", "pack",
                                                 "visa"]
    assert got["pages"] == [p.model_dump() for p in book.pages]
    assert {p["key"]: p["title"] for p in got["pages"]}["inbox"] == "Your next steps"


def test_self_serve_plan_pages(api):  # R-51
    plan_id = self_plan(api, "stu-1", "PK", "PK", "bachelor")
    got = get(api)
    assert (got["state"], got["source"], got["plan_id"], got["route_key"], got["abroad"]) == (
        "active", "self_serve", plan_id, "pakistan_bs", False)
    assert [p["key"] for p in got["pages"]] == ["inbox", "documents", "programmes"]


def test_sources_dates_from_knowledge_and_playbook(api):  # R-54
    self_plan(api, "stu-1", "PK", "IE", "master")
    a, b = datetime(2027, 1, 5, 10, tzinfo=timezone.utc), datetime(2027, 2, 9, 10, tzinfo=timezone.utc)
    fact(api, "programme", "p1", "deadline_close", "https://uni.example/same", b)
    fact(api, "route", "ireland_master", "fee", "https://uni.example/same", a)
    fact(api, "programme", "p1", "english_requirement", "https://uni.example/other", b, status="unconfirmed")
    got = get(api)["sources"]
    assert got["https://uni.example/same"] == {"checked_at": "2027-01-05", "confirmed": True}
    assert got["https://uni.example/other"] == {"checked_at": "2027-02-09", "confirmed": False}
    # a playbook citation carries the playbook's own date; a source the reviewer did not confirm says so
    counsellor_plan(api, "stu-2")
    book = api.books[("germany_master", 1)]
    cited = {c.source: str(c.url) for t in book.tasks for c in t.citations}
    sources = get(api, "stu-2")["sources"]
    assert sources[cited["S5"]] == {"checked_at": "2026-10-17", "confirmed": True}
    assert sources[cited["S8"]] == {"checked_at": "2026-10-17", "confirmed": False}


def test_sources_only_for_the_students_plan(api):
    self_plan(api, "stu-1", "PK", "IE", "master", refs=("p1",))
    day = datetime(2027, 1, 5, tzinfo=timezone.utc)
    fact(api, "programme", "p1", "deadline_close", "https://uni.example/mine", day)
    fact(api, "programme", "p2", "deadline_close", "https://uni.example/not-mine", day)
    fact(api, "route", "pakistan_bs", "fee", "https://uni.example/other-route", day)
    fact(api, "programme", "p1", "deadline_close", "https://uni.example/other-year", day, year=2028)
    assert set(get(api)["sources"]) == {"https://uni.example/mine"}


def test_other_students_plan_never_shown(api):
    counsellor_plan(api, "stu-2")
    self_plan(api, "stu-3", "PK", "PK", "bachelor")
    assert get(api, "stu-1") == EMPTY
    assert get(api, "stu-2")["route_key"] == "germany_master"
    assert get(api, "stu-3")["route_key"] == "pakistan_bs"
