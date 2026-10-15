# Spike 3 report: core loop under random worker kills

**Verdict: PENDING the OpenAI run.** The harness, the CI chaos test and a 100-task rehearsal with
the test model all pass. The pass bar is defined for the real model, so this report cannot say PASS
until the OpenAI run below is done and its numbers are filled in. No Slice 1 work starts before then.

Code: `backend/spikes/spike3/` (`loop.py` from Task 6; `chaos.py` and `worker.py` from Task 7).
How to run everything: `backend/spikes/spike3/README.md`.

## Pass bar

100 task runs with random worker kills (SIGKILL):

- zero lost tasks (`lost == 0`);
- zero duplicated work or results (`duplicated == 0`, `duplicate_results == 0`, `extra_workflows == 0`);
- at least 99% valid structured outputs (`valid_rate >= 0.99`).

The CLI checks these itself and prints `pass bar: PASS` or `pass bar: FAIL (...)` (exit code 1 on FAIL).
It also fails a run that timed out.

## Method

- **Driver = kernel side.** `chaos.py` never executes workflows. It talks to DBOS only through a
  `DBOSClient`: it enqueues (`enqueue_pending(conn, client=...)`), reads workflow status, and runs
  `reconcile(conn, client=...)` every 5 s (5 minutes in production).
- **Workers.** `python -m spikes.spike3.worker --model {test|openai}` configures DBOS as Task 6 does,
  launches and polls the `spike3` queue with `worker_concurrency` 2.
- **Kills.** Every `--kill-every` seconds the driver SIGKILLs the worker in a random slot, waits until
  it is gone, and starts the replacement in the same slot. Slot `i` always has DBOS executor ID
  `spike3-w{i}`, so the replacement's DBOS recovers the workflows its predecessor left `PENDING`. Each
  process also has a label `w{i}g{generation}` that is written to `step_runs.worker` and
  `model_calls.worker`.
- **Same application version** (`spike3`) in every process, so every worker dequeues every workflow,
  including recovered ones.
- **Reconcile** fails an open task with `workflow_error` when its workflow ended as ERROR, CANCELLED or
  MAX_RECOVERY_ATTEMPTS_EXCEEDED. Without this, such a task would count as lost.
- **Test model.** A `FunctionModel` waits `--model-delay` seconds and answers with a quote copied from
  the page in the prompt. The delay makes kills land on in-flight model requests.

### What is measured (`ChaosReport`)

| Field | Meaning |
|---|---|
| `tasks`, `done`, `failed`, `lost` | `lost` = tasks − done − failed |
| `duplicated` | re-runs not explained by an earlier kill: a spike step run again, or a model request repeated by another process, when the first run's worker had not been killed before the re-run started (kill time read from the database clock) |
| `duplicate_results` | `results` rows beyond one per task attempt. This is 0 by the primary key, but measured anyway. |
| `extra_workflows` | tasks with more than one attempt or more than one DBOS workflow ID |
| `step_reruns` | `step_runs` rows beyond one per (task, attempt, step) |
| `recovered_attempts` | attempts whose rows were written by more than one worker process, meaning they were interrupted and then recovered |
| `valid_outputs`, `model_calls`, `valid_rate` | `valid_rate` = valid outputs / tasks |
| `kills`, `kills_in_flight`, `interrupted_workflows` | kills; kills of a worker that had `PENDING` workflows at that moment; how many such workflows there were |
| `failed_workflows`, `reconcile_reenqueued`, `reconcile_applied` | what `reconcile` repaired |
| `unexpected_exits` | workers that exited without being killed (they are restarted in place) |
| `workflows`, `open_workflows`, `timed_out`, `elapsed_s` | how the run ended |

## Results

Environment: Postgres 16.15, Python 3.13 locally (CI uses 3.12), DBOS 3.2.0, pydantic-ai 2.55.0.

### CI chaos test (`tests/os/test_spike3_chaos.py`, marker `chaos`, part of the default suite)

The test runs 20 tasks with 3 workers, a kill every 2 s, the test model at 1.5 s and a 180 s timeout.
It asserts `lost == 0`, `done == 20`, `duplicated == 0`, `duplicate_results == 0`,
`extra_workflows == 0`, `unexpected_exits == 0`, `kills >= 3`, `recovered_attempts >= 1` and a
`valid_rate` of 1.0. These are three consecutive runs on the final code:

| Run | done | lost | duplicated | dup. results | extra wf | kills | in flight | recovered attempts | model calls | elapsed |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 0 | 0 | 0 | 0 | 6 | 5 | 6 | 26 | 17.6 s |
| 2 | 20 | 0 | 0 | 0 | 0 | 7 | 5 | 6 | 26 | 19.0 s |
| 3 | 20 | 0 | 0 | 0 | 0 | 7 | 6 | 6 | 26 | 19.9 s |

### Rehearsal: 100 tasks, test model (not the pass-bar run)

`python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model test --timeout 1800 --seed 7`

| Field | Model delay 0.5 s (default) | Model delay 3 s (`--model-delay 3`, closer to real latency) |
|---|---|---|
| tasks | 100 | 100 |
| done | 100 | 100 |
| failed | 0 | 0 |
| lost | 0 | 0 |
| duplicated | 0 | 0 |
| duplicate_results | 0 | 0 |
| extra_workflows | 0 | 0 |
| step_reruns | 0 | 0 |
| recovered_attempts | 2 | 29 |
| valid_outputs | 100 | 100 |
| model_calls | 102 | 140 |
| valid_rate | 1.0 | 1.0 |
| kills | 5 | 28 |
| kills_in_flight | 1 | 20 |
| interrupted_workflows | 2 | 40 |
| unexpected_exits | 0 | 0 |
| failed_workflows | 0 | 0 |
| reconcile_reenqueued | 0 | 0 |
| reconcile_applied | 0 | 0 |
| workflows | 100 | 100 |
| open_workflows | 0 | 0 |
| timed_out | false | false |
| elapsed_s | 22.0 | 92.4 |
| pass bar (CLI) | PASS | PASS |

With a 0.5 s model the 100 tasks finish in about 15 s, so only 5 kills happen and 1 of them hits
work. The 3 s run is the meaningful rehearsal: 20 of 28 kills hit in-flight work, and 40
interrupted workflows were recovered. All 100 tasks finished, each exactly once.

### Negative control: the measurement catches duplicates

To check that `duplicated` is not vacuous, the CI-sized run was repeated once with a deliberate bug:
every worker used the same executor ID (`local`, the DBOS default). Each new worker then "recovers"
workflows that are still running on live workers, so the same attempt runs on two processes at once.
Result: `duplicated = 9`, `model_calls = 78` for 20 tasks, and CLI verdict FAIL (`duplicated == 0`).
This setup is not part of the code. It shows why R1 (one stable executor ID per worker slot) is required.

### Observed step re-runs

`step_reruns` was 0 in every run. The spike steps (`load_page`, `record_result`, `complete_task`) are
millisecond database writes, while the model step takes seconds, so the kills landed in the model
step. Those re-runs show up as model requests instead: in the 3 s rehearsal, `model_calls = 140` =
100 needed + 40 re-run after the 40 interrupted workflows were recovered. Every one of them came
after the kill of the worker that started it (`duplicated = 0`). A kill between a step's `step_runs`
insert and its DBOS checkpoint would re-run that step. That is safe because every write a step makes
is idempotent (invariant 8), but this run did not hit that window.

### Failures and their causes

There were no loop failures in the final runs: no lost task, no duplicate, no ERROR workflow, and no
unexpected worker exit. Two harness problems were found and fixed during development:

1. The first `duplicated` metric counted a re-run as legitimate when the first run's worker was killed
   at any point, even after the re-run. Under heavy kills nearly every worker is killed at some point,
   so the negative control read 0. The metric now requires the kill to come before the re-run.
2. A worker that was still importing when the driver died recorded the reaper as its parent, and it
   outlived the driver. The driver now passes its PID (`SPIKE3_DRIVER_PID`), and workers exit within
   about 0.5 s of the driver's death. Verified by SIGKILLing the driver at 1.2 s, 4.5 s and 10 s:
   no worker remained in any case. Timeout and exception paths also leave no worker processes.

## Pass-bar run: OpenAI (to be done by the developers)

This run is billed and needs the dev key, so it was not run while building the harness. Run it on
staging, or on a laptop with Postgres 16, from `backend/`:

```
OS_DATABASE_URL=postgresql://USER@HOST:PORT/DB OS_OPENAI_API_KEY=<dev key> \
    python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model openai --timeout 1800
```

It uses `OS_MODEL_CHEAP` (default `gpt-5.4-mini`). It drops and recreates schema `dbos_chaos` and
empties schema `spike3` in that database. Without the key it stops at once with a clear message.

Paste the printed JSON here:

| Field | Value |
|---|---|
| tasks | |
| done | |
| failed | |
| lost | |
| duplicated | |
| duplicate_results | |
| extra_workflows | |
| step_reruns | |
| recovered_attempts | |
| valid_outputs | |
| model_calls | |
| valid_rate | |
| kills | |
| kills_in_flight | |
| interrupted_workflows | |
| unexpected_exits | |
| failed_workflows | |
| workflows | |
| open_workflows | |
| timed_out | |
| elapsed_s | |
| CLI pass bar line | |

- Cost (from the OpenAI project's usage page, for the run's time window): ______
- Failures and their cause (from `failure_reason` in `spike3.tasks` and the worker logs in `log_dir`): ______
- Verdict against the pass bar: ______ (PASS / FAIL)

If it fails: stop, fix, re-run, and update this report. No Slice 1 work starts until this report says
PASS and both developers have signed it.

## Sign-off

| Developer | Verdict | Date |
|---|---|---|
| | | |
| | | |
