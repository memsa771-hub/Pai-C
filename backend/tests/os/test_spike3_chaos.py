"""Spike 3 chaos: random SIGKILLs of worker processes lose and duplicate nothing.

The driver (kernel side) enqueues 20 tasks through a DBOSClient and SIGKILLs a random
worker subprocess every 2 s, starting a replacement with the same executor ID. The test
model is slow enough that kills hit in-flight attempts, which DBOS must recover.
Real Postgres; no API key, no cost.
"""

from pathlib import Path

import pytest

from spikes.spike3.chaos import run_chaos

pytestmark = pytest.mark.chaos

# Slower than the CLI default (0.5 s) so 20 tasks span several kill windows (kills >= 3 with margin).
MODEL_DELAY_S = 1.5


def test_chaos_small_run(pg_url: str, tmp_path: Path) -> None:
    report = run_chaos(
        tasks=20, workers=3, kill_every_s=2, model="test", timeout_s=180,
        database_url=pg_url, model_delay_s=MODEL_DELAY_S, log_dir=tmp_path,
    )
    print(report)
    assert not report.timed_out, report
    assert report.lost == 0, report
    assert report.done == report.tasks == 20, report
    assert report.duplicated == 0, report
    assert report.duplicate_results == 0, report
    assert report.extra_workflows == 0, report
    assert report.unexpected_exits == 0, report
    assert report.kills >= 3, report
    # Non-vacuous: at least one attempt was interrupted by a kill and finished on another
    # worker process (its step_runs / model_calls rows come from two processes).
    assert report.recovered_attempts >= 1, report
    assert report.valid_outputs == 20 and report.valid_rate == 1.0, report
