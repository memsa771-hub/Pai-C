"""The HTTP boundary: Firebase bearers reach routes untouched, no cookies, no leaked secrets."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import Header
from fastapi.testclient import TestClient

from app.main import app
from app.routers.account import _canonical_workspace_row


@app.get("/v1/_auth_test_probe")
def _auth_test_probe(authorization: str | None = Header(None)):
    return {"authorization": authorization}


class AuthBoundaryTests(unittest.TestCase):
    def setUp(self):
        from app.database import get_db
        overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: Mock()
        def restore_overrides():
            app.dependency_overrides.clear()
            app.dependency_overrides.update(overrides)
        self.addCleanup(restore_overrides)
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_bearer_reaches_the_route_as_sent_and_answers_are_private(self):
        response = self.client.get("/v1/_auth_test_probe", headers={"Authorization": "Bearer firebase-id-token"})
        self.assertEqual(response.json(), {"authorization": "Bearer firebase-id-token"})
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_a_cookie_never_authorizes(self):
        self.client.cookies.set("pai_session", "pai_old-session")
        response = self.client.get("/v1/_auth_test_probe")
        self.assertEqual(response.json(), {"authorization": None})

    def test_no_auth_endpoint_sets_a_cookie(self):
        for path, body in (("/v1/auth/session", {"deviceId": "device-fixture"}),
                           ("/v1/auth/send-verification", None),
                           ("/v1/auth/forgot-password", {"email": "nobody@example.test"})):
            response = self.client.post(path, json=body, headers={"Authorization": "Bearer not-a-firebase-token"})
            self.assertNotIn("set-cookie", response.headers, path)

    def test_browser_workspace_bootstrap_never_contains_machine_token(self):
        workspace = SimpleNamespace(
            id="workspace-id", slug="personal", name="My Workspace",
            last_activity_at=None, password_hash="machine-secret", owner_user_id="user-id",
        )
        payload = _canonical_workspace_row(workspace, SimpleNamespace(id="user-id", firebase_uid="uid"))
        self.assertNotIn("password_hash", payload)
        self.assertNotIn("token", payload)
        self.assertNotIn("machine-secret", str(payload))
        self.assertIsNotNone(payload["streamTicket"])


if __name__ == "__main__":
    unittest.main()
