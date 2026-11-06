"""P1-T9 Task 5 (R-51, R-53, R-54, R-55; gate item 8): the whole My plan flow against a real PAI OS on Postgres. The
Counsellor side is the real HTTP API on a student session, the OS side the real services behind the ports. A student
who has not chosen sees an empty plan; after the choice the plan has the route's pages; the pages and sources of a
Germany student; a self-serve plan and its adoption; and with the part off the plan is a 404 and every other answer is
byte for byte what it was with the part on. Fictional students and facts, no model call, and no chat row at any step."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app import pai_os_bridge as bridge
from app.config import config
from app.os import ports
from app.os.knowledge import Fact, SqlKnowledge
from tests.os.test_adoption_flow import own_plan, sources
from tests.os.test_api import agree
from tests.os.test_builder_choice_flow import os_client
from tests.os.test_connect_t5_flow import (  # noqa: F401 - fixtures
    WINTER,
    chosen,
    germany_student,
    level,
    run_os,
    svc,
    vault,
    world,
)
from tests.os.test_connect_t6_flow import OVGU, chat_rows, no_chat
from tests.test_roadmap_api import TOKEN, data
from tests.test_roadmap_choice_api import choose_with

pytestmark = [pytest.mark.req("R-51"), pytest.mark.req("R-53"), pytest.mark.req("R-54"), pytest.mark.req("R-55")]

CHECKED = datetime(2026, 11, 5, tzinfo=timezone.utc)
TODAY = {"start": "Start your plan", "inbox": "Your next steps", "documents": "Your documents",
         "programmes": "Your programmes", "statements": "Your statement and CV", "pack": "Your application packs",
         "visa": "Your visa file"}
EMPTY = {"state": "empty", "source": None, "plan_id": None, "route_key": None, "abroad": None, "pages": [],
         "sources": {}}


@pytest.fixture
def on(world):  # noqa: F811
    """The My plan part on, the OS reading it through the bridge as the host does."""
    ports.configure(world, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice,
                    choice_sink_enabled=bridge.choice_enabled, my_plan_enabled=bridge.my_plan_enabled)
    with patch.object(config, "CONNECT_MY_PLAN", True, create=True):
        yield world


def plan_of(api, ref):
    r = api.get("/v1/os/plan", headers={"X-Test-Student": ref})
    assert r.status_code == 200, r.text
    return r.json()


def test_pk_bs_student_before_and_after_a_choice(on):
    """R-53, R-51: nothing before the choice, then the route's own three pages, no abroad, no visa."""
    from tests.test_roadmap_api import pre_eng

    api = os_client(on)
    with pre_eng() as (client, who, params), level("bachelor"):
        vault((client, who, params))
        before = chat_rows(who)
        assert plan_of(api, who.workspace_id) == EMPTY
        data(choose_with(client, params, destination="PK", places=[{"ref": "pk-p1", "rank": 1}], intake=WINTER))
        assert plan_of(api, who.workspace_id) == EMPTY  # delivered, not yet applied
        assert run_os(on) == [("planned", None)]
        got = plan_of(api, who.workspace_id)
        assert got["state"] != "empty" and got["source"] == "counsellor" and got["route_key"] == "pakistan_bs"
        assert got["abroad"] is False
        assert [p["key"] for p in got["pages"]] == ["inbox", "documents", "programmes"]
        assert bridge.plan_view(who.workspace_id)["pages"] == ["inbox", "documents", "programmes"]  # R-51: the same codes
        assert "visa" not in [p["key"] for p in got["pages"]]
        no_chat(who, before)


def test_germany_student_pages_and_sources(on):
    """R-51, R-54: the seven pages with today's titles; the playbook's source dates and the seeded fact's date."""
    api = os_client(on)
    SqlKnowledge(on.engine, "pai").upsert("programme", OVGU, "english_requirement", Fact(
        {"ielts": 6.0}, "q", "https://uni.example/english", CHECKED, 2027, "confirmed"), "manual")
    with germany_student() as (client, who, params), level("master"):
        vault((client, who, params))
        before = chat_rows(who)
        assert plan_of(api, who.workspace_id) == EMPTY
        data(choose_with(client, params, destination="DE", places=[{"ref": OVGU, "rank": 1}], intake=WINTER))
        assert run_os(on) == [("planned", None)]
        got = plan_of(api, who.workspace_id)
        assert (got["source"], got["route_key"], got["abroad"]) == ("counsellor", "germany_master", True)
        assert {p["key"]: p["title"] for p in got["pages"]} == TODAY and list(TODAY) == [p["key"] for p in got["pages"]]
        assert got["sources"]["https://uni.example/english"] == {"checked_at": "2026-11-05", "confirmed": True}
        dated = {url: s for url, s in got["sources"].items() if s["checked_at"] == "2026-10-17"}
        assert dated and all(s["confirmed"] in (True, False) for s in dated.values())
        assert any(s["confirmed"] is False for s in dated.values())  # the walkthrough's unticked sources say so
        assert any(s["confirmed"] is True for s in dated.values())
        no_chat(who, before)


def test_self_serve_student_and_adoption(on):
    """R-51: an own plan reads self_serve; after the T6 adoption the same plan id reads counsellor with the same pages."""
    with germany_student() as (client, who, params), level("master"):
        vault((client, who, params))
        api = os_client(on)
        before = chat_rows(who)
        plan_id = own_plan(on, who.workspace_id)
        mine = plan_of(api, who.workspace_id)
        assert (mine["source"], mine["plan_id"], mine["state"]) == ("self_serve", plan_id, "active")
        assert {p["key"]: p["title"] for p in mine["pages"]} == TODAY
        data(choose_with(client, params, destination="DE", places=[{"ref": OVGU, "rank": 1}], intake=WINTER))
        assert run_os(on) == [("refused", "self_serve_plan_open")]
        posted = data(client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id}))
        assert posted["state"] == "linking"
        assert run_os(on) == [("revised", None)]
        assert sources(on) == {"counsellor": 1}
        theirs = plan_of(api, who.workspace_id)
        assert (theirs["source"], theirs["plan_id"]) == ("counsellor", plan_id)
        assert theirs["pages"] == mine["pages"]
        no_chat(who, before)


def test_part_off_the_plan_is_a_404_and_nothing_else_changes(on):
    """R-53: the part off, GET /v1/os/plan answers like a route that does not exist; every other answer is the same
    bytes as with the part on (the Task 2 proof, repeated on these students)."""
    api = os_client(on)
    with germany_student() as (client, who, params), level("master"):
        vault((client, who, params))
        agree(api, who.workspace_id)
        data(choose_with(client, params, destination="DE", places=[{"ref": OVGU, "rank": 1}], intake=WINTER))
        assert run_os(on) == [("planned", None)]
        head = {"X-Test-Student": who.workspace_id}
        paths = ["/v1/os/inbox", "/v1/os/programmes", "/v1/os/routes", "/v1/os/consent",
                 f"/v1/os/eligibility/{OVGU}?route=germany_master&intake=2027"]

        def answers():
            out = {p: (lambda r: (r.status_code, r.content))(api.get(p, headers=head)) for p in paths}
            out["roadmap"] = (lambda r: (r.status_code, r.content))(client.get("/v1/roadmap", params=params, headers=TOKEN))
            return out

        with_part = answers()
        assert plan_of(api, who.workspace_id)["state"] != "empty"
        assert all(status == 200 for status, _ in with_part.values()), {p: s for p, (s, _) in with_part.items()}
        with patch.object(config, "CONNECT_MY_PLAN", False, create=True):
            off = api.get("/v1/os/plan", headers=head)
            unknown = api.get("/v1/os/no-such-route", headers=head)
            assert (off.status_code, off.json()) == (unknown.status_code, unknown.json()) == (404, {"detail": "Not Found"})
            assert answers() == with_part
