"""Slice 4 Task 9: the self-serve and eligibility API (spec §4, Q1, Q3). Synthetic values only."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.documents.store import ProfileStore
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings
from tests.os.test_api_knowledge import FakeClient

FAKE = Path(__file__).parent / "playbooks"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
TOKEN = "test-admin-token"
P = "/v1/os"


def me(student="stu-1") -> dict:
    return {"X-Test-Student": student}


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    fake = FakeClient()
    books = load_playbook_dir(FAKE) | load_playbook_dir(PLAYBOOK_DIR)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1),
                        dbos_client=lambda: fake)
    store, kb = ProgrammeStore(engine, "pai"), SqlKnowledge(engine, "pai")
    for ref, ielts, status in (("p1", 6.5, "confirmed"), ("p2", 6.0, "confirmed"), ("p3", 7.5, "unconfirmed")):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="Uni X", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://uni.example/{ref}",),
                               official_domains=("uni.example",)))
        for field, value in (("grade_requirement", {"percent_min": 60}), ("english_requirement", {"ielts": ielts}),
                             ("deadline_close", {"date": "2027-07-15"})):
            kb.upsert("programme", ref, field, Fact(value, "q" if status == "confirmed" else "", "https://uni.example/r",
                                                    CHECKED, 2027, status), "manual")
    profiles = ProfileStore(engine, "pai")
    for key, v in (("transcript.percentage", 70), ("ielts_trf.overall", 6.0)):
        profiles.set("stu-1", key, v, None)
    profiles.set("stu-2", "transcript.percentage", 50, None)
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.fake = fake
    return c


def start(api, student="stu-1", refs=("p1",)):
    return api.post(f"{P}/plans/self", headers=me(student), json={
        "route": "ireland_master", "intake": {"term": "winter", "year": 2027},
        "choices": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


def test_routes_lists_playbooks(api):
    routes = {r["key"]: r for r in api.get(f"{P}/routes", headers=me()).json()["routes"]}
    assert {"germany_master", "ireland_master", "pakistan_bs"} <= set(routes)
    assert (routes["ireland_master"]["destination"], routes["ireland_master"]["level"]) == ("IE", "master")


def test_route_programmes_with_cards(api):
    body = api.get(f"{P}/routes/ireland_master/programmes?intake=2027", headers=me()).json()
    by_ref = {p["ref"]: p for p in body["programmes"]}
    assert set(by_ref) == {"p1", "p2", "p3"}
    assert by_ref["p1"]["card"]["verdict"] == "likely_below"  # IELTS 6.0, needs 6.5
    assert by_ref["p2"]["card"]["verdict"] == "likely_meets"
    # confirmed facts the eligibility rules read (grade and English), not the deadline
    assert (by_ref["p1"]["research_state"], by_ref["p1"]["confirmed_facts"]) == ("researched", 2)
    eng = next(ln for ln in by_ref["p1"]["card"]["lines"] if ln["check"] == "language:english")
    assert (eng["have"], eng["need"], eng["sources"][0]["status"]) == (6.0, 6.5, "confirmed")


def test_student_sees_only_own_cards(api):
    other = {p["ref"]: p for p in api.get(f"{P}/routes/ireland_master/programmes?intake=2027",
                                          headers=me("stu-2")).json()["programmes"]}
    assert other["p2"]["card"]["verdict"] == "likely_below"  # stu-2's 50% against 60%, not stu-1's 70%


def test_card_uses_confirmed_profile(api, engine):
    ProfileStore(engine, "pai").set("stu-1", "ielts_trf.overall", 7.0, None)
    body = api.get(f"{P}/eligibility/p1?route=ireland_master&intake=2027", headers=me()).json()
    assert body["card"]["verdict"] == "likely_meets" and body["suggestions"] == []


def test_eligibility_detail_with_suggestions(api):
    body = api.get(f"{P}/eligibility/p1?route=ireland_master&intake=2027", headers=me()).json()
    assert body["card"]["verdict"] == "likely_below"
    assert [s["programme_ref"] for s in body["suggestions"]] == ["p2"]
    assert body["suggestions"][0]["name"] == "Programme p2"


def test_eligibility_unknown_programme_404(api):
    assert api.get(f"{P}/eligibility/nope?route=ireland_master&intake=2027", headers=me()).status_code == 404
    assert api.get(f"{P}/eligibility/p1?route=mars&intake=2027", headers=me()).status_code == 404


def test_start_201_then_200(api):
    first = start(api)
    assert first.status_code == 201 and first.json()["programmes"] == [{"programme_ref": "p1", "rank": 1}]
    again = start(api)
    assert again.status_code == 200 and again.json()["plan_id"] == first.json()["plan_id"]


def test_start_refusals_422(api):
    bad = api.post(f"{P}/plans/self", headers=me(), json={
        "route": "mars", "intake": {"term": "winter", "year": 2027}, "choices": [{"programme_ref": "p1", "rank": 1}]})
    assert bad.status_code == 422 and "route" in bad.json()["detail"]
    assert start(api, refs=[f"x{i}" for i in range(11)]).status_code == 422


def test_swap_200_409_404(api):
    plan = start(api, refs=("p1",)).json()["plan_id"]
    ok = api.post(f"{P}/plans/{plan}/swap", headers=me(), json={"out": "p1", "in": "p2"})
    assert ok.status_code == 200 and [p["programme_ref"] for p in ok.json()["programmes"]] == ["p2"]
    assert api.post(f"{P}/plans/{plan}/swap", headers=me("stu-2"), json={"out": "p2", "in": "p3"}).status_code == 404
    taken = api.post(f"{P}/plans/{plan}/swap", headers=me(), json={"out": "p2", "in": "p2"})
    assert taken.status_code == 409 and "already" in taken.json()["detail"]
    for out, new in (("p2", "p3"), ("p3", "p1")):
        assert api.post(f"{P}/plans/{plan}/swap", headers=me(), json={"out": out, "in": new}).status_code == 200
    limit = api.post(f"{P}/plans/{plan}/swap", headers=me(), json={"out": "p1", "in": "p2"})
    assert limit.status_code == 409 and "tomorrow" in limit.json()["detail"]


def test_remove(api):
    plan = start(api, refs=("p1", "p2")).json()["plan_id"]
    r = api.delete(f"{P}/plans/{plan}/programmes/p1", headers=me())
    assert r.status_code == 200 and [p["programme_ref"] for p in r.json()["programmes"]] == ["p2"]
    assert api.delete(f"{P}/plans/{plan}/programmes/p2", headers=me()).status_code == 409  # the last one
    assert api.delete(f"{P}/plans/{plan}/programmes/p2", headers=me("stu-2")).status_code == 404


def request(api, student="stu-1", n=0, url=None):
    return api.post(f"{P}/programmes/requests", headers=me(student), json={
        "route": "ireland_master", "intake_year": 2027, "university": f"Uni {n}", "name": f"Course {n}",
        "url": url or f"https://uni-{n}.example/course"})


def test_request_202_enqueues_once(api):
    r = request(api)
    assert r.status_code == 202 and r.json()["created"] and len(api.fake.calls) == 1
    again = request(api, student="stu-2")
    assert again.status_code == 202 and not again.json()["created"] and len(api.fake.calls) == 1
    assert again.json()["programme_ref"] == r.json()["programme_ref"]


def test_request_cap_429_and_bad_url_422(api):
    for n in range(3):
        assert request(api, n=n).status_code == 202
    assert request(api, n=9).status_code == 429
    assert request(api, student="stu-2", url="http://uni.example/x").status_code == 422
    unknown = api.post(f"{P}/programmes/requests", headers=me(), json={
        "route": "mars", "intake_year": 2027, "university": "U", "name": "N", "url": "https://u.example/n"})
    assert unknown.status_code == 422


def test_requested_shown_to_requester_while_researched(api):
    ref = request(api).json()["programme_ref"]
    mine = {p["ref"]: p for p in api.get(f"{P}/routes/ireland_master/programmes?intake=2027",
                                         headers=me()).json()["programmes"]}
    assert mine[ref]["research_state"] == "being_researched" and mine[ref]["requested_by_student"]
    assert mine[ref]["card"] is None
    theirs = api.get(f"{P}/routes/ireland_master/programmes?intake=2027", headers=me("stu-2")).json()
    assert ref not in {p["ref"] for p in theirs["programmes"]}


def test_admin_open_facts_lists_requested_programmes(api):
    ref = request(api).json()["programme_ref"]
    body = api.get(f"{P}/facts/open", headers={"X-OS-Admin-Token": TOKEN}).json()
    assert [p["ref"] for p in body["requested_programmes"]] == [ref]
