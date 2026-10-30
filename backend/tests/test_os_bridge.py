"""The Counsellor-side bridge in app/main.py that tells the PAI OS API who the signed-in student is.

The OS never imports Counsellor auth; main.py maps the workspace (read for GET, write for POST) to
the OS student ref. These tests pin that mapping without a database.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.main as main
from app.api.response import ResponseCode, json_response


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_auth(db, network, token, authorization, *, write=False):
        seen.append({"network": network, "token": token, "authorization": authorization, "write": write})
        if network == "missing":
            return None, json_response(ResponseCode.NOT_FOUND, "Workspace not found")
        if write and authorization != "Bearer student":
            return None, json_response(ResponseCode.FORBIDDEN, "Student account required")
        return SimpleNamespace(id="ws-123"), None

    monkeypatch.setattr(main, "_workspace_auth", fake_auth)
    return seen


def test_read_maps_workspace_to_student_ref(calls):
    assert main._os_student_ref("net-1", None, "Bearer anyone", db=None) == "ws-123"
    assert calls[-1]["write"] is False


def test_write_requires_write_access(calls):
    assert main._os_student_ref_for_write("net-1", None, "Bearer student", db=None) == "ws-123"
    assert calls[-1]["write"] is True
    with pytest.raises(HTTPException) as e:
        main._os_student_ref_for_write("net-1", "machine-token", None, db=None)
    assert (e.value.status_code, e.value.detail) == (403, "Student account required")


def test_unknown_workspace_is_404_with_host_message(calls):
    with pytest.raises(HTTPException) as e:
        main._os_student_ref("missing", None, None, db=None)
    assert (e.value.status_code, e.value.detail) == (404, "Workspace not found")


def test_os_admin_token_survives_the_session_middleware():
    """PaiSessionBoundaryMiddleware rewrites Authorization on every /v1/ request (only PAI session tokens
    survive), so the OS admin token must travel in its own header. Through the real middleware: the
    admin check passes (the empty body then fails validation, 422) and a missing token is still 401."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.os.api import mount_os

    app = FastAPI()
    # Merge pai-c + pai-os: pai-c removed PaiSessionBoundaryMiddleware with Supabase (3112f0e); run the
    # check through the /v1/ middlewares main.py has now instead.
    app.add_middleware(main.PrivateApiMiddleware)
    app.add_middleware(main.SafeAccessLogMiddleware)
    env = {"DATABASE_URL": "postgresql://x/y", "OS_ENABLED": "true", "OS_ADMIN_TOKEN": "admin-secret"}
    assert mount_os(app, env=env)
    client = TestClient(app)
    assert client.post("/v1/os/plans", json={}, headers={"X-OS-Admin-Token": "admin-secret"}).status_code == 422
    assert client.post("/v1/os/plans", json={}, headers={"X-OS-Admin-Token": "wrong"}).status_code == 401
    assert client.post("/v1/os/plans", json={}).status_code == 401
