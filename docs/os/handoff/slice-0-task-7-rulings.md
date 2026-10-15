# Task 7 context and controller rulings (binding; read after the brief)

Where this fits: PAI OS Slice 0, last task. Task 6 built the core loop in `backend/spikes/spike3/loop.py`
(read it fully, plus `schema.sql`, `README.md`, `tests/os/test_spike3_loop.py`, `tests/os/conftest.py`).
Task 7 proves it survives random SIGKILLs of worker processes.

## Existing interfaces (loop.py, Task 6 — keep its tests green)
- `start(database_url, system_database_url, schema, model)`, `shutdown()`, `apply_schema(conn)`,
  `mark_ready(conn, task_id)`, `enqueue_pending(conn) -> int`, `reconcile(conn) -> dict[str,int]`,
  `workflow_id(task_id, attempt) -> "task:attempt"`, `build_agent(model)`, `register`, `launch`, `dbos_config`.
- Queue name `spike3`; workflow name `spike3.run_attempt`; tables in schema `spike3`.
- Retry rules (invariant 7) and idempotent writes (invariant 8) must not change.

## Rulings (R1–R9)
R1 Executor ids. Each worker *slot* i has a stable executor id `spike3-w{i}` (set `DBOS__VMID` or
   `executor_id` in config). When the driver SIGKILLs the worker in slot i it starts the replacement in the
   SAME slot with the SAME executor id, so DBOS startup recovery re-enqueues the dead worker's PENDING
   workflows (DBOS 3.2.0 `_recovery.py` re-enqueues into its internal queue; exactly one runner dequeues).
   Never share one id across live workers (the default "local" would make every new worker recover
   workflows still running on live workers). Each worker *process* also gets a unique label
   `w{i}g{generation}` (env `SPIKE3_WORKER`) used for measurement (R5).
R2 The driver never executes workflows. It is the kernel side: it uses `dbos.DBOSClient`
   (system DB) to enqueue and to read workflow status, not a launched DBOS (a launched DBOS always
   dequeues DBOS's internal recovery queue, even with listen_queues). Add an optional
   `client: DBOSClient | None = None` parameter to `loop.enqueue_pending` and `loop.reconcile`
   (None = current in-process behaviour, so Task 6 tests stay unchanged). Client enqueue uses
   queue `spike3`, workflow name `spike3.run_attempt`, workflow id `task:attempt`.
R3 Same application version everywhere: set `application_version` (e.g. "spike3") in `loop.dbos_config`
   so client-enqueued workflows and recovered ones are dequeued by every worker.
R4 `loop.reconcile` maps terminal non-SUCCESS workflow statuses (ERROR, CANCELLED,
   MAX_RECOVERY_ATTEMPTS_EXCEEDED) of an open task to `failed` with reason `workflow_error`
   (use FAIL_TASK_SQL; count it as `failed_workflows`). Otherwise these tasks would count as lost.
   Add tests for this in `tests/os/test_spike3_loop.py`.
R5 Duplicates. `results` rows cannot duplicate (PK), so report it but do not rely on it. Add a nullable
   `worker text` column to `spike3.step_runs` and `spike3.model_calls` (schema.sql must stay idempotent:
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`), filled from env `SPIKE3_WORKER` (NULL when unset, e.g.
   in Task 6 tests). Metrics:
   - `step_reruns`: step_runs rows beyond one per (task, attempt, step). Expected > 0 under chaos.
   - `duplicated`: re-runs of a (task, attempt, step) whose earlier run was by a worker process that was
     NOT killed (a kill is the only legitimate cause of a re-run). Must be 0.
   - `extra_workflows`: tasks with more than one attempt / more than one workflow id. Must be 0
     (the driver calls mark_ready once per task).
   - `duplicate_results`: as in the brief.
R6 Non-vacuous chaos. The `test` model must be slow enough that kills hit in-flight work: a pydantic-ai
   `FunctionModel` that sleeps a configurable delay (default about 0.5 s; worker flag `--model-delay`)
   and returns a ProgrammeFact whose `quote` is copied from the page inside the prompt (so it is valid for
   every page). Limit concurrency per worker (queue `worker_concurrency`, e.g. 2) so work spans the kill
   window. The CI test asserts `lost == 0`, `duplicated == 0`, `duplicate_results == 0`,
   `extra_workflows == 0`, `kills >= 3`, `done == tasks`, AND `step_reruns >= 1` or another recovery
   signal proving at least one attempt was interrupted and recovered.
R7 Report fields: keep every field the brief lists; add `duplicated`, `extra_workflows`,
   `failed_workflows` (and anything else needed) — extra fields are fine.
R8 The `chaos` marker: register it in `backend/pytest.ini` but do NOT exclude it from the default run
   (the brief says "small run in CI"). The test must use its own DBOS system schema (e.g. `dbos_chaos`)
   and reset it plus the spike3 tables, so it does not depend on test order. Clean up all worker
   subprocesses on every exit path (no orphans after a failure or timeout).
R9 The real OpenAI run (Step 4) is NOT run by you: there is no key here, and it is billed. Implement and
   CLI-test `--model openai` wiring only as far as possible without a key (e.g. it fails fast with a clear
   message when `OS_OPENAI_API_KEY` is unset). Run the CLI with `--model test` at a medium size
   (e.g. 100 tasks, 4 workers, kill every 3 s) and put those numbers in the report as a rehearsal.
   The report (Step 5) has the pass bar, the rehearsal numbers, the exact command for the user's
   OpenAI run, empty slots for its numbers and cost, and verdict "PENDING the OpenAI run" — never
   claim PASS for the OpenAI bar.
Other: update `backend/spikes/spike3/README.md` with how to run the chaos test and CLI. Files outside
the brief you may touch: loop.py, schema.sql, README.md, test_spike3_loop.py, pytest.ini.
Nothing in `backend/app/` changes. No secrets anywhere.

## Environment
- Postgres 16 is running: `OS_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/os_test`
  (if it is down: `su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/os-pg/data -l /var/tmp/os-pg/log -o '-p 5433 -k /tmp' -w start"`).
- Run from `backend/`: `tach check` and `OS_TEST_DATABASE_URL=... python -m pytest tests/os -v -rs`.
- CI runs Python 3.12 (local is 3.13): no 3.13-only syntax.
- Branch `os/s0-t7-spike3-chaos` is checked out (from pai-os da38f02). Commit there; do not push.
