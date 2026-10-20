"""Students sign in with email/password or Google; no username routes exist."""

from app.routers import auth


def test_no_username_routes_are_exposed():
    paths = {route.path for route in auth.router.routes}
    assert "/v1/auth/session" in paths
    assert not [path for path in paths if "username" in path]


def test_session_payload_has_no_username():
    class _User:
        id, email, display_name, username = "u1", "student@example.test", None, "legacy"

    class _Workspace:
        id, slug = "w1", "student"

    payload = auth._session_payload(_User(), _Workspace())
    assert "username" not in payload["user"]
    assert payload["user"]["displayName"] == "student@example.test"
