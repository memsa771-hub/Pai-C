"""P1-T6 Task 6 (R-08, row 6.16): the adoption offer and the student's agreement over HTTP. PAI OS is stubbed at the
bridge (the real OS flow is in tests/os/test_adoption_flow.py); fictional data."""

from unittest.mock import patch

import pytest
from sqlalchemy import select, update

from app import pai_os_bridge as bridge
from app.config import config
from app.models import RouteDecision, StudentJourney
from app.pai_c.connect import adoption_texts
from tests.test_handoff_delivery import flag, os_stub  # noqa: F401 - the fixture is used by name
from tests.test_roadmap_api import TOKEN, data, pre_eng
from tests.test_roadmap_choice_api import choose_with, stubs, vault  # noqa: F401 - stubs is autouse

pytestmark = pytest.mark.req("R-08")

AUTUMN = {"term": "autumn", "year": 2027}
SHA = "a" * 64


def plan(places=2, plan_id=7) -> dict:
    return {"plan_id": plan_id, "route_key": "gb_bachelor", "origin": "PK", "destination": "GB", "level": "bachelor",
            "intake": AUTUMN, "programmes": [{"programme_ref": r, "rank": i + 1}
                                             for i, r in enumerate(("uni-c:cs", "uni-a:cs", "uni-b:ee", "uni-d", "uni-e",
                                                                    "uni-f")[:places])],
            "contract_sha256": SHA}


@pytest.fixture
def world(os_stub):  # noqa: F811
    got = {"plan": plan(), "recorded": "recorded", "asked": [], "raises": None}

    def request(ws, plan_id):
        got["asked"].append((ws, plan_id))
        if got["raises"]:
            raise got["raises"]
        return got["recorded"]

    with flag(True), patch.object(config, "CONNECT_MY_PLAN", True, create=True), \
            patch.object(bridge, "self_serve_plan", lambda ws: got["plan"]), \
            patch.object(bridge, "request_adoption", request):
        yield got


def offer(client, params):
    return data(client.get("/v1/roadmap/adoption", params=params, headers=TOKEN))


def agree(client, params, plan_id=7):
    return client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})


def versions(student):
    with student.factory() as db:
        return list(db.scalars(select(RouteDecision).order_by(RouteDecision.decision_version)))


def chosen(client, params, student):
    vault((client, student, params))
    data(choose_with(client, params, places=[{"ref": "uni-a:cs", "rank": 1}]))


def test_offer_states(world):
    with pre_eng() as (client, student, params):
        with student.factory() as db:  # no journey: no offer
            db.execute(update(StudentJourney).values(status="abandoned"))
            db.commit()
        assert offer(client, params) == {"offer": False}
        with student.factory() as db:
            db.execute(update(StudentJourney).values(status="active"))
            db.commit()
        body = offer(client, params)  # a journey, but no active decision
        assert body["offer"] is True and body["state"] == "choose_field_first"
        assert body["plan"] == {"plan_id": 7, "route_key": "gb_bachelor", "places": 2}
        chosen(client, params, student)
        assert offer(client, params)["state"] == "ready"
        world["plan"] = plan(places=6)
        assert offer(client, params)["state"] == "too_many_places"
        world["plan"] = None  # no open self-serve plan
        assert offer(client, params) == {"offer": False}


def test_offer_false_when_my_plan_off(world):
    with pre_eng() as (client, student, params):
        chosen(client, params, student)
        with patch.object(config, "CONNECT_MY_PLAN", False, create=True):
            assert offer(client, params) == {"offer": False}
        with flag(False):
            assert offer(client, params) == {"offer": False}


def test_post_409_when_handoff_off(world):
    """The same refusal `_need_handoff` gives every hand-off write today; nothing is asked of PAI OS."""
    with pre_eng() as (client, student, params), flag(False):
        r = agree(client, params)
        assert r.status_code == 409 and r.json()["detail"] == "The connection to PAI OS is not on"
        assert world["asked"] == [] and versions(student) == []


def test_adoption_text_null_until_approved(world):
    assert adoption_texts._RAW["approved"] is False  # stored unapproved: the owner approves it
    with pre_eng() as (client, student, params):
        assert offer(client, params)["text"] is None
        with patch.object(config, "CONNECT_CONSENT_DRAFT", True, create=True):  # rehearsal
            text = offer(client, params)["text"]
        assert set(text) == set(adoption_texts.KEYS) and all(text.values())
        with patch.dict(adoption_texts._RAW, {"approved": True}):
            assert set(offer(client, params)["text"]) == set(adoption_texts.KEYS)


def test_post_adoption_writes_version_and_intent(world, os_stub):  # noqa: F811
    with pre_eng() as (client, student, params):
        chosen(client, params, student)
        ws = student.workspace_id
        body = data(agree(client, params))
        assert body == {"state": "linking", "decision_version": 2}
        assert world["asked"] == [(ws, 7)]  # the intent first
        old, new = versions(student)
        assert new.request_key == f"adopt:7:{SHA}" and old.withdrawn_at is not None
        assert [p["programme_ref"] for p in new.places] == ["uni-c:cs", "uni-a:cs"] and new.intake == AUTUMN
        assert (new.field_key, new.authorized_at, new.consent_version) == (old.field_key, old.authorized_at,
                                                                         old.consent_version)  # copied, not invented
        assert [e["decision_version"] for e in os_stub["submitted"]][-1] == 2  # delivered right away
        again = data(agree(client, params))  # a repeat: the same version, no n+2
        assert again == {"state": "linking", "decision_version": 2} and len(versions(student)) == 2


def test_post_refusals_write_nothing(world):
    with pre_eng() as (client, student, params):
        r = agree(client, params)  # no active decision
        assert r.status_code == 409 and r.json()["detail"] == "choose_field_first" and world["asked"] == []
        chosen(client, params, student)
        assert agree(client, params, plan_id=99).json()["detail"] == "no_plan"  # not the student's open plan
        world["plan"] = plan(places=6)
        assert agree(client, params).json()["detail"] == "too_many_places"
        world["plan"] = plan()
        world["recorded"] = "not_found"
        assert agree(client, params).status_code == 409
        world["recorded"] = "recorded"
        world["raises"] = RuntimeError("secret detail")
        r = agree(client, params)
        assert r.status_code == 503 and "secret" not in r.text
        assert len(versions(student)) == 1  # nothing was written for an agreement PAI OS did not take
