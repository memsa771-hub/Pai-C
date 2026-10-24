"""Students sign in with email/password or Google; no username routes exist."""

from app.routers import auth


def test_auth_routes_are_the_firebase_set_and_have_no_username():
    paths = {route.path for route in auth.router.routes}
    assert paths == {"/v1/auth/session", "/v1/auth/send-verification", "/v1/auth/forgot-password",
                     "/v1/auth/reset-password"}
    assert not [path for path in paths if "username" in path]
