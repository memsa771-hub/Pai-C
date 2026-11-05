"""P1-T2 Task 6 (R-59): with every connection flag at its default the app behaves as before this branch. Choose and
withdraw answer with the same keys and values the roadmap API tests rely on (the response never shows the added
`decision_version`), the journey moves as before, no outbox row is written, and the sweep never touches PAI OS."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import OsOutbox, RouteDecision, StudentJourney
from app.os import ports
from app.os.ports import escalation as os_escalation
from app.os.ports import plan_source
from app.pai_c.connect.flags import PARTS
from tests.test_route_journey import TOKEN, choose, confirmed_student, stage, with_routes

pytestmark = pytest.mark.req("R-59")

CHOOSE_KEYS = {"id", "field_key", "possibility_id", "title", "chosen_at", "withdrawn_at", "steps", "time",
               "snapshot_steps", "steps_done", "route", "snapshot_verdict", "live_status"}


def test_every_connection_flag_defaults_to_off():
    assert PARTS and not any(getattr(config, name) for name in PARTS)


def outbox_count(db) -> int:
    db.expire_all()
    return len(db.scalars(select(OsOutbox)).all())


@pytest.mark.asyncio
async def test_choose_and_withdraw_behave_as_before(monkeypatch):
    touched = MagicMock()  # any call into PAI OS lands here
    for module, names in ((plan_source, ("submit_decision", "latest_version", "supports", "counsellor_enabled")),
                          (os_escalation, ("pending_counsellor_escalations",))):
        for name in names:
            monkeypatch.setattr(module, name, getattr(touched, name))
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        first = choose(client, student, "electrical_engineering")
        assert set(first) == CHOOSE_KEYS and "decision_version" not in first
        assert (first["field_key"], first["withdrawn_at"], first["steps_done"]) == ("electrical_engineering", None, [])
        assert stage(db, journey_id) == "CHOSEN"
        journey = db.get(StudentJourney, journey_id)
        assert journey.current_objective == first["title"]
        assert journey.active_goal == {"route_decision_id": first["id"], "field_key": "electrical_engineering",
                                       "title": first["title"], "route": first["route"]}
        assert journey.decisions[-1]["kind"] == "route_choice"

        second = choose(client, student, "computer_engineering")  # choosing again withdraws the first
        db.expire_all()
        kinds = [(d["kind"], d["route_decision_id"]) for d in db.get(StudentJourney, journey_id).decisions]
        assert kinds[-3:] == [("route_choice", first["id"]), ("route_withdrawn", first["id"]),
                              ("route_choice", second["id"])]
        assert db.get(RouteDecision, first["id"]).withdrawn_at is not None

        response = client.post("/v1/roadmap/withdraw", params={"network": student.workspace_id}, headers=TOKEN)
        assert response.status_code == 200, response.text
        withdrawn = response.json()["data"]
        assert set(withdrawn) == CHOOSE_KEYS and withdrawn["id"] == second["id"]
        assert withdrawn["withdrawn_at"] is not None
        assert stage(db, journey_id) == "PROPOSED"
        journey = db.get(StudentJourney, journey_id)
        assert journey.active_goal is None and journey.current_objective is None
        assert journey.decisions[-1]["kind"] == "route_withdrawn" and journey.decisions[-1]["route_decision_id"] == second["id"]

        assert outbox_count(db) == 0  # nothing queued for PAI OS
        assert touched.mock_calls == []  # and nothing asked of it


@pytest.mark.asyncio
async def test_sweep_and_delivery_do_not_touch_the_os_ports(monkeypatch):
    touched = MagicMock()
    touched.pending.return_value = []
    monkeypatch.setattr(ports, "services", touched.services)
    monkeypatch.setattr(plan_source, "submit_decision", touched.submit_decision)
    monkeypatch.setattr(plan_source, "latest_version", touched.latest_version)
    monkeypatch.setattr(os_escalation, "pending_counsellor_escalations", touched.pending)
    async with confirmed_student() as (client, student, db, _j):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        assert bridge.deliver_pending(db) == {"delivered": 0, "failed": 0, "not_sent": 0}
        assert bridge.deliver_pending(db, student.workspace_id) == {"delivered": 0, "failed": 0, "not_sent": 0}
        got = bridge.sweep_once(db)  # flags off: decisions are left alone (escalation delivery is the old behaviour)
        assert got.get("submitted") == 0 and got.get("failed") == 0
        assert touched.submit_decision.mock_calls == [] and touched.latest_version.mock_calls == []
        assert outbox_count(db) == 0
