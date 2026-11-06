"""P1-T6 Task 5 (R-09, rows 6.13 and 6.17): the whole builder flow with the Counsellor on, against a real PAI OS on
Postgres. The student starts a plan in the OS route builder; the choice goes through the decision service (version
n+1), the OS builder answers 202 and makes no plan of its own, and the Counsellor plan is revised from the intake.
With the host part off the builder works standalone. Fictional data."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import pai_os_bridge as bridge
from app.models import RouteDecision
from app.os import models, ports
from app.os.api import build_router, current_student_ref, current_student_ref_for_write
from app.os.knowledge.programmes import Programme, ProgrammeStore
from tests.os.test_api import TEST_TERMS, agree
from tests.os.test_connect_t5_flow import chosen, germany_student, level, run_os, svc, world  # noqa: F401 - fixtures
from tests.test_roadmap_api import data
from tests.test_roadmap_choice_api import choose_with, vault

pytestmark = pytest.mark.req("R-09")

P = "/v1/os"
WINTER = {"term": "winter", "year": 2027}

# --- the bridge and the whole flow -----------------------------------------------------------------------------

def os_client(svc_) -> TestClient:
    """The OS API on the world's services, with the pilot terms of the tests; the student is the header."""
    app = FastAPI()
    app.include_router(build_router(lambda: replace(svc_, terms_dir=TEST_TERMS)), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    return TestClient(app)


def count(svc_, source: str) -> int:
    with svc_.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.plans).where(models.plans.c.source == source)).scalar()


START = {"route": "germany_master", "intake": WINTER}


def begin(world_, client, who, params, places):
    """A student with a Germany master choice (version 1) planned by the OS."""
    vault((client, who, params))
    data(choose_with(client, params, destination="DE", places=places, intake=WINTER))
    assert run_os(world_) == [("planned", None)]


def test_builder_with_counsellor_on_writes_decision(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"):
        begin(svc_, client, who, params, [{"ref": "ovgu-eeit", "rank": 1}])
        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice)
        os_api = os_client(svc_)
        agree(os_api, who.workspace_id)
        body = {**START, "choices": [{"programme_ref": "ovgu-eeit", "rank": 1},
                                     {"programme_ref": "btu-artificial-intelligence", "rank": 2}]}
        r = os_api.post(f"{P}/plans/self", headers={"X-Test-Student": who.workspace_id}, json=body)
        assert r.status_code == 202, r.text
        assert r.json() == {"state": "preparing", "decision_version": 2, "note": None}
        assert count(svc_, "self_serve") == 0  # the builder made no plan of its own
        # the bridge delivered version 2 to the OS; the intake revises the Counsellor plan
        assert run_os(svc_) == [("revised", None)]
        assert count(svc_, "self_serve") == 0 and count(svc_, "counsellor") == 1
        page = chosen(client, params)
        assert page["plan"]["decision_version"] == 2
        with svc_.engine.connect() as conn:  # the Counsellor plan now holds the builder's places, in order
            contract = conn.execute(select(models.plans.c.contract).where(models.plans.c.source == "counsellor")).scalar()
        assert [p["programme_ref"] for p in sorted(contract["programmes"], key=lambda p: p["rank"])] == [
            "ovgu-eeit", "btu-artificial-intelligence"]


def test_builder_no_field_is_409_choose_field_first(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"):
        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice)
        os_api = os_client(svc_)
        agree(os_api, who.workspace_id)
        body = {**START, "choices": [{"programme_ref": "ovgu-eeit", "rank": 1}]}
        r = os_api.post(f"{P}/plans/self", headers={"X-Test-Student": who.workspace_id}, json=body)
        assert r.status_code == 409 and r.json()["detail"] == "choose_field_first"
        assert count(svc_, "self_serve") == 0 and count(svc_, "counsellor") == 0


def test_builder_six_places_is_409_too_many_places(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"):
        begin(svc_, client, who, params, [{"ref": "ovgu-eeit", "rank": 1}])
        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice)
        os_api = os_client(svc_)
        agree(os_api, who.workspace_id)
        store = ProgrammeStore(svc_.engine, "pai")
        for i in range(6):  # fictional programmes of the route, so six places pass the builder's own checks
            store.upsert(Programme(ref=f"six-{i}", route_key="germany_master", university="Uni X", name=f"P {i}",
                                   aliases=(), start_urls=(f"https://uni.example/{i}",), official_domains=("uni.example",)))
        refs = [f"six-{i}" for i in range(6)]
        body = {**START, "choices": [{"programme_ref": r_, "rank": i + 1} for i, r_ in enumerate(refs[:6])]}
        r = os_api.post(f"{P}/plans/self", headers={"X-Test-Student": who.workspace_id}, json=body)
        assert r.status_code == 409 and r.json()["detail"] == "too_many_places"


def test_builder_repeat_is_unchanged_not_new_version(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"):
        begin(svc_, client, who, params, [{"ref": "ovgu-eeit", "rank": 1}])
        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice)
        os_api = os_client(svc_)
        agree(os_api, who.workspace_id)
        h = {"X-Test-Student": who.workspace_id}
        body = {**START, "choices": [{"programme_ref": "ovgu-eeit", "rank": 1},
                                     {"programme_ref": "btu-artificial-intelligence", "rank": 2}]}
        assert os_api.post(f"{P}/plans/self", headers=h, json=body).json()["decision_version"] == 2
        again = os_api.post(f"{P}/plans/self", headers=h, json=body)
        assert again.status_code == 202 and again.json()["decision_version"] == 2
        with who.factory() as db:
            assert db.scalar(select(func.max(RouteDecision.decision_version)).where(
                RouteDecision.workspace_id == who.workspace_id)) == 2


def test_builder_note_null_until_approved(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"):
        begin(svc_, client, who, params, [{"ref": "ovgu-eeit", "rank": 1}])
        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice)
        os_api = os_client(svc_)
        agree(os_api, who.workspace_id)
        r = os_api.post(f"{P}/plans/self", headers={"X-Test-Student": who.workspace_id}, json={
            **START, "choices": [{"programme_ref": "ovgu-eeit", "rank": 1},
                                 {"programme_ref": "btu-artificial-intelligence", "rank": 2}]})
        assert r.status_code == 202 and r.json()["note"] is None


def test_handoff_off_the_bridge_answers_none_and_the_builder_is_standalone(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"), \
            patch("app.config.config.CONNECT_HANDOFF", False, create=True):
        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice)
        assert bridge.request_choice(who.workspace_id, "PK", "DE", "master", WINTER,
                                     [{"programme_ref": "ovgu-eeit", "rank": 1}]) is None
        os_api = os_client(svc_)
        agree(os_api, who.workspace_id)
        r = os_api.post(f"{P}/plans/self", headers={"X-Test-Student": who.workspace_id}, json={
            **START, "choices": [{"programme_ref": "ovgu-eeit", "rank": 1}]})
        assert r.status_code == 201, r.text
        assert count(svc_, "self_serve") == 1
        with who.factory() as db:
            assert db.scalar(select(func.count()).select_from(RouteDecision).where(
                RouteDecision.workspace_id == who.workspace_id)) == 0
