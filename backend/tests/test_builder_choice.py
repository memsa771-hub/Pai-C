"""P1-T6 Task 5 (R-09, rows 6.13 and 6.17): with the Counsellor on, the OS route builder writes through the decision
service. `request_from_builder` copies the student's field and consent from the active decision (D-x4); the builder's
start then answers 202 and the plan comes from the intake of the new version. With the host part off the builder works
standalone. Fictional data; the OS is real, on Postgres."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import OsOutbox, RouteDecision
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap.decisions import RouteDecisionService
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = pytest.mark.req("R-09")

DETAILS = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                        places=(("uni-a:cs", 1), ("uni-b:cs", 2)), intake=("autumn", 2027), path_ref="path-1",
                        authorized_at=datetime(2026, 11, 1, tzinfo=timezone.utc), consent_version="1")
AUTUMN = {"term": "autumn", "year": 2027}
THREE = [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(("uni-c:cs", "uni-a:cs", "uni-b:cs"))]


@pytest.fixture(autouse=True)
def route_runs():
    with patch("app.pai_os_bridge.route_supported", return_value=True):
        yield


def on():
    return patch("app.pai_c.connect.outbox.part_on", return_value=True)


def rows(db, ws):
    db.expire_all()
    return list(db.scalars(select(RouteDecision).where(RouteDecision.workspace_id == ws)
                           .order_by(RouteDecision.decision_version)))


async def one_choice(student, db):
    with_routes(student, db)
    service = RouteDecisionService(db)
    with on():
        service.choose(student.workspace_id, "electrical_engineering", details=DETAILS)
    db.commit()
    return service


# --- the decision service (D-x4) -------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_from_builder_copies_field_and_consent():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await one_choice(student, db)
        with on():
            assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE) == ("written", 2, None)
        db.commit()
        old, new = rows(db, ws)
        for name in ("field_key", "possibility_id", "title", "verdict", "route", "steps", "steps_done", "chosen_at",
                     "authorized_at", "guardian_authorized_at", "guardian_required", "consent_version", "path_ref"):
            assert getattr(new, name) == getattr(old, name), name
        assert [p["programme_ref"] for p in new.places] == ["uni-c:cs", "uni-a:cs", "uni-b:cs"]
        assert [p["rank"] for p in new.places] == [1, 2, 3]
        assert new.request_key.startswith("builder:") and old.request_key is None
        assert new.status == "chosen" and old.withdrawn_at is not None and new.withdrawn_at is None
        assert db.scalar(select(OsOutbox.status).where(OsOutbox.key == f"decision:{ws}:2")) == "pending"


@pytest.mark.asyncio
async def test_no_active_decision_is_choose_field_first():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = RouteDecisionService(db)
        assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE) == (
            "refused", None, "choose_field_first")
        assert rows(db, ws) == []
        service = await one_choice(student, db)  # a withdrawn choice is no choice
        with on():
            service.withdraw(ws)
        db.commit()
        assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE)[2] == "choose_field_first"
        assert len(rows(db, ws)) == 2


@pytest.mark.asyncio
async def test_six_places_is_too_many_places_and_writes_nothing():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await one_choice(student, db)
        six = [{"programme_ref": f"uni-{i}:cs", "rank": i + 1} for i in range(6)]
        assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, six) == (
            "refused", None, "too_many_places")
        assert len(rows(db, ws)) == 1


@pytest.mark.asyncio
async def test_repeat_is_unchanged_not_a_new_version():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await one_choice(student, db)
        same = [{"programme_ref": "uni-a:cs", "rank": 1}, {"programme_ref": "uni-b:cs", "rank": 2}]
        with on():
            assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, same) == ("unchanged", 1, None)
            assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE) == ("written", 2, None)
            db.commit()
            assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE) == ("unchanged", 2, None)
        db.commit()
        assert len(rows(db, ws)) == 2


@pytest.mark.asyncio
async def test_going_back_to_an_earlier_choice_is_a_new_version():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await one_choice(student, db)
        first = [{"programme_ref": "uni-a:cs", "rank": 1}, {"programme_ref": "uni-b:cs", "rank": 2}]
        with on():
            service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE)
            db.commit()
            assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, first) == ("written", 3, None)
            db.commit()
            assert service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE) == ("written", 4, None)


@pytest.mark.asyncio
async def test_path_ref_kept_only_when_destination_and_level_unchanged():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await one_choice(student, db)
        with on():
            service.request_from_builder(ws, "PK", "GB", "bachelor", AUTUMN, THREE)
            db.commit()
            assert rows(db, ws)[-1].path_ref == "path-1"
            service.request_from_builder(ws, "PK", "DE", "master", AUTUMN, THREE)
            db.commit()
        last = rows(db, ws)[-1]
        assert last.path_ref is None and (last.destination_country, last.level) == ("DE", "master")


@pytest.mark.asyncio
async def test_intake_change_alone_is_a_change():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await one_choice(student, db)
        same = [{"programme_ref": "uni-a:cs", "rank": 1}, {"programme_ref": "uni-b:cs", "rank": 2}]
        with on():
            assert service.request_from_builder(ws, "PK", "GB", "bachelor", {"term": "autumn", "year": 2028},
                                                same) == ("written", 2, None)
