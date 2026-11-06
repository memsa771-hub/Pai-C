"""P1-T9 Task 5 (R-55, R-52): the label test, backend half. A real plan of each of the four routes (the Counsellor's
intake on Postgres, fictional students and facts) is read through `GET /v1/os/plan` and `GET /v1/os/inbox`. Every word
the student could read is checked: no route shows another route's country, body or document name, and a route that
stays in one country never says "abroad" or "visa" and has no visa page. The word lists are test data
(`fixtures/route_labels.yaml`); the frontend half reads the same lists."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.os.api import build_router, current_student_ref, current_student_ref_for_write
from app.os.adapters.counsellor.store import IntakeStore
from app.os.knowledge import Fact, SqlKnowledge
from app.os.ports import my_plan as my_plan_port
from tests.os.route_labels import ROUTES, abroad_words, all_text, foreign_words, load_words
from tests.os.test_counsellor_intake_v2 import run, v2
from tests.os.test_counsellor_intake_v2 import svc  # noqa: F401 - the fixture is used by name

pytestmark = [pytest.mark.req("R-55"), pytest.mark.req("R-52")]

CHECKED = datetime(2026, 11, 5, tzinfo=timezone.utc)
ROUTE_EXPORT = {  # route key -> (origin, destination, level, programme)
    "germany_master": ("PK", "DE", "master", "ovgu-eeit"),
    "ireland_master": ("PK", "IE", "master", "ie-p1"),
    "pakistan_bs": ("PK", "PK", "bachelor", "pk-p1"),
    "pakistan_inter": ("PK", "PK", "intermediate", "pk-i1"),
}


@pytest.fixture
def api(svc):  # noqa: F811
    my_plan_port.configure(lambda: True)
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.svc = svc
    try:
        yield c
    finally:
        my_plan_port.configure(None)


def seed(svc, route_key: str, ref: str) -> None:
    """A confirmed date for the route's programme (the Germany seed is loaded by the fixture)."""
    kb = SqlKnowledge(svc.engine, "pai")
    for field in ("deadline_close", "merit_list_date", "semester_start"):
        kb.upsert("programme", ref, field, Fact({"date": "2027-08-15"}, "q", f"https://source.example/{field}",
                                                CHECKED, 2027, "confirmed"), "manual")


def read_route(api, route_key: str) -> tuple[dict, dict]:
    origin, destination, level, ref = ROUTE_EXPORT[route_key]
    student = f"stu-{route_key}"
    seed(api.svc, route_key, ref)
    store = IntakeStore(api.svc.engine, "pai")
    result = run(api.svc, v2(student_ref=student, decision_id=f"d-{route_key}", origin_country=origin,
                              destination_country=destination, level=level,
                              programmes=[{"programme_ref": ref, "rank": 1}]))
    assert result.status == "planned", (route_key, result.status, result.reason)
    store.finish(store.get(f"d-{route_key}").id, result.status, result.reason, result.plan_id)
    head = {"X-Test-Student": student}
    plan, inbox = api.get("/v1/os/plan", headers=head), api.get("/v1/os/inbox", headers=head)
    assert plan.status_code == 200 and inbox.status_code == 200, (plan.text, inbox.text)
    return plan.json(), inbox.json()


@pytest.fixture
def seen(api):
    """Route key -> (plan answer, inbox answer, all their words)."""
    out = {}
    for route_key in ROUTES:
        plan, inbox = read_route(api, route_key)
        out[route_key] = (plan, inbox, all_text(plan, inbox))
    return out


def test_every_route_shows_its_own_plan_and_something_to_check(seen):
    for route_key, (plan, inbox, text) in seen.items():
        assert plan["route_key"] == route_key and plan["pages"], route_key
        assert inbox["items"], route_key  # the check below is not empty
        assert all(p["title"] in text for p in plan["pages"]), route_key


def test_no_route_shows_another_routes_words(seen):
    for route_key, (_, _, text) in seen.items():
        assert foreign_words(route_key, text) == [], route_key


def test_the_word_lists_are_really_in_the_routes_own_text(seen):
    """The rule is not empty: Germany says its own words, so a leak of them elsewhere would be found."""
    words = load_words()
    own = seen["germany_master"][2].lower()
    assert "attested by hec" in own  # only the steps that are open show; the later ones are in the frontend fixture
    assert "entry test" in seen["pakistan_bs"][2].lower() and "admission form" in seen["pakistan_inter"][2].lower()
    assert all(words[r]["country"] for r in ROUTES)


def test_non_abroad_routes_never_say_abroad_or_visa(seen):
    for route_key in ("pakistan_bs", "pakistan_inter"):
        assert abroad_words(seen[route_key][2]) == [], route_key
    assert abroad_words(seen["germany_master"][2]) == ["visa"]  # and the rule sees it where it belongs


def test_pk_routes_have_no_visa_page(seen):
    for route_key in ("pakistan_bs", "pakistan_inter"):
        assert "visa" not in [p["key"] for p in seen[route_key][0]["pages"]], route_key
        assert seen[route_key][0]["abroad"] is False
    assert "visa" in [p["key"] for p in seen["germany_master"][0]["pages"]]


def test_label_rule_catches_a_planted_word(seen):
    """The test can fail: Germany's "uni-assist" in a PK BS title, a body in an Irish page, a visa on a PK page."""
    plan, inbox, _ = seen["pakistan_bs"]
    planted = {**inbox, "items": [{**inbox["items"][0], "title": "Submit to uni-assist"}, *inbox["items"][1:]]}
    assert foreign_words("pakistan_bs", all_text(plan, planted)) == ["uni-assist"]
    assert foreign_words("ireland_master", "Get it from the Consular Services Portal; blocked account") == [
        "Consular Services Portal", "blocked account"]
    assert foreign_words("germany_master", "Your German blocked account") == []  # its own words are allowed
    assert abroad_words(all_text(plan, {**inbox, "items": [{"title": "Study abroad"}, {"title": "Your Visa file"}]})) \
        == ["abroad", "visa"]
    assert foreign_words("pakistan_inter", "Sit the entry test and the merit-list round") == ["entry test"]
