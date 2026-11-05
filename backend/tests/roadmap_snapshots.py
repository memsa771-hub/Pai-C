"""A fixed walk through the roadmap API (choose, tick, untick, refused tick, withdraw) with the request day frozen,
and the volatile values (ids, timestamps) normalised. P1-T5 captured it from the code before the plan adapter existed
(tests/fixtures/connect/roadmap_pre_adapter.json); the flags-off test must still produce exactly that."""

import json
import re
from datetime import date
from unittest.mock import patch

from tests.test_roadmap_api import TOKEN, choose, pre_eng

DAY = date(2026, 11, 5)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class _FrozenDate(date):
    @classmethod
    def today(cls):
        return DAY


def normalise(value, key=None):
    if isinstance(value, dict):
        return {k: normalise(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v, key) for v in value]
    if isinstance(value, str) and _UUID.search(value):
        return _UUID.sub("<uuid>", value)
    if isinstance(value, str) and _STAMP.match(value):
        return "<stamp>"
    if isinstance(value, int) and not isinstance(value, bool) and key in {"id", "possibility_id", "route_decision_id"}:
        return "<n>"
    return value


def walk() -> dict:
    """Every answer of the walk, status code and body, as plain JSON."""
    out = {}
    with patch("app.routers.roadmap.date", _FrozenDate), patch("app.pai_c.roadmap.engine.date", _FrozenDate):
        with pre_eng() as (client, student, params):
            def record(name, response):
                out[name] = {"status": response.status_code, "body": normalise(response.json())}
                return response

            record("get_before_choice", client.get("/v1/roadmap", params=params, headers=TOKEN))
            record("choose", choose(client, params, "electrical_engineering"))
            record("get_after_choice", client.get("/v1/roadmap", params=params, headers=TOKEN))
            for name, body in (("tick_apply", {"key": "apply", "done": True}),
                               ("tick_vault_step", {"key": "marks", "done": True}),
                               ("tick_unknown_key", {"key": "nope", "done": True}),
                               ("untick_apply", {"key": "apply", "done": False})):
                record(name, client.post("/v1/roadmap/steps", params=params, headers=TOKEN, json=body))
            record("withdraw", client.post("/v1/roadmap/withdraw", params=params, headers=TOKEN))
            record("get_after_withdraw", client.get("/v1/roadmap", params=params, headers=TOKEN))
    return json.loads(json.dumps(out))
