"""Consent texts and gate, the age rule, update_consent and D-k 2 (R-10)."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import OsOutbox, RouteDecision, StudentJourney
from app.pai_c.connect import consent, outbox
from app.pai_c.connect.age import under_18
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap.decisions import RouteDecisionError, RouteDecisionService
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = pytest.mark.req("R-10")

DETAILS = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                        places=(("uni-a:cs", 1), ("uni-b:cs", 2)), intake=("autumn", 2027), path_ref="path-1",
                        authorized_at=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc), guardian_required=True)
NOW = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)


def same(left, right):
    """Datetimes compared as the same instant (SQLite hands them back without a zone)."""
    strip = lambda d: d if d is None else d.replace(tzinfo=None)  # noqa: E731
    return strip(left) == strip(right)


def on():
    return patch("app.pai_c.connect.outbox.part_on", return_value=True)


def rows(db, ws):
    db.expire_all()
    return list(db.scalars(select(RouteDecision).where(RouteDecision.workspace_id == ws)
                           .order_by(RouteDecision.decision_version)))


def items(db, ws):
    db.expire_all()
    return list(db.scalars(select(OsOutbox).where(OsOutbox.workspace_id == ws).order_by(OsOutbox.key)))


# ---- age ----

@pytest.mark.parametrize("dob, expected", [
    ("2009", True), ("2007-11-04", False), ("2008-11-06", True), ("2008-11-05", False), (None, None),
    ("2007", False), ("2008", True), ("2008-10", False), ("2008-11", True), ("2026-11-06", True),
    ("2008-02-29", False), ("", None), ("not a date", None)])
def test_under_18(dob, expected):
    assert under_18(dob, date(2026, 11, 5)) is expected


def test_under_18_counts_on_the_given_day():
    assert under_18("2008-11-06", date(2026, 11, 5)) is True
    assert under_18("2008-11-06", date(2026, 11, 6)) is False


# ---- texts and the gate ----

def test_texts_are_approved_and_versioned():
    texts = consent.texts()
    assert consent.current_version() == "1" and texts["approved"] is True
    assert texts["approved_by"] == "owner, chat 2026-11-05"
    assert {"student", "guardian_email", "guardian_page", "guardian_withdraw_page", "guardian_confirmation"} <= set(texts)
    consent.ensure_usable()
    blob = str(texts).lower()
    for word in ("pakistan", "germany", "ireland", "united", "gdpr", "law ", "legal"):
        assert word not in blob


def test_texts_cover_what_the_brief_asks():
    texts = consent.texts()
    student = " ".join(texts["student"]["body"]).lower()
    assert "route" in student and "places" in student and "intake" in student
    assert "withdraw" in student and "pauses" in student
    guardian = " ".join(texts["guardian_email"]["paragraphs"]).lower()
    assert "{student_first_name}" in guardian and "{hours}" in guardian and "link" in guardian
    assert "withdraw" in (texts["guardian_email"]["footer"] + " ".join(texts["guardian_confirmation"]["paragraphs"])).lower()


def test_unapproved_text_is_refused_unless_draft(tmp_path, monkeypatch):
    path = tmp_path / "texts.yaml"
    path.write_text('version: "9"\napproved: false\napproved_by: ""\nstudent: {title: t, body: []}\n')
    monkeypatch.setattr(consent, "TEXTS_PATH", path)
    monkeypatch.setattr(config, "CONNECT_CONSENT_DRAFT", False)
    assert consent.current_version() == "9"
    with pytest.raises(consent.ConsentTextNotApproved):
        consent.ensure_usable()
    monkeypatch.setattr(config, "CONNECT_CONSENT_DRAFT", True)
    consent.ensure_usable()


def test_draft_flag_defaults_off():
    assert config.CONNECT_CONSENT_DRAFT is False


# ---- update_consent ----

@pytest.mark.asyncio
async def test_update_consent_copies_everything_into_a_new_version():
    async with confirmed_student() as (_, student, db, journey_id):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
            journey_before = db.get(StudentJourney, journey_id)
            stage, goal, decisions = journey_before.current_stage, dict(journey_before.active_goal), \
                list(journey_before.decisions)
            result = service.update_consent(ws, guardian_authorized_at=NOW)
            db.commit()
        first, second = rows(db, ws)
        assert (first.decision_version, second.decision_version) == (1, 2)
        assert first.withdrawn_at is not None and second.withdrawn_at is None and second.status == "chosen"
        for name in ("field_key", "possibility_id", "title", "verdict", "route", "steps", "steps_done",
                     "origin_country", "destination_country", "level", "path_ref", "places", "intake",
                     "os_supported", "authorized_at", "guardian_required", "chosen_at"):
            if name in ("authorized_at", "chosen_at"):
                assert same(getattr(second, name), getattr(first, name)), name
            else:
                assert getattr(second, name) == getattr(first, name), name
        assert first.guardian_authorized_at is None and same(second.guardian_authorized_at, NOW)
        assert second.places == [{"programme_ref": "uni-a:cs", "rank": 1}, {"programme_ref": "uni-b:cs", "rank": 2}]
        assert result["field_key"] == "electrical_engineering" and result["id"] == second.id
        # the journey and the possibility are not touched
        journey = db.get(StudentJourney, journey_id)
        assert journey.current_stage == stage and journey.decisions == decisions
        assert journey.active_goal["field_key"] == goal["field_key"]
        assert service.active(ws).id == second.id


@pytest.mark.asyncio
async def test_update_consent_queues_an_outbox_row_and_no_checkin():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True), \
                patch("app.pai_c.checkins.schedule") as schedule_mock:
            service.choose(ws, "electrical_engineering", details=DETAILS)
            assert schedule_mock.call_count == 1
            service.update_consent(ws, guardian_authorized_at=NOW)
            service.update_consent(ws, authorized_at=None)
            assert schedule_mock.call_count == 1  # consent changes never reschedule check-ins
            db.commit()
        found = items(db, ws)
        assert [i.key for i in found] == [f"decision:{ws}:{v}" for v in (1, 2, 3)]
        assert [i.status for i in found] == ["pending"] * 3
        assert found[1].payload["guardian_authorized_at"].startswith("2026-11-06")
        assert found[2].payload["authorized_at"] is None and found[2].payload["status"] == "chosen"
        assert "@" not in str(found[1].payload)  # no e-mail address ever reaches the OS
        from app.os.contracts.decision_record_v2 import DecisionRecordV2
        for item in found:
            DecisionRecordV2.model_validate(item.payload)


@pytest.mark.asyncio
async def test_withdrawing_student_consent_clears_authorized_at_and_keeps_status():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            service.update_consent(ws, authorized_at=None)
            db.commit()
        newest = service.newest(ws)
        assert newest.authorized_at is None and newest.status == "chosen" and newest.withdrawn_at is None
        assert newest.guardian_authorized_at is None and newest.guardian_required is True
        assert len(newest.places) == 2 and newest.intake == {"term": "autumn", "year": 2027}
        (_, second) = items(db, ws)
        assert second.payload["authorized_at"] is None and second.payload["status"] == "chosen"
        assert second.payload["programmes"] and second.payload["target_intake"] == {"term": "autumn", "year": 2027}


@pytest.mark.asyncio
async def test_no_change_is_a_no_op():
    """A change to nothing writes no version and no outbox row (it used to write a copy)."""
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            service.update_consent(ws, guardian_authorized_at=NOW)
            db.commit()
            before = (len(rows(db, ws)), len(items(db, ws)))
            assert before == (2, 2)
            for call in ({}, {"guardian_authorized_at": NOW}, {"authorized_at": DETAILS.authorized_at},
                         {"authorized_at": DETAILS.authorized_at.replace(tzinfo=None), "guardian_authorized_at": ...}):
                result = service.update_consent(ws, **call)
                assert result["field_key"] == "electrical_engineering"
            db.commit()
        assert (len(rows(db, ws)), len(items(db, ws))) == before
        newest = service.newest(ws)
        assert same(newest.guardian_authorized_at, NOW) and same(newest.authorized_at, DETAILS.authorized_at)
        assert newest.decision_version == 2 and newest.withdrawn_at is None


@pytest.mark.asyncio
async def test_a_real_change_after_a_no_op_still_makes_a_version():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        service.choose(ws, "electrical_engineering", details=DETAILS)
        service.update_consent(ws)
        service.update_consent(ws, guardian_authorized_at=NOW)
        assert service.newest(ws).decision_version == 2


@pytest.mark.asyncio
async def test_update_consent_needs_an_active_choice():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with pytest.raises(RouteDecisionError) as error:
            service.update_consent(ws, authorized_at=None)
        assert error.value.status_code == 404
        service.choose(ws, "electrical_engineering", details=DETAILS)
        service.withdraw(ws)
        with pytest.raises(RouteDecisionError):
            service.update_consent(ws, authorized_at=NOW)
        assert [r.decision_version for r in rows(db, ws)] == [1, 2]


@pytest.mark.asyncio
async def test_withdraw_after_a_consent_change_still_clears_the_journey_goal():
    async with confirmed_student() as (_, student, db, journey_id):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        service.choose(ws, "electrical_engineering", details=DETAILS)
        service.update_consent(ws, guardian_authorized_at=NOW)
        service.withdraw(ws)
        db.commit()
        db.expire_all()
        journey = db.get(StudentJourney, journey_id)
        assert journey.active_goal is None and journey.current_objective is None


# ---- D-k 2 ----

@pytest.mark.asyncio
async def test_a_pending_earlier_version_counts_like_a_delivered_one():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
        with on(), patch("app.pai_os_bridge.route_supported", return_value=False):
            service.choose(ws, "computer_engineering", details=DETAILS)
            db.commit()
        first, second = items(db, ws)
        assert first.status == "pending"
        assert second.status == "pending" and second.last_error is None
        assert second.payload["os_supported"] is False


@pytest.mark.asyncio
async def test_not_sent_earlier_version_does_not_count():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=False):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            service.choose(ws, "computer_engineering", details=DETAILS)
            db.commit()
        assert [(i.status, i.last_error) for i in items(db, ws)] == [("not_sent", "not_supported")] * 2


# ---- the 7-day check-in survives a consent change ----

async def _run_checkin(db, ws):
    from app.models import BackgroundJob
    from app.pai_c.checkins import checkin_job
    job = db.query(BackgroundJob).filter(BackgroundJob.job_type == "counselor.checkin",
                                         BackgroundJob.workspace_id == ws).one()
    from app.pai_c import checkins
    open_rules = {**checkins.policy(), "quiet_hours": 0, "minimum_spacing_hours": 0, "care_retry_hours": 0}
    with patch("app.pai_c.checkins.policy", return_value=open_rules), \
            patch("app.pai_c.posting.send_to_student", return_value="event-1") as post:
        return await checkin_job(job, db), post


@pytest.mark.asyncio
async def test_checkin_is_posted_after_a_consent_change():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        service.choose(ws, "electrical_engineering", details=DETAILS)
        service.update_consent(ws, guardian_authorized_at=NOW)
        service.update_consent(ws, authorized_at=None)
        db.commit()
        result, post = await _run_checkin(db, ws)
        assert result["status"] == "posted" and post.call_count == 1


@pytest.mark.asyncio
async def test_checkin_is_superseded_after_a_withdrawal():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        service.choose(ws, "electrical_engineering", details=DETAILS)
        service.update_consent(ws, guardian_authorized_at=NOW)
        service.withdraw(ws)
        db.commit()
        result, post = await _run_checkin(db, ws)
        assert result == {"status": "superseded"} and post.call_count == 0


@pytest.mark.asyncio
async def test_checkin_is_superseded_by_another_choice():
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        service = RouteDecisionService(db)
        service.choose(ws, "electrical_engineering", details=DETAILS)
        service.update_consent(ws, guardian_authorized_at=NOW)
        service.choose(ws, "computer_engineering", details=DETAILS)
        db.commit()
        from app.models import BackgroundJob
        from app.pai_c.checkins import checkin_job
        first = db.query(BackgroundJob).filter(BackgroundJob.job_type == "counselor.checkin").order_by(
            BackgroundJob.created_at).first()
        with patch("app.pai_c.posting.send_to_student", return_value="event-1"):
            assert await checkin_job(first, db) == {"status": "superseded"}
