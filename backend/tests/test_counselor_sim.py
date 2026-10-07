"""Explicitly opted-in model-backed acceptance suite."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.eval_counselor_sim import evaluate, report


@pytest.mark.counselor_sim
@pytest.mark.asyncio
async def test_ten_personas_chat_voice_and_switch():
    results = await evaluate(runs=20, max_turns=25, switch_runs=3)
    output = Path("eval_reports") / f"counselor_sim_{datetime.now(timezone.utc):%Y%m%d}.md"
    report(results, output)
    assert len(results) == 203
    assert all(item["checks"].get("queued") for item in results)
    assert all(not item["checks"].get("leak") for item in results)
    assert all(not item["checks"].get("repeat_slot") for item in results)
    assert all(not item["checks"].get("reply_rule_failure") for item in results)
    assert all(all(item["judge"].values()) for item in results)
