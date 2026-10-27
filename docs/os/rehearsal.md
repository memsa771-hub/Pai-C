# Rehearsal record (Slice 9a)

Rehearsal mode lets us run the whole OS on one machine, with a clock we control and no real AI or email. We use it to
rehearse 12 fictional students through a full intake cycle, and to let three of them be walked through in a browser at
phone width. It is off unless someone turns it on.

This file lists everything 9a adds, so that all of it can be found and removed. **Every 9a PR updates this file, and
reviewers check it** (spec S9-D8). One row per thing: what it is, where it lives, how it is switched on or off, and how
to remove it.

Only fictional, non-secret values belong here. Never put a key, token or real student data in this file.

Plain audit stamps written by the database (for example `sent_at`, `read_at`, `approved_at`, and a `created_at` that is not used in a rule) stay real time under a rehearsal offset. Anything the OS decides with time (daily limits, spend by month, freshness, the 24 hour swap window) uses the shared clock.

## Settings

| item | where | on/off | how to remove |
|---|---|---|---|

## Tables

| item | where | on/off | how to remove |
|---|---|---|---|

## Endpoints

| item | where | on/off | how to remove |
|---|---|---|---|

## Files

| item | where | on/off | how to remove |
|---|---|---|---|
| The shared clock | `backend/app/os/clock.py`. Every OS module reads time through `clock.now()` and `clock.today()` | Always on. It gives real time unless rehearsal mode installs an offset (Task 3) | Not removable on its own. Delete the file and change each `clock.now`/`clock.today` back to a direct date call (the check below then goes too) |

## Checks

| item | where | on/off | how to remove |
|---|---|---|---|
| No direct clock calls | `test_no_direct_clock_calls` in `backend/tests/os/test_invariants.py`. It fails if any file in `app/os` (except `clock.py`) reads the real date or time itself | Runs with the tests; cannot be switched off | Delete the two clock tests in that file (`test_no_direct_clock_calls` and `test_clock_check_catches_a_violation`) |

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
