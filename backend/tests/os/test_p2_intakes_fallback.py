"""P2-T8: the labelled previous-year read (P2-D24; R-26, R-63) in the port and in the compiler."""

from datetime import UTC, datetime

import pytest

from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge

pytestmark = pytest.mark.req("R-26")
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)


def fact(year, value="v", status="confirmed", term="fall", **kw) -> Fact:
    return Fact(value=value, quote="q", url="https://admissions.alpha.test/n", checked_at=AT, intake_year=year,
                status=status, intake_term=term, **kw)


def test_read_is_strict_by_default(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p", "deadline", fact(2026, "2026-12-01"))
    assert k.programme_facts(["p"], ["deadline"], 2027) == {}
    assert k.route_facts("r", ["deadline"], 2027) == {}


def test_fallback_returns_the_newest_earlier_fact_with_its_year(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p", "deadline", fact(2025, "2025-12-01"))
    k.upsert("programme", "p", "deadline", fact(2026, "2026-12-01"))
    k.upsert("programme", "p", "fee", fact(2024, 50))
    k.upsert("route", "r", "deadline", fact(2026, "2026-12-01"))
    got = k.programme_facts(["p", "q"], ["deadline", "fee"], 2027, fallback_previous=True)
    assert set(got) == {("p", "deadline"), ("p", "fee")}
    assert got[("p", "deadline")].intake_year == 2026 and got[("p", "deadline")].value == "2026-12-01"
    assert got[("p", "fee")].intake_year == 2024  # marked by its own year, never by the asked one
    assert k.route_facts("r", ["deadline"], 2027, fallback_previous=True)["deadline"].intake_year == 2026


def test_this_years_fact_wins_even_if_unconfirmed(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p", "deadline", fact(2026, "2026-12-01"))
    k.upsert("programme", "p", "deadline",
             Fact(value="2027-12-01", quote="", url="", checked_at=AT, intake_year=2027, status="unconfirmed",
                  intake_term="fall"))
    got = k.programme_facts(["p"], ["deadline"], 2027, fallback_previous=True)
    assert got[("p", "deadline")].intake_year == 2027


def test_never_a_later_year_other_term_or_other_owner(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p", "deadline", fact(2028, "x"))
    k.upsert("programme", "p", "deadline", fact(2026, "y", term="spring"))
    k.upsert("programme", "p", "deadline", fact(2026, "z", owner_ref="body:one"))
    assert k.programme_facts(["p"], ["deadline"], 2027, intake_term="fall", owner_ref="", fallback_previous=True) == {}
    got = k.programme_facts(["p"], ["deadline"], 2027, intake_term="spring", fallback_previous=True)
    assert got[("p", "deadline")].value == "y"
    got = k.programme_facts(["p"], ["deadline"], 2027, owner_ref="body:one", fallback_previous=True)
    assert got[("p", "deadline")].value == "z"


def test_asked_year_row_without_a_recorded_term_counts_in_the_fallback_read(engine, clean):
    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p", "deadline", fact(2026, "old"))
    k.upsert("programme", "p", "deadline", fact(2027, "new", term=""))  # written the pre-P2 way
    k.upsert("programme", "q", "deadline", fact(2026, "other", term=""))  # an earlier row with no term: not read
    got = k.programme_facts(["p", "q"], ["deadline"], 2027, intake_term="fall", fallback_previous=True)
    assert got[("p", "deadline")].value == "new" and ("q", "deadline") not in got
    # the strict read keeps T1's meaning: an exact term filter
    assert k.programme_facts(["p"], ["deadline"], 2027, intake_term="fall") == {}


@pytest.mark.req("R-62")
def test_current_term_wins_a_clash_and_requested_programmes_follow_the_term(engine, clean):
    from app.os.intakes import IntakeStore
    from app.os.knowledge.programmes import Programme, ProgrammeStore
    from app.os.knowledge.requests import visible_programmes

    k = SqlKnowledge(engine, "pai")
    k.upsert("programme", "p", "fee", fact(2027, "fall-value", term="fall"))
    k.upsert("programme", "p", "fee", fact(2027, "spring-value", term="spring"))  # the newest row
    assert k.programme_facts(["p"], ["fee"], 2027)[("p", "fee")].value == "spring-value"  # no intake registered
    IntakeStore(engine, "pai").create("r_one", "undergrad", "fall", 2027, state="open")
    assert k.programme_facts(["p"], ["fee"], 2027)[("p", "fee")].value == "fall-value"  # the intake's term wins
    assert k.programme_facts(["p"], ["fee"], 2027, intake_term="spring")[("p", "fee")].value == "spring-value"
    ProgrammeStore(engine, "pai").upsert(Programme("p", "r", "U", "N", (), (), (), status="requested"))
    assert [p.ref for p in visible_programmes(engine, "pai", "r", 2027)] == ["p"]
    assert [p.ref for p in visible_programmes(engine, "pai", "r", 2027, "fall")] == ["p"]
    assert visible_programmes(engine, "pai", "r", 2027, "winter") == []
