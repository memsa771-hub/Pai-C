"""Every choice and withdrawal is a new decision version row (rule D-a)."""

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import RouteDecision, StudentJourney
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap.decisions import RouteDecisionService
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = [pytest.mark.req("R-02"), pytest.mark.req("R-79")]

# The keys the returned dict had before versions existed.
TODAY_KEYS = {"id", "field_key", "possibility_id", "title", "chosen_at", "withdrawn_at", "steps", "time",
              "snapshot_steps", "steps_done", "route", "snapshot_verdict", "live_status"}


def rows(db, workspace_id):
    db.expire_all()
    return list(db.scalars(select(RouteDecision).where(RouteDecision.workspace_id == workspace_id)
                           .order_by(RouteDecision.decision_version)))


DETAILS = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                        places=(("uni-a:cs", 1), ("uni-b:cs", 2)), intake=("autumn", 2027), path_ref="path-1")


@pytest.mark.asyncio
async def test_versions_go_up_per_student():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        service = RouteDecisionService(db)
        service.choose(student.workspace_id, "electrical_engineering")
        service.choose(student.workspace_id, "computer_engineering")
        service.withdraw(student.workspace_id)
        service.choose(student.workspace_id, "electrical_engineering")
        db.commit()
        found = rows(db, student.workspace_id)
        assert [r.decision_version for r in found] == [1, 2, 3, 4]
        assert [r.status for r in found] == ["chosen", "chosen", "withdrawn", "chosen"]
        assert found[2].places == []
        assert service.newest(student.workspace_id).decision_version == 4
        assert [r.decision_version for r in found if r.withdrawn_at is None] == [4]


@pytest.mark.asyncio
async def test_withdraw_row_is_never_active():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        service = RouteDecisionService(db)
        service.choose(student.workspace_id, "electrical_engineering")
        service.withdraw(student.workspace_id)
        db.commit()
        assert service.active(student.workspace_id) is None
        found = rows(db, student.workspace_id)
        withdrawn = found[-1]
        assert withdrawn.status == "withdrawn" and withdrawn.withdrawn_at == withdrawn.chosen_at
        assert withdrawn.field_key == found[0].field_key and withdrawn.steps_done == []
        assert found[0].withdrawn_at is not None


@pytest.mark.asyncio
async def test_versions_are_per_workspace():
    async with confirmed_student() as (_, first, db, _journey):
        with_routes(first, db)
        RouteDecisionService(db).choose(first.workspace_id, "electrical_engineering")
        db.commit()
    async with confirmed_student() as (_, second, db2, _journey):
        with_routes(second, db2)
        RouteDecisionService(db2).choose(second.workspace_id, "electrical_engineering")
        db2.commit()
        assert [r.decision_version for r in rows(db2, second.workspace_id)] == [1]


@pytest.mark.asyncio
async def test_version_is_unique_by_index():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        service = RouteDecisionService(db)
        service.choose(student.workspace_id, "electrical_engineering")
        db.commit()
        first = rows(db, student.workspace_id)[0]
        assert service._next_version(student.workspace_id) == 2
        db.add(RouteDecision(workspace_id=student.workspace_id, decision_version=1, field_key="x", title="x",
                             verdict={}, route={}, steps=[], steps_done=[], withdrawn_at=first.chosen_at))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [True, False])
async def test_details_stored(supported):
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        with patch("app.pai_os_bridge.route_supported", return_value=supported) as check:
            RouteDecisionService(db).choose(student.workspace_id, "electrical_engineering", details=DETAILS)
        check.assert_called_once_with("PK", "GB", "bachelor")
        db.commit()
        row = rows(db, student.workspace_id)[0]
        assert (row.origin_country, row.destination_country, row.level) == ("PK", "GB", "bachelor")
        assert row.places == [{"programme_ref": "uni-a:cs", "rank": 1}, {"programme_ref": "uni-b:cs", "rank": 2}]
        assert row.intake == {"term": "autumn", "year": 2027} and row.path_ref == "path-1"
        assert row.os_supported is supported and row.status == "chosen"


@pytest.mark.asyncio
async def test_no_details_is_not_supported():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        with patch("app.pai_os_bridge.route_supported") as check:
            RouteDecisionService(db).choose(student.workspace_id, "electrical_engineering")
        check.assert_not_called()
        db.commit()
        row = rows(db, student.workspace_id)[0]
        assert row.os_supported is False and row.places == [] and row.intake is None


@pytest.mark.asyncio
async def test_withdraw_copies_the_route_fields():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        service = RouteDecisionService(db)
        with patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(student.workspace_id, "electrical_engineering", details=DETAILS)
        service.withdraw(student.workspace_id)
        db.commit()
        chosen, withdrawn = rows(db, student.workspace_id)
        for name in ("field_key", "possibility_id", "title", "verdict", "route", "origin_country",
                     "destination_country", "level", "path_ref", "os_supported"):
            assert getattr(withdrawn, name) == getattr(chosen, name), name
        assert withdrawn.places == [] and withdrawn.intake is None


@pytest.mark.asyncio
async def test_journey_entries_carry_the_version():
    async with confirmed_student() as (_, student, db, journey_id):
        with_routes(student, db)
        service = RouteDecisionService(db)
        service.choose(student.workspace_id, "electrical_engineering")
        service.withdraw(student.workspace_id)
        db.commit()
        db.expire_all()
        entries = db.get(StudentJourney, journey_id).decisions
        by_kind = {e["kind"]: e for e in entries}
        assert by_kind["route_choice"]["decision_version"] == 1
        assert by_kind["route_withdrawn"]["decision_version"] == 2


@pytest.mark.asyncio
async def test_today_shape_unchanged():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        service = RouteDecisionService(db)
        assert set(service.choose(student.workspace_id, "electrical_engineering")) == TODAY_KEYS
        assert set(service.withdraw(student.workspace_id)) == TODAY_KEYS


def test_route_supported_is_false_on_any_failure(monkeypatch):
    from app import pai_os_bridge
    from app.os import ports
    from app.os.ports import plan_source

    monkeypatch.setattr(plan_source, "supports", lambda *a: True)
    assert pai_os_bridge.route_supported("PK", "GB", "bachelor") is True
    for error in (ports.OsUnavailable("off"), RuntimeError("boom")):
        def fail(*args, _error=error):
            raise _error
        monkeypatch.setattr(plan_source, "supports", fail)
        assert pai_os_bridge.route_supported("PK", "GB", "bachelor") is False
