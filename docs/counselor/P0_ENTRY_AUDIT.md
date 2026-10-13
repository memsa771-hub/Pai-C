# P0 entry audit

Date: 2026-10-10. Branch: `pai-c`. Scope: existing entry path only; no rebuild,
new features, migrations, PAI OS changes, environment-file edits or live provider/model calls.

## Sources

- `MASTER_PLAN.md`, phase P0, and `CLEAN_ARCHITECTURE.md`, section 5.
- [FigJam master map](https://www.figma.com/board/NyfnqKOPD7rIAxUxky5dag),
  diagram 1, section `A Entry` (node `1:12`): sign up/sign in -> onboarding
  basics -> student workspace. The board was read, not changed.

## Audit results

| Check | Result | Evidence and boundary |
| --- | --- | --- |
| 2a Signup/signin, workspace, onboarding, initial journey | PASS (offline) | Existing frontend `lib/auth/auth.test.ts` exercises provider signup/signin with fake fetch. `test_verified_identity_to_onboarding_refresh_logout_and_expiry` uses a fake verified identity but real account/workspace/session provisioning, onboarding API, Vault reconciliation and `user.onboarded_at` persistence. `JourneyService.ensure_counselor` starts at the existing `IDENTITY` stage. |
| 2b Signout, invalid/expired session, refresh | PASS (offline) | Same test proves session rotation preserves the workspace and revokes the old token, logout revokes the new token, and invalid/expired tokens return 401. `test_browser_cookie_session_refresh_and_logout` proves HttpOnly/SameSite cookie restore and logout with a synthetic allowed origin. Existing auth-boundary/session tests remain green. |
| 2c Workspace isolation | PASS | OpenAPI-derived matrix checks all 49 GET/POST/PATCH/DELETE routes under events, counselor (including voice), roadmaps, student-profile, student-requests and files, each anonymously and as a different student (98 cases). Uses actual foreign workspace/file/roadmap records and schema-valid request bodies/uploads; only 401/403/404 count as denial, not validation errors. |
| 2d Generic onboarding | PASS after fix | Removed the five identity/location example placeholders from `frontend/lib/onboarding.ts`. Existing free-form identity/location fields, status/gender options and i18n labels contain no country, language or institution assumption. `frontend/lib/onboarding.test.ts` prevents those example answers returning. |

The HTTP matrix is in `backend/tests/test_p0_entry_audit.py`; it enumerates the
application's registered routes rather than maintaining a separate endpoint list.
Tests run in an isolated SQLite fixture using existing helpers. The fake provider
represents an already verified Supabase identity; it does not verify hosted
Supabase delivery, credentials or availability.

## Defects fixed

1. **Folder no-op bypassed the access check.** `PATCH /v1/files/folders` returned
   200 before authenticating when old/new paths matched. This was a success-status
   bypass, not demonstrated unauthorized data mutation. Moved only the no-op
   return after workspace/actor checks. The anonymous/foreign matrix covers the
   denial; `test_folder_noop_still_works_for_authenticated_owner` preserves owner behavior.
2. **Onboarding suggested specific identity/location answers.** Removed those
   placeholders without changing questions, layout or accepted values. Regression
   test: `does not suggest an identity or location using example answers`.

## PAI OS contract

No contract code changed. The new contract test asserts the exact
`pai_decision_records` and `pai_student_requests` table names and rejects absent
or wrong `PAI_OS_SERVICE_TOKEN` credentials on `POST /v1/escalations`.
Existing `test_internal_escalation_preserves_history_and_queues_replan` exercises
an authorized service-token escalation; roadmap decision snapshots and student
request persistence/isolation tests remain green.

## Baseline and final verification

| Run | Backend | Frontend | Build |
| --- | --- | --- | --- |
| Before production fixes (committed-source archive) | 631 passed, 3 skipped, 8 subtests passed | 22 passed | PASS |
| Final source with P0 tests/fixes | 733 passed, 3 skipped, 8 subtests passed | 23 passed (8 files) | PASS |

The three skips are existing production-only app-startup checks. An initial host
run with an older document parser had two DOCX-test failures; using the project's
required parser version in temporary test dependencies resolved them without a
production-code change. Temporary offline test setup blocked external sockets
(Windows asyncio loopback remained allowed) and resolved the host's unrelated
`tests` package namespace collision. Temporary dependencies/archive were removed
after verification and are not shipped.

Local stack was started using the documented Compose files and existing images,
with `up --no-build -d`, honoring the no-rebuild scope. Backend was healthy;
worker, frontend, Caddy, Postgres, Redis and Qdrant were running. Local backend
`/health` and frontend `/sign-in` returned 200. These are startup checks on the
existing images, not a claim that new source fixes were rebuilt/deployed there.
No student turn, live voice session or provider-backed job was submitted. Recent worker
log history contained an earlier database connection OperationalError; no new
OperationalError appeared in the last two minutes. This audit does not certify
background-job health from process status alone.

## Defects left and open questions

- No remaining defect was demonstrated by this audit. Hosted Supabase signup,
  email delivery, provider-token renewal and real voice negotiation remain
  unverified because this task requires fake providers/offline operation.
- The host-process origin configuration did not allow the checklist's localhost
  browser origin. Cookie tests use an explicit synthetic allowed origin to test
  the boundary independently of deployment settings. Which local browser origin
  should be allowed is a configuration question; `.env` was left unchanged.
- Current first stage is `IDENTITY`; broader planning documents describe later
  discovery terminology. No stage rename or new entry flow was invented in P0.
- Production-only startup checks remain skipped in the test environment. This
  report does not certify a production deployment or hosted provider integration.
