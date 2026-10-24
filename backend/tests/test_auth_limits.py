"""The account-endpoint limits in auth_limits.json, counted in process (no Redis)."""

from unittest.mock import patch

import pytest

from app.security import rate_limit


@pytest.fixture(autouse=True)
def in_process():
    rate_limit.reset()
    with patch("app.infrastructure.cache._lazy_client", return_value=None):
        yield
    rate_limit.reset()


def tries(action, n, **who):
    return [rate_limit.allow(action, **who) for _ in range(n)]


def test_the_limits_are_the_agreed_ones():
    assert rate_limit.LIMITS == {
        "send_verification": [{"per": "user", "limit": 1, "window_seconds": 60},
                              {"per": "user", "limit": 5, "window_seconds": 3600}],
        "forgot_password": [{"per": "email", "limit": 3, "window_seconds": 3600},
                            {"per": "ip", "limit": 10, "window_seconds": 3600}],
        "reset_password": [{"per": "ip", "limit": 10, "window_seconds": 3600}],
        "session": [{"per": "user", "limit": 30, "window_seconds": 3600}],
    }


def test_verification_one_a_minute_and_five_an_hour():
    clock = [1000.0]
    with patch("app.security.rate_limit.time.monotonic", side_effect=lambda: clock[0]):
        assert tries("send_verification", 2, user="uid-1") == [True, False]
        sent = 1
        for _ in range(10):
            clock[0] += 61
            sent += rate_limit.allow("send_verification", user="uid-1")
        assert sent == 5
        assert rate_limit.allow("send_verification", user="uid-2")


def test_forgot_password_per_email_and_per_ip():
    assert tries("forgot_password", 4, email="a@example.test", ip="1.1.1.1") == [True] * 3 + [False]
    # Other addresses from the same IP share the IP's 10.
    others = [rate_limit.allow("forgot_password", email=f"x{i}@example.test", ip="1.1.1.1") for i in range(8)]
    assert others == [True] * 7 + [False]
    assert rate_limit.allow("forgot_password", email="x0@example.test", ip="2.2.2.2")


def test_session_thirty_an_hour_per_user():
    assert tries("session", 31, user="uid-1") == [True] * 30 + [False]
    assert rate_limit.allow("session", user="uid-2")
