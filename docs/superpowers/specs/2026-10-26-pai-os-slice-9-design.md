# PAI OS Slice 9: the pilot (design)

Date: 2026-10-26. Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (§1 success criterion 1, §5 Spikes 5
and 6, §6 Slice 9, §10 student terms, §11 D3 and D7; invariants 7, 8, 11, 12, 13). FigJam: PAI OS review board
(`sEWRgciL9Quwmklh492qUW`, "Phases and gates": "3 Pilot (Slice 9): 10 to 20 real students, one intake. Gate: pilot
passes"; the setup table's "Student terms … Before pilot"). Builds on Slices 0–8 on `pai-os` (tip `b2e384c`).
Earlier "before the pilot" items: `docs/os/slice-1-readiness.md` §6, `docs/os/handoff/README.md` §8, and each slice
handoff's open items.

**Goal.** Get PAI OS ready for real students, prove it on fictional students first, then run the real pilot.
Slice 9 has two parts (S9-D1):
- **9a, pilot-ready (this spec and its plan):** a rehearsal in which fictional students, played by a script and by
  Claude agents, run the whole Germany master's route; the pieces a real student meets (menu, consent, email, a cost
  report); every failure fixed or put to the owners; one small billed run on real AI.
- **9b, the real pilot (outlined in §11, not designed here):** 10–20 real students, one intake. It gets its own full
  spec when 9a passes.

The pilot runs **standalone and self-serve**; the Counsellor module stays off (Slice 8, S8-D2).

**9a is done when (the 9a gate, S9-D6):**
1. every scripted student runs the whole route (the end state is checked in two places):
   - **ready to submit:** for each of their programmes the pack is approved and the apply step (`uni_assist_apply`
     or `direct_apply`) waits for the student (the student submits; PAI OS never does). The driver then reports it
     submitted;
   - **visa file ready:** after the driver reports an admission (S3's rejected programme aside), the visa file is
     reviewed and `visa_apply` waits for the student;
2. every scripted event gives the right change (§2.4);
3. no task is lost or duplicated, including a rehearsal with the worker killed at random points;
4. the failure log is clear: every entry fixed with a test, or put to the owners and accepted as "not before the
   pilot";
5. the three phone walkthroughs find nothing that blocks a student (confusing wording may stay, logged);
6. the billed run (3 students, real AI) finishes the route within its hard cap (S9-D9) and gives a cost-per-student
   estimate below the D7 ceiling ($10 per student per year);
7. the usual checks pass: `tests/os`, the Counsellor (legacy) suite, the standalone suite with the Counsellor off,
   Tach, the single-alembic-head check, and the frontend tests, `tsc` and the OS-enabled build.

## 1. Decisions (brainstorm with the user, 2026-10-26)

| # | Topic | Decision |
|---|---|---|
| S9-D1 | Split | Slice 9 is **9a (pilot-ready)** and **9b (the real pilot)**. This spec designs 9a in full and outlines 9b (§11). |
| S9-D2 | Rehearsal first | Before any real student, fictional students run the whole route. Real students are still needed for what fakes cannot show (real documents, missing playbook steps, real cost, real people on phones) and for the parent spec's success criterion 1; that is 9b. |
| S9-D3 | AI in the rehearsal | **Offline AI by default** (canned answers, no cost, repeatable). **One billed run** at the end with 3 of the students on real OpenAI, with the owners' OK and a hard cap (S9-D9). |
| S9-D4 | What 9a holds | (1) the rehearsal: clock, offline AI, fictional students, driver, failure log, report; (2) what a real student meets: menu links, pilot consent, email through Resend with an allow-list, a per-student cost report; (3) fixing: every failure the rehearsal finds, plus four old deferred minors that touch students (S9-D10). Left for 9b: the pilot server, monitoring and alerts, the qualified review of the terms, recruiting, the real run. |
| S9-D5 | How fictional students act | **A Python driver through the API** plays all 12 students (repeatable; a short version runs in CI), **plus 3 walkthroughs by Claude agents** in a browser at phone size against the real app and frontend (not repeatable tests; like a person trying the app). No Playwright. |
| S9-D6 | 9a gate | The seven pass marks above, set before building. |
| S9-D7 | Time | **One shared clock** (`app/os/clock.py`) for all of `app/os`, and a **rehearsal mode** (`OS_REHEARSAL=on`) in which it adds a forward-only offset stored in the database, so the API and the worker agree on "now". Admin-only calls move time and run the scheduled jobs. With rehearsal mode off, those calls return 404 and the offset is ignored. A check fails CI on any direct `datetime.now` / `date.today` in `app/os`. |
| S9-D8 | Record of what 9a adds | `docs/os/rehearsal.md` lists every setting, table, endpoint, file, check and sender 9a adds: what it is, where it lives, how it is switched on or off, how to remove it. Every 9a PR updates it; reviewers check it (user, 2026-10-26). |
| S9-D9 | Billed run cap | $15 in total, enforced by the existing monthly caps on a separate tenant (§2.7). **A proposal; the owners approve the figure and the run (§10 Q1).** |
| S9-D10 | Old deferred minors | Fixed in 9a whether or not the rehearsal hits them: Slice 7 #1 (accept while changes are paused), #5 (an empty Supervisor answer closes the event as applied), #6 ("its remaining steps are removed" wording when some are kept), #7 (an empty "What changed" entry). Other deferred minors are fixed only if the rehearsal hits them. Slice 8's minors are Counsellor-only and the module is off: they stay listed. |
| S9-D11 | Consent | A pilot consent screen before starting a plan. The text is a versioned file the owners write; a placeholder until then, and the placeholder cannot be accepted outside rehearsal mode. Starting a plan and uploading a document are refused without consent to the current version. |
| S9-D12 | Stuck | A plan is **stuck** when 30 rehearsal days pass with no change while nothing waits on the student. A stuck plan is a failure. |

## 2. The rehearsal

### 2.1 The shared clock (`app/os/clock.py`)

- `now() -> datetime` (UTC, timezone-aware, invariant 13) and `today() -> date`. Normally the real time.
- With `OS_REHEARSAL=on`: real time plus the offset in `os_rehearsal_clock` (one row per tenant), read on every call
  (rehearsal only, so no caching). The offset only moves forward; a clean database resets it.
- Every current `datetime.now(...)` / `date.today()` in `app/os` (about 18 places in 14 files) calls `clock.now()` /
  `clock.today()`. `Kernel`'s default clock and every injected `clock=` default become `clock.now`. Code that already
  takes `now` or `clock` as an argument keeps it (tests still pass their own).
- **Check:** `tests/os/test_clock_rule.py` scans `app/os` and fails on a direct `datetime.now`, `datetime.utcnow` or
  `date.today` outside `clock.py` (like the Slice 0 red-flag search).

### 2.2 Rehearsal mode (`app/os/rehearsal/`)

- `OS_REHEARSAL` (default off). Admin calls (the existing admin token header; 404 when rehearsal mode is off, so they
  do not exist on a pilot server):
  - `POST /v1/os/admin/rehearsal/advance {days}`: moves the offset forward (1–60 days per call);
  - `POST /v1/os/admin/rehearsal/tick`: enqueues one `os.rehearsal_tick` workflow on the worker that runs the
    scheduled jobs once, in a fixed order (deadline engine, reminders, replan, deliver outbox, freshness, documents
    retry, reconcile), and returns its ID; `GET …/tick/{id}` says when it has finished.
- In rehearsal mode the worker does **not** register its cron schedules, so real-time ticks never mix with
  rehearsal time; time-based work happens only through `tick`.
- **Startup warning:** with `OS_REHEARSAL=on` the API and the worker log a loud warning at start.

### 2.3 Offline AI (`OS_MODEL_MODE=offline`)

- `OS_MODEL_MODE` is `openai` (default) or `offline`. **`offline` is refused at startup unless `OS_REHEARSAL=on`**,
  so canned answers can never reach a real student.
- The model router returns a Pydantic AI `FunctionModel` per agent instead of OpenAI. Its answers come from files in
  `OS_OFFLINE_ANSWERS_DIR` (the fixtures live in `tests/os/rehearsal/answers/`; app code holds no answers, invariant
  12):
  - **Documents:** the field values for a page, looked up by the page's SHA-256 in the sample key (the existing
    Spike 2 sample maker writes both). Planted mismatches therefore reach the cross-checks as in real use.
  - **Writer:** a fixed draft built from the student's interview answers and confirmed profile (template fill), within
    the word limit. **Critic:** a passing score. **Supervisor:** a fixed answer per event type from the answer file.
  - **Research:** no web fetches; a research task ends with its facts unchanged (seeded facts stay as they are;
    unconfirmed stays unconfirmed, as the student would see it).
- Offline calls record `model = "offline"` and cost 0 in the existing cost rows. Output validation still runs
  (invariant 7 unchanged).

### 2.4 Fictional students and the driver (`backend/tests/os/rehearsal/`)

- **12 students** (`students.yaml`): invented names, degrees, grades, documents (the Spike 2 sample bundles, two of
  them with planted mistakes) and 2–4 programmes each from the existing Germany programme list. Test code: country
  words allowed (invariant 12 covers `app/os` only). Fictional data only.
- **Sign-in:** the driver mounts PAI OS's API in its own small FastAPI app with a rehearsal student dependency (the
  way the existing `tests/os` API tests do). No host code changes.
- **One rehearsal:**
  1. clean `os_test`, load the playbook and the existing programme facts, set the clock to **1 Dec 2026**, offline AI;
  2. each student accepts the consent, starts a self-serve plan, uploads their documents;
  3. loop: read the inbox; answer every item as the student file says (provide, approve, choose, act; "I submitted
     it" once the apply step waits; the admission result the student file gives); advance 1–3 days; tick; record
     anything unexpected; stop when every plan has `visa_apply` waiting, is stuck (S9-D12) or is past
     **30 Sep 2027**;
  4. **scripted events** and the change each must give:

     | Student | Event | Expected |
     |---|---|---|
     | S3 | rejected by one programme ("Not admitted") | that programme is removed, or swapped if below `min_programmes` (a suggestion; accepted) |
     | S5 | never uploads one document | reminders by slack, then an ask, then a support case |
     | S7 | answers late so a deadline is at risk | the blocking student step moves ahead and is asked for |
     | S9 | a new version of an approved statement | its review step is added back |
     | S11 | ignores a big suggestion | it expires; the plan carries on |
     | S2, S4 | documents with planted mistakes | the mismatch is shown and the student confirms the right value |

  5. **report** (`report.json` and a short Markdown summary; counts and states only, no personal data): per student
     the plan state, events and rehearsal days taken; totals; the failure log's counts by severity.
- **Kill run:** the same rehearsal with the worker SIGKILLed at random points (the Spike 3 / crash-test pattern;
  Linux only). Pass: every plan reaches the same end state as the run without kills, 0 lost, 0 duplicated.
- **CI:** `test_rehearsal_short.py` runs 3 students offline end to end (S1, S3, S5) in the normal suite. The full 12
  and the kill run are run by hand (`python -m tests.os.rehearsal.run --students all [--kill]`).

### 2.5 Failure log

- One YAML file per run, **outside the repo** (`~/s9-rehearsal/<run>/failures.yaml`). Each entry: id, student number,
  step (`template_key`), expected, got, severity (`blocks` | `workaround` | `wording`), and later `fixed_by` (PR) or
  `owner_accepted` (the owners' words and date).
- The driver writes entries for what it can see (a wrong state, a stuck plan, an error response, a missed expected
  change). The walkthroughs add theirs by hand.
- The gate's summary (counts, and each entry's one-line outcome) goes into the 9a handoff.

### 2.6 Phone walkthroughs

- Three of the 12 students (S1, S3, S9), played by Claude agents in a browser at phone width (375 px) against the
  local API, worker and frontend, with rehearsal mode and offline AI on.
- **Sign-in:** a local test account per walkthrough student in the host app. Task 1 finds how local sign-in works; if
  it cannot work without a real Supabase project, work stops and the owners are asked (no workaround is built).
- A written script per walkthrough (`tests/os/rehearsal/walkthroughs.md`): what to try (start, consent, upload, answer
  the interview, approve a draft, read a suggestion and accept it, read "What changed", reach the pack) and what to
  note (anything blocking, wrong or unclear). The `advance` / `tick` calls move time between steps.

### 2.7 The billed run

- After the offline rehearsals pass, and only with the owners' OK (§10 Q1): **S1, S3, S5** on real OpenAI
  (`OS_MODEL_MODE=openai`, rehearsal mode on), on a separate tenant `rehearsal-billed` and a clean database.
- **Hard cap $15**, enforced by the existing monthly caps set for the run: `OS_RESEARCH_MONTHLY_USD=5`,
  `OS_DOCUMENTS_MONTHLY_USD=4`, `OS_STATEMENTS_MONTHLY_USD=4`, `OS_REPLAN_MONTHLY_USD=2`. Hitting a cap is the
  system's normal "over budget" path (a support case), recorded as a result, not worked around.
- Output: the cost report (§3.4) for the 3 students, and any failures in the log. The figure goes to the owners for
  D7 (parent §11) and is the start of Spike 6.
- Research fetches real public pages (robots.txt respected, as in Slice 2). The documents are the fictional samples.
  **No real student document is used** (`~/spike2-docs` never enters the repo, chat or logs).

## 3. What a real student meets

### 3.1 Menu links

- A "Study abroad plan" entry in the student's menu leading to the PAI OS pages (`os-start`, `os-inbox`,
  `os-documents`, `os-programmes`, `os-statements`, `os-pack`, `os-visa`). Shown only when PAI OS is on (the existing
  OS-enabled build flag), so the shared frontend is unchanged when it is off. Mobile-first, like the pages. The menu is
  shared code: Counsellor review.

### 3.2 Pilot consent

- **Text:** `app/os/consent/pilot.v1.md` with front matter (`version: 1`, `placeholder: true` until the owners
  supply the text). It says, in plain words: this is a pilot; your documents and answers are sent to OpenAI to read
  them and write drafts (data location as the owners state it); how long we keep your files; you can ask us to delete
  your data. No country words (invariant 12).
- **Screen:** shown on `os-start` before anything else, and on `os-documents` if missing: the text and one "I agree"
  button. Mobile-first.
- **Storage:** `os_consents` (`tenant_id`, `student_ref`, `terms_version`, `agreed_at`), unique on (tenant,
  student, version).
- **API:** `GET /v1/os/consent` (current version, text, whether the student agreed), `POST /v1/os/consent {version}`
  (409 if not the current version). **A placeholder is refused** (409 `terms_not_set`) unless rehearsal mode is on,
  so no real student can start before the owners write the text.
- **Refusals:** self-serve start and document upload return 409 `consent_needed` without a row for the current
  version. A new version asks again. Existing tests get a consent helper.

### 3.3 Email through Resend

- `ResendSender` beside `LogSender` (`OS_EMAIL_SENDER=resend`), called by the existing outbox delivery job, so each
  email has its outbox key and goes once (invariant 8); the key is also sent as Resend's `Idempotency-Key`.
- Settings: `OS_RESEND_API_KEY` (set by the owners; never in chat, logs or the repo), `OS_EMAIL_FROM`,
  `OS_EMAIL_ALLOWLIST` (exact addresses, comma-separated; **empty means nobody**).
- An address not on the list is not sent: its outbox row is marked `blocked` and logged (the address hashed in the
  log).
- Network failures: DBOS step retries only (invariant 7). A refusal from Resend marks the row `failed` with the code.
- Tests use a fake HTTP server; no real email is ever sent from tests or the rehearsal (it keeps `log`).

### 3.4 Cost report

- `GET /v1/os/admin/costs?from=&to=` (admin token) and `python -m scripts.os_costs`: AI cost per student from the
  rows already recorded (document readings, statement Writer/Critic runs, Supervisor runs), each linked to the
  student through its document, statement or plan.
- Research is reported separately as a shared cost (one programme's research serves all students).
- Each student's total is set against D7 ($10 per year; flagged at $8). Rows that cannot be linked to a student are
  counted and shown as "unlinked", never guessed. No new tracking.

## 4. Tables (Alembic `os` branch, `os_0014`; every table has `tenant_id`)

| Table | Columns |
|---|---|
| `os_rehearsal_clock` | `tenant_id` (PK), `offset_seconds` (bigint ≥ 0), `updated_at` |
| `os_consents` | `id`, `tenant_id`, `student_ref`, `terms_version`, `agreed_at`; unique (`tenant_id`, `student_ref`, `terms_version`) |

The outbox's status check (`ck_os_outbox_status`: `pending`, `sent`, `skipped`) gains `blocked` (not on the
allow-list) and `failed` (refused by Resend). Downgrade drops both tables and turns `blocked` and `failed` rows into
`skipped`.

## 5. API (all under `/v1/os`)

| Call | Who | Notes |
|---|---|---|
| `GET /consent`, `POST /consent` | student | §3.2 |
| `POST /admin/rehearsal/advance`, `POST /admin/rehearsal/tick`, `GET /admin/rehearsal/tick/{id}` | admin | 404 unless rehearsal mode |
| `GET /admin/costs` | admin | §3.4 |

`frontend/lib/api.ts` gains the two consent calls (shared file: Counsellor review).

## 6. Screens

- **Consent** (`os-start` and `os-documents`): the terms text, "I agree", and a line "This is a pilot". A refused
  start shows "Please agree to the pilot terms first."
- **Menu entry** (§3.1).
- No other new screens. The walkthroughs check the existing ones at phone width.

## 7. Error handling

| Case | Result |
|---|---|
| `OS_MODEL_MODE=offline` without rehearsal mode | the API and the worker refuse to start, with the reason |
| An offline answer missing for a page or event | the call fails as `invalid_output` (the normal path); the driver logs a failure naming the missing answer |
| Rehearsal calls with rehearsal mode off | 404 |
| `advance` with days outside 1–60 | 422 |
| Consent to an old version | 409 `consent_version` |
| Consent while the text is a placeholder (rehearsal off) | 409 `terms_not_set` |
| Start or upload without consent | 409 `consent_needed` |
| Email address not on the allow-list | not sent; row `blocked` |
| Resend down | DBOS step retries; then the row waits for the next delivery run |
| A billed run reaches a cap | the normal over-budget path (support case); recorded as a result |

## 8. Invariants touched

- **7:** Resend failures retry only as DBOS step retries; offline answers still pass output validation.
- **8:** Resend sends carry the outbox key and an `Idempotency-Key`.
- **11:** the driver and walkthrough scripts live in `tests/`; `app/os` imports nothing from them. Tach unchanged.
- **12:** the consent text holds no country words; offline answers and fictional students are test data, outside
  `app/os`.
- **13:** one clock, always timezone-aware UTC; rehearsal time is real time plus an offset.
- 1–6, 9, 10 unchanged.

## 9. Build order (one PR per task, each into `pai-os`, merged in order)

| # | Task |
|---|---|
| 1 | Find how local sign-in works for the walkthroughs; start `docs/os/rehearsal.md` |
| 2 | The shared clock and the clock check (§2.1) |
| 3 | Rehearsal mode: `os_0014`'s clock table, `advance`, `tick`, no cron in rehearsal (§2.2) |
| 4 | Offline AI and its answer files (§2.3) |
| 5 | Pilot consent: table, API, screen, refusals (§3.2) |
| 6 | Menu links (§3.1) |
| 7 | Resend sender with the allow-list (§3.3) |
| 8 | Cost report (§3.4) |
| 9 | The driver, 12 students, failure log, report, the short CI rehearsal (§2.4–2.5) |
| 10 | Full rehearsals, the kill run, the three walkthroughs → failure log (§2.4–2.6) |
| 11 | Fix pass: a RED→GREEN test per fixed failure, and the four old minors (S9-D10) |
| 12 | Billed run (owners' OK), the gate, the 9a handoff (§2.7) |

Every task updates `docs/os/rehearsal.md` (S9-D8).

## 10. Open questions for the owners

1. **The billed run:** OK to run it, and is $15 the right cap (S9-D9)? Not run without your OK.
2. **The pilot terms text** (S9-D11), including data location and how long files are kept (Slice 3 spec §11 Q1). A
   qualified review is a 9b item.
3. **Where the pilot server lives** (9b): its own server from `pai-os`, or the real merge first. The rule "never open
   or prepare a `pai-os` → `dev` PR" stands until you decide.
4. **Still open from Slice 8:** confirm S8-D3 (the pilot opens when Slice 8 passes on the PAI OS side). With this
   spec, real students also wait for the 9a gate.
5. **D7:** confirm the cost ceiling once the billed run gives a figure.

## 11. 9b outline: the real pilot (not designed here)

- **Before students:** the pilot server (Q3) with `OS_ENABLED`, its own `OS_WORKER_ID` per replica,
  `OS_ADMIN_TOKEN`, rehearsal mode **off**; monitoring and alerts (uptime, errors, worker health, spend); the terms
  text with a qualified review (parent §10); the Resend domain, key and allow-list; the owners' hand-checks (Germany
  grade rounding `truncate`, TU Chemnitz Automotive `application_route`, student-requested programmes); D7 confirmed.
- **Running it:** 10–20 students for winter semester 2027 (D3), told it is a pilot; a weekly failure review; fixes
  through the normal PR flow; playbook gaps applied as upgrades (parent §4.3; Spike 5's pilot part); cost watched
  against D7 (Spike 6).
- **Gate:** parent §1 criterion 1: every plan runs to submission for the chosen programmes, every failure logged and
  fixed.

## 12. Rulings (decisions taken without the owners; agreed with the user in the brainstorm, 2026-10-26)

1. Slice 9 is split into 9a and 9b (S9-D1).
2. Fictional students rehearse the route before real ones (S9-D2).
3. The billed run's $15 cap is a proposal for the owners (S9-D9).
4. Consent blocks starting a plan and uploading a document; a placeholder text cannot be accepted outside rehearsal
   mode (S9-D11).
5. Offline AI needs rehearsal mode (§2.3).
6. The four old deferred minors chosen for the fix pass (S9-D10).
7. "Stuck" means 30 rehearsal days without change while nothing waits on the student (S9-D12).
8. In rehearsal mode the worker registers no cron schedules; time-based work runs only through `tick` (§2.2).
9. The driver mounts PAI OS's API in its own test app rather than going through host sign-in; host sign-in is covered
   by the walkthroughs (§2.4, §2.6).
10. Pass mark 1 is checked at two points, ready to submit and visa file ready, because the playbook puts the visa
    file after the admission result; the driver reports submission and admission as the student would (found while
    writing this spec; the brainstorm wording put both at one point).
11. Resend refusals use a new outbox status `failed` beside `blocked`; the outbox had only `pending`, `sent` and
    `skipped`.
