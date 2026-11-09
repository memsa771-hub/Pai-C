"""P2-T5 (plan D-t1-2): every place that read `status == "confirmed"` treats a verified fact as confirmed (R-25).
Fictional values only."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.research.run import store_research
from app.os.packs.config import load_pack_configs
from app.os.packs.inputs import load_inputs
from app.os.packs.instructions import fees, instructions
from app.os.replan.apply import Replanner
from app.os.workers import freshness
from tests.os.test_freshness import NOW, status_of
from tests.os.test_pack_rules import BOOK, CFG, fact, inputs
from tests.os.test_workers import service

pytestmark = pytest.mark.req("R-25")
URL, QUOTE = "https://uni.example/apply", "Apply by 15 July"
AT = datetime(2026, 10, 22, tzinfo=timezone.utc)


def upsert_as(kb, scope, ref, field, fact) -> int:
    """T1: `verified` is reached only through review, so a verified row is made confirmed first."""
    if fact.status != "verified":
        return kb.upsert(scope, ref, field, fact)
    fid = kb.upsert(scope, ref, field, Fact(**{**fact.__dict__, "status": "confirmed"}))
    kb.set_status(fid, "verified", cause="review")
    return fid


def put(kb, field="deadline_close", value=None, status="confirmed") -> int:
    value = value if value is not None else {"date": "2027-07-15", "tz": "Europe/Berlin"}
    quote, url = (QUOTE, URL) if status in ("confirmed", "verified") else ("", "")
    return upsert_as(kb, "programme", "p1", field, Fact(value, quote, url, NOW, 2027, status))


def test_instructions_use_a_verified_route():
    route, steps = instructions(inputs(facts={"application_route": fact("uni_assist", "verified")}), "p1")
    assert route == "uni_assist" and steps


def test_instructions_still_refuse_unconfirmed_and_stale():
    for status in ("unconfirmed", "stale"):
        route, _ = instructions(inputs(facts={"application_route": fact("uni_assist", status)}), "p1")
        assert route is None


def test_fee_row_passes_verified_through():
    rows = fees(inputs(facts={"tuition_fee_non_eu_eur": fact(1500, "verified")}))
    assert any(r.status == "verified" for r in rows)


def test_verified_required_documents_override_the_checklist(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    upsert_as(kb, "programme", "p1", "required_documents", Fact(["passport", "other"], QUOTE, URL, AT, 2027, "verified"))
    inp = load_inputs(engine, "pai", kb, BOOK, CFG, None, "s1", "p1", 2027)
    assert inp.required_override == ["passport"]
    kb.upsert("programme", "p1", "required_documents", Fact(["passport"], "", "", AT, 2027, "unconfirmed"))
    assert load_inputs(engine, "pai", kb, BOOK, CFG, None, "s1", "p1", 2027).required_override is None


def test_replan_counts_a_verified_programme_as_confirmed(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    me = SimpleNamespace(engine=engine, tenant="pai")
    assert Replanner.confirmed(me, "p1", 2027) is False
    kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-07-15"}, QUOTE, URL, AT, 2027, "unconfirmed"))
    assert Replanner.confirmed(me, "p1", 2027) is False
    upsert_as(kb, "programme", "p1", "deadline_close", Fact({"date": "2027-07-15"}, QUOTE, URL, AT, 2027, "verified"))
    assert Replanner.confirmed(me, "p1", 2027) is True


def test_sweeper_makes_an_old_verified_fact_stale(engine, clean):
    svc, kb, _ = service(engine)
    fid = upsert_as(kb, "programme", "p1", "application_route",
                    Fact("direct", QUOTE, URL, NOW - timedelta(days=40), 2027, "verified"))
    assert freshness.run(svc, engine, NOW, ttl_days=30) == 1
    assert status_of(engine, fid) == "stale"
    with engine.connect() as conn:
        payload = conn.execute(select(models.events.c.payload).where(models.events.c.type == "fact_changed")).scalar()
    assert payload["old"]["status"] == "verified" and payload["new"]["status"] == "stale"
    assert freshness.run(svc, engine, NOW, ttl_days=30) == 0


def test_mark_stale_takes_verified_and_not_unconfirmed(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    v = put(kb, status="verified")
    assert kb.mark_stale(v) is True and status_of(engine, v) == "stale"
    u = put(kb, field="application_route", value="x", status="unconfirmed")
    assert kb.mark_stale(u) is False


def test_research_never_overwrites_a_verified_fact(engine, clean):
    """store_research keeps a verified value, and notes a different finding as a conflict (as for confirmed)."""
    svc, kb, kernel = service(engine)
    fid = put(kb, status="verified")
    profile = SimpleNamespace(fields=[SimpleNamespace(name="deadline_close")])
    svc.check_fact_value = lambda *a: None
    verdicts = {"deadline_close": {"status": "confirmed", "value": {"date": "2027-08-01"}, "quote": "Apply by 1 Aug",
                                   "url": URL, "evidence": [], "conflict_note": None}}
    import app.os.knowledge.research.run as run

    orig = run.fact_value
    run.fact_value = lambda spec, value, year: value
    try:
        counts = store_research(engine, svc, kernel, 1, "p1", 2027, profile, verdicts, NOW)
    finally:
        run.fact_value = orig
    assert counts["conflicts"] == 1
    _, _, _, f = kb.get(fid)
    assert f.status == "verified" and f.value == {"date": "2027-07-15", "tz": "Europe/Berlin"}
    assert f.conflict_note and "research found" in f.conflict_note
