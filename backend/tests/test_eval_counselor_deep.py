"""Recorded deep-evaluation harness tests; no provider or network calls."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.eval.cost import load_prices, token_record
from scripts.eval_counselor_deep import PERSONAS, PRICES, load_personas, run_evaluation


def test_persona_fixtures_are_diverse_data():
    personas = load_personas(PERSONAS)
    assert len(personas) >= 12
    assert len({persona["country"] for persona in personas}) >= 8
    assert len({persona["education_system"] for persona in personas}) >= 8
    assert all(persona["hidden_truths"] and persona["recorded_turns"] for persona in personas)


@pytest.mark.asyncio
async def test_recorded_persona_runs_deep_turn_analyst_and_memory_end_to_end(tmp_path):
    with patch("openai.AsyncOpenAI", side_effect=AssertionError("provider client forbidden")):
        result = await run_evaluation(persona_ids={"danish"}, result_dir=tmp_path)
    assert result["status"] == "complete"
    person = result["personas"][0]
    assert len(person["turns"]) == 2
    assert person["turns"][0]["reply"] == "What have you done independently with Python so far?"
    assert person["turns"][0]["model_calls"] == 4
    assert person["notebook"]["stated_goal"]["first_said_turn"] == 1
    assert person["notebook"]["claims"][0]["evidence_level"] == "tried"
    assert set(person["usage_by_phase"]) == {
        "counselor", "analyst", "sensitive", "memory_extractor"}
    assert person["metrics"]["hidden_truth_recall"] == 0.167
    assert len(result["paths"]) == 2
    assert all(path.exists() for path in tmp_path.iterdir())
    report = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert report["personas"][0]["turns"][0]["usage"][0]["input"] == 100


@pytest.mark.asyncio
async def test_recorded_goal_switcher_retains_three_session_goals(tmp_path):
    result = await run_evaluation(persona_ids={"goal_switcher"}, result_dir=tmp_path)
    person = result["personas"][0]
    assert len(person["turns"]) == 3
    assert [item["goal"] for item in person["notebook"]["goal_history"]] == [
        "architecture", "business", "environmental science"]


@pytest.mark.asyncio
async def test_recorded_run_stops_at_mirror_or_turn_limit(tmp_path):
    persona = next(item for item in load_personas(PERSONAS) if item["id"] == "danish")
    persona["recorded_turns"][0]["counselor"]["action"] = {"type": "mirror"}
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "one.json").write_text(json.dumps(persona), encoding="utf-8")
    mirrored = await run_evaluation(fixture_dir=fixture_dir, result_dir=tmp_path / "mirror")
    assert len(mirrored["personas"][0]["turns"]) == 1
    limited = await run_evaluation(persona_ids={"danish"}, max_turns=1,
                                   result_dir=tmp_path / "limit")
    assert len(limited["personas"][0]["turns"]) == 1


@pytest.mark.asyncio
async def test_budget_guard_stops_recorded_run_and_writes_partial_report(tmp_path):
    result = await run_evaluation(
        persona_ids={"danish"}, result_dir=tmp_path, max_cost_usd=0.00001)
    assert result["status"] == "budget_reached"
    assert result["personas"][0]["turns"] == []
    assert len(result["all_calls"]) == 1
    assert next(tmp_path.glob("*.md")).is_file()


def test_cost_uses_editable_model_prices_file():
    prices = load_prices(PRICES)
    usage = SimpleNamespace(
        prompt_tokens=100, completion_tokens=20,
        prompt_tokens_details=SimpleNamespace(cached_tokens=20),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
    )
    row = token_record(usage, "gpt-5-mini", "counselor", prices)
    assert row == {"phase": "counselor", "model": "gpt-5-mini", "input": 100,
                   "cached_input": 20, "output": 20, "reasoning": 5,
                   "cost_usd": 0.0000605}
    long_usage = SimpleNamespace(
        prompt_tokens=272001, completion_tokens=100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=10),
    )
    long_row = token_record(long_usage, "gpt-6-astra", "analyst", prices)
    assert long_row["cost_usd"] == round((272001 * 10 * 2 + 100 * 50 * 1.5) / 1_000_000, 8)


@pytest.mark.asyncio
async def test_live_requires_explicit_positive_budget_before_any_client(tmp_path):
    with patch("openai.AsyncOpenAI", side_effect=AssertionError("provider client forbidden")):
        with pytest.raises(ValueError, match="positive --max-cost-usd"):
            await run_evaluation(live=True, result_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []
