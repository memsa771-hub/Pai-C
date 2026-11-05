"""The guardian one-time email link (R-10): hashed token, 72 h, single use, bound to a version, rate limited,
audited, and the address masked in every log line."""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import GuardianConsent, OsOutbox
from app.pai_c.connect import guardian
from app.pai_c.connect.choice import ChoiceDetails
from app.pai_c.roadmap.decisions import RouteDecisionService
from app.security import rate_limit
from app.services import auth_emails, email as email_service
from tests.test_route_journey import confirmed_student, with_routes

pytestmark = pytest.mark.req("R-10")

EMAIL = "parent.person@example.org"
MASKED = "p***@example.org"
DETAILS = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                        places=(("uni-a:cs", 1),), intake=("autumn", 2027), path_ref="path-1",
                        authorized_at=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc), guardian_required=True)
START = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(auth_emails, "send_email",
                        lambda to, subject, html, text_body=None: sent.append(
                            {"to": to, "subject": subject, "html": html, "text": text_body}) or True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    return sent


def same(left, right):
    """Datetimes compared as the same instant (SQLite hands them back without a zone)."""
    strip = lambda d: d if d is None else d.replace(tzinfo=None)  # noqa: E731
    return strip(left) == strip(right)


def clock(moment):
    return patch.object(guardian, "now", lambda: moment)


def token_of(mail):
    text = mail["text"]
    link = next(part for part in text.split() if "/guardian/" in part)
    return link.rsplit("/", 1)[1]


def consents(db, ws):
    db.expire_all()
    return list(db.scalars(select(GuardianConsent).where(GuardianConsent.workspace_id == ws)
                           .order_by(GuardianConsent.created_at, GuardianConsent.purpose)))


async def chosen(student, db):
    with_routes(student, db)
    service = RouteDecisionService(db)
    with patch("app.pai_os_bridge.route_supported", return_value=True):
        service.choose(student.workspace_id, "electrical_engineering", details=DETAILS)
    db.commit()
    return service, service.newest(student.workspace_id)


@pytest.mark.asyncio
async def test_request_stores_only_the_hash_and_sends_the_link_once(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START):
            row = guardian.request(db, student.workspace_id, decision, EMAIL)
        db.commit()
        assert len(mails) == 1 and mails[0]["to"] == EMAIL
        token = token_of(mails[0])
        assert len(token) >= 43 and mails[0]["text"].count("https://app.example.test/guardian/" + token) == 1
        assert token in mails[0]["html"]
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(row.__dict__)
        dump = db.execute(select(GuardianConsent.token_hash, GuardianConsent.email)).all()
        assert all(token not in str(cell) for line in dump for cell in line)
        assert row.outcome == "sent" and row.used_at is None and row.decision_version == decision.decision_version
        assert row.decision_id == decision.id and row.text_version == "1" and row.purpose == "agree"
        assert same(row.expires_at, START + timedelta(hours=72))
        assert "Placement AI" in mails[0]["subject"] or "agreement" in mails[0]["subject"]


@pytest.mark.asyncio
async def test_open_shows_the_text_and_the_first_name(mails):
    async with confirmed_student() as (_, student, db, _journey):
        _, decision = await chosen(student, db)
        with clock(START):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            token = token_of(mails[0])
            state = guardian.open(db, token)
        assert state["state"] == "ok" and state["student_first_name"]
        assert state["student_first_name"] in state["text"]["title"]
        assert "{student" not in str(state["text"]) and "{hours" not in str(state["text"])
        assert guardian.open(db, "no-such-token")["state"] == "expired"


@pytest.mark.asyncio
async def test_agree_writes_a_version_and_sends_the_withdraw_link(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            token = token_of(mails[0])
        with clock(START + timedelta(hours=71)), patch("app.pai_os_bridge.route_supported", return_value=True):
            assert guardian.agree(db, token) == "agreed"
        db.commit()
        newest = service.newest(student.workspace_id)
        assert newest.decision_version == decision.decision_version + 1
        assert same(newest.guardian_authorized_at, START + timedelta(hours=71))
        assert same(newest.authorized_at, DETAILS.authorized_at)
        found = consents(db, student.workspace_id)
        agree = next(c for c in found if c.purpose == "agree")
        assert agree.outcome == "agreed" and same(agree.used_at, START + timedelta(hours=71))
        # the confirmation email carries a new token for withdrawing
        assert len(mails) == 2 and mails[1]["to"] == EMAIL
        withdraw_token = token_of(mails[1])
        assert withdraw_token != token
        withdraw = next(c for c in found if c.purpose == "withdraw")
        assert withdraw.token_hash == hashlib.sha256(withdraw_token.encode()).hexdigest()
        assert withdraw.decision_version == newest.decision_version and withdraw.outcome == "sent"
        # the OS never gets the address
        payloads = [str(i.payload) for i in db.scalars(select(OsOutbox))]
        assert all("@" not in p for p in payloads)


@pytest.mark.asyncio
async def test_token_is_single_use(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            token = token_of(mails[0])
            assert guardian.agree(db, token) == "agreed"
            versions = service.newest(student.workspace_id).decision_version
            assert guardian.agree(db, token) == "used"
            assert guardian.open(db, token)["state"] == "used"
        assert service.newest(student.workspace_id).decision_version == versions
        assert len(mails) == 2  # no second confirmation


@pytest.mark.asyncio
async def test_token_expires_after_72_hours(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            token = token_of(mails[0])
        late = START + timedelta(hours=72, seconds=1)
        with clock(late):
            assert guardian.open(db, token)["state"] == "expired"
            assert guardian.agree(db, token) == "expired"
        db.commit()
        row = consents(db, student.workspace_id)[0]
        assert row.outcome == "expired" and row.used_at is None
        assert service.newest(student.workspace_id).decision_version == decision.decision_version
        with clock(START + timedelta(hours=1)):
            assert guardian.agree(db, token) == "expired"  # stays expired


@pytest.mark.asyncio
async def test_stale_when_a_newer_version_exists(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            token = token_of(mails[0])
        with patch("app.pai_os_bridge.route_supported", return_value=True):
            service.update_consent(student.workspace_id, authorized_at=None)
        db.commit()
        with clock(START):
            assert guardian.open(db, token)["state"] == "stale"
            assert guardian.agree(db, token) == "stale"
        db.commit()
        newest = service.newest(student.workspace_id)
        assert newest.decision_version == decision.decision_version + 1 and newest.guardian_authorized_at is None
        row = consents(db, student.workspace_id)[0]
        assert row.outcome == "stale" and len(mails) == 1


@pytest.mark.asyncio
async def test_stale_when_the_choice_was_withdrawn(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            token = token_of(mails[0])
        service.withdraw(student.workspace_id)
        db.commit()
        with clock(START):
            assert guardian.agree(db, token) == "stale"


@pytest.mark.asyncio
async def test_withdraw_link_pauses_by_clearing_the_guardian_consent(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START), patch("app.pai_os_bridge.route_supported", return_value=True):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            assert guardian.agree(db, token_of(mails[0])) == "agreed"
            withdraw_token = token_of(mails[1])
        with clock(START + timedelta(days=30)), patch("app.pai_os_bridge.route_supported", return_value=True):
            assert guardian.withdraw(db, withdraw_token) == "withdrawn"
            assert guardian.withdraw(db, withdraw_token) == "used"
        db.commit()
        newest = service.newest(student.workspace_id)
        assert newest.guardian_authorized_at is None and newest.status == "chosen"
        assert same(newest.authorized_at, DETAILS.authorized_at)
        assert newest.decision_version == decision.decision_version + 2
        outcomes = sorted(c.outcome for c in consents(db, student.workspace_id))
        assert outcomes == ["agreed", "withdrawn"]
        assert len(mails) == 3  # the withdrawal is confirmed by email


@pytest.mark.asyncio
async def test_unknown_withdraw_token_and_agree_token_do_not_mix(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with clock(START), patch("app.pai_os_bridge.route_supported", return_value=True):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            agree_token = token_of(mails[0])
            assert guardian.withdraw(db, agree_token) == "expired"  # an agree link cannot withdraw
            assert guardian.withdraw(db, "nope") == "expired"
            assert guardian.agree(db, agree_token) == "agreed"
            assert guardian.agree(db, token_of(mails[1])) == "expired"  # a withdraw link cannot agree


@pytest.mark.asyncio
async def test_request_is_rate_limited_per_user_and_email(mails):
    async with confirmed_student() as (_, student, db, _journey):
        _, decision = await chosen(student, db)
        with clock(START):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            with pytest.raises(guardian.GuardianRateLimited):
                guardian.request(db, student.workspace_id, decision, EMAIL)
        assert len(mails) == 1
        rate_limit.reset()
        with clock(START):
            for index in range(5):
                guardian.request(db, student.workspace_id, decision, f"other{index}@example.org")
            with pytest.raises(guardian.GuardianRateLimited):
                guardian.request(db, student.workspace_id, decision, "yet.another@example.org")


@pytest.mark.asyncio
async def test_open_is_rate_limited_per_ip(mails):
    async with confirmed_student() as (_, student, db, _journey):
        for _ in range(30):
            guardian.open(db, "x", ip="203.0.113.9")
        with pytest.raises(guardian.GuardianRateLimited):
            guardian.open(db, "x", ip="203.0.113.9")
        guardian.open(db, "x", ip="203.0.113.10")


def test_limits_are_listed():
    assert {"user", "email"} == {r["per"] for r in rate_limit.LIMITS["guardian_request"]}
    assert {"ip"} == {r["per"] for r in rate_limit.LIMITS["guardian_open"]}


@pytest.mark.asyncio
async def test_unapproved_text_blocks_the_request(mails, monkeypatch, tmp_path):
    from app.pai_c.connect import consent
    async with confirmed_student() as (_, student, db, _journey):
        _, decision = await chosen(student, db)
        path = tmp_path / "texts.yaml"
        path.write_text('version: "2"\napproved: false\napproved_by: ""\n')
        monkeypatch.setattr(consent, "TEXTS_PATH", path)
        monkeypatch.setattr(config, "CONNECT_CONSENT_DRAFT", False)
        with pytest.raises(consent.ConsentTextNotApproved):
            guardian.request(db, student.workspace_id, decision, EMAIL)
        assert mails == [] and consents(db, student.workspace_id) == []


@pytest.mark.asyncio
async def test_logs_show_only_the_masked_address(mails, caplog):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        with caplog.at_level(logging.DEBUG), clock(START), patch("app.pai_os_bridge.route_supported", return_value=True):
            guardian.request(db, student.workspace_id, decision, EMAIL)
            token = token_of(mails[0])
            guardian.agree(db, token)
        assert EMAIL not in caplog.text and token not in caplog.text
        assert MASKED in caplog.text


def test_email_service_logs_the_masked_address(caplog, monkeypatch):
    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    with caplog.at_level(logging.DEBUG):
        assert email_service.send_email(EMAIL, "s", "<p>x</p>") is False
    assert EMAIL not in caplog.text and MASKED in caplog.text


def test_email_service_failure_logs_are_masked(caplog, monkeypatch):
    monkeypatch.setattr(config, "RESEND_API_KEY", "key")

    def boom(*a, **k):
        raise RuntimeError("network down for " + EMAIL)

    monkeypatch.setattr(email_service.httpx, "post", boom)
    with caplog.at_level(logging.DEBUG):
        assert email_service.send_email(EMAIL, "s", "<p>x</p>") is False
    assert EMAIL not in caplog.text and MASKED in caplog.text


def test_mask_email():
    from app.services.email import mask_email
    assert mask_email("parent.person@example.org") == "p***@example.org"
    assert mask_email("a@b.co") == "a***@b.co"
    assert mask_email("no-at-sign") == "***"
    assert mask_email("") == "***"


@pytest.mark.asyncio
async def test_withdraw_link_stale_is_not_recorded_and_can_work_later(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        ws = student.workspace_id
        with clock(START), patch("app.pai_os_bridge.route_supported", return_value=True):
            guardian.request(db, ws, decision, EMAIL)
            guardian.agree(db, token_of(mails[0]))
            withdraw_token = token_of(mails[1])
            granted = service.newest(ws).guardian_authorized_at
            service.update_consent(ws, guardian_authorized_at=None)  # no guardian consent for the moment
            assert guardian.open(db, withdraw_token, purpose="withdraw")["state"] == "stale"
            assert guardian.withdraw(db, withdraw_token) == "stale"
            db.commit()
            withdraw_row = next(c for c in consents(db, ws) if c.purpose == "withdraw")
            assert withdraw_row.outcome == "sent"  # stale is never persisted for a withdraw link
            service.update_consent(ws, guardian_authorized_at=granted)  # the consent is live again
            assert guardian.open(db, withdraw_token, purpose="withdraw")["state"] == "ok"
            assert guardian.withdraw(db, withdraw_token) == "withdrawn"
        assert service.newest(ws).guardian_authorized_at is None


@pytest.mark.asyncio
async def test_withdraw_link_has_no_fixed_lifetime_and_ends_when_its_consent_is_replaced(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        ws = student.workspace_id
        with clock(START), patch("app.pai_os_bridge.route_supported", return_value=True):
            guardian.request(db, ws, decision, EMAIL)
            guardian.agree(db, token_of(mails[0]))
            first_withdraw = token_of(mails[1])
            row = next(c for c in consents(db, ws) if c.purpose == "withdraw")
            assert row.expires_at is None
        years_later = START + timedelta(days=800)
        with clock(years_later), patch("app.pai_os_bridge.route_supported", return_value=True):
            assert guardian.open(db, first_withdraw, purpose="withdraw")["state"] == "ok"
            # a newer guardian consent replaces the one the first link guards
            service.update_consent(ws, guardian_authorized_at=None)
            newest = service.newest(ws)
            guardian.request(db, ws, newest, EMAIL.replace("parent", "other"))
            assert guardian.agree(db, token_of(mails[2])) == "agreed"
            second_withdraw = token_of(mails[3])
            assert guardian.withdraw(db, first_withdraw) == "expired"
            db.commit()
            assert guardian.withdraw(db, first_withdraw) == "expired"
            assert next(c for c in consents(db, ws) if c.token_hash == hashlib.sha256(
                first_withdraw.encode()).hexdigest()).outcome == "expired"
            assert guardian.withdraw(db, second_withdraw) == "withdrawn"


@pytest.mark.asyncio
async def test_request_checks_the_decision(mails):
    async with confirmed_student() as (_, student, db, _journey):
        service, decision = await chosen(student, db)
        ws = student.workspace_id
        with clock(START), patch("app.pai_os_bridge.route_supported", return_value=True):
            with pytest.raises(guardian.GuardianRequestError):
                guardian.request(db, "another-workspace", decision, EMAIL)  # not this student's
            old = decision
            service.update_consent(ws, authorized_at=None)
            with pytest.raises(guardian.GuardianRequestError):
                guardian.request(db, ws, old, EMAIL)  # no longer the newest
            service.withdraw(ws)
            with pytest.raises(guardian.GuardianRequestError):
                guardian.request(db, ws, service.newest(ws), EMAIL)  # a withdrawal
        assert mails == [] and consents(db, ws) == []


@pytest.mark.asyncio
async def test_request_needs_guardian_required(mails):
    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        adult = ChoiceDetails(origin_country="PK", destination_country="GB", level="bachelor",
                              places=(("uni-a:cs", 1),), intake=("autumn", 2027))
        service = RouteDecisionService(db)
        service.choose(student.workspace_id, "electrical_engineering", details=adult)
        with pytest.raises(guardian.GuardianRequestError):
            guardian.request(db, student.workspace_id, service.newest(student.workspace_id), EMAIL)


@pytest.mark.asyncio
async def test_email_is_stripped_and_lower_cased(mails):
    async with confirmed_student() as (_, student, db, _journey):
        _, decision = await chosen(student, db)
        with clock(START):
            row = guardian.request(db, student.workspace_id, decision, "  Parent.Person@Example.ORG ")
        assert row.email == EMAIL and mails[0]["to"] == EMAIL
