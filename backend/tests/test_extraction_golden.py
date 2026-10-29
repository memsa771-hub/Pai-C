# -*- coding: utf-8 -*-
"""Extraction golden set (spec §5): each case's fixed extractor output goes
through the real normalizer, candidate store and reconciler, and the Vault
view must show what the student said, in English labels, and nothing the
case rules out. The same cases run against the live model in
scripts/eval_extraction.py."""

import pytest

from scripts import eval_extraction

CASES = eval_extraction.load_cases()


def test_the_set_covers_each_language_and_the_core_facts():
    assert len(CASES) >= 12
    languages = {case["language"] for case in CASES}
    assert languages == set(eval_extraction.LANGUAGES)
    types = {spec["type"] for case in CASES for spec in case["expected_vault"]}
    assert {"education", "interest", "strength", "family_member", "finance.budget",
            "mobility.relocation_willingness", "goal", "pressure"} <= types
    assert all(case.get("synthetic") is True for case in CASES)


@pytest.mark.parametrize("change, reason", [
    ({"language": "fr"}, "language"), ({"student_messages": []}, "student_messages"),
    ({"extractor_output": [{"candidates": []}, {"candidates": []}]}, "one extractor_output"),
    ({"expected_vault": [{"kind": "row", "type": "x"}]}, "kind"),
    ({"must_not": [{"type": "goal"}]}, "why")])
def test_a_malformed_case_is_refused(change, reason):
    base = {"id": "x", "language": "en", "student_messages": ["hi"], "extractor_output": {"candidates": []},
            "expected_vault": []}
    eval_extraction.validate_case(base)
    with pytest.raises(ValueError, match=reason):
        eval_extraction.validate_case({**base, **change})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_golden_case(case):
    result = await eval_extraction.run_case(case, eval_extraction.fixed_model)
    missed = [(item["type"], item.get("display") or item.get("display_any"), item["seen"])
              for item in result["expected"] if not item["found"]]
    assert not missed, missed
    assert not result["violations"], result["violations"]


def test_the_live_script_refuses_without_an_explicit_mode(capsys):
    with pytest.raises(SystemExit):
        eval_extraction.main([])
    assert "--live" in capsys.readouterr().err


def test_live_cost_rates_fall_back_to_the_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_extraction, "MODEL_COSTS", tmp_path / "missing.json")
    assert eval_extraction.model_rates("gpt-5-mini", 3.0) == (3.0, 3.0)
    costs = tmp_path / "model_costs.json"
    costs.write_text('{"models": {"gpt-5-mini": {"input": 0.25, "output": 2}}}', encoding="utf-8")
    monkeypatch.setattr(eval_extraction, "MODEL_COSTS", costs)
    assert eval_extraction.model_rates("gpt-5-mini", 3.0) == (0.25, 2.0)
    costs.write_text('{"usd_per_million_tokens": {"default": {"input": 3, "output": 15}}}', encoding="utf-8")
    assert eval_extraction.model_rates("gpt-5-mini", 0.1) == (3.0, 15.0)


@pytest.mark.asyncio
async def test_the_live_model_stops_before_the_cap(monkeypatch):
    """The call that would cross the cap is never made."""
    from app.memory import extractor
    calls = []

    async def real(**kwargs):
        calls.append(kwargs)
        return '{"candidates": []}'

    monkeypatch.setattr(extractor, "chat_completion", real)
    live = eval_extraction.LiveModel(cap_usd=0.01, usd_per_million=2.0, fingerprint="f")
    case = {"id": "c"}
    kwargs = {"system_prompt": "x" * 4000, "messages": [{"content": "y" * 4000}]}
    assert await live(case, 0, kwargs, None) == '{"candidates": []}'
    live.spent = 0.0099
    with pytest.raises(LookupError, match="budget_reached"):
        await live(case, 1, kwargs, None)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_replay_reports_a_missing_recording_as_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_extraction, "RECORDINGS", tmp_path)
    report = await eval_extraction.evaluate(CASES[:1], eval_extraction.recorded_model("fp"))
    assert report["skipped"] == [{"id": CASES[0]["id"], "reason": "not_recorded"}]
