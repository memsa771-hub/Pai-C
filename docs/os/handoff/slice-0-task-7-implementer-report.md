# Task 7 report: Spike 3 chaos run and report

Status: DONE_WITH_CONCERNS (the concerns are minor; see the end)

Branch `os/s0-t7-spike3-chaos`, not pushed.
- `cb85e6d` spike(os): spike 3 loop: DBOSClient kernel side, worker labels, workflow_error reconcile
- `8e5cc78` spike(os): spike 3 chaos run and report

## What was implemented

**loop.py (rulings R1–R4)**
- `enqueue_pending(conn, client=None)` and `reconcile(conn, client=None)`: with a `DBOSClient`, the
  enqueue goes through `client.enqueue({queue_name: "spike3", workflow_name: "spike3.run_attempt",
  workflow_id: "task:attempt", app_version: "spike3"}, task_id, attempt)` and status is read with
  `client.list_workflows(workflow_ids=[...])`. `None` keeps the Task 6 in-process path unchanged.
- `dbos_config(..., executor_id=None)` sets `application_version: "spike3"` and `executor_id`.
  `launch(worker_concurrency=None)` and `start(..., executor_id=None, worker_concurrency=None)` are new
  optional parameters.
- R4: `reconcile` maps ERROR, CANCELLED and MAX_RECOVERY_ATTEMPTS_EXCEEDED of an open task to
  `failed`/`workflow_error` through `FAIL_TASK_SQL`, counted as `failed_workflows`.
- R5: `step_runs` and `model_calls` rows carry `worker_label()` (env `SPIKE3_WORKER`; NULL in-process).

**schema.sql**: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS worker text` on `step_runs` and
`model_calls`. It stays idempotent.

**worker.py**: `main()` reads settings (`OS_DATABASE_URL`, also used as the system DB, and
`OS_DBOS_SYSTEM_SCHEMA`), builds the model, calls `loop.start(...)` (DBOS configured as in Task 6, plus
an executor ID per slot and `worker_concurrency` 2), then blocks until SIGTERM/SIGINT or until the
driver PID (`SPIKE3_DRIVER_PID`) is no longer its parent, and finally runs `loop.shutdown()`.
- `--model test`: a `FunctionModel` that sleeps `--model-delay` (default 0.5 s) and returns a
  ProgrammeFact whose quote is the page's "Language requirements:" line, taken from the `<page>` in
  the prompt (R6).
- `--model openai`: uses `loop.openai_model(settings)`, and exits at once with a clear message when
  `OS_OPENAI_API_KEY` is unset (R9).

**chaos.py**: `run_chaos(tasks, workers, kill_every_s, model, timeout_s, *, database_url=None,
schema="dbos_chaos", model_delay_s=0.5, worker_concurrency=2, reconcile_every_s=5.0, seed=None,
log_dir=None) -> ChaosReport`, plus a CLI. The run goes like this:
1. Drop the DBOS schema (the name must start with `dbos_chaos`), apply and truncate the spike3 tables.
2. Start workers. The driver is a `DBOSClient` only (R2). It waits until a worker has migrated DBOS
   and registered the queue.
3. `mark_ready` each task once, then `enqueue_pending(client=...)`.
4. Until no task is open: restart unexpectedly exited workers. Every `kill_every_s`, record the slot's
   PENDING workflows, SIGKILL it, wait, record the database time, and start the replacement in the
   same slot with the same executor ID (R1). Every 5 s, run `reconcile(client=...)`.
5. Wait for the workflows to drain, stop the workers (SIGTERM, then SIGKILL after 15 s), and measure.

`ChaosReport` has every brief field (`tasks`, `done`, `failed`, `lost`, `duplicate_results`,
`step_reruns`, `valid_outputs`, `model_calls`, `valid_rate`, `kills`, `elapsed_s`), plus
`duplicated`, `extra_workflows`, `failed_workflows` (R7), `recovered_attempts`, `kills_in_flight`,
`interrupted_workflows`, `unexpected_exits`, `reconcile_reenqueued`, `reconcile_applied`,
`workflows`, `open_workflows`, `timed_out`, `model`, `workers`, `kill_every_s` and `log_dir`.
The CLI prints JSON and `pass bar: PASS|FAIL (...)`, and exits 1 on FAIL.

**Metrics (R5)**
- `duplicated` is time-aware. A step_runs re-run, or a model request followed by one from another
  process, counts as a duplicate unless the earlier row's worker was SIGKILLed before the re-run row
  was written. Kill times come from the DB clock, taken after the process was reaped.
- `extra_workflows` = tasks with `attempt <> 1` ∪ tasks with more than one `run_attempt` workflow ID.
- `recovered_attempts` = attempts whose rows come from more than one worker label. This is the
  non-vacuous recovery signal.

**Other files**
- `pytest.ini`: registers the `chaos` marker. It is not excluded from the default run (R8).
- README: a chaos section with the design, the metric table and run commands.
- `docs/os/spikes/spike3-report.md`: the pass bar, method, CI runs, rehearsal, negative control, the
  OpenAI command with empty slots and cost, verdict "PENDING the OpenAI run" (R9), and the sign-off table.

## TDD evidence

RED:
```
$ python -m pytest tests/os/test_spike3_chaos.py tests/os/test_spike3_loop.py -q
E   ModuleNotFoundError: No module named 'spikes.spike3.chaos'
$ python -m pytest tests/os/test_spike3_loop.py -q -p no:logging
E       TypeError: reconcile() got an unexpected keyword argument 'client'   (x3, parametrized)
E       KeyError: 'failed_workflows'                                          (real ERROR workflow test)
4 failed, 5 passed
```
(The real-ERROR test had already passed its ERROR-status and `model_calls == 3` assertions before it
reached the missing key. That confirms the test reaches the reconcile path.)

GREEN: loop tests `9 passed`. Then the chaos test passed on its first run, but with `kills=3`, exactly
at the threshold. I set `model_delay_s=1.5` and `log_dir=tmp_path` in the test for margin.

## Chaos test: three consecutive runs (final code)

```
run 1: done=20 lost=0 duplicated=0 duplicate_results=0 extra_workflows=0 kills=6 kills_in_flight=5 recovered_attempts=6 model_calls=26 elapsed=17.6s PASSED
run 2: done=20 lost=0 duplicated=0 duplicate_results=0 extra_workflows=0 kills=7 kills_in_flight=5 recovered_attempts=6 model_calls=26 elapsed=19.0s PASSED
run 3: done=20 lost=0 duplicated=0 duplicate_results=0 extra_workflows=0 kills=7 kills_in_flight=6 recovered_attempts=6 model_calls=26 elapsed=19.9s PASSED
orphans after: 0
```
Three earlier runs on the near-final code had kills of 7, 8 and 11. The test also passes when run
after the loop tests, and it skips without `OS_TEST_DATABASE_URL`.

## Rehearsal (R9; CLI, test model)

`python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model test --timeout 1800 --seed 7`
- Default delay 0.5 s: done 100, lost 0, duplicated 0, duplicate_results 0, extra_workflows 0,
  step_reruns 0, recovered_attempts 2, model_calls 102, valid_rate 1.0, kills 5, kills_in_flight 1,
  elapsed 22.0 s. PASS.
- `--model-delay 3`: done 100, lost 0, duplicated 0, duplicate_results 0, extra_workflows 0,
  step_reruns 0, recovered_attempts 29, model_calls 140, valid_rate 1.0, kills 28, kills_in_flight 20,
  interrupted_workflows 40, elapsed 92.4 s. PASS.

Negative control (not committed): all workers used executor ID `local`. Result: `duplicated=9`,
`model_calls=78` for 20 tasks, CLI FAIL. This proves the duplicate metric can fire. The first version
of the metric read 0 here, because almost every worker was eventually killed. That is why the metric
became time-aware.

Without a key, `--model openai` gives `chaos.py: error: model 'openai' needs OS_OPENAI_API_KEY (the dev
key); it is not set` (exit 2). The worker alone exits 1 with the same message.

## Full suite + tach (from backend/)

```
$ tach check
✅ All modules validated!
$ OS_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/os_test python -m pytest tests/os -v -rs
...
tests/os/test_spike3_chaos.py::test_chaos_small_run PASSED
tests/os/test_spike3_loop.py::test_happy_path PASSED
tests/os/test_spike3_loop.py::test_record_result_is_idempotent PASSED
tests/os/test_spike3_loop.py::test_enqueue_twice_runs_once PASSED
tests/os/test_spike3_loop.py::test_reconciler_and_enqueuer_race PASSED
tests/os/test_spike3_loop.py::test_invalid_quote_is_retried_then_fails PASSED
tests/os/test_spike3_loop.py::test_reconcile_fails_task_whose_workflow_ended_without_success[ERROR] PASSED
tests/os/test_spike3_loop.py::test_reconcile_fails_task_whose_workflow_ended_without_success[CANCELLED] PASSED
tests/os/test_spike3_loop.py::test_reconcile_fails_task_whose_workflow_ended_without_success[MAX_RECOVERY_ATTEMPTS_EXCEEDED] PASSED
tests/os/test_spike3_loop.py::test_reconcile_fails_task_of_errored_workflow PASSED
============================= 56 passed in 53.19s ==============================
```
No warnings. All five files compile with Python 3.12 (`/usr/bin/python3.12 -m py_compile`).
`ruff check` (E, F, W, I) is clean on the new files.

## Files changed

- `backend/spikes/spike3/chaos.py` (new)
- `backend/spikes/spike3/worker.py` (new)
- `backend/tests/os/test_spike3_chaos.py` (new)
- `docs/os/spikes/spike3-report.md` (new)
- `backend/spikes/spike3/loop.py`
- `backend/spikes/spike3/schema.sql`
- `backend/spikes/spike3/README.md`
- `backend/tests/os/test_spike3_loop.py`: `_run_dbos` now takes a model, and the existing fixtures pass
  the same `TestModel`s as before, so behaviour is unchanged. Added the R4 tests.
- `backend/pytest.ini`

Nothing in `backend/app/` changed.

## Self-review

- **Orphans**: checked on every path.
  - Normal end: SIGTERM, and the logs show "DBOS successfully shut down".
  - Timeout (`timeout_s=8`): `timed_out=True`, 0 workers left.
  - Exception mid-run (reconcile raising): 0 left.
  - Driver SIGKILLed at 1.2 s, 4.5 s and 10 s: 0 left after 8 s.
  - The 1.2 s case found a real bug: a worker still importing recorded the reaper as its parent. It is
    fixed with `SPIKE3_DRIVER_PID`.
- **Non-vacuous**: the test asserts `recovered_attempts >= 1`, which means rows from two processes
  for one attempt. Every run had 6 or more, plus 5 or more kills of workers with PENDING workflows.
  The negative control proves `duplicated` detects real duplicates.
- **Task 6 behaviour**: the in-process paths are unchanged. `application_version` is now fixed to
  "spike3" for Task 6 too, which is harmless because `dbos_test` is reset per session.
- **Secrets**: none. The OpenAI run was not attempted.

## Concerns

1. `step_reruns` was 0 in every run. The kills land in the seconds-long model step, not in the
   millisecond DB steps, so recovery shows as model re-requests and `recovered_attempts`. The test
   therefore uses `recovered_attempts >= 1` as R6's "another recovery signal" and does not assert
   `step_reruns >= 1`. The report explains this.
2. The CI test passes `model_delay_s=1.5`, not the CLI default of 0.5 s. At 0.5 s, 20 tasks finish
   with only about 3 kills, which is too close to the `kills >= 3` assertion. The brief's five
   arguments are unchanged; the delay is an extra keyword argument.
3. `kills_in_flight` counts PENDING workflows under the slot's executor ID at kill time. Right after a
   restart, those can still belong to the previous dead generation, before startup recovery re-enqueues
   them, so this count is approximate. `recovered_attempts` and `duplicated` are exact.
4. chaos.py is about 440 lines, larger than a minimal spike, mostly SQL metrics and process management.
5. The CLI writes worker logs to a new temp directory per run and does not delete it. The path is in
   the report as `log_dir`.

---

# Fix round 1

Commit: `a9e6dd7` spike(os): spike 3 chaos review fixes (on top of `8e5cc78`; not pushed).

## Changes per finding

- **I1**: `pass_bar_failures` now also requires `"kills >= 1 (no worker was killed)"` and
  `"recovered_attempts >= 1 (no kill interrupted in-flight work)"`. New test
  `test_pass_bar_needs_kills_that_interrupted_work` (no DB needed) checks four cases on a hand-built
  `ChaosReport`:
  - a passing report gives `[]`;
  - `recovered_attempts=0` gives exactly the recovered_attempts failure;
  - `kills=0` includes the kills failure;
  - `duplicated=1` gives `["duplicated == 0"]`.

  Also checked through the CLI: `--kill-every 600` printed
  `pass bar: FAIL (kills >= 1 (no worker was killed), recovered_attempts >= 1 (no kill interrupted in-flight work))`
  and exited 1.
- **M1**: the CI test asserts `report.workflows == report.tasks and report.open_workflows == 0`.
- **M2** (no code change): the report (under the measurement table) and the README state that a legal
  same-process DBOS step retry is counted in `duplicated`. That can only give a false FAIL, never a
  false PASS. They also say how to tell the cases apart: a legal retry has the same `worker` label on
  both rows, and DBOS's `Step being automatically retried` warning with the exception appears in
  `<log_dir>/<label>.log`. I verified the message text in `dbos/_core.py:2270`.
- **M3**: the report now gives the measured numbers (`model_calls = 140`, `recovered_attempts = 29`,
  `interrupted_workflows = 40`) and says they are consistent but not an exact accounting, and why.
  "each exactly once" became "one result per task".
- **M4**: `worker.py --executor-id` is required. Without it you get
  `worker.py: error: the following arguments are required: --executor-id`.
- **M5**: the CI test passes `seed=7`. The seed fixes which slots are killed; timing still varies, as
  noted in the report.
- **M6**: the new `validate_args(model, schema)` raises `ValueError`. `run_chaos` calls it first, and
  the CLI calls it before the run, turning only its errors into `parser.error`. The run itself is no
  longer wrapped in `except ValueError`. Both the openai-without-key and the bad-schema cases still
  give clean usage errors.
- **M7**: done, as a clean move. A `_RunState` dataclass holds what the loop observes (kills and their
  DB times, kills in flight, interrupted workflows, unexpected exits, reconcile counts, timed_out,
  open_workflows), and `_measure(conn, client, state, ...)` builds the `ChaosReport`. `run_chaos`
  only runs the loop.
- **M8**: `SPIKE3_TABLES` lives in `loop.py`, and both `chaos.py` and `test_spike3_loop.py` use
  `loop.SPIKE3_TABLES`.
- **M9**: `DEFAULT_MODEL_DELAY_S` is 1.5 (worker and CLI), and the README says so. The report states
  the delay each rehearsal used (`--model-delay 0.5`, the default at the time, and `--model-delay 3`)
  and that both still meet the current pass bar (recovered_attempts 2 and 29). I did not re-run the
  rehearsals, because the quoted numbers are still correct for their stated delays.
- **M10**: after a passing CLI run the temp log directory is removed. On FAIL or timeout it is kept,
  and `worker logs kept in <dir>` is printed. Checked: the PASS run's directory was gone, and the
  no-kill FAIL run kept `w0g0.log` and `w1g0.log`.
- **M11**: `_Workers.start` closes the log file if `Popen` raises (`except BaseException: log.close(); raise`).

## Commands and output

Covering tests, run twice (`-s` to show the reports):
```
$ OS_TEST_DATABASE_URL=... python -m pytest tests/os/test_spike3_chaos.py tests/os/test_spike3_loop.py -v -rs
run 1: ChaosReport(... done=20, lost=0, duplicated=0, duplicate_results=0, extra_workflows=0, recovered_attempts=8, kills=8, kills_in_flight=6, workflows=20, open_workflows=0, elapsed_s=21.2 ...)
       ============================= 11 passed in 33.99s ==============================
run 2: ChaosReport(... done=20, lost=0, duplicated=0, duplicate_results=0, extra_workflows=0, recovered_attempts=4, kills=12, kills_in_flight=8, workflows=20, open_workflows=0, elapsed_s=29.2 ...)
       ============================= 11 passed in 41.71s ==============================
orphans: 0
```
Full suite and tach:
```
$ tach check
✅ All modules validated!
$ OS_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/os_test python -m pytest tests/os -v -rs
tests/os/test_spike3_chaos.py::test_pass_bar_needs_kills_that_interrupted_work PASSED
tests/os/test_spike3_chaos.py::test_chaos_small_run PASSED
tests/os/test_spike3_loop.py::... (9 tests) PASSED
============================= 57 passed in 45.18s ==============================
orphans: 0
```
Other checks:
- Python 3.12 `py_compile` passes for chaos.py, worker.py and test_spike3_chaos.py.
- `ruff check --select E,F,W,I` from backend/ reports only E702 (`;` one-liners) in
  test_spike3_loop.py. That is the Task 6 test file's existing style, which my R4 test follows. CI
  runs no linter.
- I removed the temp log directories left in /tmp by my earlier CLI runs.

---

# Fix round 2 (re-review follow-ups)

Commit: `2256b45` spike(os): spike 3 chaos CLI prints kept log dir on a crash.

1. `main()` now creates the temp log directory itself and passes it to `run_chaos`. If the run raises,
   main prints `chaos run crashed; worker logs kept in <dir>` to stderr and re-raises. Checked with
   workers given an invalid `--executor-id`, which makes them exit during startup. Output:
   `chaos run crashed; worker logs kept in /tmp/spike3-chaos-qthdceie`, then
   `RuntimeError: worker w0g0 exited during startup; see .../w0g0.log`, and that log held the worker's
   usage error. No worker processes were left.
2. `assert client is not None` is back at the `_measure` call site, so the `DBOSClient | None` type is
   narrowed before the call.

Tests:
- `tests/os/test_spike3_chaos.py`: 2 passed.
- `tach check`: All modules validated.
- `tests/os`: 57 passed.
- No worker processes left; chaos.py compiles under Python 3.12.
