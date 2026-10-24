# -*- coding: utf-8 -*-
"""Sliding-window limits for the account endpoints, all set in auth_limits.json.

With Redis configured every worker and instance shares one count. Without it
(local runs, tests), or while Redis is down, each process counts on its own.
Keys hold a hash of the user, email or IP, never the value itself.
"""

import hashlib
import json
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from app.infrastructure import cache

LIMITS: dict = {action: rules for action, rules in
                json.loads(Path(__file__).with_name("auth_limits.json").read_text(encoding="utf-8")).items()
                if not action.startswith("_")}

# Drop hits older than the window, refuse when full, else record this one; atomic in Redis.
_SLIDING_WINDOW = """
local now, window = tonumber(ARGV[1]), tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return 1
"""

_local: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _hit(key: str, limit: int, window: float) -> bool:
    client = cache._lazy_client()
    if client is not None:
        try:
            now = int(time.time() * 1000)
            return bool(client.eval(_SLIDING_WINDOW, 1, key, now, int(window * 1000), limit,
                                    f"{now}-{uuid.uuid4().hex}"))
        except Exception as exc:
            cache._sync_failed(exc)
    now = time.monotonic()
    with _lock:
        hits = _local[key]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


def allow(action: str, **subjects: str | None) -> bool:
    """Record one attempt at `action` (user=, email=, ip=); False once any of its limits is used up."""
    for rule in LIMITS[action]:
        who = subjects.get(rule["per"])
        if not who:
            continue
        digest = hashlib.sha256(who.encode()).hexdigest()[:32]
        key = f"pai:ratelimit:{action}:{rule['per']}:{rule['window_seconds']}:{digest}"
        if not _hit(key, rule["limit"], rule["window_seconds"]):
            return False
    return True


def reset() -> None:
    """Forget the in-process counts (tests)."""
    with _lock:
        _local.clear()
