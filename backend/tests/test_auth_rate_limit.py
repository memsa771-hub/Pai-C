"""Shared username auth throttling cannot silently fail open."""

import unittest
from unittest.mock import patch

from app.routers import auth


class _Redis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1

    def expire(self, key, seconds, nx=False):
        assert seconds == 3600 and nx

    def delete(self, key):
        self.values.pop(key, None)


class AuthRateLimitTests(unittest.TestCase):
    def test_shared_budget_and_success_reset(self):
        redis = _Redis()
        with patch.object(auth.config, "REDIS_URL", "redis://test"), \
             patch("app.infrastructure.cache._lazy_client", return_value=redis):
            self.assertFalse(auth._over_budget("user:student", 2))
            auth._charge("user:student")
            auth._charge("user:student")
            self.assertTrue(auth._over_budget("user:student", 2))
            auth._clear("user:student")
            self.assertFalse(auth._over_budget("user:student", 2))

    def test_configured_redis_outage_fails_closed(self):
        with patch.object(auth.config, "REDIS_URL", "redis://test"), \
             patch("app.infrastructure.cache._lazy_client", return_value=None):
            self.assertTrue(auth._over_budget("user:student", 2))


if __name__ == "__main__":
    unittest.main()
