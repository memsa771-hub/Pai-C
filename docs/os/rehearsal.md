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
| Rehearsal mode (`OS_REHEARSAL`) | `OsSettings.rehearsal` in `backend/app/os/settings.py` (same true words as `OS_ENABLED`: 1, true, yes, on). Set it on both the API and the worker. It is separate from `scripts/offline_startup_app.py`: with that entry point, set `OS_REHEARSAL` in the same environment as `OS_ENABLED` | Off by default. On: the shared clock reads the stored offset, the worker registers no cron schedules, the three admin calls below exist, and the API and worker log a WARNING containing "REHEARSAL MODE" at start. Off: real time even if an offset row is left, and the calls answer 404 | Delete the field and `flag(env, "OS_REHEARSAL")` in `settings.py`, the `install_clock` calls in `app/os/api/services.py` and `app/os/runner/worker.py` `build`, the `if settings.rehearsal` branch in `build` (keep the `register_job` loop), and the `if get_services().settings.rehearsal` block in `app/os/api/router.py` |
| Offline AI (`OS_MODEL_MODE`) | `OsSettings.model_mode` in `backend/app/os/settings.py`: `openai` (default) or `offline`. Set it on the worker, and the same value on the API. `load_settings` raises `ModelModeError` (a `ValueError`) for any other value, for `offline` without `OS_REHEARSAL` on, and for `offline` without `OS_OFFLINE_ANSWERS_DIR`; the worker then stops at start, and so does the API when `OS_ENABLED` is on (`mount_os` in `app/os/api/mount.py` re-raises it instead of switching the OS off) | `openai` by default. `offline`: every agent (research, documents, writer, critic, supervisor) gets a Pydantic AI `FunctionModel` named `offline` that answers from the files below, no OpenAI key is needed (offline counts as "configured" in the four `register_*` functions of `app/os/runner/worker.py`; the `OS_TEST_*_MODEL` hooks still come first), runs record `model = "offline"` and cost 0, and research fetches no page (`OfflinePages`). Output validation still runs | Delete the two fields and their checks in `settings.py`, `model_for_spec` in `app/os/knowledge/research/readings.py` (call `model_for(settings, spec.tier)` again), the `model == OFFLINE_MODEL` test in `cost` (and its `model` argument at the four call sites), `_models_on` and the `OfflinePages` branch in `worker.py`, the `critic_model` argument of `build_agents` in `app/os/statements/agents.py`, the `except ModelModeError` branch in `app/os/api/mount.py`, and `app/os/agents/offline.py` |
| Offline answers folder (`OS_OFFLINE_ANSWERS_DIR`) | `OsSettings.offline_answers_dir` in `backend/app/os/settings.py`; read only by `offline_model` in `backend/app/os/agents/offline.py` (`<dir>/<agent id>.yaml`, read once when the worker builds its agents, so a missing file stops the worker) | Needed only with `OS_MODEL_MODE=offline`; point it at `backend/tests/os/rehearsal/answers` | With `OS_MODEL_MODE` above |

## Tables

| item | where | on/off | how to remove |
|---|---|---|---|
| `os_rehearsal_clock` (`tenant_id` PK, `offset_seconds` bigint >= 0, `updated_at`) | Migration `backend/alembic/versions_os/os_0014_slice9_rehearsal_clock.py`; model `rehearsal_clock` in `backend/app/os/models.py`. One row per tenant, moved only by `advance` (one atomic `INSERT ... ON CONFLICT DO UPDATE SET offset_seconds = os_rehearsal_clock.offset_seconds + :s`) | Always created. Read only when rehearsal mode is on; a leftover row is ignored when it is off | A new migration that drops the table (the `os_0014` downgrade does exactly that), then delete the model and `"os_rehearsal_clock"` in `tests/os/test_models.py` |
| `os_consents` (`id`, `tenant_id`, `student_ref`, `terms_version`, `agreed_at`; unique (`tenant_id`, `student_ref`, `terms_version`)) | Migration `backend/alembic/versions_os/os_0015_slice9_consents.py`; model `consents` in `backend/app/os/models.py`; written and read only by `ConsentStore` in `backend/app/os/consent/store.py` (`agree` is idempotent, `agreed_at` from the shared clock) | Always created and always used: it is not a rehearsal-only table. Rows written in a rehearsal are test data; a clean database drops them | A new migration that drops the table (the `os_0015` downgrade does exactly that), then delete the model, `"os_consents"` in `tests/os/test_models.py`, and the consent package and calls (see Endpoints, Files, Checks) |

## Endpoints

| item | where | on/off | how to remove |
|---|---|---|---|
| `POST /v1/os/admin/rehearsal/advance` `{days}` (1 to 60, else 422) -> `{offset_days, now}` | `backend/app/os/rehearsal/api.py`, added by `build_router` | Admin token (`X-OS-Admin-Token`). Exists only in rehearsal mode (404 otherwise). Time only moves forward | Delete with `app/os/rehearsal/` (see Files) |
| `POST /v1/os/admin/rehearsal/tick` -> `{tick_id}` | Same file. Enqueues one `os.rehearsal_tick` workflow on the `os` queue through the API's DBOS client; the ID is `rehearsal-tick:<tenant>:<random>` | Same as above | Same as above |
| `GET /v1/os/admin/rehearsal/tick/{tick_id}` -> `{status: running/done/error, ran, failed}` | Same file. Reads the workflow from DBOS: finished with no failed job is done, finished with a failed job is error (`ran` lists the jobs that completed, `failed` those that did not), a workflow that itself ended `ERROR`/`CANCELLED`/`MAX_RECOVERY_ATTEMPTS_EXCEEDED` is error with both lists empty, anything else is running. Another tenant's or a non-tick workflow ID is 404 | Same as above | Same as above |
| `GET /v1/os/consent` -> `{version, text, placeholder, agreed}` | `build_router` in `backend/app/os/api/router.py` | Student sign-in. Always on. Reads the current terms on every call | Delete the route, `ConsentOut` in `app/os/api/schemas.py`, and `getOsConsent` in `frontend/lib/api.ts` |
| `POST /v1/os/consent` `{version}` -> 204 | Same file | Student sign-in (write). Always on. 409 `consent_version` if not the current version; 409 `terms_not_set` if the current terms are a placeholder and rehearsal mode is off. Agreeing twice is fine | Delete the route, `ConsentIn`, and `agreeOsConsent` in `frontend/lib/api.ts` |

## Files

| item | where | on/off | how to remove |
|---|---|---|---|
| The shared clock | `backend/app/os/clock.py`. Every OS module reads time through `clock.now()` and `clock.today()` | Always on. It gives real time unless rehearsal mode installs an offset (Task 3) | Not removable on its own. Delete the file and change each `clock.now`/`clock.today` back to a direct date call (the check below then goes too) |
| Rehearsal package | `backend/app/os/rehearsal/`: `store.py` (`ClockStore`, `install_clock`, the warning text), `tick.py` (`JOB_ORDER`, `run_tick`, `register_tick`, `enqueue_tick`, `tick_status`), `api.py` (the three calls). Tests: `backend/tests/os/test_rehearsal_mode.py` | Imported always; does nothing unless rehearsal mode is on | Delete the folder and the test file, after removing the setting's uses (see Settings) |
| Offline models | `backend/app/os/agents/offline.py`: `offline_model(agent_id, answers_dir)` (one `FunctionModel` per agent, model name `offline`) and `OfflinePages` (research's page gateway in offline mode: fetches and stores nothing; every page is blocked as `offline`). Holds no answers. Documents: the SHA-256 of the first image the reader receives (page 1 or its first tile) looks up the values; a missing one is answered with a field no reading model has, so output validation fails (the normal invalid-output path, error kind `UnexpectedModelBehavior` after 2 repairs) and each try logs a WARNING `offline answer missing: agent=documents key=<sha256>` (logger `app.os.agents.offline`). Research: every field null. Writer: the kind's template, filled with the fenced answers and profile values, cut to the word or character limit. Critic: one passing review. Supervisor: the event type's operations (a missing type is logged and fails the same way). Tests: `backend/tests/os/test_offline_ai.py` | Used only with `OS_MODEL_MODE=offline` | Delete the file and the test file, after removing the setting's uses (see Settings) |
| Offline answers | `backend/tests/os/rehearsal/answers/`: `documents.yaml` (SHA-256 -> sample file name and field values, 32 samples, about 19 KB), `writer.yaml` (statement kind -> template), `critic.yaml` (one passing review), `supervisor.yaml` (replan event type -> operations and summary), `research.yaml` (the "not found" value). Test data only (invariant 12) | Read only in offline mode | Delete the folder |
| Answers maker | `backend/tests/os/rehearsal/make_answers.py` (`python -m tests.os.rehearsal.make_answers`, from `backend/`). Runs each Spike 2 sample (`tests/os/fixtures/documents/samples`, keyed by `samples_key.yaml`) through the pipeline's own `intake.check_upload`, `intake.prepare` and `reader.content` (the documents agent's `tiles` mode) and writes `documents.yaml`. Run it again when the samples, page preparation or tiling change; `test_document_answer_by_hash` fails if it is out of date | A script; nothing runs it automatically | Delete the file |
| Workflow `os.rehearsal_tick` | `register_tick` in `app/os/rehearsal/tick.py`, called by `build` in `app/os/runner/worker.py` instead of the `register_job` loop. It runs the worker's jobs once, each as a DBOS step (`os.tick.<job>`, the normal step retries), in this order: deadline_engine, reminders, replan, deliver_outbox, freshness, documents_retry (only on a worker with a model key or offline AI), reconcile. A job that still fails after its step retries is logged and listed in `failed`, and the tick goes on with the next job (so one broken job does not stall the rehearsal); the tick then reports error. **`counsellor_intake` is not ticked** and, with no cron, does not run at all in rehearsal mode: the Counsellor module is off for the pilot (Slice 8 S8-D2) | Registered only in rehearsal mode; with it off the worker registers today's schedules and no tick workflow | Delete with the package; in `build` keep only the `register_job` loop |
| Pilot terms | `backend/app/os/consent/pilot.v1.md` (front matter `version: 1`, `placeholder: true`), read by `current_terms` in `backend/app/os/consent/terms.py` (the highest `pilot.vN.md`; `make_services` takes `terms_dir` so tests use their own folder, and checks the file at start). The text is a marked placeholder naming what the owners' terms must say; no country words. Test-only terms that are not a placeholder: `backend/tests/os/fixtures/terms/pilot.v1.md` | A placeholder is accepted only in rehearsal mode. When the owners write the text, add `pilot.v2.md` with `placeholder: false`: every student is asked again | Not rehearsal-only: the owners' text replaces the placeholder. To drop consent altogether, delete `backend/app/os/consent/`, the `terms_dir` field and argument in `app/os/api/services.py`, and the rows below |
| Consent card | `frontend/components/os/consent-card.tsx` (terms text, "This is a pilot", "I agree"), `frontend/lib/os-consent.ts`; shown first on `os-start` and above the list on `os-documents` while the student has not agreed. Tests: `frontend/components/os/consent-card.test.tsx` | Shown whenever the current terms are not agreed | Delete the two files and the test, and the consent parts of the two pages |
| Menu entry "Study abroad plan" | `frontend/components/os/os-nav-group.tsx` (`OsNavGroup`: links Start, Inbox, Documents, Programmes, Statements, Pack, Visa to `/<workspaceId>/os-*`; workspace id from the route), rendered by one line in `frontend/components/layout/nav-main.tsx` (the mobile drawer, shared file); labels are the `nav.studyAbroadPlan` and `nav.os*` keys in `frontend/lib/i18n/messages/en-US.ts`. Tests: `frontend/components/layout/nav-main.test.tsx`. The desktop rail (`nav-rail.tsx`) does not show it yet | `NEXT_PUBLIC_OS_ENABLED=true` at build time (`OS_UI_ENABLED`); off by default, and then the group renders nothing | Delete `os-nav-group.tsx`, the test, the `OsNavGroup` import and line in `nav-main.tsx`, and the `nav.studyAbroadPlan` / `nav.os*` keys |

## Checks

| item | where | on/off | how to remove |
|---|---|---|---|
| No direct clock calls | `test_no_direct_clock_calls` in `backend/tests/os/test_invariants.py`. It fails if any file in `app/os` (except `clock.py`) reads the real date or time itself | Runs with the tests; cannot be switched off | Delete the two clock tests in that file (`test_no_direct_clock_calls` and `test_clock_check_catches_a_violation`) |
| Consent before a start (`consent_needed`) | `consented_student` in `backend/app/os/api/router.py`, a dependency of `POST /v1/os/plans/self` (runs before the body is checked and before any write). Tests: `backend/tests/os/test_api_consent.py`; every existing test that starts a plan or uploads calls `agree` from `tests/os/test_api.py` | Always on. 409 `consent_needed` without a row for the current terms version. The inbox and changes to a running plan are not blocked. A refused start on `os-start` shows "Please agree to the pilot terms first." | Use `current_student_ref_for_write` again in the route, then remove the `agree` calls in the tests |
| Consent before an upload (`consent_needed`) | The same dependency on `POST /v1/os/documents` (before the file is checked, stored or enqueued) | Same as above | Same as above |

## Senders

| item | where | on/off | how to remove |
|---|---|---|---|

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
