"""Slice 4 gate (spec §9, plan Task 11): the "done when" journey end to end through the API, on three routes.

A student starts a plan alone, sees eligibility waiting for documents, confirms documents (Slice 3, with the reading
simulated as the workflow would store it), gets one note when a verdict changes, swaps from that note, and requests a
programme that research (faked) makes visible to a second student with no second research. The same code runs on
Germany master's and the two fake routes, with three different grade methods. Fictional values only.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.documents.store import ProfileStore
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.changes import after_fact_change
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings
from tests.os.test_api_documents import FakeClient, confirm_body, jpeg, simulate_read, upload

FAKE = Path(__file__).parent / "playbooks"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
P = "/v1/os"
IELTS = {"family_name": "KHAN", "first_name": "SARA", "listening": 6.0, "reading": 6.0, "writing": 6.0,
         "speaking": 6.0, "overall": 6.0, "module": "Academic"}

# Per route: its programmes (ref -> facts) and the student's documents, confirmed in order.
ROUTES = {
    "germany_master": {
        "programmes": {"g1": {"grade_requirement": {"german_max": 2.5}, "english_requirement": {"cefr": "B2", "ielts": 6.5},
                              "german_requirement": {"level": "none"}, "admission_test": None},
                       "g2": {"grade_requirement": {"german_max": 3.0}, "english_requirement": {"ielts": 6.0},
                              "german_requirement": {"level": "none"}, "admission_test": None}},
        "documents": [("transcript", {"student_name": "Sara Ahmed Khan", "cgpa": 3.2, "cgpa_scale": 4.0}),
                      ("ielts_trf", IELTS)],
    },
    "ireland_master": {
        "programmes": {"i1": {"grade_requirement": {"percent_min": 60}, "english_requirement": {"ielts": 6.5}},
                       "i2": {"grade_requirement": {"percent_min": 60}, "english_requirement": {"ielts": 6.0}}},
        "documents": [("transcript", {"student_name": "Sara Ahmed Khan", "percentage": 70}), ("ielts_trf", IELTS)],
    },
    "pakistan_bs": {
        "programmes": {"k1": {"merit_closing": {"aggregate": 90}, "entry_test_required": {"any_of": []}},
                       "k2": {"merit_closing": {"aggregate": 80}, "entry_test_required": {"any_of": []}}},
        # no entry-test document type yet: its score is set as a confirmed value would be
        "documents": [("hssc_certificate", {"student_name": "Sara Ahmed Khan", "marks_obtained": 990,
                                            "marks_total": 1100})],
        "profile": {"entry_test.score": 80},
    },
}


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})
    fake = FakeClient()
    books = load_playbook_dir(FAKE) | load_playbook_dir(PLAYBOOK_DIR)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1),
                        dbos_client=lambda: fake)
    store, kb = ProgrammeStore(engine, "pai"), SqlKnowledge(engine, "pai")
    for route, spec in ROUTES.items():
        for ref, facts in spec["programmes"].items():
            store.upsert(Programme(ref=ref, route_key=route, university="Uni X", name=f"Programme {ref}", aliases=(),
                                   start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
            for field, value in facts.items():
                kb.upsert("programme", ref, field, Fact(value, "q", "https://uni.example/r", CHECKED, 2027,
                                                        "confirmed"), "manual")
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.fake, c.engine, c.svc = fake, engine, svc
    return c


def me(student="stu-1") -> dict:
    return {"X-Test-Student": student}


def cards(api, route, student="stu-1") -> dict:
    r = api.get(f"{P}/routes/{route}/programmes?intake=2027", headers=me(student))
    assert r.status_code == 200
    return {p["ref"]: p for p in r.json()["programmes"]}


def notes(api, student="stu-1") -> list:
    return api.get(f"{P}/inbox", headers=me(student)).json()["notes"]


def research_runs(api) -> int:
    """Research workflows enqueued (the fake client also records the uploads' reading workflows)."""
    return sum(1 for options, _ in api.fake.calls if options["workflow_id"].startswith("research:"))


def confirm(api, doc_type, values, student="stu-1"):
    data = jpeg(seed=len(doc_type) * 7)  # a different image per document type: the same file twice is refused
    doc_id = upload(api, doc_type=doc_type, data=data, name=f"{doc_type}.jpg", student=student).json()["id"]
    simulate_read(api.engine, doc_id, doc_type, values)
    r = api.post(f"{P}/documents/{doc_id}/confirm", json=confirm_body(doc_type, values), headers=me(student))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_slice4_gate(api, route):
    spec = ROUTES[route]
    first, second = sorted(spec["programmes"])

    # 1. the student starts a plan alone: no admin call, no Counsellor
    started = api.post(f"{P}/plans/self", headers=me(), json={
        "route": route, "intake": {"term": "winter", "year": 2027},
        "choices": [{"programme_ref": first, "rank": 1}]})
    assert started.status_code == 201, started.text
    plan_id = started.json()["plan_id"]

    # 2. before any document, every card waits for the student's documents
    assert cards(api, route)[first]["card"]["verdict"] == "needs_input"
    assert notes(api) == []

    # 3. documents confirmed (the reading simulated as the workflow stores it): one note when the verdict changes
    for key, value in spec.get("profile", {}).items():
        ProfileStore(api.engine, "pai").set("stu-1", key, value, None)
    for doc_type, values in spec["documents"]:
        confirm(api, doc_type, values)
    card = cards(api, route)[first]["card"]
    assert card["verdict"] == "likely_below", card  # every route's first programme is just out of reach
    [note] = notes(api)
    assert (note["programme_ref"], note["verdict"], note["payload"]["previous"]) == (first, "likely_below", "needs_input")
    assert note["payload"]["suggestions"] == [second] and note["payload"]["plan_id"] == plan_id

    # 4. the student swaps from the note: a kernel revision
    swapped = api.post(f"{P}/plans/{plan_id}/swap", headers=me(), json={"out": first, "in": second})
    assert swapped.status_code == 200 and swapped.json()["programmes"] == [{"programme_ref": second, "rank": 1}]
    assert swapped.json()["revision"] > started.json()["revision"]
    assert api.post(f"{P}/inbox/notes/{note['id']}/read", headers=me()).status_code == 204
    assert cards(api, route)[second]["card"]["verdict"] == "likely_meets"

    # 5. a requested programme is researched once, then visible to every student with no second research
    asked = api.post(f"{P}/programmes/requests", headers=me(), json={
        "route": route, "intake_year": 2027, "university": "Uni New", "name": "New Programme",
        "url": f"https://new.example/{route}"}).json()
    assert asked["created"] and research_runs(api) == 1
    assert asked["programme_ref"] not in cards(api, route, student="stu-2")
    kb = SqlKnowledge(api.engine, "pai")
    for field, value in spec["programmes"][second].items():  # the (faked) research run finds the same facts
        fact_id = kb.upsert("programme", asked["programme_ref"], field,
                            Fact(value, "", "https://new.example/r", CHECKED, 2027, "unconfirmed"), "research")
        after_fact_change(api.svc.plans, api.svc.kernel, "programme", asked["programme_ref"], field, fact_id,
                          "unconfirmed", 2027, complete=False)
    theirs = cards(api, route, student="stu-2")[asked["programme_ref"]]
    assert theirs["research_state"] == "researched" and theirs["requested_by_student"]
    again = api.post(f"{P}/programmes/requests", headers=me("stu-2"), json={
        "route": route, "intake_year": 2027, "university": "Uni New", "name": "New Programme",
        "url": f"https://new.example/{route}"}).json()
    assert (again["programme_ref"], again["created"], research_runs(api)) == (asked["programme_ref"], False, 1)
