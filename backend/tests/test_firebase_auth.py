"""End-to-end account flows against the Firebase Auth emulator (demo project).

Real ID tokens, real action codes, real Google sign-in through the emulator;
emails are captured instead of sent. Skipped when the emulator is not running:
    firebase emulators:start --only auth --project demo-pai
"""

import os
import re
import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select

from app.config import config
from app.database import Base
from app.models import AuthDevice, Channel, ChannelMember, User
from app.security import rate_limit
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
    rate_limit.reset()
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


def test_verification_email_is_limited_to_one_a_minute(client, mail):
    token = sign_up("spam.me@example.test")["idToken"]
    codes = [client.post("/v1/auth/send-verification", headers=bearer(token)).status_code for _ in range(3)]
    assert codes == [200, 429, 429]
    assert len(mail) == 1


def test_a_token_from_another_project_or_forged_is_refused(client):
    assert client.get("/v1/account/workspace", headers=bearer("a.b.c")).status_code == 401


def _verified_student(client, mail, email):
    """A signed-up, verified email/password student with a workspace."""
    token = sign_up(email)["idToken"]
    client.post("/v1/auth/send-verification", headers=bearer(token))
    _post("accounts:update", {"oobCode": code_in(mail[-1], "verifyEmail")})
    mail.clear()
    rate_limit.reset()
    time.sleep(1.1)  # tokens carry whole seconds; keep this one apart from later revocations
    token = sign_in(email)["idToken"]
    session = client.post("/v1/auth/session", headers=bearer(token), json={"deviceId": "browser-one"})
    assert session.status_code == 200, session.text
    return token, session.json()["data"]["workspace"]["workspaceId"]


def test_a_password_reset_signs_the_account_out_everywhere(client, mail):
    old_token, _ = _verified_student(client, mail, "revoke.me@example.test")
    assert client.get("/v1/account/workspace", headers=bearer(old_token)).status_code == 200
    client.post("/v1/auth/forgot-password", json={"email": "revoke.me@example.test"})
    code = code_in(mail[-1], "resetPassword")

    weak = client.post("/v1/auth/reset-password", json={"oobCode": code, "newPassword": "123"})
    assert weak.status_code == 400 and weak.json()["message"] == "AUTH_WEAK_PASSWORD"
    done = client.post("/v1/auth/reset-password", json={"oobCode": code, "newPassword": "Newer-pass2"})
    assert done.status_code == 200, done.text
    # The token issued before the reset no longer opens anything, on any device.
    assert client.get("/v1/account/workspace", headers=bearer(old_token)).status_code == 401
    again = client.post("/v1/auth/reset-password", json={"oobCode": code, "newPassword": "Other-pass3"})
    assert again.status_code == 400 and again.json()["message"] == "AUTH_RESET_LINK_INVALID"

    time.sleep(1.1)
    assert "error" in sign_in("revoke.me@example.test", "Better-pass1")
    fresh = sign_in("revoke.me@example.test", "Newer-pass2")["idToken"]
    assert client.get("/v1/account/workspace", headers=bearer(fresh)).status_code == 200


def test_signing_out_is_local_and_needs_no_backend(client, mail):
    # Normal logout is the client's signOut on this device only: no endpoint
    # revokes anything, so another device's token keeps working.
    laptop, _ = _verified_student(client, mail, "two.devices@example.test")
    phone = sign_in("two.devices@example.test")["idToken"]
    assert not [r for r in client.app.routes if "logout" in getattr(r, "path", "") or "sign-out" in getattr(r, "path", "")]
    assert client.get("/v1/account/workspace", headers=bearer(laptop)).status_code == 200
    assert client.get("/v1/account/workspace", headers=bearer(phone)).status_code == 200


def test_account_deletion_needs_a_recent_sign_in(client, mail, monkeypatch):
    token, _ = _verified_student(client, mail, "stale.session@example.test")
    from app.routers import account
    monkeypatch.setattr(account, "RECENT_SIGN_IN_SECONDS", -1)
    refused = client.delete("/v1/account", headers=bearer(token))
    assert refused.status_code == 403 and refused.json()["message"] == "AUTH_RECENT_SIGN_IN_REQUIRED"
    assert client.get("/v1/account/workspace", headers=bearer(token)).status_code == 200
    assert mail == []


def test_account_deletion_erases_the_data_disables_firebase_and_emails(client, mail):
    from firebase_admin import auth as firebase_admin_auth
    from app.models import VaultFact, Workspace
    from app.security import firebase_auth

    Base.metadata.create_all(client.student.engine)  # every table a deleted workspace cascades into
    token, workspace_id = _verified_student(client, mail, "leave.me@example.test")
    with client.student.factory() as db:
        db.add(VaultFact(workspace_id=workspace_id, field_key="objective", value={"value": "nursing"},
                         source_type="conversation"))
        db.commit()
        uid = db.scalar(select(User.firebase_uid).where(User.email == "leave.me@example.test"))

    gone = client.delete("/v1/account", headers=bearer(token))
    assert gone.status_code == 200, gone.text
    assert gone.json()["data"]["deleted"]["ownedWorkspace"] == 1
    with client.student.factory() as db:
        assert db.scalar(select(User).where(User.email == "leave.me@example.test")) is None
        assert db.get(Workspace, workspace_id) is None
        assert db.scalars(select(VaultFact).where(VaultFact.workspace_id == workspace_id)).all() == []
        assert db.scalars(select(AuthDevice)).all() == []
    # Firebase keeps the account, turned off; it cannot sign in and its token is dead.
    assert firebase_admin_auth.get_user(uid, app=firebase_auth._app()).disabled
    assert sign_in("leave.me@example.test")["error"]["message"] == "USER_DISABLED"
    assert client.get("/v1/account/workspace", headers=bearer(token)).status_code == 401
    with client.student.factory() as db:
        assert db.scalar(select(User).where(User.email == "leave.me@example.test")) is None
    assert [m["subject"] for m in mail] == ["Your Placement AI account has been deleted"]
    assert mail[0]["to"] == "leave.me@example.test"
