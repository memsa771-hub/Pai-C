"""Freeze exception 3 (P2-D28): PlanQuery.confirmed_facts, the read behind the Counsellor's calendar and admission-rules
adapter. Fictional refs and `.test` sources."""

import pytest

from app.os.knowledge import Fact
from app.os.ports import plan_query
from tests.os.test_p2_merit_ports import AT, URL, put, world  # noqa: F401  (fixture)

pytestmark = [pytest.mark.req("R-44"), pytest.mark.req("R-20")]


def test_confirmed_facts_only_and_labelled_by_year(world):  # noqa: F811
    put(world, "ie-1", "min_percent", {"value": 65, "unit": "percent"})
    put(world, "ie-2", "min_percent", {"value": 70, "unit": "percent"}, status="unconfirmed")
    world.knowledge.upsert("registry", "cal:alpha-result", "result_date",
                           Fact({"date": "2026-08-14", "tz": "UTC"}, "the quote", URL, AT, 2026, "confirmed"))
    keys = [("programme", "ie-1", "min_percent"), ("programme", "ie-2", "min_percent"),
            ("registry", "cal:alpha-result", "result_date"), ("route", "ireland_master", "x"),
            ("programme", "ie-3", "min_percent")]
    got = plan_query.confirmed_facts(keys, 2027)
    assert set(got) == {("programme", "ie-1", "min_percent"), ("registry", "cal:alpha-result", "result_date")}
    assert got[("programme", "ie-1", "min_percent")] == {"value": {"value": 65, "unit": "percent"}, "url": URL,
                                                         "status": "confirmed", "intake_year": 2027}
    assert got[("registry", "cal:alpha-result", "result_date")]["intake_year"] == 2026  # last year's, labelled
    assert plan_query.confirmed_facts([], 2027) == {}
