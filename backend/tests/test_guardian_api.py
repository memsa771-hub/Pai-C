"""P1-T3 Task 4: the public guardian link routes (R-10, R-79): no auth, no student data beyond the first name,
no email, no caching, no token in logs, GET has no side effect."""

import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import GuardianConsent, RouteDecision
from app.pai_c.connect import guardian
from app.security import rate_limit
from app.services import auth_emails
from tests.test_handoff_delivery import flag, os_stub  # noqa: F401
from tests.test_roadmap_api import TOKEN, data, pre_eng
from tests.test_roadmap_choice_api import EMAIL, FIELD, ROUTES, LIST, choose_with, post, rows, vault

pytestmark = [pytest.mark.req("R-10"), pytest.mark.req("R-79")]


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    rate_limit.reset()
    sent = []
    monkeypatch.setattr(auth_emails, "send_email",
                        lambda to, subject, html, text_body=None: sent.append({"to": to, "text": text_body}) or True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
         patch("app.pai_os_bridge.programmes_for", return_value=LIST), \
         patch("app.pai_os_bridge.route_supported", return_value=True):
        yield sent
    rate_limit.reset()


def token_of(mail):
    link = next(part for part in mail["text"].split() if "/guardian/" in part)
    return link.rsplit("/", 1)[1]


def minor(ctx, stubs):
    client, student, params = ctx
    vault(ctx, dob="2012-05-05")
    data(choose_with(client, params, guardian_email=EMAIL))
    return token_of(stubs[0])


def public_ok(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "no-store" in response.headers["cache-control"]
    assert EMAIL not in response.text and "token_hash" not in response.text
    return response.json()["data"]


def test_get_shows_the_page_without_changing_anything(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        before = [(c.outcome, c.used_at) for c in rows(student, GuardianConsent)]
        for _ in range(3):  # a mail scanner opening the link
            page = public_ok(client.get(f"/v1/guardian/{token}"))
        assert page["state"] == "ok" and page["student_first_name"] and page["text"]["title"]
        assert [(c.outcome, c.used_at) for c in rows(student, GuardianConsent)] == before
        assert len(rows(student)) == 1  # no new version


def test_post_agrees_once_and_get_never_does(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        assert client.get(f"/v1/guardian/{token}/agree").status_code == 405  # POST only
        out = public_ok(client.post(f"/v1/guardian/{token}/agree"))
        assert out == {"state": "agreed", "confirmation_sent": True}
        latest = rows(student)[-1]
        assert latest.decision_version == 2 and latest.guardian_authorized_at is not None
        assert len(stubs) == 2 and stubs[1]["to"] == EMAIL  # the confirmation with the withdraw link
        assert public_ok(client.post(f"/v1/guardian/{token}/agree")) == {"state": "used"}
        assert public_ok(client.get(f"/v1/guardian/{token}"))["state"] == "used"
        assert os_stub["submitted"][-1]["guardian_authorized_at"]  # delivered at once, not at the next sweep


def test_a_guardian_withdraw_is_delivered_at_once(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        public_ok(client.post(f"/v1/guardian/{token}/agree"))
        public_ok(client.post(f"/v1/guardian/{token_of(stubs[1])}/withdraw"))
        assert os_stub["submitted"][-1]["decision_version"] == 3
        assert os_stub["submitted"][-1]["guardian_authorized_at"] is None


def test_the_guardian_can_withdraw_with_the_second_link(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        public_ok(client.post(f"/v1/guardian/{token}/agree"))
        withdraw = token_of(stubs[1])
        page = public_ok(client.get(f"/v1/guardian/{withdraw}/withdraw"))
        assert page["state"] == "ok"
        assert client.get(f"/v1/guardian/{withdraw}/withdraw").status_code == 200  # still no change
        assert rows(student)[-1].guardian_authorized_at is not None
        assert public_ok(client.post(f"/v1/guardian/{withdraw}/withdraw")) == {"state": "withdrawn"}
        assert rows(student)[-1].guardian_authorized_at is None


def test_unknown_and_expired_links(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        assert public_ok(client.get("/v1/guardian/not-a-real-token"))["state"] == "expired"
        assert public_ok(client.post("/v1/guardian/not-a-real-token/agree")) == {"state": "expired"}
        later = guardian.now() + timedelta(hours=73)
        with patch.object(guardian, "now", lambda: later):
            assert public_ok(client.get(f"/v1/guardian/{token}"))["state"] == "expired"
            assert public_ok(client.post(f"/v1/guardian/{token}/agree")) == {"state": "expired"}
        assert rows(student)[-1].guardian_authorized_at is None


def test_a_newer_version_makes_the_link_stale(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        data(post(client, params, "consent/withdraw"))  # a newer version
        assert public_ok(client.post(f"/v1/guardian/{token}/agree")) == {"state": "stale"}
        assert rows(student)[-1].guardian_authorized_at is None


def test_agree_needs_the_students_own_consent(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        with student.factory() as db:  # the newest version has no own consent
            row = db.scalar(select(RouteDecision))
            row.authorized_at = None
            db.commit()
        assert public_ok(client.post(f"/v1/guardian/{token}/agree")) == {"state": "stale"}
        assert rows(student)[-1].guardian_authorized_at is None


def test_the_ip_is_rate_limited(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        statuses = [client.get(f"/v1/guardian/{token}").status_code for _ in range(32)]
        assert statuses[:30] == [200] * 30 and statuses[-1] == 429
        limited = client.post(f"/v1/guardian/{token}/agree")
        assert limited.status_code == 429 and limited.headers["referrer-policy"] == "no-referrer"
        assert "no-store" in limited.headers["cache-control"]


def test_public_routes_need_no_auth_and_the_text_gate_blocks_agree(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        assert "authorization" not in client.headers and "x-workspace-token" not in client.headers
        with patch("app.pai_c.connect.consent.texts", return_value={"approved": False, "version": "9"}):
            assert client.post(f"/v1/guardian/{token}/agree").status_code == 409
        assert rows(student)[-1].guardian_authorized_at is None


def test_the_token_is_not_written_to_the_access_log(os_stub, stubs, caplog):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        with caplog.at_level(logging.INFO):
            client.post(f"/v1/guardian/{token}/agree")
            client.get("/v1/guardian/not-a-real-token")
        text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))  # the test client logs its own URL
        assert "/v1/guardian/{token}/agree" in text
        assert token not in text and "not-a-real-token" not in text and EMAIL not in text


def test_withdraw_is_never_blocked_by_the_text_gate(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        public_ok(client.post(f"/v1/guardian/{token}/agree"))
        withdraw = token_of(stubs[1])
        from app.pai_c.connect import consent
        unapproved = {**consent.texts(), "approved": False}
        with patch("app.pai_c.connect.consent.texts", return_value=unapproved):
            assert public_ok(client.get(f"/v1/guardian/{withdraw}/withdraw"))["state"] == "ok"
            assert public_ok(client.post(f"/v1/guardian/{withdraw}/withdraw")) == {"state": "withdrawn"}
        assert rows(student)[-1].guardian_authorized_at is None


def test_with_the_flag_off_the_public_routes_answer_stale_and_write_nothing(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        before = ([(c.outcome, c.used_at) for c in rows(student, GuardianConsent)], len(rows(student)), len(stubs))
        with flag(False):
            assert public_ok(client.get(f"/v1/guardian/{token}"))["state"] == "stale"
            assert public_ok(client.post(f"/v1/guardian/{token}/agree")) == {"state": "stale"}
            assert public_ok(client.get(f"/v1/guardian/{token}/withdraw"))["state"] == "stale"
            assert public_ok(client.post(f"/v1/guardian/{token}/withdraw")) == {"state": "stale"}
        assert ([(c.outcome, c.used_at) for c in rows(student, GuardianConsent)], len(rows(student)),
                len(stubs)) == before
        assert public_ok(client.post(f"/v1/guardian/{token}/agree")) == {"state": "agreed", "confirmation_sent": True}  # on again: link still good


def test_one_get_answers_for_the_kind_of_token_it_is_given(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        agree = minor((client, student, params), stubs)
        assert public_ok(client.get(f"/v1/guardian/{agree}"))["purpose"] == "agree"
        public_ok(client.post(f"/v1/guardian/{agree}/agree"))
        withdraw = token_of(stubs[1])
        page = public_ok(client.get(f"/v1/guardian/{withdraw}"))  # the same path the mail links to
        assert page["state"] == "ok" and page["purpose"] == "withdraw"
        assert page["text"]["title"].startswith("Withdraw your agreement") and "withdraw_button" in page["text"]
        assert "agree_button" not in page["text"] and page["student_first_name"] in page["text"]["title"]
        assert public_ok(client.get(f"/v1/guardian/{withdraw}/withdraw"))["text"] == page["text"]
        assert public_ok(client.get("/v1/guardian/not-a-token"))["state"] == "expired"


def test_a_stale_withdraw_link_says_stale_with_its_kind(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        public_ok(client.post(f"/v1/guardian/{token}/agree"))
        withdraw = token_of(stubs[1])
        with student.factory() as db:  # no live guardian agreement now (a later version without it)
            live = db.scalar(select(RouteDecision).where(RouteDecision.withdrawn_at.is_(None)))
            live.guardian_authorized_at = None
            db.commit()
        page = public_ok(client.get(f"/v1/guardian/{withdraw}"))
        assert (page["state"], page["purpose"]) == ("stale", "withdraw")


def test_a_withdraw_never_meets_the_rate_limit_but_agree_and_unknown_links_do(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        public_ok(client.post(f"/v1/guardian/{token}/agree"))
        withdraw = token_of(stubs[1])
        with patch("app.pai_c.connect.guardian.rate_limit.allow", return_value=False):
            assert public_ok(client.get(f"/v1/guardian/{withdraw}"))["state"] == "ok"
            assert public_ok(client.get(f"/v1/guardian/{withdraw}/withdraw"))["state"] == "ok"
            assert client.get("/v1/guardian/not-a-token").status_code == 429
            assert client.get(f"/v1/guardian/{token}").status_code == 429
            assert public_ok(client.post(f"/v1/guardian/{withdraw}/withdraw")) == {"state": "withdrawn"}


def test_a_page_load_counts_once_for_an_agree_link(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        with patch("app.pai_c.connect.guardian.rate_limit.allow", return_value=True) as allow:
            public_ok(client.get(f"/v1/guardian/{token}"))
        assert allow.call_count == 1


def test_the_answer_says_if_the_confirmation_mail_went_out(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        token = minor((client, student, params), stubs)
        with patch.object(auth_emails, "send_email", side_effect=RuntimeError(f"smtp down for {EMAIL}")):
            out = public_ok(client.post(f"/v1/guardian/{token}/agree"))
        assert out == {"state": "agreed", "confirmation_sent": False}  # the agreement stands
        assert rows(student)[-1].guardian_authorized_at is not None
        assert os_stub["submitted"][-1]["guardian_authorized_at"]
