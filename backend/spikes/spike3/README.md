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
