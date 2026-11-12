"""P1-T10 B2, gate item 4 (R-04, R-05): after the scripted flows, the nightly consistency job finds nothing.

One scenario per student: the four fictional routes (Germany master, fake PK BS, fake Ireland, fake PK intermediate)
each walk 6.1 choose -> 6.2 places added -> 6.4 withdraw, and the nightly job (cases on) runs after each step that
settles the state; a Germany student with the version-2 playbook has two open document requests (T8); a Germany student
has a confirmed document (T7). Each ends with `opened == 0`, `findings == {}` and no open case.

Why one world per student and not one module-scoped run: the Counsellor side of a student lives in that student's own
SQLite session in tests, while the OS side is one database; the job reads one Counsellor database. A production run has one
of each. Each scenario therefore proves the job over its student alone."""

from datetime import datetime, timedelta, timezone

import pytest

from app import pai_os_bridge as bridge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.ports import consistency as port
from tests.os.connect_check import assert_consistent
from tests.os.test_connect_p1_rows import (  # noqa: F401
    GERMANY,
    IDS,
    ROUTES,
    choose,
    only_the_sweep,
    same_in_both,
    sweep,
)
from tests.os.test_connect_t5_flow import germany_student, level, row_counts, no_chat, vault  # noqa: F401
from tests.os.test_connect_t8_flow import (  # noqa: F401 - fixture and helpers
    SSC,
    SSC_VALUES,
    signed_in,
    world,
)
from tests.os.test_connect_t8_flow import choose as choose_t8

pytestmark = [pytest.mark.req("R-04"), pytest.mark.req("R-05")]


def nightly(who) -> dict:
    """The nightly job with cases on, run an hour on so nothing counts as in flight."""
    with who.factory() as db:
        return bridge.consistency_run(db, mode="nightly", open_cases=True, now=datetime.now(timezone.utc) + timedelta(hours=1))


def finds_nothing(who) -> None:
    got = nightly(who)
    assert got["students"] >= 1 and got["errors"] == 0, got
    assert got["findings"] == {} and got["opened"] == 0, got
    assert port.cases("open") == []


@pytest.fixture
def lane(world):  # noqa: F811
    store = ProgrammeStore(world.engine, "pai")
    for ref, route in (("pk-p2", "pakistan_bs"), ("pk-i2", "pakistan_inter")):
        store.upsert(Programme(ref=ref, route_key=route, university="University", name=f"Programme {ref}", aliases=(),
                               start_urls=(f"https://example.org/{ref}",), official_domains=("example.org",)))
    return world


@pytest.mark.parametrize("route", ROUTES, ids=IDS)
@pytest.mark.connect_row("6.1", "6.2", "6.4")
def test_the_nightly_job_finds_nothing_after_a_choice_a_change_and_a_withdrawal(lane, route):
    svc_ = lane.svc
    with germany_student() as (client, who, params), only_the_sweep(), level(route.level):
        vault((client, who, params))
        choose(client, params, route)
        assert sweep(svc_, who) == [("planned", None)]
        same_in_both(client, params, who)
        finds_nothing(who)
        choose(client, params, route, list(route.places))
        assert sweep(svc_, who) == [("revised", None)]
        finds_nothing(who)
        from tests.test_roadmap_choice_api import post
        data_ = post(client, params, "withdraw")
        assert data_.status_code == 200
        assert sweep(svc_, who) == [("withdrawn", None)]
        finds_nothing(who)
        assert_consistent(who.factory)


def test_the_nightly_job_finds_nothing_with_two_open_requests(world):  # noqa: F811
    with signed_in(world, germany_student()) as s, level("master"):
        vault((s.client, s.who, s.params))
        choose_t8(s, world, "DE", ["ovgu-eeit", "btu-artificial-intelligence"])
        assert s.rows("open")  # the version-2 plan asks for the certificates
        finds_nothing(s.who)
        assert_consistent(s.who.factory)


def test_the_nightly_job_finds_nothing_with_a_confirmed_document(world):  # noqa: F811
    with signed_in(world, germany_student()) as s, level("master"):
        vault((s.client, s.who, s.params))
        choose_t8(s, world, "DE", ["ovgu-eeit", "btu-artificial-intelligence"])
        s.confirmed("b1_ssc_certificate.png", SSC, SSC_VALUES)
        finds_nothing(s.who)
        assert_consistent(s.who.factory)
