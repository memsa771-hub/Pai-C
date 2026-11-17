"""P1-T9 Task 5 (R-55): the frontend label test reads `frontend/tests/fixtures/my-plan-routes.json`. That file is built
here from the four playbooks and the word list, so the two halves of the label test share one source and the file can
not drift. `UPDATE_ROUTE_FIXTURE=1` rewrites it."""

import os

import pytest

from tests.os.route_labels import FIXTURE_FILE, build_fixture, render

pytestmark = [pytest.mark.req("R-55")]


def test_route_fixture_is_current():
    want = render(build_fixture())
    if os.environ.get("UPDATE_ROUTE_FIXTURE") == "1":
        FIXTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_FILE.write_text(want)
    assert FIXTURE_FILE.read_text() == want, (
        "frontend/tests/fixtures/my-plan-routes.json is out of date: run this test with UPDATE_ROUTE_FIXTURE=1")


def test_the_fixture_has_the_four_routes_with_their_words():
    fixture = build_fixture()
    assert [r["route_key"] for r in fixture] == ["germany_master", "ireland_master", "pakistan_bs", "pakistan_inter"]
    assert [r["abroad"] for r in fixture] == [True, True, False, False]
    assert all(r["plan"]["pages"] and r["items"] and r["steps"] for r in fixture)
    assert set(fixture[0]["words"]) == {r["route_key"] for r in fixture}
