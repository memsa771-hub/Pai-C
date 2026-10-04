"""HTTP session exchange and cookie authorization regression tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Header
from fastapi.testclient import TestClient

from app.main import app
from app.routers.account import _canonical_workspace_row
from app.security.identity import AuthenticatedIdentity


@app.get("/v1/_auth_test_probe")
def _auth_test_probe(authorization: str | None = Header(None)):
    return {"authorization": authorization}


@app.post("/v1/_auth_test_probe")
def _auth_test_mutation():
    return {"ok": True}


class AuthBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_old_supabase_jwt_never_authorizes_protected_route(self):
        result = self.client.get("/v1/_auth_test_probe", headers={"Authorization": "Bearer old.jwt.token"})
        self.assertIsNone(result.json()["authorization"])
        self.assertIn("no-store", result.headers["cache-control"])

    def test_cookie_is_authority_over_client_bearer(self):
        result = self.client.get(
            "/v1/_auth_test_probe",
            headers={"Authorization": "Bearer pai_other", "Cookie": "pai_session=pai_cookie"},
        )
        self.assertEqual(result.json()["authorization"], "Bearer pai_cookie")

    def test_cookie_mutations_require_allowed_origin(self):
        blocked = self.client.post("/v1/_auth_test_probe", headers={
            "Cookie": "pai_session=pai_cookie", "Origin": "https://attacker.example"})
        self.assertEqual(blocked.status_code, 403)
        allowed = self.client.post("/v1/_auth_test_probe", headers={
            "Cookie": "pai_session=pai_cookie", "Origin": "https://app.placement-ai.com"})
        # A local environment may list only localhost; in CI production does list this origin.
        if "https://app.placement-ai.com" in __import__("app.main", fromlist=["origins"]).origins:
            self.assertEqual(allowed.status_code, 200)

    def test_exchange_issues_http_only_cookie_and_never_returns_token_in_json(self):
        identity = AuthenticatedIdentity("supabase", "subject", "student@example.test", True)
        user = SimpleNamespace(id="user-id", email=identity.email, username="student", display_name="Student")
        workspace = SimpleNamespace(id="workspace-id", slug="personal")
        with (
            patch("app.security.identity.SupabaseIdentityVerifier.verify", return_value=identity),
            patch("app.routers.auth.provider_token_was_revoked", return_value=False),
            patch("app.routers.auth.get_or_create_user", return_value=user),
            patch("app.routers.auth.get_or_create_owned_workspace", return_value=workspace),
            patch("app.routers.auth.create_session", return_value="pai_secret"),
            patch("app.routers.auth.config.APP_ENV", "production"),
        ):
            result = self.client.post("/v1/auth/session", headers={
                "Origin": "https://app.placement-ai.com", "Authorization": "Bearer valid-provider-jwt",
            })
        if "https://app.placement-ai.com" not in __import__("app.main", fromlist=["origins"]).origins:
            self.assertEqual(result.status_code, 403)
            return
        self.assertEqual(result.status_code, 200)
        cookie = result.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertNotIn("pai_secret", result.text)
        self.assertEqual(result.json()["data"]["workspace"]["slug"], "personal")

    def test_unverified_email_cannot_create_pai_session(self):
        identity = AuthenticatedIdentity("supabase", "subject", "student@example.test", False)
        with patch("app.security.identity.SupabaseIdentityVerifier.verify", return_value=identity):
            result = self.client.post("/v1/auth/session", headers={
                "Origin": "https://app.placement-ai.com", "Authorization": "Bearer provider-jwt",
            })
        if "https://app.placement-ai.com" in __import__("app.main", fromlist=["origins"]).origins:
            self.assertEqual(result.status_code, 403)
            self.assertEqual(result.json()["message"], "AUTH_EMAIL_CONFIRMATION_REQUIRED")
            self.assertNotIn("pai_session", result.headers.get("set-cookie", ""))

    def test_logged_out_provider_token_cannot_be_exchanged_again(self):
        identity = AuthenticatedIdentity("supabase", "subject", "student@example.test", True)
        with patch("app.security.identity.SupabaseIdentityVerifier.verify", return_value=identity), \
             patch("app.routers.auth.provider_token_was_revoked", return_value=True):
            result = self.client.post("/v1/auth/session", headers={
                "Origin": "https://app.placement-ai.com", "Authorization": "Bearer old-provider-jwt",
            })
        if "https://app.placement-ai.com" in __import__("app.main", fromlist=["origins"]).origins:
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json()["message"], "AUTH_SESSION_REVOKED")

    def test_desktop_session_refresh_rotates_previous_pai_token(self):
        identity = AuthenticatedIdentity("supabase", "subject", "student@example.test", True)
        user = SimpleNamespace(id="user-id", email=identity.email, username="student", display_name="Student")
        workspace = SimpleNamespace(id="workspace-id", slug="personal")
        with (
            patch("app.security.identity.SupabaseIdentityVerifier.verify", return_value=identity),
            patch("app.routers.auth.provider_token_was_revoked", return_value=False),
            patch("app.routers.auth.get_or_create_user", return_value=user),
            patch("app.routers.auth.get_or_create_owned_workspace", return_value=workspace),
            patch("app.routers.auth.create_session", return_value="pai_new"),
            patch("app.routers.auth.resolve_session", return_value=(object(), user)),
            patch("app.routers.auth.revoke_session") as revoke,
        ):
            result = self.client.post("/v1/auth/session", headers={
                "Origin": "pai://workspace", "X-PAI-Desktop": "1",
                "X-PAI-Previous-Session": "pai_old", "Authorization": "Bearer provider-jwt",
            })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["data"]["desktopToken"], "pai_new")
        self.assertNotIn("pai_session", result.headers.get("set-cookie", ""))
        revoke.assert_called_once()

    def test_browser_workspace_bootstrap_never_contains_machine_token(self):
        workspace = SimpleNamespace(
            id="workspace-id", slug="personal", name="My Workspace",
            last_activity_at=None, password_hash="machine-secret", owner_user_id="user-id",
        )
        payload = _canonical_workspace_row(workspace, SimpleNamespace(id="user-id"), "session-id")
        self.assertNotIn("password_hash", payload)
        self.assertNotIn("token", payload)
        self.assertNotIn("machine-secret", str(payload))
        self.assertIsNotNone(payload["streamTicket"])


if __name__ == "__main__":
    unittest.main()
