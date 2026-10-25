"""Offline guided policy replay; no provider or network calls."""
from unittest.mock import patch

import pytest

from scripts import eval_policy_modes as policy_eval
from scripts.eval_counselor_deep import PERSONAS, load_personas, run_evaluation


def test_ten_policy_personas_map_to_live_deep_personas():
    scripts = policy_eval.load_scripts()
    assert len(scripts) == 10
    assert {item["id"] for item in scripts} <= {item["id"] for item in load_personas(PERSONAS)}


def test_guided_guardrails_hold_on_every_persona():
    report = policy_eval.run()
    for entry in report["personas"]:
        guided = entry["modes"]["guided"]
        values = guided["metrics"]
        served, total = map(int, values["requests_served"].split("/"))
        assert served == total
        care, unsafe = map(int, values["safety_to_care"].split("/"))
        assert care == unsafe
        pictures = [row for row in guided["turns"] if row["action"] == "first_picture"]
        assert len(pictures) <= 1
        script = next(item for item in policy_eval.load_scripts() if item["id"] == entry["id"])
        for row in pictures:
            covered = set(script["turns"][row["turn"] - 1].get("covered", []))
            assert {"status", "history"} <= covered and len(covered) >= 4


def test_report_prints_capped_live_command():
    report = policy_eval.run()
    text = policy_eval.markdown(report)
    assert len(report["live_commands"]) == 1
    assert "--live --max-cost-usd 3 --policy-mode guided" in text


@pytest.mark.asyncio
async def test_deep_eval_policy_mode_uses_production_runtime(tmp_path):
    with patch("openai.AsyncOpenAI", side_effect=AssertionError("provider client forbidden")):
        result = await run_evaluation(persona_ids={"danish"}, result_dir=tmp_path, policy_mode="guided")
    assert result["policy_mode"] == "guided"
    turns = result["personas"][0]["turns"]
    # A new student is missing education basics, so the replay may ask about one; nothing else earns a question.
    assert turns and all(turn["decision"]["action"] in ("counsel", "explore_area") for turn in turns)
    assert all(turn["decision"]["question_allowed"] == (turn["decision"]["action"] == "explore_area") for turn in turns)
    assert any(turn["decision"]["action"] == "explore_area" for turn in turns)
    assert all(turn["reply"] for turn in turns)


@pytest.mark.asyncio
async def test_deep_eval_rejects_unknown_policy_mode(tmp_path):
    with pytest.raises(ValueError, match="--policy-mode"):
        await run_evaluation(persona_ids={"danish"}, result_dir=tmp_path, policy_mode="loose")
