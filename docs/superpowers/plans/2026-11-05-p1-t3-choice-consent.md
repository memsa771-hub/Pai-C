# P1-T3: choice screens and consent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A student turns a chosen field into a full choice on new screens: destination, 1–5 places, intake, date of birth if the Vault lacks it, and consent. A guardian's consent by email is needed for under-18s. Giving or withdrawing consent writes a new decision version, and the OS pauses or resumes the plan.

**Architecture:**
- The Counsellor builds `ChoiceDetails` (T2) from the screen.
- Consent lives on the decision row. Each change of consent is a new version through a new `RouteDecisionService.update_consent()`.
- Guardian consent uses a hashed one-time link (72 h, single use, audit row).
- The OS kernel gains `pause_plan` / `resume_plan`. The intake pauses a plan, or holds a decision with no plan yet, when a required consent is missing. It no longer refuses that decision and bounces the student back to choosing.
- All of it runs only with `CONNECT_HANDOFF` on. With the flag off, the old `POST /v1/roadmap/choose {field_key}` works unchanged.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, DBOS (OS), Next.js/React + vitest, Resend email (existing `app/services/auth_emails.py`).

**Spec:** `docs/superpowers/specs/2026-11-04-p1-connection-core-design.md` §3.2 (P1-D3, P1-D5, P1-D10, P1-D11), §3.1. Master R-10, R-79 (screens), §6 rows 6.1, 6.14, 6.15. Exploration notes: the T3 code map in the session scratchpad (summarised below).

## Global Constraints

- **Flags.** With `CONNECT_HANDOFF` off (default), every existing request, response and screen behaves as today.
- **The Counsellor chat stays frozen (R-43).** The new screens are cards and dialogs, never chat turns.
- **Code locations.** Counsellor connection code goes in `backend/app/pai_c/connect/` (Python/YAML only, never `.md`). Glue that imports `app.os` lives only in `backend/app/pai_os_bridge.py`. `app/os` never imports Counsellor code (Tach).
- **No country names in `app/os` Python (R-58).** The country name → ISO list is Counsellor data (`pai_c/connect/countries.yaml`), with ISO 3166-1 alpha-2 codes only. Never invent other data.
- **The guardian email is personal data.** It is masked in every log line (`a***@domain`) and never sent to the OS. It is included in the student's data export and removed with the workspace (FK CASCADE).
- **Tokens.** `secrets.token_urlsafe(32)`, stored only as SHA-256, compared with `hmac.compare_digest`, expiring after 72 hours, single use. Every outcome writes an audit row.
- **Consent texts** live in `backend/app/pai_c/connect/consent_texts.yaml` (`version`, `approved`, one text per kind).
  - The owner approved the wording in chat on 2026-11-05 ("do it and I approve it"), so `approved: true` and `approved_by: "owner, chat 2026-11-05"`.
  - The gate still exists: with `approved: false`, the consent endpoints refuse (409) unless `CONNECT_CONSENT_DRAFT=true` (a new flag, default false, for tests and rehearsal).
  - Legal review stays in P5.
- **DB changes only by Alembic.** Counsellor next is `125`; the OS needs no migration (`paused` is already a valid plan status).
- **Checks.** Run `tach check` and `pytest tests/os` before pushing OS code. Never run `tests/os` and the legacy suite at once.
- **Tests and commits.** Tag tests with R-IDs. Commit messages end with the session attribution lines. Never weaken a test.

## Decisions taken in this plan (rulings; flagged to the owner in the PR)

- **D-f, what can be chosen.** The roadmap engine opens fields only for students before or at intermediate, leading to bachelor's fields; degree holders get `unknown`. T3 does not change the engine verdict (a Counsellor behaviour change). So the screens serve the cards the engine opens.
  - **Level:** from the field's next level (`study_fields.json` `levels`, `degree_levels`), else `bachelor` for a student before or at intermediate.
  - **Origin:** the Vault `location.current_country`, mapped to ISO; if it can't be mapped, the screen asks.
  - **Destination:** the student picks it on the screen. The options are the home country plus every destination of an OS route at that level, pre-selected from the Vault `preferences.target_countries` when it maps to ISO.
  - The Germany master's route stays reachable only through the OS self-serve builder (T6 sends that through the decision service).
- **D-g, places.**
  - Supported route: from the OS `programme_list` (new port `plan_query.routes()` and the existing `programme_list(route_key, intake)`).
  - Unsupported route: optional, from the student's completed stage H list (`opportunity_id` as `programme_ref`), 0–5.
  - Intake terms come from the route's playbook (a new optional playbook field `intake_terms`, filled for the Germany and test playbooks). Unsupported routes take any term from a connect YAML list (`pai_c/connect/intakes.yaml`, generic terms only) with a year from today to today + 3.
- **D-h, the stage H consent checkbox stays.** In `paths.tsx` it is the "explore places" consent, not the hand-off consent (spec §3.2 assumed otherwise). It is left unchanged.
- **D-i, under-18.** Age is counted on the day of the choice. A year-only or year-month date of birth that cannot prove 18 or over counts as under 18. Turning 18 later does not drop an already-required guardian consent (it stays on record).
- **D-j, consent missing.**
  - A plan that exists is **paused** (`consent_missing`).
  - A decision with no plan yet is **held** (intake status `held`, no escalation).
  - A later version with consent resumes the plan, or plans the held decision.
  - Paused plans send no reminders and promote no tasks.
- **D-k, T2 entry criteria.**
  1. Every route change from the screens carries `ChoiceDetails`.
  2. In `outbox.record`, a still-`pending` earlier decision counts like a `delivered` one when deciding to send a not-supported version.

## Review Focus

1. **A guardian clicks after the student has changed the choice.** The link is bound to the decision version it was issued for. If that is no longer the newest chosen version, the link says "this choice has changed" and writes nothing. → Task 4 test.
2. **The same link is opened twice, or after 72 h.** The second agree does nothing; an expired link shows "expired" and writes nothing. → Task 4 test.
3. **The student withdraws consent while the plan is mid-revision.** The pause goes through the kernel lock; no task is promoted after the pause. → Task 1 test.
4. **A year-only date of birth (e.g. "2009") on a choice made in 2026.** It counts as under 18 (D-i). → Task 3 test.
5. **The old client calls `POST /v1/roadmap/choose {field_key}` with the flag on.** It still works; the decision is `not_sent` / `not_supported` as in T2, and nothing crashes. → Task 5 test.

---

### Task 1: OS — pause and resume, and consent in the intake

**Files:** Modify `backend/app/os/kernel/kernel.py`, `backend/app/os/adapters/counsellor/intake.py`, `backend/app/os/adapters/counsellor/store.py` (status `held`), `backend/app/os/models.py` (intake status constant), `backend/app/os/workers/reminders.py`. Migration: none if `held` is not constrained; otherwise `os_0019_intake_held.py`. Test: `backend/tests/os/test_consent_pause.py`.

**Interfaces:**
- **Produces:**
  - `Kernel.pause_plan(plan_id: int, reason: str) -> bool`: active/at_risk → paused, event `plan_paused` with `{reason}`. False if the plan is already paused or closed.
  - `Kernel.resume_plan(plan_id: int) -> bool`: paused → active, event `plan_resumed`.
  - `_promote` does not ready tasks of a paused plan; `run_reminders` skips paused plans.
- **Produces, in the intake (`process`):** for a chosen v2 decision with `os_supported` true, when `authorized_at is None` or (`guardian_required` and `guardian_authorized_at is None`):
  - an open Counsellor plan on the same `external_ref` → `pause_plan(..., "consent_missing")`, result `IntakeResult("paused", "consent_missing", plan_id)`;
  - no plan → `IntakeResult("held", "consent_missing")`;
  - in both cases no escalation, and the `not_authorized` refusal no longer applies to v2.
  - With consent present and the plan paused: `resume_plan`, then today's revise path.
  - v1 exports keep today's `not_authorized` refusal.

- [ ] **Step 1: Write the failing tests (R-10; Postgres; reuse `tests/os/test_counsellor_intake_v2.py` helpers):**
  - `test_missing_student_consent_holds_without_escalation`
  - `test_guardian_missing_holds`
  - `test_consent_withdrawn_pauses_plan`: status paused, event reason, no reminders queued, no task promoted after a deadline passes.
  - `test_consent_given_again_resumes_and_revises`
  - `test_held_decision_planned_when_consent_arrives`
  - `test_pause_twice_is_noop`
  - `test_v1_not_authorized_unchanged`
- [ ] **Step 2: Run them, see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the new file plus `tests/os -k "counsellor or intake or kernel or reminder or handoff"`, then `tach check`.** All PASS.
- [ ] **Step 5: Commit** `feat(os): pause and resume a plan; consent missing holds or pauses (R-10, P1-D11)`.

### Task 2: Routes, places and intakes for the choice screen

**Files:** Modify `backend/app/os/ports/plan_query.py`, `backend/app/os/playbooks/models.py` (optional `intake_terms: list[str]`), `backend/app/os/playbooks/germany_master.v1.yaml` and the three test playbooks (add `intake_terms`), `backend/app/pai_os_bridge.py`. Create `backend/app/pai_c/connect/countries.yaml`, `backend/app/pai_c/connect/intakes.yaml`, `backend/app/pai_c/connect/places.py`. Tests: `backend/tests/os/test_routes_port.py`, `backend/tests/test_connect_places.py`.

**Interfaces:**
- **Produces (OS port):** `plan_query.routes() -> list[dict]`, each `{"key", "origin", "destination", "level", "intake_terms": [...]}` from the loaded playbooks.
- **Produces (bridge):**
  - `list_routes() -> list[dict]` and `programmes_for(route_key: str, term: str, year: int) -> list[dict]`, each `{"ref", "name", "university"}`;
  - both return `[]` on `OsUnavailable` or any error (logged).
- **Produces (`connect/places.py`):**
  - `to_iso(name: str) -> str | None`, using `countries.yaml` (case- and space-insensitive names → ISO-2);
  - `choice_options(db, workspace_id: str, field_key: str) -> dict`:
    `{"origin": iso|None, "level": str, "destinations": [{"code", "supported": bool, "route_key"|None}], "preselected_destination": iso|None, "intake_terms": {...per destination...}, "years": [int, ...]}`;
  - `places_for(db, workspace_id, destination, level, term, year) -> list[{"ref", "name"}]`: the OS list if supported, else the student's stage H programs.

- [ ] **Step 1: Write the failing tests:**
  - **OS side (Postgres):** `routes()` lists the Germany route and the fakes with their terms; `intake_terms` defaults to `[]`; no country names in OS Python (`test_invariants`).
  - **Counsellor side:**
    - `to_iso("Pakistan") == "PK"`, `to_iso(" germany ") == "DE"`, unknown gives `None`;
    - `choice_options` for a student before intermediate: level `bachelor`; origin from `location.current_country`; destinations = home plus the stubbed route destinations at that level; preselected from `preferences.target_countries`;
    - `places_for` on a supported route calls the bridge; on an unsupported route it returns the stage H programs;
    - the bridge returns `[]` when the OS is down.
- [ ] **Step 2: Fail.** **Step 3: Implement.** The YAML lists contain only names mapped to standard ISO codes, plus generic terms (`winter`, `summer`, `spring`, `autumn`, `fall`); a header comment says so.
- [ ] **Step 4: Run the new files plus `tests/os/test_playbooks.py tests/os/test_invariants.py`, then `tach check`.**
- [ ] **Step 5: Commit** `feat(connect): routes, places and intakes for the choice screen (R-79)`.

### Task 3: Consent core in the Counsellor

**Files:** Create `backend/alembic/versions/125_guardian_consents.py`, `backend/app/pai_c/connect/consent_texts.yaml`, `backend/app/pai_c/connect/consent.py`, `backend/app/pai_c/connect/age.py`, `backend/app/pai_c/connect/guardian.py`. Modify `backend/app/models.py` (`GuardianConsent`), `backend/app/pai_c/roadmap/decisions.py` (`update_consent`), `backend/app/pai_c/connect/outbox.py` (D-k 2), `backend/app/services/auth_emails.py` (3 emails), `backend/app/services/email.py` (mask the address in logs), `backend/app/security/auth_limits.json`, `backend/app/config.py` (`CONNECT_CONSENT_DRAFT`). Tests: `backend/tests/test_migration_125.py`, `backend/tests/test_guardian_consent.py`, `backend/tests/test_consent_versions.py`.

**Interfaces:**
- **Table `pai_guardian_consents`:**
  - `id`;
  - `workspace_id` (FK CASCADE), `decision_id` (FK `pai_route_decisions` SET NULL), `decision_version`;
  - `email`, `token_hash` (unique), `expires_at`, `used_at`;
  - `text_version`, `outcome` (`sent|agreed|withdrawn|expired|stale`), `created_at`.
- **`consent.py`:** `texts() -> dict`, `current_version() -> str`, `ensure_usable() -> None` (raises `ConsentTextNotApproved` when not approved and not `config.CONNECT_CONSENT_DRAFT`).
- **`age.py`:** `under_18(dob: str | None, on: date) -> bool | None` (None = no date of birth; D-i for partial dates).
- **`guardian.py`:**
  - `request(db, workspace_id, decision: RouteDecision, email: str) -> GuardianConsent`: rate-limited (`guardian_request`: user and email); sends the email with link `{APP_URL}/guardian/{token}`.
  - `open(db, token) -> dict`: `{"state": "ok|expired|used|stale", "text": ..., "student_first_name": ...}`.
  - `agree(db, token) -> str`: writes a new version with `guardian_authorized_at`; outcomes `agreed|expired|used|stale`.
  - `withdraw(db, token) -> str`: uses a withdraw link from the confirmation email, which is a new token.
- **`RouteDecisionService.update_consent(workspace_id: str, *, authorized_at: datetime | None | ellipsis = ..., guardian_authorized_at: datetime | None | ellipsis = ...) -> dict`:**
  - supersedes the active row and copies every field into a new version;
  - does not reschedule check-ins and does not touch the journey or possibilities;
  - calls `outbox.record`;
  - `...` means "unchanged".

- [ ] **Step 1: Write the failing tests (R-10):**
  - **Migration 125:** chains to 124; model matches; downgrade.
  - **Token:** stored hashed (the raw token is not in the DB); expires at 72 h (frozen clock); single use; a stale version gives `stale`; the rate limit gives a 429-equivalent error; an audit row for each outcome.
  - **Email:** sent once with the link, through a stubbed `send_email`; the log line shows the masked address only.
  - **`update_consent`:**
    - a new version with the same places and intake;
    - an outbox row when the flag is on;
    - no new check-in;
    - withdrawing the student consent clears `authorized_at`, the export has `authorized_at: null`, and the status stays `chosen`.
  - **`under_18`:** cases `"2009"` → True (on 2026-11-05), `"2007-11-04"` → False, `"2008-11-06"` → True, `None` → None.
  - **Text gate:** not approved and no draft flag → `ConsentTextNotApproved`.
  - **D-k 2:** a pending earlier row plus a not-supported change → pending.
- [ ] **Step 2: Fail.** **Step 3: Implement.** The consent texts are drafted by the implementer in plain English and short:
  - **student:** what is shared with the plan, that it can be withdrawn, and what happens then;
  - **guardian email:** who asks, what for, the link, the 72 h validity, and how to withdraw.

  They use `approved: true`, `approved_by: "owner, chat 2026-11-05"` and `version: "1"`. No legal claims, no country names.
- [ ] **Step 4: Run the new files plus `tests/test_decision_versions.py tests/test_decision_outbox.py tests/test_handoff_delivery.py tests/test_migration_124.py`, then `tach check`.**
- [ ] **Step 5: Commit** `feat(connect): consent texts, guardian link and consent versions (R-10)`.

### Task 4: HTTP API — choose with details, consent and the public guardian link

**Files:** Modify `backend/app/routers/roadmap.py`, `backend/app/main.py`. Create `backend/app/routers/guardian.py`. Tests: `backend/tests/test_roadmap_choice_api.py`, `backend/tests/test_guardian_api.py`.

**Interfaces:**
- `GET /v1/roadmap/choice-options?field_key=…` returns `choice_options` plus `consent_text` / `consent_version` and `needs_dob: bool`.
- `GET /v1/roadmap/places?destination=&level=&term=&year=`
- `POST /v1/roadmap/choose`:
  - the body is `{field_key}` (unchanged), or adds `details: {destination, places: [{ref, rank}], intake: {term, year}, date_of_birth?, consent: true, guardian_email?}`;
  - with details: `consent.ensure_usable()`; the date of birth is written to the Vault as `stated` when given and missing (the existing `routers/vault.py` write path); `guardian_required` comes from `under_18`, and a guardian email is required when it is set; `ChoiceDetails` is built, `choose(...)` called, then `guardian.request(...)` sent after commit;
  - the response is today's shape plus `choice: {version, places, intake, destination, level, os_supported, consent: {student, guardian}}`.
- `POST /v1/roadmap/consent/withdraw` and `POST /v1/roadmap/consent/give` (the student's own consent); `POST /v1/roadmap/guardian/resend`.
- Public, no auth: `GET /v1/guardian/{token}`, `POST /v1/guardian/{token}/agree`, `POST /v1/guardian/{token}/withdraw`. Rate-limited by IP (`guardian_open`), with no student data beyond the first name.

- [ ] **Step 1: Write the failing tests (R-10, R-79):**
  - the old body works with the flag on and off (Review Focus 5);
  - details with consent → a version with places and intake, outbox `pending` (stub `route_supported`);
  - an under-18 student without a guardian email → 422; an adult → no guardian needed;
  - a missing date of birth plus `date_of_birth` given → the Vault fact is stored as `stated`;
  - an unapproved text → 409;
  - consent withdraw → a new version, `authorized_at` null;
  - the guardian page: ok, agree, the second agree is used, expired, stale (Review Focus 1, 2);
  - the public routes never return the email.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Run the new files plus `tests/test_roadmap_api.py tests/test_handoff_delivery.py tests/test_connect_flags_off.py`.** **Step 5: Commit** `feat(connect): choice and consent API, public guardian link (R-10, R-79)`.

### Task 5: Data rights

**Files:** Modify `backend/app/pai_c/data_export.py`. Test: extend `backend/tests/test_export_counselor_session.py` (or the data-export test that exists).

- [ ] **Step 1: Write the failing tests (R-10):**
  - the export lists `places`, `intake`, `level`, `destination_country`, `os_supported`, `authorized_at`, `guardian_required`, `guardian_authorized_at` per decision;
  - `guardian_consents` list `email`, `outcome`, `text_version` and dates, but never `token_hash`. The email is added after `redact()` so it survives;
  - deleting the workspace removes the `pai_guardian_consents` rows (CASCADE, using the account deletion path).
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Run.** **Step 5: Commit** `feat(connect): consent data in the student's export (R-10)`.

### Task 6: Frontend — the choice flow and consent state

**Files:**
- Modify `frontend/lib/roadmap.ts` and `frontend/lib/api.ts` (`choiceOptions`, `places`, `chooseRoute(fieldKey, details?)`, `withdrawConsent`, `giveConsent`, `resendGuardian`).
- Create `frontend/components/counselor/workspace/choice-flow.tsx`, in steps: destination → places (1–5, reorder up/down) → intake → date of birth (`DobPicker`, only if `needs_dob`) → consent (the text from the API) → guardian email (only if under 18).
- Modify `frontend/components/counselor/workspace/roadmap-parts.tsx`: `RouteSheet` opens the flow when the API says the hand-off is on, else today's one-click choose; `YourRoute` shows the consent state, withdraw/give consent and guardian status.
- Modify `frontend/components/counselor/workspace/copy.json`: `roadmap.choice.*`, plain English.
- Tests: `frontend/components/counselor/workspace/choice-flow.test.tsx`; update `roadmap.test.tsx` and `frontend/tests/fixtures/counselor.ts` without loosening assertions.

**Interfaces:** `choice-options` returns `handoff: bool`. When it is false, the UI is today's.

- [ ] **Step 1: Write the failing tests (`// req: R-79`, `// req: R-10`):**
  - flag off: one-click choose, as in today's test;
  - flag on: steps in order; no more than 5 places; reordering changes the ranks; the date-of-birth step only shows when needed; under 18 requires the guardian email; submit calls `chooseRoute` with exact details;
  - consent withdraw in `YourRoute`;
  - accessibility: labelled inputs, focus moves to the first error.
- [ ] **Step 2: Fail.** **Step 3: Implement**, reusing `responsive-dialog` and the step pattern of `onboarding-view.tsx`. **Step 4: Run `npm test` and `npm run build` in `frontend/`.** **Step 5: Commit** `feat(connect): choice and consent screens (R-79, R-10)`.

### Task 7: The guardian page, the scripted flow and traceability

**Files:** Create `frontend/app/guardian/[token]/page.tsx`, `frontend/lib/guardian.ts`, `frontend/app/guardian/[token]/page.test.tsx`; modify `frontend/lib/i18n/messages/en-US.ts` (`guardian.*`). Create `backend/tests/os/test_connect_t3_flow.py`. Modify `docs/requirements/connection.yaml`.

- [ ] **Step 1: The guardian page (like `frontend/app/share/[token]/page.tsx`).** It shows the text, Agree, and the states expired, used and stale. Tests cover each state (`// req: R-10`).
- [ ] **Step 2: Scripted flow (Postgres OS with an app session, reusing the pattern of `tests/os/test_handoff_crash.py`; R-10, R-79).** The steps run in this order:
  1. The adult chooses a supported fake route with places and intake → planned.
  2. The student withdraws consent → paused.
  3. The student gives consent → resumed.
  4. An under-18 student chooses → held.
  5. The guardian agrees → planned.
  6. The guardian withdraws → paused.
  7. An unsupported route → nothing in the OS.
- [ ] **Step 3:** Set R-10 `built: true` (the mechanism; legal review stays P5, and the yaml title already says consent). R-79 is already built; add the screen tests to its tags. Run `python scripts/check_traceability.py`.
- [ ] **Step 4: Full checks, one after the other:**
  - the legacy suite (`--ignore=tests/os`), then `tests/os`;
  - `npm test`, then `npm run build`;
  - `tach check`, `check_freeze.py --base origin/pai-connect`, `check_alembic_heads.py`.

  Report the counts.
- [ ] **Step 5: Commit** `feat(connect): guardian page and the T3 flow test; R-10 built`.
