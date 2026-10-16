# Spike 3 report: core loop under random worker kills

**Verdict: PASS.** The harness, the CI chaos test, a 100-task rehearsal with the test model and the
100-task OpenAI pass-bar run below all pass. No Slice 1 work starts until both developers have signed
this report.

Code: `backend/spikes/spike3/` (`loop.py` from Task 6; `chaos.py` and `worker.py` from Task 7).
How to run everything: `backend/spikes/spike3/README.md`.

## Pass bar

100 task runs with random worker kills (SIGKILL):

- zero lost tasks (`lost == 0`);
- zero duplicated work or results (`duplicated == 0`, `duplicate_results == 0`, `extra_workflows == 0`);
- at least 99% valid structured outputs (`valid_rate >= 0.99`).

The CLI checks these itself and prints `pass bar: PASS` or `pass bar: FAIL (...)` (exit code 1 on FAIL).
It also fails a run that timed out, and a run without real chaos: the bar is about runs *with* kills,
so it needs `kills >= 1` and `recovered_attempts >= 1` (at least one kill interrupted in-flight work
that another process then finished).

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
- **Test model.** A `FunctionModel` waits `--model-delay` seconds (default 1.5) and answers with a quote
  copied from the page in the prompt. The delay makes kills land on in-flight model requests.

### What is measured (`ChaosReport`)

| Field | Meaning |
|---|---|
| `tasks`, `done`, `failed`, `lost` | `lost` = tasks − done − failed |
| `duplicated` | re-runs not explained by an earlier kill: a spike step run again, or a model request repeated by another process, when the first run's worker had not been killed before the re-run started (kill time read from the database clock). See the note below on step retries. |
| `duplicate_results` | `results` rows beyond one per task attempt. This is 0 by the primary key, but measured anyway. |
| `extra_workflows` | tasks with more than one attempt or more than one DBOS workflow ID |
| `step_reruns` | `step_runs` rows beyond one per (task, attempt, step) |
| `recovered_attempts` | attempts whose rows were written by more than one worker process, meaning they were interrupted and then recovered |
| `valid_outputs`, `model_calls`, `valid_rate` | `valid_rate` = valid outputs / tasks |
| `kills`, `kills_in_flight`, `interrupted_workflows` | kills; kills of a worker that had `PENDING` workflows at that moment; how many such workflows there were |
| `failed_workflows`, `reconcile_reenqueued`, `reconcile_applied` | what `reconcile` repaired |
| `unexpected_exits` | workers that exited without being killed (they are restarted in place) |
| `workflows`, `open_workflows`, `timed_out`, `elapsed_s` | how the run ended |

**`duplicated` and legal step retries.** A spike step that fails inside one process (for example a
transient database error) is retried by DBOS in that same process, as invariant 7 allows. That retry
writes a second `step_runs` row by a worker that was not killed, so `duplicated` counts it. The metric
can therefore produce a false FAIL, never a false PASS. To tell the two apart, look at the first
row's `worker` label in `spike3.step_runs` and open `<log_dir>/<label>.log`. A legal retry shows
DBOS's `Step being automatically retried` warning, with the exception, in that log, and the re-run row has the same `worker`
label. A real duplicate has a re-run row from a different label with no kill in between.

## Results

Environment: Postgres 16.15, Python 3.13 locally (CI uses 3.12), DBOS 3.2.0, pydantic-ai 2.55.0.

### CI chaos test (`tests/os/test_spike3_chaos.py`, marker `chaos`, part of the default suite)

The test runs 20 tasks with 3 workers, a kill every 2 s, the test model at 1.5 s, seed 7 and a 180 s
timeout. The seed fixes which slots are killed; timing still varies from run to run. The test asserts
`lost == 0`, `done == 20`, `duplicated == 0`, `duplicate_results == 0`, `extra_workflows == 0`,
`workflows == 20`, `open_workflows == 0`, `unexpected_exits == 0`, `kills >= 3`,
`recovered_attempts >= 1` and a `valid_rate` of 1.0. A second test checks that the pass bar fails a
run with no kills or no recovered attempts. These are three consecutive runs from the first
submission:

| Run | done | lost | duplicated | dup. results | extra wf | kills | in flight | recovered attempts | model calls | elapsed |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 0 | 0 | 0 | 0 | 6 | 5 | 6 | 26 | 17.6 s |
| 2 | 20 | 0 | 0 | 0 | 0 | 7 | 5 | 6 | 26 | 19.0 s |
| 3 | 20 | 0 | 0 | 0 | 0 | 7 | 6 | 6 | 26 | 19.9 s |

After the review fixes, with seed 7, two more runs gave kills 8 and 12, recovered attempts 8 and 4,
and `lost = duplicated = 0`, `workflows = 20` in both.

### Rehearsal: 100 tasks, test model (not the pass-bar run)

`python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model test --timeout 1800 --seed 7 --model-delay D`

Both rehearsals ran before the review changes. One used `D = 0.5` (the CLI default at the time; the
default is now 1.5 s), the other `D = 3` (closer to real model latency). Both still meet the current
pass bar, including `kills >= 1` and `recovered_attempts >= 1`.

| Field | `--model-delay 0.5` | `--model-delay 3` |
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
work. That is why the default is now 1.5 s. The 3 s run is the meaningful rehearsal: 20 of 28 kills
hit in-flight work, and 29 attempts were finished by a different process than the one that started
them. All 100 tasks finished with one result per task.

### Negative control: the measurement catches duplicates

To check that `duplicated` is not vacuous, the CI-sized run was repeated once with a deliberate bug:
every worker used the same executor ID (`local`, the DBOS default). Each new worker then "recovers"
workflows that are still running on live workers, so the same attempt runs on two processes at once.
Result: `duplicated = 9`, `model_calls = 78` for 20 tasks, and CLI verdict FAIL (`duplicated == 0`).
This setup is not part of the code. It shows why R1 (one stable executor ID per worker slot) is required.

### Observed step re-runs

`step_reruns` was 0 in every run. The spike steps (`load_page`, `record_result`, `complete_task`) are
millisecond database writes, while the model step takes seconds, so the kills landed in the model
step. Those re-runs show up as extra model requests instead. In the 3 s rehearsal we measured
`model_calls = 140` for 100 tasks (each needs one request with the test model), `recovered_attempts =
29` and `interrupted_workflows = 40`. These numbers are consistent, but they are not an exact
accounting. `interrupted_workflows` is approximate: it counts `PENDING` workflows under the killed
slot's executor ID, which can include workflows of an earlier dead generation not yet re-enqueued.
Also, an attempt can be interrupted more than once. What is exact is that every repeated request came
from a different process only after the earlier process had been killed (`duplicated = 0`). A kill between a step's `step_runs`
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

Run on 2026-10-16, model `gpt-5.4-mini` (`OS_MODEL_CHEAP`, default), local WSL2 Ubuntu 24.04,
Postgres 16 in Docker, Python 3.12.3.

| Field | Value |
|---|---|
| tasks | 100 |
| done | 100 |
| failed | 0 |
| lost | 0 |
| duplicated | 0 |
| duplicate_results | 0 |
| extra_workflows | 0 |
| step_reruns | 1 |
| recovered_attempts | 17 |
| valid_outputs | 100 |
| model_calls | 118 |
| valid_rate | 1.0 |
| kills | 12 |
| kills_in_flight | 10 |
| interrupted_workflows | 19 |
| unexpected_exits | 0 |
| failed_workflows | 0 |
| reconcile_reenqueued | 0 |
| reconcile_applied | 0 |
| workflows | 100 |
| open_workflows | 0 |
| timed_out | false |
| elapsed_s | 42.3 |
| model | openai |
| workers | 4 |
| kill_every_s | 3.0 |
| log_dir | /tmp/spike3-chaos-hx5a_zul |
| CLI pass bar line | `pass bar: PASS` |

- Cost: <fill from OpenAI usage page>
- Failures and their cause: none. All 100 tasks in `spike3.tasks` are `done` with no `failure_reason`.
  The one step re-run has `duplicated = 0`, so it came after a kill of the first run's worker.
- Verdict against the pass bar: PASS

If it fails: stop, fix, re-run, and update this report. No Slice 1 work starts until this report says
PASS and both developers have signed it.

## Sign-off

- [ ] @10Faheem
- [ ] @MusawirKtk

| Developer | Verdict | Date |
|---|---|---|
| | | |
| | | |
