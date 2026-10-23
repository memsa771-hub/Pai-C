"""End-to-end account flows against the Firebase Auth emulator (demo project).

Real ID tokens, real action codes, real Google sign-in through the emulator;
emails are captured instead of sent. Skipped when the emulator is not running:
    firebase emulators:start --only auth --project demo-pai
"""

import os
import re
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select

from app.config import config
from app.database import Base
from app.models import AuthDevice, Channel, ChannelMember, User
from scripts.counselor_eval_support import StudentSession
from tests.test_p0_entry_audit import client_for

EMULATOR = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
PROJECT = "demo-pai"
API = f"http://{EMULATOR}/identitytoolkit.googleapis.com/v1"


def _emulator_up() -> bool:
    try:
        return httpx.get(f"http://{EMULATOR}/", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _emulator_up(), reason="Firebase Auth emulator is not running")


@pytest.fixture(autouse=True)
def emulator(monkeypatch):
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", EMULATOR)
    monkeypatch.setattr(config, "FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    httpx.delete(f"http://{EMULATOR}/emulator/v1/projects/{PROJECT}/accounts")
    from app.routers import auth
    auth._per_ip.reset()
    auth._per_address.reset()
    yield


@pytest.fixture
def mail():
    sent = []
    with patch("app.services.auth_emails.send_email",
               side_effect=lambda to, subject, html, text_body=None: sent.append(
                   {"to": to, "subject": subject, "html": html, "text": text_body}) or True):
        yield sent


@pytest.fixture
def client():
    with StudentSession() as student:
        Base.metadata.create_all(student.engine, tables=[AuthDevice.__table__, Channel.__table__, ChannelMember.__table__])
        with client_for(student) as http:
            http.student = student
            yield http


def _post(path, body):
    response = httpx.post(f"{API}/{path}?key=fake-api-key", json=body)
    return response.json()


def sign_up(email, password="Better-pass1"):
    return _post("accounts:signUp", {"email": email, "password": password, "returnSecureToken": True})


def sign_in(email, password="Better-pass1"):
    return _post("accounts:signInWithPassword", {"email": email, "password": password, "returnSecureToken": True})


def google(email, sub):
    claims = '{"sub":"%s","email":"%s","email_verified":true,"name":"Google Student"}' % (sub, email)
    return _post("accounts:signInWithIdp", {"postBody": f"id_token={claims}&providerId=google.com",
                                            "requestUri": "http://localhost", "returnSecureToken": True})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def code_in(email: dict, mode: str) -> str:
    link = re.search(r"https://app\.example\.test/auth/action\?\S+", email["text"]).group(0)
    query = parse_qs(urlparse(link).query)
    assert query["mode"] == [mode]
    return query["oobCode"][0]


def test_google_sign_in_creates_the_account_and_opens_the_workspace(client, mail):
    token = google("g.student@example.test", "google-sub-1")["idToken"]
    session = client.post("/v1/auth/session", headers=bearer(token), json={"deviceId": "browser-one"})
    assert session.status_code == 200, session.text
    assert session.json()["data"]["user"]["displayName"] == "Google Student"
    assert "username" not in session.json()["data"]["user"]
    workspace = client.get("/v1/account/workspace", headers=bearer(token))
    assert workspace.status_code == 200 and workspace.json()["data"]["streamTicket"]
    assert mail == []  # the first device is not a "new" one


def test_email_sign_up_is_blocked_until_verified_then_works(client, mail):
    account = sign_up("new.student@example.test")
    token = account["idToken"]
    blocked = client.get("/v1/account/workspace", headers=bearer(token))
    assert blocked.status_code == 403 and blocked.json()["message"] == "AUTH_EMAIL_NOT_VERIFIED"
    assert client.post("/v1/auth/session", headers=bearer(token), json={"deviceId": "browser-one"}).status_code == 403

    sent = client.post("/v1/auth/send-verification", headers=bearer(token))
    assert sent.status_code == 200 and sent.json()["data"]["sent"]
    assert mail[-1]["to"] == "new.student@example.test" and "Verify" in mail[-1]["subject"]
    assert "<a href=\"https://app.example.test/auth/action?mode=verifyEmail&amp;oobCode=" in mail[-1]["html"]
    applied = _post("accounts:update", {"oobCode": code_in(mail[-1], "verifyEmail")})
    assert applied.get("emailVerified") is True

    fresh = sign_in("new.student@example.test")["idToken"]
    assert client.post("/v1/auth/session", headers=bearer(fresh), json={"deviceId": "browser-one"}).status_code == 200
    assert client.post("/v1/auth/send-verification", headers=bearer(fresh)).json()["data"]["alreadyVerified"]
    with client.student.factory() as db:
        user = db.scalar(select(User).where(User.email == "new.student@example.test"))
        assert user.firebase_uid == account["localId"]


def test_forgot_password_is_generic_and_the_reset_link_works(client, mail):
    sign_up("reset.me@example.test")
    unknown = client.post("/v1/auth/forgot-password", json={"email": "nobody@example.test"})
    known = client.post("/v1/auth/forgot-password", json={"email": "Reset.Me@example.test"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    assert [m["to"] for m in mail] == ["reset.me@example.test"]
    code = code_in(mail[0], "resetPassword")
    assert _post("accounts:resetPassword", {"oobCode": code, "newPassword": "Newer-pass2"}).get("email")
    assert sign_in("reset.me@example.test", "Newer-pass2").get("idToken")
    # A used (or expired) code is refused; the page then offers a new link.
    again = _post("accounts:resetPassword", {"oobCode": code, "newPassword": "Other-pass3"})
    assert again["error"]["message"].startswith(("INVALID_OOB_CODE", "EXPIRED_OOB_CODE"))


def test_new_device_alert_only_after_the_first_device(client, mail):
    token = google("devices@example.test", "google-sub-2")["idToken"]
    first = client.post("/v1/auth/session", headers=bearer(token), json={"deviceId": "laptop-browser"})
    same = client.post("/v1/auth/session", headers=bearer(token), json={"deviceId": "laptop-browser"})
    assert first.json()["data"]["newDevice"] and not same.json()["data"]["newDevice"]
    assert mail == []
    phone = client.post("/v1/auth/session", headers={**bearer(token), "User-Agent": "Mozilla/5.0 (iPhone) Safari/605.1"},
                        json={"deviceId": "phone-browser"})
    assert phone.json()["data"]["newDevice"]
    assert len(mail) == 1 and "New sign-in" in mail[0]["subject"] and "Safari on iPhone" in mail[0]["text"]


def test_account_email_endpoints_are_rate_limited(client, mail):
    token = sign_up("spam.me@example.test")["idToken"]
    codes = [client.post("/v1/auth/send-verification", headers=bearer(token)).status_code for _ in range(7)]
    assert codes[:config.AUTH_EMAILS_PER_ADDRESS_PER_HOUR] == [200] * config.AUTH_EMAILS_PER_ADDRESS_PER_HOUR
    assert codes[-1] == 429
    assert len(mail) == config.AUTH_EMAILS_PER_ADDRESS_PER_HOUR


def test_a_token_from_another_project_or_forged_is_refused(client):
    assert client.get("/v1/account/workspace", headers=bearer("a.b.c")).status_code == 401
