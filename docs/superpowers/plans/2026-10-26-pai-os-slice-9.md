# PAI OS Slice 9a: pilot-ready (the rehearsal), Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PAI OS ready for real pilot students and prove it first on 12 fictional students who run the whole
Germany master's route on rehearsal time and offline AI, then on 3 students with real AI.

**Architecture:** One shared clock (`app/os/clock.py`) with a database offset that only rehearsal mode reads;
rehearsal-only admin calls move time and run the scheduled jobs as one `os.rehearsal_tick` workflow. Offline AI is a
Pydantic AI `FunctionModel` per agent, answering from fixture files, allowed only in rehearsal mode. A test-side driver
(`tests/os/rehearsal/`) plays the students through the API against a real worker process. Pilot-facing pieces
(consent, menu, Resend, cost report) are ordinary PAI OS features.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic (`os` branch), PostgreSQL 16, DBOS, Pydantic AI, httpx, Next.js + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-pai-os-slice-9-design.md`

Paths are under `backend/` unless they start with `frontend/` or `docs/`.

## Global Constraints

- `OS_REHEARSAL` is off by default. Off: the stored offset is ignored, the rehearsal calls return 404, and the worker
  registers its cron schedules as today (S9-D7).
- `OS_MODEL_MODE` ∈ `openai` (default) | `offline`; `offline` without `OS_REHEARSAL=on` stops startup (spec §2.3).
- No direct `datetime.now`, `datetime.utcnow` or `date.today` in `app/os` outside `app/os/clock.py` (S9-D7).
- Exact values: advance 1–60 days per call; rehearsal start **1 Dec 2026**; stop at **30 Sep 2027**; stuck = **30**
  rehearsal days without change while nothing waits on the student (S9-D12); 12 students, short CI run S1, S3, S5;
  walkthroughs S1, S3, S9 at **375 px**; billed run S1, S3, S5, tenant `rehearsal-billed`, caps research 5,
  documents 4, statements 4, replan 2 (USD, total 15); D7 $10 per student per year, flagged at $8.
- Error codes, exactly: `consent_needed`, `consent_version`, `terms_not_set` (all 409). Outbox statuses after Task 7:
  `pending`, `sent`, `skipped`, `blocked`, `failed`. Failure severities: `blocks`, `workaround`, `wording`.
- No answers, student data or country words in `app/os` (invariant 12): offline answers and students are in
  `tests/os/rehearsal/`. Fictional data only; `~/spike2-docs` never enters the repo, chat or logs.
- Invariant 7: no retry code (Resend retries are DBOS step retries). Invariant 8: every email carries its outbox key.
- `docs/os/rehearsal.md` is updated in **every** task's PR (S9-D8): each added setting, table, endpoint, file, check
  or sender with where it lives, how it is switched, and how to remove it.
- One PR per task into `pai-os`, merged in order; PR body uses the template (Spec link, What changed, Rulings, Tests,
  How to see it work, Rules touched) and ends with the Claude Code line. Shared files (`frontend/lib/api.ts`,
  `frontend/components/layout/*`) need @memsa771-hub. Never open or prepare a `pai-os` → `dev` PR.
- Before every push: `tach check`, `python scripts/check_alembic_heads.py`, `pytest tests/os`; the legacy suite when a
  shared file changes; `npm test`, `npx tsc --noEmit` and the OS-enabled build when `frontend/` changes.
- No billed AI run without the owners' OK (Task 12 only).

## Review Focus

1. **A pilot server with a leftover offset row and rehearsal off** must use real time and must not expose the
   rehearsal calls. → `test_offset_ignored_when_rehearsal_off`, `test_rehearsal_calls_404_when_off` (Task 3).
2. **Two `advance` calls at the same moment** both count; time never goes back.
   → `test_concurrent_advance_adds_both` (Task 3).
3. **A student who agreed to v1 when v2 of the terms appears** cannot start a new plan or upload until they agree
   again, but their inbox and running plan keep working. → `test_new_terms_version_blocks_start_not_inbox` (Task 5).
4. **An allow-list entry with other case or spaces** (`" Ali@Example.com"`) matches the recipient
   `ali@example.com`. → `test_allowlist_normalises_case_and_space` (Task 7).
5. **An offline answer missing for one student's document** fails that call through the normal `invalid_output` path,
   is logged as a failure naming the missing key, and the other students carry on.
   → `test_missing_offline_answer_logged_run_continues` (Task 9).

---

### Task 1: Walkthrough sign-in and the rehearsal record

**Files:**
- Create: `docs/os/rehearsal.md`

**Interfaces:**
- Produces: `docs/os/rehearsal.md` with sections `Settings`, `Tables`, `Endpoints`, `Files`, `Checks`, `Senders`,
  `Walkthrough sign-in`, each a table (item | where | on/off | how to remove). Later tasks add rows.

- [ ] **Step 1: Find how a student signs in locally.** Read `_workspace_auth` in `app/main.py` and the frontend's
  sign-in. Start the local API, worker and frontend with `OS_ENABLED=true`, `NEXT_PUBLIC_OS_ENABLED=true`, and try
  creating one local test student account (test values from the project's seed or example config, recorded there, not
  in chat).
- [ ] **Step 2: Record the result** under `Walkthrough sign-in`: the exact steps for one walkthrough student, or
  "needs a real Supabase project". In the second case **stop and ask the owners** (spec §2.6); do not build a
  workaround.
- [ ] **Step 3: Write the empty tables** of `docs/os/rehearsal.md` and a short opening: what rehearsal mode is, and
  that every 9a PR updates this file.
- [ ] **Step 4: Commit** (`docs(os): Slice 9 Task 1, walkthrough sign-in and rehearsal record`) and open the PR.

### Task 2: The shared clock

**Files:**
- Create: `app/os/clock.py`, `tests/os/test_clock.py`
- Modify: every `app/os` file with a direct clock call (today: `adapters/counsellor/escalation.py`, `api/router.py`,
  `api/services.py`, `documents/run.py`, `documents/validators.py`, `kernel/kernel.py`, `knowledge/research/pages.py`,
  `knowledge/research/run.py`, `ports/plan_query.py`, `replan/apply.py`, `runner/worker.py`, `statements/run.py`,
  `workers/jobs.py`, `workers/manual.py`), `tests/os/test_invariants.py`, `docs/os/rehearsal.md`

**Interfaces:**
- Produces: `clock.now() -> datetime` (aware, UTC); `clock.today() -> date` (UTC date of `now()`);
  `clock.configure(offset: Callable[[], timedelta] | None) -> None` (Task 3 installs the reader; `None` = real time).

- [ ] **Step 1: Write the failing tests** in `tests/os/test_clock.py`:

```python
def test_now_is_aware_utc():
    assert clock.now().tzinfo is timezone.utc

def test_configured_offset_moves_now_and_today():
    clock.configure(lambda: timedelta(days=40))
    try:
        assert clock.now() - datetime.now(timezone.utc) > timedelta(days=39, hours=23)
        assert clock.today() == clock.now().date()
    finally:
        clock.configure(None)
```

  And in `tests/os/test_invariants.py`, `test_no_direct_clock_calls` (scans `app/os/**/*.py` except `clock.py` for
  `datetime.now(`, `datetime.utcnow(`, `date.today(`) plus `test_clock_check_catches_a_violation(tmp_path)` in the
  style of `test_write_check_catches_a_violation`.
- [ ] **Step 2: Run** `pytest tests/os/test_clock.py tests/os/test_invariants.py -q`. Expected: FAIL (no
  `app.os.clock`; the scan lists the current call sites).
- [ ] **Step 3: Implement `app/os/clock.py`** (module-level offset reader, default `None`) and replace every direct call
  with `clock.now()` / `clock.today()`. Defaults such as `Kernel(..., clock=None)` become `clock.now`; parameters that
  already take `now`/`clock`/`today` keep them.
- [ ] **Step 4: Run** `pytest tests/os -q`. Expected: all pass (behaviour unchanged).
- [ ] **Step 5:** add the clock and the check to `docs/os/rehearsal.md`; commit
  (`feat(os): Slice 9 Task 2, one shared clock`) and open the PR.

### Task 3: Rehearsal mode (stored offset, advance, tick)

**Files:**
- Create: `alembic/versions_os/os_0014_slice9_rehearsal_clock.py`, `app/os/rehearsal/__init__.py`,
  `app/os/rehearsal/store.py`, `app/os/rehearsal/api.py`, `app/os/rehearsal/tick.py`,
  `tests/os/test_rehearsal_mode.py`
- Modify: `app/os/settings.py`, `app/os/models.py`, `app/os/api/router.py`, `app/os/api/services.py`,
  `app/os/runner/worker.py`, `docs/os/rehearsal.md`

**Interfaces:**
- Consumes: `clock.configure` (Task 2).
- Produces:
  - `OsSettings.rehearsal: bool` (env `OS_REHEARSAL`, same truthy words as `OS_ENABLED`);
  - table `os_rehearsal_clock(tenant_id text PK, offset_seconds bigint not null default 0 check >= 0, updated_at)`;
  - `ClockStore(engine, tenant_id).offset() -> timedelta`; `.advance(days: int) -> timedelta` (one atomic
    `INSERT … ON CONFLICT DO UPDATE SET offset_seconds = offset_seconds + :s`; returns the new offset);
  - `install_clock(settings, engine) -> None`: `clock.configure(ClockStore(...).offset)` when `settings.rehearsal`,
    else `clock.configure(None)`; called by `make_services` and the worker's `build`;
  - `JOB_ORDER = ("deadline_engine", "reminders", "replan", "deliver_outbox", "freshness", "documents_retry",
    "reconcile")`; `run_tick(jobs: Mapping[str, Callable[[], object]]) -> list[str]` (runs those present, in order,
    returns the names run), registered as DBOS workflow `os.rehearsal_tick`;
  - routes (admin token; included only when `settings.rehearsal`): `POST /v1/os/admin/rehearsal/advance {days: int}`
    → `{offset_days: float, now: datetime}`; `POST /v1/os/admin/rehearsal/tick` → `{tick_id: str}`;
    `GET /v1/os/admin/rehearsal/tick/{tick_id}` → `{status: "running" | "done" | "error", ran: list[str]}`.

- [ ] **Step 1: Write the failing tests** in `tests/os/test_rehearsal_mode.py`:
  `test_advance_moves_now` (advance 10 → `clock.now()` ≈ real + 10 days);
  `test_concurrent_advance_adds_both` (two threads advance 5 → offset 10 days);
  `test_offset_ignored_when_rehearsal_off` (row with 30 days, settings off, `install_clock` → `clock.now()` ≈ real);
  `test_rehearsal_calls_404_when_off`; `test_advance_bounds` (0 and 61 → 422; 1 and 60 → 200);
  `test_advance_needs_admin` (401); `test_tick_runs_jobs_in_order` (`run_tick` with recording fakes, given out of
  order → recorded in `JOB_ORDER`); `test_worker_registers_no_cron_in_rehearsal` (build with rehearsal on → no
  `os.<job>` schedules, `os.rehearsal_tick` registered; off → today's schedules, no tick workflow);
  `test_startup_warns_in_rehearsal` (caplog, level WARNING, text contains "REHEARSAL MODE").
- [ ] **Step 2: Run** `pytest tests/os/test_rehearsal_mode.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the migration (downgrade drops the table), the model, the settings field, `store.py`,
  `tick.py`, `api.py`, and the worker change: collect job callables in a dict (today's `register_job` calls become
  entries); off → `register_job` each as today; on → register `os.rehearsal_tick` with that dict and no schedules. The
  tick route enqueues `os.rehearsal_tick` through the services' DBOS client and reads its status from DBOS.
- [ ] **Step 4: Run** `pytest tests/os -q`, `python scripts/check_alembic_heads.py`, `tach check`. Expected: pass,
  head `os_0014`.
- [ ] **Step 5:** add the setting, table, three endpoints and the workflow to `docs/os/rehearsal.md`; commit
  (`feat(os): Slice 9 Task 3, rehearsal mode`) and open the PR.

### Task 4: Offline AI

**Files:**
- Create: `app/os/agents/offline.py`, `tests/os/test_offline_ai.py`, `tests/os/rehearsal/answers/` (`documents.yaml`,
  `writer.yaml`, `critic.yaml`, `supervisor.yaml`, `research.yaml`), `tests/os/rehearsal/make_answers.py`
- Modify: `app/os/settings.py`, `app/os/knowledge/research/readings.py`, `app/os/runner/worker.py`, the cost function
  (wherever `price_*` is applied), `docs/os/rehearsal.md`

**Interfaces:**
- Consumes: `OsSettings.rehearsal` (Task 3).
- Produces:
  - `OsSettings.model_mode: str` (env `OS_MODEL_MODE`, default `openai`) and `offline_answers_dir: str | None`
    (env `OS_OFFLINE_ANSWERS_DIR`); `load_settings` raises `ValueError` for an unknown mode, for `offline` without
    rehearsal, and for `offline` without an answers dir;
  - `offline_model(agent_id: str, answers_dir: Path) -> FunctionModel` with model name `"offline"`;
  - `model_for_spec(settings: OsSettings, spec: AgentSpec) -> Model` in `readings.py`: offline → `offline_model`,
    else today's `model_for(settings, spec.tier)`. The four `register_*` functions in `worker.py` call it (the
    existing `OS_TEST_*_MODEL` hooks stay first);
  - cost of a run whose model is `"offline"` is 0;
  - answer files: `documents.yaml` maps the SHA-256 of the image bytes that reach the model (a page or a tile, as the
    pipeline sends them) to field values; `writer.yaml` maps statement kind to a draft text; `critic.yaml` is one
    passing output; `supervisor.yaml` maps event type to an operations list; `research.yaml` gives the "not found"
    reading for every field (no tool calls, so no fetch);
  - `python -m tests.os.rehearsal.make_answers` writes `documents.yaml` by running the sample bundles through the same
    render/tile functions the pipeline uses, keyed from the existing sample key.

- [ ] **Step 1: Write the failing tests** in `tests/os/test_offline_ai.py`:
  `test_offline_refused_without_rehearsal` (`load_settings({..., "OS_MODEL_MODE": "offline"})` raises `ValueError`
  naming `OS_REHEARSAL`); `test_unknown_mode_refused`; `test_document_answer_by_hash` (an agent on `offline_model`
  given sample page bytes returns the key's values); `test_missing_answer_fails_validation` (unknown bytes → the
  agent's output validation fails, which the pipeline records as `invalid_output`);
  `test_research_offline_makes_no_fetch` (offline research run on a fake profile → no page-fetch calls, facts
  unchanged); `test_writer_draft_within_word_limit`; `test_offline_cost_zero`.
- [ ] **Step 2: Run** `pytest tests/os/test_offline_ai.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `offline.py` (each agent's function reads the request messages: documents hash the first
  binary part; others answer from their file), the settings checks, `model_for_spec`, the worker wiring, the zero
  cost, and `make_answers.py`; generate and commit the answer files.
- [ ] **Step 4: Run** `pytest tests/os -q`, `tach check`. Expected: pass; the provider-SDK check still passes.
- [ ] **Step 5:** add `OS_MODEL_MODE`, `OS_OFFLINE_ANSWERS_DIR`, the answer files and `make_answers.py` to
  `docs/os/rehearsal.md`; commit (`feat(os): Slice 9 Task 4, offline AI for rehearsals`) and open the PR.

### Task 5: Pilot consent

**Files:**
- Create: `alembic/versions_os/os_0015_slice9_consents.py`, `app/os/consent/__init__.py`, `app/os/consent/store.py`,
  `app/os/consent/pilot.v1.md`, `tests/os/test_api_consent.py`, `frontend/components/os/consent-card.tsx`,
  `frontend/components/os/consent-card.test.tsx`
- Modify: `app/os/models.py`, `app/os/api/router.py`, `app/os/api/schemas.py`, test helpers that start plans or upload
  (`tests/os/test_api*.py`, `document_helpers.py`), `frontend/lib/api.ts`, `frontend/app/[workspaceId]/os-start/page.tsx`,
  `frontend/app/[workspaceId]/os-documents/page.tsx`, `docs/os/rehearsal.md`

**Interfaces:**
- Produces:
  - table `os_consents(id, tenant_id, student_ref, terms_version int, agreed_at timestamptz)`, unique
    (`tenant_id`, `student_ref`, `terms_version`);
  - `Terms(version: int, text: str, placeholder: bool)`; `current_terms() -> Terms` (highest `pilot.vN.md`, front
    matter `version`, `placeholder`);
  - `ConsentStore(engine, tenant_id).agree(student_ref, version) -> None` (idempotent), `.has(student_ref, version)
    -> bool`;
  - `GET /v1/os/consent` → `{version, text, placeholder, agreed: bool}`; `POST /v1/os/consent {version}` → 204;
    409 `consent_version` if not current; 409 `terms_not_set` if placeholder and rehearsal off;
  - `POST /v1/os/plans/self` and `POST /v1/os/documents` return 409 `consent_needed` without consent to the current
    version (checked before any other work);
  - test helper `agree(client, student="stu-1")` in `tests/os/test_api.py`;
  - `api.ts`: `getOsConsent(workspaceId)`, `agreeOsConsent(workspaceId, version)`.

- [ ] **Step 1: Write the failing tests** in `tests/os/test_api_consent.py`: `test_start_needs_consent`,
  `test_upload_needs_consent`, `test_agree_then_start`, `test_agree_twice_is_fine`,
  `test_old_version_refused` (`consent_version`), `test_placeholder_refused_outside_rehearsal` (`terms_not_set`),
  `test_placeholder_accepted_in_rehearsal`, `test_new_terms_version_blocks_start_not_inbox` (agree v1, add v2 in a
  tmp terms dir → start 409, `GET /inbox` 200). `consent-card.test.tsx`: renders the text and "This is a pilot",
  "I agree" calls `agreeOsConsent` with the version, a 409 shows "Please agree to the pilot terms first."
- [ ] **Step 2: Run** `pytest tests/os/test_api_consent.py -q` and `npm test -- consent-card`. Expected: FAIL.
- [ ] **Step 3: Implement** the migration (downgrade drops the table), store, terms loader (terms dir injectable for
  tests), routes, the two refusals, the card, and the two pages (card first on `os-start`; on `os-documents` when not
  agreed). `pilot.v1.md` holds `placeholder: true` and a marked placeholder text naming the points of spec §3.2,
  without country words. Add `agree(...)` to every existing test that starts a plan or uploads.
- [ ] **Step 4: Run** `pytest tests/os -q`, the legacy suite, `npm test`, `npx tsc --noEmit`, the OS-enabled build.
  Expected: pass, head `os_0015`.
- [ ] **Step 5:** add the table, endpoints, terms file and the two refusals to `docs/os/rehearsal.md`; commit
  (`feat(os): Slice 9 Task 5, pilot consent`) and open the PR (needs @memsa771-hub for `api.ts`).

### Task 6: Menu links

**Files:**
- Modify: `frontend/components/layout/nav-main.tsx`, `docs/os/rehearsal.md`
- Create: `frontend/components/layout/nav-main.test.tsx` (if none exists; else add to it)

**Interfaces:**
- Consumes: `OS_UI_ENABLED` from `frontend/lib/config.ts`.
- Produces: a menu group "Study abroad plan" with items Start (`os-start`), Inbox (`os-inbox`), Documents
  (`os-documents`), Programmes (`os-programmes`), Statements (`os-statements`), Pack (`os-pack`), Visa (`os-visa`),
  each `/<workspaceId>/<page>`, in the existing item shape, only when `OS_UI_ENABLED`.

- [ ] **Step 1: Write the failing tests:** `shows the study abroad group when OS is enabled` (7 links with those
  hrefs), `hides it when OS is disabled`.
- [ ] **Step 2: Run** `npm test -- nav-main`. Expected: FAIL.
- [ ] **Step 3: Implement** the group in `nav-main.tsx` (mobile sheet uses the same component).
- [ ] **Step 4: Run** `npm test`, `npx tsc --noEmit`, the OS-enabled build and the normal build. Expected: pass.
- [ ] **Step 5:** add the menu entry to `docs/os/rehearsal.md`; commit (`feat(os): Slice 9 Task 6, menu links`) and
  open the PR (shared file: @memsa771-hub).

### Task 7: Email through Resend

**Files:**
- Create: `alembic/versions_os/os_0016_slice9_outbox_statuses.py`, `tests/os/test_resend_sender.py`
- Modify: `app/os/settings.py`, `app/os/models.py` (`ck_os_outbox_status`), `app/os/outbox/senders.py`, the outbox
  delivery (`app/os/outbox/outbox.py`), `docs/os/rehearsal.md`

**Interfaces:**
- Produces:
  - settings `resend_api_key: str | None` (`OS_RESEND_API_KEY`), `email_from: str | None` (`OS_EMAIL_FROM`),
    `email_allowlist: frozenset[str]` (`OS_EMAIL_ALLOWLIST`, comma-separated, each stripped and lower-cased; empty =
    nobody); `load_settings` raises `ValueError` for `OS_EMAIL_SENDER=resend` without a key or a from address;
  - `class NotAllowed(Exception)`, `class Refused(Exception)` (carries the HTTP status) in `senders.py`;
  - `ResendSender(settings, http: httpx.Client)`: `send(msg)` raises `NotAllowed` if `msg.recipient.strip().lower()`
    is not on the list; otherwise `POST https://api.resend.com/emails` with `Authorization: Bearer <key>`,
    `Idempotency-Key: <msg.idempotency_key>`; 2xx → return; 4xx → `Refused`; 5xx / network → raise (the DBOS step
    retries);
  - `make_sender` returns it for `"resend"`; delivery marks `NotAllowed` → `blocked`, `Refused` → `failed`, logging the
    recipient as its SHA-256 only;
  - migration widens `ck_os_outbox_status` to the five statuses; downgrade sets `blocked`/`failed` rows to `skipped`.

- [ ] **Step 1: Write the failing tests** with `httpx.MockTransport`: `test_sends_with_idempotency_key`,
  `test_not_on_allowlist_is_blocked_not_sent` (no request made; row `blocked`), `test_empty_allowlist_sends_nothing`,
  `test_allowlist_normalises_case_and_space`, `test_4xx_marks_failed`, `test_5xx_raises_for_step_retry`,
  `test_resend_needs_key_and_from`, `test_log_never_contains_address` (caplog).
- [ ] **Step 2: Run** `pytest tests/os/test_resend_sender.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the settings, sender, delivery handling and migration.
- [ ] **Step 4: Run** `pytest tests/os -q`, `python scripts/check_alembic_heads.py`. Expected: pass, head `os_0016`.
- [ ] **Step 5:** add the sender and three settings to `docs/os/rehearsal.md` (and that the rehearsal keeps `log`);
  commit (`feat(os): Slice 9 Task 7, Resend sender with allow-list`) and open the PR.

### Task 8: Cost report

**Files:**
- Create: `app/os/costs.py`, `scripts/os_costs.py`, `tests/os/test_costs.py`
- Modify: `app/os/api/router.py`, `app/os/api/schemas.py`, `docs/os/rehearsal.md`

**Interfaces:**
- Produces:
  - `StudentCost(student_ref: str, documents_usd: Decimal, statements_usd: Decimal, replan_usd: Decimal,
    total_usd: Decimal, flag: Literal["ok", "alert", "over"])` (alert ≥ 8, over ≥ 10);
  - `CostReport(start: date, end: date, students: list[StudentCost], research_usd: Decimal, unlinked_rows: int,
    unlinked_usd: Decimal)`;
  - `cost_report(engine, tenant_id, start: date, end: date) -> CostReport`: document readings via their document's
    student; Writer/Critic runs via their artifact's student; Supervisor runs via their plan's student; research
    runs as the shared total; anything else counted as unlinked;
  - `GET /v1/os/admin/costs?from=YYYY-MM-DD&to=YYYY-MM-DD` (admin) → the report as JSON;
  - `python -m scripts.os_costs --from … --to …` prints one line per student plus the totals.

- [ ] **Step 1: Write the failing tests:** `test_costs_per_student` (seeded rows for two students → exact sums),
  `test_research_is_shared`, `test_unlinked_counted_not_guessed`, `test_flags_at_8_and_10`,
  `test_costs_needs_admin`, `test_date_range_inclusive`.
- [ ] **Step 2: Run** `pytest tests/os/test_costs.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `costs.py`, the route and the script (read only; no new tracking).
- [ ] **Step 4: Run** `pytest tests/os -q`. Expected: pass.
- [ ] **Step 5:** add the endpoint and script to `docs/os/rehearsal.md`; commit
  (`feat(os): Slice 9 Task 8, cost report`) and open the PR.

### Task 9: The rehearsal driver

**Files:**
- Create in `tests/os/rehearsal/`: `__init__.py`, `students.yaml`, `driver.py`, `failures.py`, `report.py`, `run.py`,
  `test_driver.py`, `test_rehearsal_short.py`
- Modify: `docs/os/rehearsal.md`

**Interfaces:**
- Consumes: Tasks 3–5 (advance, tick, offline AI, consent).
- Produces:
  - `students.yaml`: 12 entries `S1`…`S12`, each: `programmes` (2–4 refs from the seeded Germany list), `bundle`
    (Spike 2 sample bundle 1–5; S2 and S4 use bundles with planted mistakes), `answers` (interview answers, choices,
    admission result per programme), `event` (S3 `rejected`, S5 `missing_document`, S7 `late`, S9 `approved_changed`,
    S11 `ignore_big`, others none);
  - `Failure(id: str, student: str, step: str | None, expected: str, got: str, severity: Literal["blocks",
    "workaround", "wording"])`; `FailureLog(path).add(f)`, `.entries() -> list[Failure]` (YAML, outside the repo);
  - `Rehearsal(students: list[str], out_dir: Path, *, kill: bool = False)`: starts one worker subprocess
    (env `OS_REHEARSAL=on`, `OS_MODEL_MODE=offline`, `OS_OFFLINE_ANSWERS_DIR`, `OS_TEST_DATABASE_URL`), mounts the API
    in-process like `tests/os/test_api.py`'s `client` (student by header), runs spec §2.4 steps 1–5; with `kill`,
    SIGKILLs and restarts the worker at random ticks (as `tests/os/test_crash.py`);
    `.run() -> Report`;
  - `Report(students: dict[str, StudentResult], failures: dict[str, int])`, `StudentResult(state: str, events:
    list[str], days: int, reached: list[Literal["ready_to_submit", "visa_ready"]])`; written as `report.json` and
    `report.md` (counts and states only);
  - `python -m tests.os.rehearsal.run --students all|S1,S3 [--kill] --out ~/s9-rehearsal/<run>`.

- [ ] **Step 1: Write the failing unit tests** in `test_driver.py`: `test_students_file_valid` (12, events as listed,
  only fictional bundles), `test_failure_log_roundtrip`, `test_stuck_after_30_days` (fake plan state unchanged for 30
  advanced days with nothing waiting → a `blocks` failure "stuck"), `test_stop_at_30_sep_2027`,
  `test_missing_offline_answer_logged_run_continues` (one student's bundle hash removed from a copy of the answers →
  one failure naming the key; other students' results unaffected).
- [ ] **Step 2: Run** `pytest tests/os/rehearsal/test_driver.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the driver. Ready to submit = every chosen programme's `uni_assist_apply` or
  `direct_apply` is `waiting_student` and its pack approved; visa ready = `visa_apply` is `waiting_student` and the
  visa file approved. Each scripted event's expected change is checked as in spec §2.4's table; a miss is a failure.
- [ ] **Step 4: Write `test_rehearsal_short.py`** (S1, S3, S5; asserts both end states for each, S3's programme removed
  or swapped, S5's support case, `failures == {}`). Run it. If it fails because of product bugs, mark it
  `xfail(strict=True, reason="<failure ids>")`, log the failures, and leave the fixes to Task 11.
- [ ] **Step 5: Run** `pytest tests/os -q`. Expected: pass (or the one strict xfail).
- [ ] **Step 6:** add the driver, students file and command to `docs/os/rehearsal.md`; commit
  (`test(os): Slice 9 Task 9, rehearsal driver`) and open the PR.

### Task 10: Full rehearsals, kill run, walkthroughs

**Files:**
- Create: `tests/os/rehearsal/walkthroughs.md`, `docs/os/slice-9a-rehearsal-report.md`
- Modify: `docs/os/rehearsal.md`

- [ ] **Step 1: Write `walkthroughs.md`:** for S1, S3, S9 the steps of spec §2.6 in order, when to `advance`/`tick`,
  what to note (blocking, wrong, unclear), at 375 px.
- [ ] **Step 2: Run the full rehearsal** (`--students all`). Expected: a report and a failure log under
  `~/s9-rehearsal/full-1/`.
- [ ] **Step 3: Run the kill rehearsal** (`--students all --kill`, Linux). Expected: same end states as Step 2,
  0 lost, 0 duplicated (compare the two `report.json`).
- [ ] **Step 4: Do the three walkthroughs** with Claude agents in the built-in browser at 375 px against the local
  servers (sign-in per Task 1). Add each finding to the failure log with a severity.
- [ ] **Step 5: Write `slice-9a-rehearsal-report.md`:** counts per severity, end states, the kill comparison, and each
  failure's one-line summary (no personal data). Commit (`docs(os): Slice 9 Task 10, rehearsal findings`) and open
  the PR.

### Task 11: Fix pass

**Files:**
- Create: `tests/os/test_slice9_fixes.py`
- Modify: whatever each failure needs; `tests/os/rehearsal/test_rehearsal_short.py` (drop the xfail);
  `docs/os/rehearsal.md` if anything is added

- [ ] **Step 1: For each `blocks` and `workaround` failure** (and each `wording` one the owners want fixed): write a
  test that reproduces it, run it (RED), fix, run it (GREEN), and record `fixed_by` in the failure log.
- [ ] **Step 2: The four old minors (S9-D10), each RED→GREEN:**
  `test_accept_refused_while_paused` (Slice 7 #1: 409 while `changes_paused`);
  `test_empty_supervisor_answer_escalates` (#5: `ops=[]` opens a support case instead of `applied`);
  `test_cancel_programme_wording_when_steps_kept` (#6: the text no longer says all remaining steps are removed when a
  started or protected step is kept);
  `test_no_empty_what_changed_entry` (#7: a proposal that made no revision adds no "What changed" entry).
- [ ] **Step 3: Remaining failures** the owners accept as "not before the pilot": record `owner_accepted` with their
  words and date (ask them; do not decide for them).
- [ ] **Step 4: Rerun** the full rehearsal and the kill run. Expected: failure log clear (pass mark 4), the short
  rehearsal passes without xfail.
- [ ] **Step 5: Run** every check of the Global Constraints. Commit (`fix(os): Slice 9 Task 11, rehearsal fix pass`)
  and open the PR.

### Task 12: Billed run, gate and handoff

**Files:**
- Create: `docs/os/handoff/slice-9a-handoff.md`
- Modify: `docs/os/slice-9a-rehearsal-report.md`, `docs/os/rehearsal.md`

- [ ] **Step 1: Ask the owners** for the billed run's OK and cap (spec §10 Q1). Without a yes, stop here and write
  the handoff with pass mark 6 "not run".
- [ ] **Step 2: Run** `python -m tests.os.rehearsal.run --students S1,S3,S5 --billed --out ~/s9-rehearsal/billed`
  with `OS_MODEL_MODE=openai`, `OS_TENANT_ID=rehearsal-billed`, the four caps of the Global Constraints, a clean
  database and a budgeted PAI OS key set by the owners. (`--billed` only switches the worker env; it refuses to start
  unless all four caps are set and sum to ≤ 15.) Then `python -m scripts.os_costs` for the run's dates.
- [ ] **Step 3: Check the gate:** the seven pass marks, each with its number from the runs.
- [ ] **Step 4: Write `slice-9a-handoff.md`** (like `slice-8-handoff.md`): where things stand, the PR table, results,
  rulings, the failure summary, the cost figure for D7, the open owner items (spec §10) and the 9b next steps
  (spec §11). Point to `docs/os/rehearsal.md`, and check that it lists everything 9a added.
- [ ] **Step 5: Commit** (`docs(os): Slice 9a gate and handoff`) and open the PR.

---

## Plan-level rulings (recorded in the PRs that carry them)

1. The spec's single `os_0014` is split into `os_0014` (clock, Task 3), `os_0015` (consents, Task 5) and `os_0016`
   (outbox statuses, Task 7), so each task owns its migration.
2. Offline answers for documents are keyed by the SHA-256 of the bytes that reach the model (page or tile), and
   `make_answers.py` computes them with the pipeline's own render/tile functions, so the keys can't drift.
3. The rehearsal runs the API in-process and the worker as a subprocess, so the kill run can SIGKILL the worker only.
4. If the short rehearsal finds product bugs in Task 9, it lands as a strict xfail naming the failures; Task 11
   removes it.
5. `--billed` refuses to start unless the four caps are set and sum to at most $15.
