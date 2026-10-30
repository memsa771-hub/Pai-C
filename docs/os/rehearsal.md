# Rehearsal record (Slice 9a)

Rehearsal mode lets us run the whole OS on one machine, with a clock we control and no real AI or email. We use it to
rehearse 12 fictional students through a full intake cycle, and to let three of them be walked through in a browser at
phone width. It is off unless someone turns it on.

This file lists everything 9a adds, so that all of it can be found and removed. **Every 9a PR updates this file, and
reviewers check it** (spec S9-D8). One row per thing: what it is, where it lives, how it is switched on or off, and how
to remove it.

Only fictional, non-secret values belong here. Never put a key, token or real student data in this file.

Plain audit stamps written by the database (for example `sent_at`, `read_at`, `approved_at`, and a `created_at` that is not used in a rule) stay real time under a rehearsal offset. Anything the OS decides with time (daily limits, spend by month, freshness, the 24 hour swap window) uses the shared clock.

In rehearsal mode every `clock.now()` reads the offset with its own short database connection. A tick runs on whichever worker takes it from the queue, with that worker's tenant (one tenant per deployment).

## Settings

| item | where | on/off | how to remove |
|---|---|---|---|
| Rehearsal mode (`OS_REHEARSAL`) | `OsSettings.rehearsal` in `backend/app/os/settings.py` (same true words as `OS_ENABLED`: 1, true, yes, on). Set it on both the API and the worker. It is separate from `scripts/offline_startup_app.py`: with that entry point, set `OS_REHEARSAL` in the same environment as `OS_ENABLED` | Off by default. On: the shared clock reads the stored offset, the worker registers no cron schedules, the three admin calls below exist, and the API and worker log a WARNING containing "REHEARSAL MODE" at start. Off: real time and the calls answer 404; if the tenant still has an `os_rehearsal_clock` row, the API and worker refuse to start (`RehearsalDataLeft`): rehearsal data must not become a pilot database (an unreachable database at that moment is only logged) | Delete the field and `flag(env, "OS_REHEARSAL")` in `settings.py`, the `install_clock` calls in `app/os/api/services.py` and `app/os/runner/worker.py` `build`, the `if settings.rehearsal` branch in `build` (keep the `register_job` loop), and the `if get_services().settings.rehearsal` block in `app/os/api/router.py` |
| Offline AI (`OS_MODEL_MODE`) | `OsSettings.model_mode` in `backend/app/os/settings.py`: `openai` (default) or `offline`. Set it on the worker, and the same value on the API. `load_settings` raises `ModelModeError` (a `ValueError`) for any other value, for `offline` without `OS_REHEARSAL` on, and for `offline` without `OS_OFFLINE_ANSWERS_DIR`; the worker then stops at start, and so does the API when `OS_ENABLED` is on (`mount_os` in `app/os/api/mount.py` re-raises it instead of switching the OS off) | `openai` by default. `offline`: every agent (research, documents, writer, critic, supervisor) gets a Pydantic AI `FunctionModel` named `offline` that answers from the files below, no OpenAI key is needed (offline counts as "configured" in the four `register_*` functions of `app/os/runner/worker.py`; the `OS_TEST_*_MODEL` hooks still come first), runs record `model = "offline"` and cost 0, and research fetches no page (`OfflinePages`). Output validation still runs | Delete the two fields and their checks in `settings.py`, `model_for_spec` in `app/os/knowledge/research/readings.py` (call `model_for(settings, spec.tier)` again), the `model == OFFLINE_MODEL` test in `cost` (and its `model` argument at the four call sites), `_models_on` and the `OfflinePages` branch in `worker.py`, the `critic_model` argument of `build_agents` in `app/os/statements/agents.py`, the `except ModelModeError` branch in `app/os/api/mount.py`, and `app/os/agents/offline.py` |
| Offline answers folder (`OS_OFFLINE_ANSWERS_DIR`) | `OsSettings.offline_answers_dir` in `backend/app/os/settings.py`; read only by `offline_model` in `backend/app/os/agents/offline.py` (`<dir>/<agent id>.yaml`, read once when the worker builds its agents, so a missing file stops the worker) | Needed only with `OS_MODEL_MODE=offline`; point it at `backend/tests/os/rehearsal/answers` | With `OS_MODEL_MODE` above |
| Resend API key (`OS_RESEND_API_KEY`) | `OsSettings.resend_api_key` in `backend/app/os/settings.py`; used only by `ResendSender` in `backend/app/os/outbox/senders.py` | Needed only with `OS_EMAIL_SENDER=resend` (`load_settings` raises `ValueError` without it). Set by the owners on the worker; never in chat, logs, error messages or the repo. Tests use a fake key. **Rehearsals keep `OS_EMAIL_SENDER=log`**: no key, no real email | Delete the field and its check in `settings.py`, with the Resend sender (see Senders) |
| Email from address (`OS_EMAIL_FROM`) | `OsSettings.email_from` in `settings.py` | Needed only with `OS_EMAIL_SENDER=resend` | Same as above |
| Email allow-list (`OS_EMAIL_ALLOWLIST`) | `OsSettings.email_allowlist` in `settings.py`: comma-separated exact addresses, each stripped and lower-cased | Empty or unset means nobody: every message is `blocked`. A recipient is compared after `strip().lower()` | Same as above |
| Billed rehearsal (`--billed`) and its caps | `billed_env` in `backend/tests/os/rehearsal/run.py` (Task 12; spec 2.7, S9-D9, plan ruling 5). It needs `OS_OPENAI_API_KEY` (a budgeted key the owners set; never in chat, logs or the repo) and the four existing monthly caps, all set: `OS_RESEARCH_MONTHLY_USD=5`, `OS_DOCUMENTS_MONTHLY_USD=4`, `OS_STATEMENTS_MONTHLY_USD=4`, `OS_REPLAN_MONTHLY_USD=2` (USD; the caps are older settings, 9a only uses them). It then gives the in-process API and the worker `OS_MODEL_MODE=openai`, `OS_TENANT_ID=rehearsal-billed` and `OS_REHEARSAL=on`, and the driver seeds and checks that tenant. **The caps are monthly and follow rehearsal time** (`AgentRuns.month_spend` counts from the start of the clock's month), so a run that crosses rehearsal months could spend them again each month. The driver therefore has a whole-run guard (`_billed_stop` in `driver.py`), checked after every wait for the worker (after the starts, after each act round, after each tick): it stops the run once the tenant's whole spend reaches the caps' sum minus a margin of the larger of $1 and 20 % (**$12** for $15), when a wait times out (`worker_busy`: spend in flight unknown), or when the spend cannot be read (also a `billed_guard_error` failure). The stop is a safety stop, not a product failure: it is an admin step in the report (`billed_stop: <reason>`), the stopped students end in state `billed_stop`, and their events and `not_finished` are not checked | Off unless `--billed` is passed. It refuses to start (exit 2, the reason names the setting, never the key's value) without the key, with a cap missing, not a number or below 0, or when the four caps sum to more than $15. Unset caps would fall back to the defaults (20, 10, 10, 5), so it never runs without them. Only with the owners' OK (approved by the user on the owners' behalf on 2026-10-29; see "Billed run" below) | Delete `billed_env`, `BilledRefused`, the `--billed` flag in `run.py`, the `billed` argument, `self.tenant`, `_spent`, `billed_stop_at`, `_billed_stop` and its calls, and the `billed_stop` state in `driver.py` (use `TENANT` again), `repr=False` on `openai_api_key` may stay, and `test_run_billed.py` |

## Tables

| item | where | on/off | how to remove |
|---|---|---|---|
| `os_rehearsal_clock` (`tenant_id` PK, `offset_seconds` bigint, `updated_at`) | Migration `backend/alembic/versions_os/os_0014_slice9_rehearsal_clock.py`; model `rehearsal_clock` in `backend/app/os/models.py`. One row per tenant, written first by `start` (only when no row and no plan exist: `INSERT ... SELECT ... WHERE NOT EXISTS (plans) ON CONFLICT DO NOTHING`; the offset may be negative) or `advance`, then moved only by `advance` (one atomic `INSERT ... ON CONFLICT DO UPDATE SET offset_seconds = os_rehearsal_clock.offset_seconds + :s`) | Always created. Read only when rehearsal mode is on; with it off, a row for the tenant stops startup (see above) | A new migration that drops the table (the `os_0014` downgrade does exactly that), then delete the model and `"os_rehearsal_clock"` in `tests/os/test_models.py` |
| Negative rehearsal offset (`os_0017`) | Migration `backend/alembic/versions_os/os_0017_slice9_rehearsal_start.py` drops `ck_os_rehearsal_clock_offset` (`offset_seconds >= 0`, from `os_0014`), so `start` can set a day before the real date (Task 11). Tests: `test_clock_reads_a_negative_offset`, `test_migration_down_clamps_a_negative_offset` in `backend/tests/os/test_slice9_fixes.py` | Always applied. Only `start` writes a negative offset | Its downgrade sets every negative offset to 0, then restores the check (or drop the table with `os_0014`) |
| `os_consents` (`id`, `tenant_id`, `student_ref`, `terms_version`, `agreed_at`; unique (`tenant_id`, `student_ref`, `terms_version`)) | Migration `backend/alembic/versions_os/os_0015_slice9_consents.py`; model `consents` in `backend/app/os/models.py`; written and read only by `ConsentStore` in `backend/app/os/consent/store.py` (`agree` is idempotent, `agreed_at` from the shared clock) | Always created and always used: it is not a rehearsal-only table. Rows written in a rehearsal are test data; a clean database drops them | A new migration that drops the table (the `os_0015` downgrade does exactly that), then delete the model, `"os_consents"` in `tests/os/test_models.py`, and the consent package and calls (see Endpoints, Files, Checks) |
| Outbox statuses `blocked` and `failed` | Migration `backend/alembic/versions_os/os_0016_slice9_outbox_statuses.py` widens `ck_os_outbox_status` to `pending`, `sent`, `skipped`, `blocked`, `failed` (model `outbox` in `backend/app/os/models.py`); set by `Outbox.deliver` in `backend/app/os/outbox/outbox.py`. `blocked`: not on the allow-list, no request made. `failed`: Resend answered 4xx (the HTTP status is in the log only, hashed address; the outbox has no error column) | Always created. Used only by `ResendSender`; the log sender never sets them | A new migration that sets those rows to `skipped` and restores the old check (the `os_0016` downgrade does exactly that), then the model check and the `except (NotAllowed, Refused)` branch in `deliver` |

## Endpoints

| item | where | on/off | how to remove |
|---|---|---|---|
| `POST /v1/os/admin/rehearsal/start` `{date}` (2000-01-01 to 2099-12-31, else 422) -> `{offset_days, now}` | `backend/app/os/rehearsal/api.py`, added by `build_router`; `ClockStore.start` in `backend/app/os/rehearsal/store.py` sets the offset in whole days from the database's UTC date so that `clock.today()` is `date` (a past day gives a negative offset). The driver calls it with 1 Dec 2026 (Task 11). Tests: `backend/tests/os/test_slice9_fixes.py` | Admin token. Exists only in rehearsal mode (404 otherwise). Only once, on a clean clock (no clock row and no plan of the tenant yet; seeded facts do not count, the driver calls it before any plan starts): 409 once the clock was set or moved or a plan exists, so time never goes back once set; a clean database (the driver truncates every os_* table) allows it again | Delete with `app/os/rehearsal/` (see Files) and migration `os_0017` (see Tables) |
| `POST /v1/os/admin/rehearsal/advance` `{days}` (1 to 60, else 422) -> `{offset_days, now}` | `backend/app/os/rehearsal/api.py`, added by `build_router` | Admin token (`X-OS-Admin-Token`). Exists only in rehearsal mode (404 otherwise). Time only moves forward | Delete with `app/os/rehearsal/` (see Files) |
| `POST /v1/os/admin/rehearsal/tick` -> `{tick_id}` | Same file. Enqueues one `os.rehearsal_tick` workflow on the `os` queue through the API's DBOS client; the ID is `rehearsal-tick:<tenant>:<random>` | Same as above | Same as above |
| `GET /v1/os/admin/rehearsal/tick/{tick_id}` -> `{status: running/done/error, ran, failed}` | Same file. Reads the workflow from DBOS: finished with no failed job is done, finished with a failed job is error (`ran` lists the jobs that completed, `failed` those that did not), a workflow that itself ended `ERROR`/`CANCELLED`/`MAX_RECOVERY_ATTEMPTS_EXCEEDED` is error with both lists empty, anything else is running. Another tenant's or a non-tick workflow ID is 404 | Same as above | Same as above |
| `GET /v1/os/consent` -> `{version, text, placeholder, agreed}` | `build_router` in `backend/app/os/api/router.py` | Student sign-in. Always on. Reads the current terms on every call | Delete the route, `ConsentOut` in `app/os/api/schemas.py`, and `getOsConsent` in `frontend/lib/api.ts` |
| `POST /v1/os/consent` `{version}` -> 204 | Same file | Student sign-in (write). Always on. 409 `consent_version` if not the current version; 409 `terms_not_set` if the current terms are a placeholder and rehearsal mode is off. Agreeing twice is fine | Delete the route, `ConsentIn`, and `agreeOsConsent` in `frontend/lib/api.ts` |
| `GET /v1/os/admin/costs?from=YYYY-MM-DD&to=YYYY-MM-DD` -> `{start, end, students: [{student_ref, documents_usd, statements_usd, replan_usd, total_usd, flag}], research_usd, unlinked_rows, unlinked_usd}` | `build_router` in `backend/app/os/api/router.py`; the report is `cost_report` in `backend/app/os/costs.py`; bodies `CostReportOut`, `StudentCostOut` in `app/os/api/schemas.py`. Read only: sums `os_agent_runs.cost_usd` with `at` from start 00:00 UTC up to (not including) the day after end 00:00 UTC. A student is reached through the row's document, artifact (Writer/Critic) or plan (Supervisor), joined inside the tenant; research runs are one shared total; a row with no link or a nulled link is counted as unlinked. Money is Decimal, sent as strings. Flag per student: `alert` at 8 USD or more, `over` at 10 or more (D7). Tests: `backend/tests/os/test_costs.py` | Admin token (`X-OS-Admin-Token`). Always on (not rehearsal-only). Missing or bad dates, or `to` before `from`, answer 422 | Delete the route, `CostReportOut` and `StudentCostOut` in `schemas.py`, and `app/os/costs.py` with its test |

## Files

| item | where | on/off | how to remove |
|---|---|---|---|
| The shared clock | `backend/app/os/clock.py`. Every OS module reads time through `clock.now()` and `clock.today()` | Always on. It gives real time unless rehearsal mode installs an offset (Task 3) | Not removable on its own. Delete the file and change each `clock.now`/`clock.today` back to a direct date call (the check below then goes too) |
| Rehearsal package | `backend/app/os/rehearsal/`: `store.py` (`ClockStore`, `install_clock`, the warning text), `tick.py` (`JOB_ORDER`, `run_tick`, `register_tick`, `enqueue_tick`, `tick_status`), `api.py` (the four calls). Tests: `backend/tests/os/test_rehearsal_mode.py` | Imported always; does nothing unless rehearsal mode is on | Delete the folder and the test file, after removing the setting's uses (see Settings) |
| Offline models | `backend/app/os/agents/offline.py`: `offline_model(agent_id, answers_dir)` (one `FunctionModel` per agent, model name `offline`) and `OfflinePages` (research's page gateway in offline mode: fetches and stores nothing; every page is blocked as `offline`). Holds no answers. Documents: the SHA-256 of the first image the reader receives (page 1 or its first tile) looks up the values; a missing one is answered with a field no reading model has, so output validation fails (the normal invalid-output path, error kind `UnexpectedModelBehavior` after 2 repairs) and each try logs a WARNING `offline answer missing: agent=documents key=<sha256>` (logger `app.os.agents.offline`). Research: every field null. Writer: the kind's template, filled with the fenced answers and profile values, cut to the word or character limit. Critic: one passing review. Supervisor: the event type's operations (a missing type is logged and fails the same way). Tests: `backend/tests/os/test_offline_ai.py` | Used only with `OS_MODEL_MODE=offline` | Delete the file and the test file, after removing the setting's uses (see Settings) |
| Offline answers | `backend/tests/os/rehearsal/answers/`: `documents.yaml` (SHA-256 -> sample file name and field values, 32 samples, about 19 KB), `writer.yaml` (statement kind -> template), `critic.yaml` (one passing review), `supervisor.yaml` (replan event type -> operations and summary), `research.yaml` (the "not found" value). Test data only (invariant 12) | Read only in offline mode | Delete the folder |
| Answers maker | `backend/tests/os/rehearsal/make_answers.py` (`python -m tests.os.rehearsal.make_answers`, from `backend/`). Runs each Spike 2 sample (`tests/os/fixtures/documents/samples`, keyed by `samples_key.yaml`) through the pipeline's own `intake.check_upload`, `intake.prepare` and `reader.content` (the documents agent's `tiles` mode) and writes `documents.yaml`. Run it again when the samples, page preparation or tiling change; `test_document_answer_by_hash` fails if it is out of date | A script; nothing runs it automatically | Delete the file |
| Rehearsal driver | `backend/tests/os/rehearsal/driver.py` (`Rehearsal(students, out_dir, kill=False).run() -> Report`), with `failures.py` (`Failure`, `FailureLog`) and `report.py` (`Report`, `StudentResult`). It cleans `os_test` (every os_* table, the DBOS test schema), loads the programme registry and the seeded facts, plus the rehearsal's fictional semester starts (`backend/tests/os/rehearsal/semester_starts.yaml`, test data for the three programmes the students use, with `example.invalid` URLs: the visa step's date is derived from the visa programme's `semester_start`, Task 11 F1, and offline research finds nothing), writes a fresh offline answers folder in a temporary directory (the fixed answer files copied, `documents.yaml` written again by the answers maker so its keys match the installed Pillow, plus answers for four documents the driver draws per student: minimum passing grade letter, admission letter, blocked account, insurance), sets the clock to 1 Dec 2026 with the admin `start` call, whatever the real date (Task 11; if the call is refused it goes on from the clock's today and logs a `start_late:<date>` failure, `workaround`), starts one worker subprocess (`OS_REHEARSAL=on`, `OS_MODEL_MODE=offline`, `OS_OFFLINE_ANSWERS_DIR`, `OS_EMAIL_SENDER=log`) and mounts the API in its own FastAPI app (student by the `X-Test-Student` header, admin by a fictional token). Then each student agrees, starts a plan, uploads, and the loop answers the inbox, documents, statements, packs and visa file, waits for the worker to be idle, advances 1 to 3 days and ticks, until every plan has `visa_apply` waiting, is stuck (30 days with no change and nothing waiting) or the date is past 30 Sep 2027. It checks each scripted event (spec 2.4; S5's reminders, ask and missing-document support case in that order), that every step the plan says waits for the student is in their inbox (`inbox_missing`), that no work task is left ready or running, and `duplicates`: work the schema does not already forbid done twice (an event in two proposals, two revisions or two support cases for one proposal, a work task run again without a failure, a pack or visa version built from the same inputs as the one before, more Writer versions than draft requests). It acts only through the API; it reads the database only to check results and to see when the worker is idle. With `kill`, it SIGKILLs the worker at random ticks and at random moments while it is busy, and starts it again with the same executor ID each time (Linux). The driver supplies no fact as the admin (Task 11 removed the `visa_target_date` admin step); a `visa_apply` still blocked on a missing fact once the visa file is approved is a `fact_missing:<field>` failure. Inbox items with state `blocked` (steps waiting for a fact, or for a programme that admits the student, listed so the student is told what for) are not acted on. Paying and applying come after approval (Task 11 batch D): the driver ticks a pack's "after approval" steps (`fee_paid`) just before saying "I submitted it", and the visa file's (`portal_applied`, `visa_fee_paid`) when the visa step waits, through the API, and checks the approval still stands on the same version (else an `after_approval_tick:<student>:<pack|visa>` failure). After the run the process's clock is set back to real time | Test code; runs only when called | Delete the four files and the tests below |
| Rehearsal students | `backend/tests/os/rehearsal/students.yaml`: S1 to S12, each with 2 or 3 of the seeded programmes that have a deadline and an application route, a Spike 2 sample bundle (S2 bundle 3 and S4 bundle 4 carry the planted mistakes, the others bundles 1 and 5), interview answers, admission result per programme, visa programme, typed contact details (`@example.invalid`), and an event: S3 `rejected`, S5 `missing_document` (holds back the minimum passing grade letter until a support case opens), S7 `late` (does nothing until the plan asks for a step), S9 `approved_changed` (changes its approved SOP after every pack is approved), S11 `ignore_big` (rejected by one programme, ignores the suggestion), others `none`. Fictional data only | Read by the driver | Delete the file |
| Rehearsal command | `backend/tests/os/rehearsal/run.py`: `python -m tests.os.rehearsal.run --students all\|S1,S3 [--kill] [--billed] [--seed N] --out ~/s9-rehearsal/<run>` from `backend/`, with `OS_TEST_DATABASE_URL` set. It cleans that database, so use only `os_test` and run no pytest on it at the same time. Offline AI unless `--billed` (see Settings and "Billed run"). Refuses an `--out` inside the repo. Exit 0 when every student reached both end points and the failure log is empty, 1 otherwise, 2 when it refused to start | Run by hand (the full 12, the kill run, the billed run) | Delete the file |
| Walkthrough script | `backend/tests/os/rehearsal/walkthroughs.md`: the set-up and the steps of spec 2.6 for S1, S3 and S9 at 375 px (start, consent, upload, interview, approve a draft, a suggestion, "What changed", the pack and the visa file), when to `advance`/`tick`, and what to log (`walk:<student>:...`, severity `blocks`/`workaround`/`wording`). Screenshots and the walkthrough failure log go outside the repo (`~/s9-rehearsal/walkthroughs/`) | Read by whoever plays a walkthrough; nothing runs it | Delete the file |
| Rehearsal findings (Task 10) | `docs/os/slice-9a-rehearsal-report.md`: the full run, the kill run and the three walkthroughs: counts per severity, end states per student, the kill comparison, runtimes, one line per failure (no personal data); then the fix pass's re-runs and each failure's outcome (Task 11), and the gate line (Task 12) | A record; nothing reads it | Delete the file |
| 9a handoff (Task 12) | `docs/os/handoff/slice-9a-handoff.md`: where 9a stands, the PRs, the gate's seven pass marks with their numbers, the rulings, the failure outcomes, the open owner items and the 9b next steps | A record; read first by the next session | Not removed: it is the record of the slice |
| Rehearsal failure log and report | Written by the driver to the run's folder, outside the repo (default `~/s9-rehearsal/<UTC time>/`; tests use a temporary folder): `failures.yaml` (id, student, step, expected, got, severity `blocks`/`workaround`/`wording`; add `fixed_by` or `owner_accepted` by hand), `report.json` and `report.md` (per student: end state, events and how each went, rehearsal days, end points reached; totals; failures per severity; worker kills; admin steps: counts and states only, no names or documents), and `logs/worker-g<N>.log`. A second run into a folder that already holds a `failures.yaml` is refused, so hand-written entries are never mixed with a new run | Written on every run | Delete the run's folder |
| Workflow `os.rehearsal_tick` | `register_tick` in `app/os/rehearsal/tick.py`, called by `build` in `app/os/runner/worker.py` instead of the `register_job` loop. It runs the worker's jobs once, each as a DBOS step (`os.tick.<job>`, the normal step retries), in this order: deadline_engine, reminders, replan, deliver_outbox, freshness, documents_retry (only on a worker with a model key or offline AI), reconcile. A job that still fails after its step retries is logged and listed in `failed`, and the tick goes on with the next job (so one broken job does not stall the rehearsal); the tick then reports error. **`counsellor_intake` is not ticked** and, with no cron, does not run at all in rehearsal mode: the Counsellor module is off for the pilot (Slice 8 S8-D2) | Registered only in rehearsal mode; with it off the worker registers today's schedules and no tick workflow | Delete with the package; in `build` keep only the `register_job` loop |
| Pilot terms | `backend/app/os/consent/pilot.v1.md` (front matter `version: 1`, `placeholder: true`), read by `current_terms` in `backend/app/os/consent/terms.py` (the highest `pilot.vN.md`; `make_services` takes `terms_dir` so tests use their own folder, and checks the file at start). The text is a marked placeholder naming what the owners' terms must say; no country words. Test-only terms that are not a placeholder: `backend/tests/os/fixtures/terms/pilot.v1.md` | A placeholder is accepted only in rehearsal mode. When the owners write the text, add `pilot.v2.md` with `placeholder: false`: every student is asked again | Not rehearsal-only: the owners' text replaces the placeholder. To drop consent altogether, delete `backend/app/os/consent/`, the `terms_dir` field and argument in `app/os/api/services.py`, and the rows below |
| Consent card | `frontend/components/os/consent-card.tsx` (terms text, "This is a pilot", "I agree"), `frontend/lib/os-consent.ts`; shown first on `os-start` and above the list on `os-documents` while the student has not agreed. Tests: `frontend/components/os/consent-card.test.tsx` | Shown whenever the current terms are not agreed | Delete the two files and the test, and the consent parts of the two pages |
| Cost script | `backend/scripts/os_costs.py`: `python -m scripts.os_costs --from YYYY-MM-DD --to YYYY-MM-DD`, from `backend/`. Prints one line per student (student ref, the three buckets, total, flag; highest total first), then the shared research cost and the unlinked row count and cost. Student refs and money only. Uses `cost_report` | A script; nothing runs it automatically. Needs `OS_DATABASE_URL` (or `DATABASE_URL`) | Delete the file (and the script test in `test_costs.py`) |
| Menu entry "Study abroad plan" | `frontend/components/os/os-nav-group.tsx` (`OsNavGroup`: links Start, Inbox, Documents, Programmes, Statements, Pack, Visa to `/<workspaceId>/os-*`; workspace id from the route), rendered by one line in `frontend/components/layout/nav-main.tsx` (the mobile drawer, shared file); labels are the `nav.studyAbroadPlan` and `nav.os*` keys in `frontend/lib/i18n/messages/en-US.ts`. Tests: `frontend/components/layout/nav-main.test.tsx`. The desktop rail (`nav-rail.tsx`) does not show it yet | `NEXT_PUBLIC_OS_ENABLED=true` at build time (`OS_UI_ENABLED`); off by default, and then the group renders nothing | Delete `os-nav-group.tsx`, the test, the `OsNavGroup` import and line in `nav-main.tsx`, and the `nav.studyAbroadPlan` / `nav.os*` keys |
| OS page header (Task 11, `walk:S1:no_menu_on_os_pages`) | `frontend/components/os/os-header.tsx` (`OsHeader`: the page title and a Menu button that opens the links to the other OS pages, from `OS_PAGES` in `os-nav-group.tsx`, and back to the workspace home), used at the top of the seven `frontend/app/[workspaceId]/os-*/page.tsx` pages. Tests: `frontend/components/os/os-header.test.tsx` | Always shown on the OS pages (which exist only in the OS-enabled build) | Not rehearsal-only: a product fix. To drop it, delete the file and its test and the `OsHeader` line in each page |
| Visa apply-by date from `semester_start` (Task 11, F1) | A new per-programme research fact `semester_start` (`month_day`, cycle bound) in `backend/app/os/knowledge/profiles/germany_master.research.v1.yaml`; a playbook constant `visa_before_semester_days` (an estimate: 105 days, 15 weeks, since Slice 9b = the 90-day processing time plus a 2-week buffer, rounded up to whole weeks; it was 42) and the `visa_apply` step's `anchor` (fact, programme `visa`, the note, passed-date and waiting texts) in `backend/app/os/playbooks/germany_master.v1.yaml` (v1 edited in place before the pilot: no real plans exist), read by `backend/app/os/playbooks/models.py` and `backend/app/os/compiler/compile.py`. The due date is the apply-by date; `visa_processing_days` (90) is shown as an estimate. If the apply-by date has already passed when the plan is compiled, the step says "Apply now" (`note_passed`) and is due on the semester start itself (Slice 9b). The step waits for the admission result, but its date never pulls the admission or the applications earlier (`pull: false` on that dependency, Task 11C). The seed gives no `semester_start`; rehearsals load `backend/tests/os/rehearsal/semester_starts.yaml` (see Rehearsal driver). Tests: `backend/tests/os/test_slice9_fixes.py`, `backend/tests/os/test_compiler.py` | Always on. Until a programme's `semester_start` is researched and confirmed, `visa_apply` waits and says what for | Not rehearsal-only: a product fix. Reverting it brings F1 back (no date source for `visa_apply`) |
| Paying and applying after approval (Task 11 batch D) | `after_approval: true` on the `fee_paid` checklist step of `backend/app/os/packs/germany_master.yaml` and on `portal_applied` / `visa_fee_paid` in `backend/app/os/packs/germany_master.visa.yaml`, both now `version: 2`; handled in `backend/app/os/packs/checklist.py` and `config.py`: these ticks never block approval and are offered after it. The version bump rebuilds every pack and visa file once (old approvals raise an `approved_changed` review) | Always on | Not rehearsal-only: a product fix (the user's ruling). Reverting: drop the flag, set the configs back to `version: 1` |

## Checks

| item | where | on/off | how to remove |
|---|---|---|---|
| No direct clock calls | `test_no_direct_clock_calls` in `backend/tests/os/test_invariants.py`. It fails if any file in `app/os` (except `clock.py`) reads the real date or time itself | Runs with the tests; cannot be switched off | Delete the two clock tests in that file (`test_no_direct_clock_calls` and `test_clock_check_catches_a_violation`) |
| Consent before a start (`consent_needed`) | `consented_student` in `backend/app/os/api/router.py`, a dependency of `POST /v1/os/plans/self` (runs before the body is checked and before any write). Tests: `backend/tests/os/test_api_consent.py`; every existing test that starts a plan or uploads calls `agree` from `tests/os/test_api.py` | Always on. 409 `consent_needed` without a row for the current terms version. The inbox and changes to a running plan are not blocked. A refused start on `os-start` shows "Please agree to the pilot terms first." | Use `current_student_ref_for_write` again in the route, then remove the `agree` calls in the tests |
| Consent before an upload (`consent_needed`) | The same dependency on `POST /v1/os/documents` (before the file is checked, stored or enqueued) | Same as above | Same as above |
| Shared clock tests | `backend/tests/os/test_clock.py`: real aware UTC time by default, the installed offset reader, today from now | Runs with `tests/os` | Delete with the clock |
| Fix pass tests (Task 11) | `backend/tests/os/test_slice9_fixes.py`: one RED→GREEN test (or a few) per fixed rehearsal failure (F1, F2, F3, the visa apply-by date and its real-date regression test, after-approval ticks) and the four old Slice 7 minors (S9-D10); screen fixes have Vitest tests beside their components | Runs with `tests/os` | Not removed: they guard the fixes |
| Billed start check | `backend/tests/os/rehearsal/test_run_billed.py`: `--billed` refuses without the key, with a cap missing or not an amount, and when the caps sum to more than 15; accepts a valid set; the refusal never shows the key; the CLI refuses before anything starts; the driver takes the billed tenant; the budget guard stops at $12 of $15, after a timed-out wait and on a spend query error, after every settle in the loop, latched, as an admin step not a failure, with no `not_finished` after it (spend, worker and API faked); `OsSettings` hides `openai_api_key` from `repr`. Only the check runs: no billed run starts from a test, and the key is a fictional placeholder | Runs with `tests/os` | Delete with `--billed` |
| Rehearsal driver tests | `backend/tests/os/rehearsal/test_driver.py`: the students file (12, the events, only sample bundles, two with planted mistakes), the failure log round trip, stuck after 30 days, the stop after 30 Sep 2027, and a short real run in which one student's document has no offline answer: one failure names the missing key and file, and the other student carries on (plan Review Focus 5) | Runs with `tests/os` (the last test starts a worker and needs Postgres) | Delete the file |
| Short rehearsal in CI | `backend/tests/os/rehearsal/test_rehearsal_short.py`: S1, S3 and S5 offline, end to end, on a real worker: both end points for each, S3's programme removed, S5's reminders, ask and support case, and an empty failure log. About 3 minutes | Runs with `tests/os`. No xfail since Task 11 (F1 and F2 fixed): any failure in the log, a missed end point or a missed event fails the suite | Delete the file |

## Senders

| item | where | on/off | how to remove |
|---|---|---|---|
| `ResendSender` (`OS_EMAIL_SENDER=resend`) | `backend/app/os/outbox/senders.py`: `ResendSender(settings, httpx.Client)`, `NotAllowed`, `Refused`, `ProviderUnavailable`, built by `make_sender`; delivery handling in `Outbox.deliver`. POSTs to `https://api.resend.com/emails` with `Authorization: Bearer` and `Idempotency-Key` = the outbox key. Subject is the template name in words; text is `key: value` lines of the payload (no renderer exists yet). A recipient off the allow-list is `blocked` and nothing is sent; 4xx other than 408/429 is `failed`; 408, 429, 5xx and network errors raise `ProviderUnavailable` (a plain exception with no httpx cause, so the key never reaches DBOS's stored errors) and the DBOS step retries (invariant 7). Logs show only the SHA-256 of the address. Tests: `backend/tests/os/test_resend_sender.py` (`httpx.MockTransport`, no network) | Off by default (`OS_EMAIL_SENDER=log`). **Rehearsals keep `log`.** Outbox recipients are student references today, not addresses, so a real send also needs the workspace-id to email lookup that is not built | Delete the class, the three exceptions (`NotAllowed`, `Refused`, `ProviderUnavailable`), `address_hash`, the `resend` branch of `make_sender`, the `except` branch in `deliver`, the settings and the test file |

## Billed run

Only with the owners' OK (spec 2.7, S9-D9). Approved by the user on the owners' behalf on 2026-10-29: S1, S3 and S5,
tenant `rehearsal-billed`, caps 5 + 4 + 4 + 2 = $15. **Not yet run:** it waits for the owners' budgeted
`OS_OPENAI_API_KEY` in the environment. Use a clean `os_test` database (the run cleans it). Hitting a cap is the normal
"over budget" path (a support case): record it as a result, do not raise the cap.

Before it runs:

- **Spend limit.** The owners set a hard monthly spend limit on the OpenAI project that owns the key, at or near the
  run's $15. The driver's budget guard (below) and the four OS caps are a soft backstop: they read recorded spend
  after each wait, so they cannot stop a call already in flight. The project limit is the real ceiling.
- **Network.** The environment's network policy must allow `api.openai.com` and the universities' sites (research
  fetches their pages). A proxy that refuses a host fails every call to it, it does not stop the run.
- **Preflight.** `--billed` makes one cheap request before anything starts: `GET https://api.openai.com/v1/models`
  with the key from the environment, 10 s timeout. If it cannot connect, or the answer is not 2xx, the run prints
  `--billed refused: <reason>` and exits 2, like the other start checks. The reason names only the host and the HTTP
  status or the error type, never the key. (An earlier billed run went 2 hours with every model call failing because
  the proxy refused CONNECT to `api.openai.com` with 403; the preflight stops that at the start. It does not check
  the universities' sites.)

```
cd backend
export OS_TEST_DATABASE_URL=postgresql://os_test:os_test@localhost:5432/os_test
# OS_OPENAI_API_KEY is set by the owners in the environment; never type it into chat, a file or a log
# reduced at the user's request (handoff ruling 31): S1 only, $4 in caps, the guard stops at $3
export OS_RESEARCH_MONTHLY_USD=1.5 OS_DOCUMENTS_MONTHLY_USD=1 OS_STATEMENTS_MONTHLY_USD=1 OS_REPLAN_MONTHLY_USD=0.5
python -m tests.os.rehearsal.run --students S1 --billed --out ~/s9-rehearsal/billed
```

Then the cost report. `os_agent_runs.at` is stamped with the shared clock, so the dates are **rehearsal** dates: the
run starts on 1 Dec 2026 and stops by 30 Sep 2027. The script reads one tenant, so name the billed one:

```
OS_DATABASE_URL=$OS_TEST_DATABASE_URL OS_TENANT_ID=rehearsal-billed \
  python -m scripts.os_costs --from 2026-12-01 --to 2027-09-30
```

Run it before anything else cleans `os_test` (a pytest run or another rehearsal empties it).

**How to read the result.** If the report's admin steps show `billed_stop: ...`, the whole-run budget guard stopped the
run (at $12 spent of $15, after a wait that timed out, or when the spend could not be read). The students still
running then end in state `billed_stop`, and the driver logs no `not_finished` and no event results for them: that is
the stop's effect, not a product failure. The run's exit code is 1 (not every student finished). A `worker_busy`
entry next to such a stop is the wait that timed out, and a `lost_tasks` entry may then be work the stop cut off.
The worst case is the stop point ($12) plus what was in flight in the one wait before the guard looked; that stays
under the $15 cap unless a single wait's work costs more than $3. Real research fetches through this container's
proxy have not been tried.

The per-student totals (and research as a shared cost) go to the owners for D7 ($10 per student per year).

## Walkthrough sign-in

Finding (Task 1, 2026-10-27): **the real sign-in needs a real Supabase project. A local test sign-in works only through
an existing test entry point that swaps the Supabase check for a fake one.** The owners must say whether that is
acceptable for the walkthroughs (spec 2.6). Nothing was built for this; 9a adds no sign-in code.

This path gives only **one fixed student**. The entry point accepts one token and always returns the same account
(`offline-student@example.invalid`), so S1, S3 and S9 cannot each have their own test account without new code. The owners
should judge it with that limit in view.

| item | where | on/off | how to remove |
|---|---|---|---|
| Real sign-in (email or username and password) | Browser form calls `${NEXT_PUBLIC_SUPABASE_URL}/auth/v1/token` (`frontend/lib/supabase-auth.ts`). The API then checks the Supabase token (`backend/app/security/human_auth.py`) at `POST /v1/auth/session` (`backend/app/routers/auth.py`) | Needs `SUPABASE_URL` and `SUPABASE_ANON_KEY` on the API, and the same two as `NEXT_PUBLIC_SUPABASE_*` in the frontend build. We have no Supabase project, so this does not work locally | Not ours. Nothing to remove |
| Workspace token (`x-workspace-token`) | `_workspace_auth` in `backend/app/main.py` | Only gives read access to OS calls. Writes (for example completing an inbox item) need a signed-in student (`backend/app/application_workspace/access.py`). The frontend page cannot sign in with it | Not ours. Nothing to remove |
| Offline test entry point (fake identity) | `backend/scripts/offline_startup_app.py`, already in the repo before 9a. It makes the API accept one fake provider token for one fake student | Used by starting the API with `scripts.offline_startup_app:app` and `PAI_OFFLINE_STARTUP_CHECK=1`. It also blocks outside hostnames and fakes the Counsellor model, so use it only on a local machine | Not ours. 9a does not change it |

### Steps for one walkthrough student (as tried on 2026-10-27)

The student is fictional: `offline-student@example.invalid`, created on first sign-in. All values below are made up
and not secret. Run from the repo root. Postgres 16 must be running.

1. Make an empty database (once):

   ```
   createdb -h localhost -U os_test walk_probe     # password: os_test
   ```

2. Set the API environment and migrate:

   ```
   cd backend
   export PYTHONPATH=. APP_ENV=development PAI_OFFLINE_STARTUP_CHECK=1 OS_ENABLED=true
   export DATABASE_URL=postgresql+psycopg2://os_test:os_test@localhost:5432/walk_probe
   export CORS_ORIGINS=http://localhost:3000 FRONTEND_BASE_URL=http://localhost:3000
   export PUBLIC_API_BASE=http://localhost:8000
   alembic upgrade heads
   ```

3. Start the API (leave it running):

   ```
   python -m uvicorn scripts.offline_startup_app:app --port 8000
   ```

   The log shows one error, "SUPABASE_URL/SUPABASE_ANON_KEY are not set". That is expected here.

4. Start the frontend in a second terminal:

   ```
   cd frontend
   NEXT_PUBLIC_API_URL=http://localhost:8000 NEXT_PUBLIC_OS_ENABLED=true npx next dev -p 3000
   ```

5. Sign in. The login form cannot be used (it needs Supabase). Instead, from a page on `http://localhost:3000`
   (for example the login page), run this in the browser. A Playwright agent can use `page.evaluate`:

   ```
   fetch('http://localhost:8000/v1/auth/session', {
     method: 'POST', credentials: 'include',
     headers: { Authorization: 'Bearer offline-provider-token' } })
   ```

   It answers 200 and sets the `pai_session` cookie. The answer holds the student's `workspaceId`.

6. Open `http://localhost:3000/<workspaceId>/os-start`. The OS pages (`os-inbox`, `os-documents`, and the rest) open
   for this student.

What was checked: step 5 returned 200; `GET /v1/auth/session` with the cookie returned the student; the OS inbox
answered with the cookie; a write call passed the sign-in check (it answered "inbox item not found", not 403); and
`/os-start` showed "Start your plan" in a 375 px browser.

Not checked: the OS worker (not started in this try), and any page after `os-start`. This entry point blocks outside
hostnames, so research fetches from it will fail. Task 3 must decide how rehearsal mode and this entry point fit
together.
