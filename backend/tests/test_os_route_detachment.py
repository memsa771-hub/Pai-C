"""Approved OS detachment leaves Counselor transport and shared contracts alive."""
import asyncio
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.pai import WorkspaceApi


@pytest.mark.parametrize("path", [
    "/v1/application-workspace/institutions", "/v1/application-workspace/applications",
    "/v1/deadlines", "/v1/deadlines/settings/reminders",
    "/v1/integrations", "/v1/routines", "/v1/todos", "/v1/timers", "/v1/knowledge",
    "/v1/browser/tabs",
])
def test_os_routes_are_not_exposed_by_counselor_app(path):
    assert TestClient(main.app).get(path).status_code == 404


def test_counselor_and_os_contract_routes_stay_mounted():
    paths = {route.path for route in main.app.routes if hasattr(route, "path")}
    for prefix in ("/v1/fetch", "/v1/escalations", "/v1/student-requests", "/v1/decision-records",
                   "/v1/counselor", "/v1/roadmaps", "/v1/student-profile", "/v1/files"):
        assert any(path.startswith(prefix) for path in paths), prefix


def test_counselor_keeps_in_process_asgi_transport():
    response = asyncio.run(WorkspaceApi("offline-workspace", "offline-token")._raw_request("GET", "/health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_maintenance_keeps_shared_cleanup(monkeypatch):
    from app import database
    db = Mock()
    db.execute.return_value.fetchall.return_value = []
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    main._run_maintenance()
    assert db.execute.call_count == 2
    db.commit.assert_called_once()
    db.close.assert_called_once()
