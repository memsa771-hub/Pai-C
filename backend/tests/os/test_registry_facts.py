"""P2-T11: `SqlKnowledge.registry_facts` reads facts about registry entities with the same owner, term and previous-year
rules as programme facts (P2-D8, P2-D24; R-26)."""

from datetime import UTC, datetime

import pytest

from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge

pytestmark = pytest.mark.req("R-26")
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)


def fact(day, year, term="main", status="confirmed", **kw) -> Fact:
    return Fact({"date": day}, "q", "https://c.test/x", AT, year, status, intake_term=term, **kw)


def test_strict_read_by_entity_and_field(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("registry", "cal:a", "result_date", fact("2031-05-20", 2031))
    k.upsert("registry", "cal:a", "exam_date", fact("2031-03-02", 2031))
    k.upsert("registry", "cal:b", "result_date", fact("2031-06-01", 2031))
    k.upsert("programme", "cal:a", "result_date", fact("2099-01-01", 2031))  # another scope is never read
    got = k.registry_facts(["cal:a", "cal:b"], ["result_date"], 2031)
    assert {key: f.value["date"] for key, f in got.items()} == {("cal:a", "result_date"): "2031-05-20",
                                                                ("cal:b", "result_date"): "2031-06-01"}
    assert k.registry_facts([], ["result_date"], 2031) == {} and k.registry_facts(["cal:a"], [], 2031) == {}
    assert k.registry_facts(["cal:a"], ["result_date"], 2032) == {}


def test_term_and_owner_filters(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("registry", "cal:a", "result_date", fact("2031-05-20", 2031, term="main"))
    k.upsert("registry", "cal:a", "result_date", fact("2031-09-20", 2031, term="supplementary"))
    k.upsert("registry", "cal:a", "result_date", fact("2031-05-25", 2031, term="main", owner_ref="body:x"))
    assert k.registry_facts(["cal:a"], ["result_date"], 2031, intake_term="supplementary")[
        ("cal:a", "result_date")].value["date"] == "2031-09-20"
    assert k.registry_facts(["cal:a"], ["result_date"], 2031, intake_term="main", owner_ref="body:x")[
        ("cal:a", "result_date")].value["date"] == "2031-05-25"
    assert k.registry_facts(["cal:a"], ["result_date"], 2031, intake_term="main", owner_ref="")[
        ("cal:a", "result_date")].value["date"] == "2031-05-20"


def test_previous_year_fallback_is_labelled_by_its_own_year(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("registry", "cal:a", "result_date", fact("2030-05-19", 2030))
    assert k.registry_facts(["cal:a"], ["result_date"], 2031) == {}  # the strict read is as before
    got = k.registry_facts(["cal:a"], ["result_date"], 2031, intake_term="main", fallback_previous=True)
    assert got[("cal:a", "result_date")].intake_year == 2030  # R-26: marked by a year other than the one asked
    k.upsert("registry", "cal:a", "result_date", fact("2031-05-20", 2031))
    again = k.registry_facts(["cal:a"], ["result_date"], 2031, intake_term="main", fallback_previous=True)
    assert again[("cal:a", "result_date")].intake_year == 2031  # the asked year wins
