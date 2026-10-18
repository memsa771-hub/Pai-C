"""Sourced claims, cache season bounds and reviewed-rule data fail closed."""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from app.pai_c.deep.grounding import guard_reply
from app.research import seasons
from app.research.requirements import RequirementStore


def fact(**changes):
    return {"fact_id": "fact", "value": "The entry threshold is 70%.",
        "quote": "The entry threshold is 70%.", "source_url": "https://catalog.example.test/entry",
        "status": "verified", "checked_at": datetime.now(timezone.utc).isoformat(), **changes}


def test_only_exact_current_cited_world_claim_survives():
    text = fact()["value"]
    raw = json.dumps({"world_claims": [{"text": text, "fact_ids": ["fact"]}]})
    reply, violations = guard_reply(text, raw, [fact()], "")
    assert text in reply and "[source," in reply and not violations
    for evidence in [[], [fact(status="unconfirmed")], [fact(checked_at="2000-01-01T00:00:00+00:00")]]:
        reply, violations = guard_reply(text, raw, evidence, "")
        assert text not in reply and "ungrounded_world_claim" in violations


def test_student_numbers_survive_world_numbers_do_not():
    student = "My result is 82%."
    assert guard_reply(student, "{}", [], student) == (student, [])
    reply, violations = guard_reply("A place requires 82%.", "{}", [], "")
    assert "82%" not in reply and "ungrounded_world_number" in violations


def test_malformed_world_claims_fail_closed():
    reply, violations = guard_reply("An unsupported assertion.", '{"world_claims":[{"text":"another text"}]}', [], "")
    assert "unsupported assertion" not in reply and violations == ["invalid_world_claim"]


def test_season_expiry_is_data_owned_and_supplements_ttl(monkeypatch):
    today = date.today()
    data = {"seasons": [{"key": "cycle", "starts_on": str(today - timedelta(days=30)),
                           "ends_on": str(today - timedelta(days=1))}], "rules": []}
    monkeypatch.setattr(seasons, "policy", lambda: data)
    row = SimpleNamespace(cycle_label="cycle", checked_at=datetime.now(timezone.utc))
    assert not RequirementStore.is_fresh(row)
    assert not seasons.verified_rules("program", "cycle")
    data["seasons"][0]["ends_on"] = str(today + timedelta(days=30))
    assert seasons.season_current("cycle")


def test_no_merit_rule_is_invented_without_verified_source(monkeypatch):
    data = {"seasons": [], "rules": [{"program_id": "p", "season": "s", "threshold": 70}]}
    monkeypatch.setattr(seasons, "policy", lambda: data)
    assert seasons.verified_rules("p", "s") == []
    data["rules"][0].update(source_url="https://catalog.example.test/rules", checked_at=datetime.now(timezone.utc).isoformat(), verification_status="verified")
    assert len(seasons.verified_rules("p", "s")) == 1
