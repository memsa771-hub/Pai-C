"""P1-T6 Task 3 (R-07): the decision service writes an accepted OS choice request as version n+1, once, and only while
the choice it was made against is still the newest. Fictional data; PAI OS stubbed."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import OsOutbox, RouteDecision
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap.decisions import RouteDecisionService
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = pytest.mark.req("R-07")

DETAILS = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                        places=(("uni-a:cs", 1), ("uni-b:cs", 2)), intake=("autumn", 2027), path_ref="path-1",
                        authorized_at=datetime(2026, 11, 1, tzinfo=timezone.utc), consent_version="1")
OTHER = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                      places=(("uni-c:cs", 1),), intake=("autumn", 2027), path_ref="path-1",
                      authorized_at=datetime(2026, 11, 1, tzinfo=timezone.utc), consent_version="1")


def request(key="choice_request:7", base=1, refs=("uni-b:cs", "uni-a:cs")):
    return {"schema": "pai.choice_request.v1", "key": key, "student_ref": "x", "journey_id": "j", "proposal_id": 7,
            "based_on_version": base,
            "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)],
            "target_intake": None, "requested_at": "2026-11-06T10:00:00Z"}


def on():
    return patch("app.pai_c.connect.outbox.part_on", return_value=True)


def rows(db, ws):
    db.expire_all()
    return list(db.scalars(select(RouteDecision).where(RouteDecision.workspace_id == ws)
                           .order_by(RouteDecision.decision_version)))


def outbox_keys(db, ws):
    db.expire_all()
    return sorted(db.scalars(select(OsOutbox.key).where(OsOutbox.workspace_id == ws)))


async def three_versions(student, db):
    """v1 chosen, v2 consent copy, v3 consent copy: the request below is made against v1 or v3 as a test needs."""
    with_routes(student, db)
    service = RouteDecisionService(db)
    with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
        service.choose(student.workspace_id, "electrical_engineering", details=DETAILS)
    db.commit()
    return service


@pytest.mark.asyncio
async def test_written_when_base_current():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            assert service.apply_choice_request(ws, request()) == ("written", 2)
        db.commit()
        old, new = rows(db, ws)
        assert [p["programme_ref"] for p in new.places] == ["uni-b:cs", "uni-a:cs"]
        assert [p["rank"] for p in new.places] == [1, 2]
        assert new.request_key == "choice_request:7" and new.status == "chosen" and old.withdrawn_at is not None
        assert new.intake == old.intake and new.field_key == old.field_key and new.authorized_at == old.authorized_at
        assert new.consent_version == "1" and new.destination_country == "GB" and new.level == "bachelor"
        assert outbox_keys(db, ws) == [f"decision:{ws}:1", f"decision:{ws}:2"]
        sent = db.scalar(select(OsOutbox).where(OsOutbox.key == f"decision:{ws}:2"))
        assert sent.status == "pending" and sent.payload["decision_version"] == 2


@pytest.mark.asyncio
async def test_consent_copy_does_not_make_stale():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        with on():
            service.update_consent(ws, authorized_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
            db.commit()
            assert service.newest(ws).decision_version == 2
            assert service.apply_choice_request(ws, request(base=1)) == ("written", 3)
        db.commit()
        assert rows(db, ws)[-1].authorized_at.date().isoformat() == "2026-11-02"  # the newer consent is kept


@pytest.mark.asyncio
async def test_changed_places_make_stale():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=OTHER)
            db.commit()
            before = (len(rows(db, ws)), outbox_keys(db, ws))
            assert service.apply_choice_request(ws, request(base=1)) == ("stale", None)
        db.commit()
        assert (len(rows(db, ws)), outbox_keys(db, ws)) == before


@pytest.mark.asyncio
async def test_changed_intake_makes_stale():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        later = ChoiceDetails(**{**DETAILS.__dict__, "intake": ("autumn", 2028)})
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=later)
            db.commit()
            assert service.apply_choice_request(ws, request(base=1)) == ("stale", None)


@pytest.mark.asyncio
async def test_withdrawn_makes_stale():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        with on():
            service.withdraw(ws)
            db.commit()
            assert service.apply_choice_request(ws, request(base=1)) == ("stale", None)
        db.commit()
        assert len(rows(db, ws)) == 2


@pytest.mark.asyncio
async def test_missing_base_is_stale():
    async with confirmed_student() as (_, student, db, _j):
        service = await three_versions(student, db)
        assert service.apply_choice_request(student.workspace_id, request(base=9)) == ("stale", None)


@pytest.mark.asyncio
async def test_repeat_is_duplicate_not_n_plus_2():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            assert service.apply_choice_request(ws, request()) == ("written", 2)
            db.commit()
            count, keys = len(rows(db, ws)), outbox_keys(db, ws)
            assert service.apply_choice_request(ws, request()) == ("duplicate", 2)
            db.commit()
        assert (len(rows(db, ws)), outbox_keys(db, ws)) == (count, keys)


@pytest.mark.asyncio
async def test_duplicate_wins_over_stale_after_a_later_version():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.apply_choice_request(ws, request())
            service.update_consent(ws, authorized_at=datetime(2026, 11, 3, tzinfo=timezone.utc))
            db.commit()
            assert service.apply_choice_request(ws, request()) == ("duplicate", 2)


@pytest.mark.asyncio
async def test_consent_copy_does_not_carry_request_key():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        with on():
            service.apply_choice_request(ws, request())
            service.update_consent(ws, authorized_at=datetime(2026, 11, 3, tzinfo=timezone.utc))
        db.commit()
        assert [r.request_key for r in rows(db, ws)] == [None, "choice_request:7", None]


@pytest.mark.asyncio
async def test_no_decision_is_refused():
    async with confirmed_student() as (_, student, db, _j):
        assert RouteDecisionService(db).apply_choice_request(student.workspace_id, request()) == \
            ("refused", "no_decision")


@pytest.mark.asyncio
async def test_unsupported_route_is_refused():
    async with confirmed_student() as (_, student, db, _j):
        with_routes(student, db)
        service = RouteDecisionService(db)
        service.choose(student.workspace_id, "electrical_engineering")  # no details: not os_supported
        db.commit()
        assert service.apply_choice_request(student.workspace_id, request()) == ("refused", "not_supported")


@pytest.mark.asyncio
async def test_intake_only_request_keeps_places():
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        service = await three_versions(student, db)
        req = {**request(), "programmes": None, "target_intake": {"term": "spring", "year": 2028}}
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            assert service.apply_choice_request(ws, req) == ("written", 2)
        db.commit()
        new = rows(db, ws)[-1]
        assert new.intake == {"term": "spring", "year": 2028}
        assert [p["programme_ref"] for p in new.places] == ["uni-a:cs", "uni-b:cs"]


@pytest.mark.asyncio
async def test_no_journey_possibility_or_checkin_change():
    from app.models import StudentJourney
    async with confirmed_student() as (_, student, db, journey_id):
        ws = student.workspace_id
        service = await three_versions(student, db)
        db.expire_all()
        j = db.get(StudentJourney, journey_id)
        before = (j.current_stage, list(j.decisions or []), j.active_goal)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.apply_choice_request(ws, request())
        db.commit()
        db.expire_all()
        j = db.get(StudentJourney, journey_id)
        assert (j.current_stage, list(j.decisions or []), j.active_goal) == before
