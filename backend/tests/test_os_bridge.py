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
