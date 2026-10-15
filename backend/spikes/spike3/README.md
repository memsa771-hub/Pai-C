# Spike 3: core loop (throwaway)

**Throwaway code.** This folder is deleted after the Spike 3 report
(`docs/os/spikes/spike3-report.md`, Task 7) is accepted. Nothing in `app/` may import it.

## What it proves

The PAI OS core loop runs every task attempt exactly once, even when parts of it run twice:

```
kernel: mark_ready  ->  enqueue_pending  ->  DBOS queue  ->  run_attempt workflow
                                                              load_page
                                                              extract (Pydantic AI + DBOSDurability)
                                                              record_result
                                                              complete_task
```

- `mark_ready` sets the task `ready`, bumps `attempt` and writes an enqueue request, in one transaction.
- `enqueue_pending` enqueues each unsent request with workflow ID `"{task_id}:{attempt}"`. A second
  enqueue of the same ID (crash before `sent` was saved, or a race with the reconciler) is the same
  workflow, so it runs once.
- `reconcile` re-enqueues `ready` tasks that DBOS has never seen, and applies the result of
  workflows that succeeded while their task is still open.
- The agent uses the `DBOSDurability` capability, so each model request is a DBOS step of
  `run_attempt` itself. No child workflow is created.
- Every write a re-run step could repeat is idempotent: `results` has one row per task attempt
  (`ON CONFLICT DO NOTHING`), and status changes only apply to their own attempt while the task is open.
- `step_runs` (one row per step execution) and `model_calls` (one row per model request) are
  append-only, so re-runs can be counted.
- Retries follow invariant 7: the OpenAI client has `max_retries=0`; network/service retries are
  DBOS step retries (`retries_allowed=True, max_attempts=3`); answer repair is Pydantic AI output
  validation with 2 retries. The output validator rejects a `quote` that is not on the page. When
  output retries run out, the workflow records `failed` / `invalid_output` and returns normally.

Task 7 adds the chaos run (workers killed with SIGKILL) on top of these functions.

## Chaos run (Task 7)

`chaos.py` is the driver and `worker.py` is one worker process.

- The driver is the kernel side. It never executes workflows: it enqueues and reads workflow
  status through a `DBOSClient` (`enqueue_pending(conn, client=...)`, `reconcile(conn, client=...)`).
- Each worker (`python -m spikes.spike3.worker --model {test|openai}`) configures DBOS as Task 6
  does (`loop.start`), launches and blocks while DBOS polls the `spike3` queue (`worker_concurrency` 2).
- Worker slot `i` always has executor ID `spike3-w{i}`. Every `kill_every_s` the driver SIGKILLs a
  random worker, waits until it is gone, and starts its replacement in the same slot. On launch the
  replacement's DBOS recovers the workflows its predecessor left `PENDING` (they go back to the queue,
  and exactly one worker dequeues each). Each process also has a label `w{i}g{generation}`
  (env `SPIKE3_WORKER`), written to `step_runs.worker` and `model_calls.worker`.
- `reconcile` runs every 5 s during the run (5 minutes in production). It also fails an open task
  with `workflow_error` when its workflow ended as ERROR, CANCELLED or MAX_RECOVERY_ATTEMPTS_EXCEEDED.
- Every process uses application version `spike3`, so every worker dequeues every workflow.
- The `test` model is a `FunctionModel` that waits `--model-delay` seconds (default 1.5) and answers
  with a quote copied from the page, so kills hit in-flight model requests.
- Workers stop on SIGTERM, and on their own when the driver process is gone (no orphans).

What the report measures (`ChaosReport`):

| Field | Meaning | Pass bar |
|---|---|---|
| `lost` | tasks − done − failed | 0 |
| `duplicated` | re-runs not explained by an earlier kill: a step run again, or a model request repeated by another process, when the first run's worker was not killed before the re-run | 0 |
| `duplicate_results` | `results` rows beyond one per task attempt (0 by the primary key; measured anyway) | 0 |
| `extra_workflows` | tasks with more than one attempt or more than one workflow ID | 0 |
| `valid_rate` | valid outputs / tasks | ≥ 0.99 |
| `kills` | worker processes SIGKILLed | ≥ 1 |
| `recovered_attempts` | attempts whose rows come from more than one worker process (interrupted, then recovered) | ≥ 1 |
| `step_reruns` | `step_runs` rows beyond one per (task, attempt, step) | reported |
| `kills_in_flight`, `interrupted_workflows` | kills of a worker that had `PENDING` workflows; those workflows (approximate) | reported |

A run that timed out also fails.

`duplicated` also counts a legal same-process DBOS step retry (for example after a transient database
error; invariant 7), because the first run's worker was not killed. It can only cause a false FAIL,
never a false PASS. A legal retry has the same `worker` label on both `step_runs` rows, and the step's
exception appears with DBOS's `Step being automatically retried` warning in that worker's log (`<log_dir>/<label>.log`).

Run the small chaos test (20 tasks, 3 workers, a kill every 2 s; about 20 s):

```
OS_TEST_DATABASE_URL=postgresql://USER@HOST:PORT/DB python -m pytest tests/os/test_spike3_chaos.py -v -s
```

Run the CLI (prints the `ChaosReport` as JSON and PASS/FAIL against the pass bar; exit code 1 on FAIL):

```
OS_DATABASE_URL=postgresql://USER@HOST:PORT/DB \
    python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model test --timeout 1800
OS_DATABASE_URL=... OS_OPENAI_API_KEY=<dev key> \
    python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model openai --timeout 1800
```

Both are destructive for that database's `spike3` schema and for the DBOS schema they use
(`dbos_chaos` by default, `--schema` must start with `dbos_chaos`). Worker logs go to a temporary
directory whose path is in the report (`log_dir`). The CLI deletes it after a passing run, and keeps it
(and prints its path) after a failing or timed-out run. Workers need `--executor-id` (no default). `--model openai` stops at once with a clear message
when `OS_OPENAI_API_KEY` is not set.

## Run the tests

From `backend/`, with a Postgres 16 database:

```
OS_TEST_DATABASE_URL=postgresql://USER@HOST:PORT/DB python -m pytest tests/os/test_spike3_loop.py -v
```

The tests use `TestModel` (no API key, no cost). DBOS keeps its tables in schema `dbos_test`;
the spike tables live in schema `spike3` (`schema.sql`). Both schemas are reset once per test
session, and the spike tables are emptied before each test.

## Pages

`pages/` holds 5 short programme pages. Each task loads one of them (stable crc32 of the task ID).
The text is paraphrased, not copied, because DAAD text is copyrighted. It was checked against
the DAAD listings (DAAD International Programmes 2026/2027) on 2026-10-15.

| File | Programme | Source |
|---|---|---|
| `tum-informatics.txt` | TU Munich, Informatics (M.Sc.) | https://www2.daad.de/deutschland/studienangebote/international-programmes/en/detail/3607/ |
| `hfu-international-management.txt` | Furtwangen University, International Management (M.Sc.) | https://www2.daad.de/deutschland/studienangebote/international-programmes/en/detail/4297/ |
| `kiel-uas-computer-science.txt` | Kiel University of Applied Sciences, Computer Science (M.Sc.) | https://www2.daad.de/deutschland/studienangebote/international-programmes/en/detail/9058/ |
| `rptu-computer-science.txt` | RPTU Kaiserslautern-Landau, Computer Science (M.Sc.) | https://www2.daad.de/deutschland/studienangebote/international-programmes/en/detail/3629/ |
| `saarland-visual-computing.txt` | Saarland University, Visual Computing (M.Sc.) | https://www2.daad.de/deutschland/studienangebote/international-programmes/en/detail/3827/ |

## Notes

- The Task 6 brief named `DBOSAgent`. It is deprecated in pydantic-ai 2.55, so the spike uses its
  replacement, the `DBOSDurability` capability: the shape production code will use.
- The `model_calls` counter gets `(task_id, attempt)` from a contextvar that `run_attempt` sets from
  its own (checkpointed) arguments before the agent runs. Every execution of the workflow body,
  including recovery, sets it again before any model step.
