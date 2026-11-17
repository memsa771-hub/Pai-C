"""P2-T1 review fix 4: readers that meant "confirmed" also take `verified` (P2-D6, master §8.2)."""

from datetime import timedelta

import pytest

from app.os.knowledge import Fact
from app.os.workers import freshness
from tests.os.test_freshness import NOW, QUOTE, URL, events, status_of
from tests.os.test_workers import service

pytestmark = pytest.mark.req("R-25")


def put_verified(kb, field, value, checked):
    fid = kb.upsert("programme", "p1", field, Fact(value, QUOTE, URL, checked, 2027, "confirmed"))
    kb.set_status(fid, "verified", cause="review")
    return fid


def test_old_verified_fact_goes_stale(engine, clean):
    svc, kb, _ = service(engine)
    old = put_verified(kb, "application_route", "direct", NOW - timedelta(days=31))
    assert freshness.run(svc, engine, NOW, ttl_days=30) == 1
    assert status_of(engine, old) == "stale"
    [e] = events(engine)
    assert (e["old"]["status"], e["new"]["status"]) == ("verified", "stale")


def test_pack_and_replan_readers_take_verified():
    import inspect

    from app.os.packs import inputs, instructions
    from app.os.replan import apply

    for mod in (inputs, instructions, apply):
        assert '("confirmed", "verified")' in inspect.getsource(mod), mod.__name__
