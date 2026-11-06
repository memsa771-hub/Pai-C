"""P1-T6 Task 6 (R-08, R-09, row 6.16): the whole adoption flow against a real PAI OS on Postgres. A student builds a
plan of their own, chooses in PAI (the intake refuses: a self-serve plan is open), the builder answers `adopt_first`,
the offer appears, the student agrees, version n+1 is written, and the same plan becomes the Counsellor's with its
steps unchanged. Afterwards the builder no longer answers `adopt_first`. Fictional data."""

from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import RouteDecision
from app.os import models, ports
from app.os.contracts.route_contract import RouteContract
from tests.os.test_builder_choice_flow import START, WINTER, os_client
from tests.os.test_api import agree
from tests.os.test_connect_t5_flow import chosen, germany_student, level, run_os, svc, world  # noqa: F401 - fixtures
from tests.test_roadmap_api import TOKEN, data
from tests.test_roadmap_choice_api import choose_with, vault

pytestmark = pytest.mark.req("R-08")

P, T = models.plans, models.tasks
PLACES = ["ovgu-eeit", "btu-artificial-intelligence"]


def own_plan(svc_, student_ref):
    return svc_.plans.start_plan(RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"self:{student_ref}:germany_master:winter:2027",
        "student_ref": student_ref, "origin_country": "PK", "destination_country": "DE", "level": "master",
        "target_intake": WINTER, "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(PLACES)]})).plan_id


def tasks(svc_, plan_id):
    with svc_.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(select(T.c.id, T.c.instance_key, T.c.state).where(
            T.c.plan_id == plan_id).order_by(T.c.id)).all()]


def sources(svc_):
    with svc_.engine.connect() as conn:
        return dict(conn.execute(select(P.c.source, func.count()).group_by(P.c.source)).all())


def test_adopt_first_then_adoption_then_builder_is_free(world):
    svc_ = world
    with germany_student() as (client, who, params), level("master"), \
            patch.object(config, "CONNECT_MY_PLAN", True, create=True):
        vault((client, who, params))
        plan_id = own_plan(svc_, who.workspace_id)  # the student's own plan, built before they chose
        before = tasks(svc_, plan_id)
        data(choose_with(client, params, destination="DE", places=[{"ref": "ovgu-eeit", "rank": 1}], intake=WINTER))
        assert run_os(svc_) == [("refused", "self_serve_plan_open")]  # nothing adopted without the student's word

        ports.configure(svc_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice,
                        choice_sink_enabled=bridge.choice_enabled)
        os_api = os_client(svc_)
        agree(os_api, who.workspace_id)
        h = {"X-Test-Student": who.workspace_id}
        body = {**START, "choices": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(PLACES)]}
        r = os_api.post("/v1/os/plans/self", headers=h, json=body)
        assert r.status_code == 409 and r.json()["detail"] == "adopt_first"  # adoption is the way out

        offer = data(client.get("/v1/roadmap/adoption", params=params, headers=TOKEN))
        assert offer["offer"] is True and offer["state"] == "ready"
        assert offer["plan"] == {"plan_id": plan_id, "route_key": "germany_master", "places": 2}
        posted = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})
        assert data(posted) == {"state": "linking", "decision_version": 2}
        again = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})
        assert data(again) == {"state": "linking", "decision_version": 2}  # a repeat: the same version
        with who.factory() as db:
            assert db.scalar(select(func.max(RouteDecision.decision_version)).where(
                RouteDecision.workspace_id == who.workspace_id)) == 2

        assert run_os(svc_) == [("revised", None)]  # delivered at once; the intake adopts the plan
        assert sources(svc_) == {"counsellor": 1}  # the same plan, now the Counsellor's: no second plan
        with svc_.engine.connect() as conn:
            assert conn.execute(select(P.c.id)).scalars().all() == [plan_id]
        assert tasks(svc_, plan_id) == before  # same steps, same states
        page = chosen(client, params)
        assert page["plan"]["decision_version"] == 2 and page["plan"]["state"] != "empty"
        assert data(client.get("/v1/roadmap/adoption", params=params, headers=TOKEN)) == {"offer": False}

        r = os_api.post("/v1/os/plans/self", headers=h, json=body)  # the builder is free: no adopt_first any more
        assert r.status_code == 202, r.text
        assert r.json()["state"] == "unchanged" and r.json()["decision_version"] == 2
        assert sources(svc_) == {"counsellor": 1}
