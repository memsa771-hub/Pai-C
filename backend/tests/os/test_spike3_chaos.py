"""Spike 3 chaos: random SIGKILLs of worker processes lose and duplicate nothing.

The driver (kernel side) enqueues 20 tasks through a DBOSClient and SIGKILLs a random
worker subprocess every 2 s, starting a replacement with the same executor ID. The test
model is slow enough that kills hit in-flight attempts, which DBOS must recover.
Real Postgres; no API key, no cost.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from spikes.spike3.chaos import ChaosReport, pass_bar_failures, run_chaos

pytestmark = pytest.mark.chaos

# Slow enough that 20 tasks span several kill windows (kills >= 3 with margin). Same as the CLI default.
MODEL_DELAY_S = 1.5
SEED = 7  # fixed, so a failing run's kill sequence can be reproduced

PASSING = ChaosReport(
    tasks=100, done=100, failed=0, lost=0, duplicate_results=0, duplicated=0, extra_workflows=0,
    step_reruns=0, recovered_attempts=5, valid_outputs=100, model_calls=110, valid_rate=1.0, kills=10,
    kills_in_flight=5, interrupted_workflows=10, unexpected_exits=0, failed_workflows=0,
    reconcile_reenqueued=0, reconcile_applied=0, workflows=100, open_workflows=0, timed_out=False,
    elapsed_s=60.0, model="test", workers=4, kill_every_s=3.0,
)


def test_pass_bar_needs_kills_that_interrupted_work() -> None:
    assert pass_bar_failures(PASSING) == []
    assert pass_bar_failures(replace(PASSING, recovered_attempts=0)) == [
        "recovered_attempts >= 1 (no kill interrupted in-flight work)"
    ]
    assert "kills >= 1 (no worker was killed)" in pass_bar_failures(replace(PASSING, kills=0, recovered_attempts=0))
    assert pass_bar_failures(replace(PASSING, duplicated=1)) == ["duplicated == 0"]


def test_chaos_small_run(pg_url: str, tmp_path: Path) -> None:
    report = run_chaos(
        tasks=20, workers=3, kill_every_s=2, model="test", timeout_s=180,
        database_url=pg_url, model_delay_s=MODEL_DELAY_S, seed=SEED, log_dir=tmp_path,
    )
    print(report)
    assert not report.timed_out, report
    assert report.lost == 0, report
    assert report.done == report.tasks == 20, report
    assert report.duplicated == 0, report
    assert report.duplicate_results == 0, report
    assert report.extra_workflows == 0, report
    # extra_workflows is only meaningful if the workflow listing found every attempt.
    assert report.workflows == report.tasks and report.open_workflows == 0, report
    assert report.unexpected_exits == 0, report
    assert report.kills >= 3, report
    # Non-vacuous: at least one attempt was interrupted by a kill and finished on another
    # worker process (its step_runs / model_calls rows come from two processes).
    assert report.recovered_attempts >= 1, report
    assert report.valid_outputs == 20 and report.valid_rate == 1.0, report
