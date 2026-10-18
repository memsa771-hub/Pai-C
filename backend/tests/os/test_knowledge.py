from datetime import datetime, timezone

import pytest
import yaml
from sqlalchemy import func, select

from app.os import models
from app.os.knowledge import Fact, SqlKnowledge, load_seed

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


def _fact(value, status="confirmed", year=2027, quote="q", url="https://u.example"):
    return Fact(value=value, quote=quote, url=url, checked_at=NOW, intake_year=year, status=status)


def test_confirmed_fact_needs_quote_and_url():
    with pytest.raises(ValueError, match="confirmed fact needs a quote and url"):
        Fact(value=1, quote="", url="", checked_at=NOW, intake_year=2027, status="confirmed")


def test_unconfirmed_fact_may_have_empty_quote():
    assert Fact(value=1, quote="", url="", checked_at=NOW, intake_year=2027, status="unconfirmed").quote == ""


def test_fact_needs_aware_checked_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        Fact(value=1, quote="q", url="https://u", checked_at=datetime(2026, 1, 1), intake_year=2027, status="confirmed")


def test_upsert_and_read(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("programme", "p1", "deadline_close", _fact({"date": "2027-07-15"}))
    got = kb.programme_facts(["p1"], ["deadline_close"], 2027)
    assert got[("p1", "deadline_close")].value == {"date": "2027-07-15"}
    assert got[("p1", "deadline_close")].id is not None


def test_route_facts(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("route", "germany_master", "blocked_account_yearly", _fact(11904, status="unconfirmed"))
    assert kb.route_facts("germany_master", ["blocked_account_yearly"], 2027)["blocked_account_yearly"].value == 11904


def test_other_intake_year_not_returned(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("programme", "p1", "deadline_close", _fact({"date": "2026-07-15"}, year=2026))
    assert kb.programme_facts(["p1"], ["deadline_close"], 2027) == {}


def test_other_tenant_not_returned(engine, clean):
    SqlKnowledge(engine, "other").upsert("programme", "p1", "deadline_close", _fact({"date": "2027-07-15"}))
    assert SqlKnowledge(engine, "pai").programme_facts(["p1"], ["deadline_close"], 2027) == {}


def test_upsert_updates_existing(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    first = kb.upsert("programme", "p1", "deadline_close", _fact({"date": "2027-07-15"}, status="unconfirmed", quote=""))
    second = kb.upsert("programme", "p1", "deadline_close", _fact({"date": "2027-07-01"}))
    assert first == second
    assert kb.programme_facts(["p1"], ["deadline_close"], 2027)[("p1", "deadline_close")].value == {"date": "2027-07-01"}


def test_seed_is_idempotent(engine, clean, tmp_path):
    seed = tmp_path / "seed.yaml"
    seed.write_text(yaml.safe_dump({
        "intake_year": 2027,
        "route_key": "r1",
        "route": {"blocked_account_yearly": {
            "value": 11904, "quote": "", "url": "https://e.example/f", "checked_at": "2026-10-17",
            "status": "unconfirmed", "conflict_note": "older pages say 11208"}},
        "programmes": {"p1": {"deadline_close": {
            "value": {"date": "2027-07-15"}, "quote": "", "url": "", "checked_at": "2026-10-12",
            "status": "unconfirmed"}}},
    }))
    kb = SqlKnowledge(engine, "pai")
    assert load_seed(seed, kb) == 2
    assert load_seed(seed, kb) == 2
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.knowledge_facts)).scalar_one() == 2
    note = kb.route_facts("r1", ["blocked_account_yearly"], 2027)["blocked_account_yearly"].conflict_note
    assert note == "older pages say 11208"


def test_confirm_updates_status(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    fid = kb.upsert("programme", "p1", "deadline_close", _fact({"date": "2027-07-15"}, status="unconfirmed", quote=""))
    fact = kb.confirm(fid, value={"date": "2027-07-15"}, quote="Deadline 15 July", url="https://uni.example/apply",
                      status="confirmed")
    assert fact.status == "confirmed" and fact.quote == "Deadline 15 July"
    assert kb.programme_facts(["p1"], ["deadline_close"], 2027)[("p1", "deadline_close")].status == "confirmed"


def test_confirm_unknown_fact_raises(engine, clean):
    with pytest.raises(KeyError):
        SqlKnowledge(engine, "pai").confirm(999, value=1, quote="q", url="https://u", status="confirmed")
