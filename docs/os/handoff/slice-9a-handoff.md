# PAI OS handoff: Slice 9a (pilot-ready) built (2026-10-29)

**A new session reads this file first, all of it.** It continues `slice-8-handoff.md` (and through it the earlier
handoffs), which still hold the environment, people, rules and history. Where they disagree, this file is newer.

Authority order: parent spec > Slice 9 spec > Slice 9 plan > the rulings in the PRs > this handoff.
- **Slice 9 spec and 9a plan:** `docs/superpowers/specs/2026-10-26-pai-os-slice-9-design.md`,
  `docs/superpowers/plans/2026-10-26-pai-os-slice-9.md` (#155).
- **Everything 9a added** (settings, tables, endpoints, files, checks, senders; how to switch each off and remove it):
  `docs/os/rehearsal.md`. It also holds the billed run's exact command.
- **The rehearsal's results and every failure's outcome:** `docs/os/slice-9a-rehearsal-report.md`.

## 1. Where things stand

9a is built and rehearsed. **All seven gate marks pass** (mark 5 with its stated limit). The billed run (mark 6) ran
on 2026-10-29 with real OpenAI: S1 reached `visa_ready` for **$0.49 in total**, research included. What remains is
the owners' confirmation of D7 (Q5) and the gate itself; no real student may start before 9b's entry conditions
(§7).

**Update 2026-10-30:** the user, on the owners' behalf, **confirmed D7 (Q5) and accepted the 9a gate** (ruling 34).
**9a is closed.** The same day the user decided the visa apply-by figure, 9b entry condition 1 (§7): 15 weeks
(rulings 35 to 37, branch `os/s9b-visa-lead`).

One PR per task, each into `pai-os`:

| Task | Branch | PR | What |
|---|---|---|---|
| 0 | `os/s9-spec` | #155 | Spec and 9a plan |
| 1 | `os/s9-t1-signin` | #156 | How local sign-in works for the walkthroughs; starts `docs/os/rehearsal.md` |
| 2 | `os/s9-t2-clock` | #157 | One shared clock (`app/os/clock.py`) and the clock check |
| 3 | `os/s9-t3-rehearsal` | #158 | Rehearsal mode: `os_0014` clock table, `advance`, `tick`, no cron in rehearsal |
| 4 | `os/s9-t4-offline-ai` | #159 | Offline AI (`OS_MODEL_MODE=offline`) and its answer files |
| 5 | `os/s9-t5-consent` | #160 | Pilot consent: `os_0015`, API, screen, refusals |
| 6 | `os/s9-t6-menu` | #161 | "Study abroad plan" menu links (phone drawer) |
| 7 | `os/s9-t7-resend` | #162 | Resend sender with the allow-list; `os_0016` outbox statuses |
| 8 | `os/s9-t8-costs` | #163 | Cost report (`GET /admin/costs`, `scripts.os_costs`) |
| 9 | `os/s9-t9-driver` | #164 | The rehearsal driver, 12 students, failure log, report, the short CI rehearsal |
| 10 | `os/s9-t10-rehearsals` | #165 | Full run, kill run, three walkthroughs, the findings report |
| 11 | `os/s9-t11-fixes` | #166 | The fix pass, batches A to D (`os_0017` rehearsal start; F1, F2, F3; screens; visa apply-by date; ticks after approval) |
| 12 | `os/s9-t12-gate` | #167 | `--billed` with its cap check, the gate, this handoff |
| — | `os/s9-fix-review` | #168 | The final review's fix pass, and the billed preflight |

- **Never open or prepare a `pai-os` → `dev` PR.** The owners merge once, at the very end.
- Merge policy since #162 (the user's choice A, 2026-10-27): the controller merges its own PRs into `pai-os` once the
  task review is clean and CI is green; PRs touching shared files (`api.ts`, `components/layout/*`, i18n,
  requirements) still wait for the Counsellor team. Never `dev` or `main`.
- The alembic `os` head is `os_0017`.

**Checks on `os/s9-t12-gate`** (`41587cb` plus this branch's change, 2026-10-29, Linux):
- `pytest tests/os`: **1366 passed, 1 skipped** (the German-locale test; pytest exit 0, 22 min; after Task 12 fix round 1);
- legacy, as CI runs it (`cd backend && env -u OS_TEST_DATABASE_URL python -m pytest -q`): **1809 passed, 577 skipped** (exit 0; the OS database tests skip without the URL, as on CI);
- the standalone suite with the Counsellor off (`tests/os/test_slice8_gate.py::test_standalone_suite_module_off`;
  the whole `tests/os` also runs with the module off, its default): **1 passed** (exit 0);
- `tach check` clean; the single-alembic-head check clean;
- frontend: Vitest **158 passed** (20 files), `npx tsc --noEmit` clean, `NEXT_PUBLIC_OS_ENABLED=true npx next build`
  passes.

### What 9a built
- **Rehearsal:** one shared clock with a rehearsal offset (`OS_REHEARSAL=on`), admin `start`/`advance`/`tick` calls
  (404 when rehearsal is off), offline AI from canned answers, a Python driver that plays 12 fictional students through
  the API against a real worker (with random SIGKILLs in the kill run), a failure log and report outside the repo, and a
  short CI rehearsal (S1, S3, S5).
- **What a real student meets:** the pilot consent screen and refusals (`consent_needed`, `consent_version`,
  `terms_not_set`); the "Study abroad plan" menu in the phone drawer and a header with a Menu button on every OS page;
  `ResendSender` with an allow-list (rehearsals keep `log`); a per-student cost report.
- **Fixes from the rehearsal** (Task 11): the statements list 500 (F3), steps left open after a programme is removed
  (F2), the visa step's date (F1, now an apply-by date before the visa programme's researched `semester_start`:
  6 weeks in 9a, 15 weeks since 2026-10-30, ruling 35), named per-programme inbox cards and a confirmation before "Not admitted", the 8 wording findings,
  paying and applying after approval (pack configs v2), the four old Slice 7 minors (S9-D10), and a rehearsal-only
  start date (`os_0017`) so the rehearsal does not depend on the real date.
- **Task 12:** `--billed` on the rehearsal command (see §3, mark 6).

## 2. Results

Final runs on the fix pass's last code (`2748b1b`, the same tree as `41587cb`), offline AI, the 12 students. Folders
outside the repo, in `~/s9-rehearsal/`.

| run | folder | end states | scripted events | failures | kills |
|---|---|---|---|---|---|
| Full | `full-5` | 12 of 12 `visa_ready`; 12 ready to submit, 12 visa file ready | 7 of 7 `:ok` (S2, S3, S4, S5, S7, S9, S11) | 1: `paused:S7` (owner-accepted) | 0 |
| Kill | `kill-5` | the same | the same | the same 1 id | 50 |

- Kill comparison (`~/s9-rehearsal/kill-compare-5.txt`, written in Task 12): 12 of 12 students have the same state,
  end points and event outcomes; the failure ids are identical; no `lost_tasks`, `duplicate:*` or `inbox_missing`
  entry. **Match.** The earlier pair `full-4`/`kill-4` (54 kills, on `2f82149`) matched in the same way.
- Admin steps: none (the driver no longer supplies any fact).
- The short CI rehearsal passes with no xfail.

## 3. The 9a gate (spec, top; S9-D6)

| # | Pass mark | Result | Evidence |
|---|---|---|---|
| 1 | Every scripted student runs the whole route (ready to submit, visa file ready) | **Pass** | `full-5`: 12 of 12 reached both end points; `kill-5` the same |
| 2 | Every scripted event gives the right change (§2.4) | **Pass** | `full-5` and `kill-5`: 7 of 7 scripted events `:ok` (S2 `mismatch_father_name`, S3 `rejected`, S4 `mismatch_date_of_birth`, S5 `missing_document`, S7 `late`, S9 `approved_changed`, S11 `ignore_big`); the short CI rehearsal checks S3's and S5's |
| 3 | No task lost or duplicated, also with the worker killed | **Pass** | `kill-5`: 50 SIGKILLs, 0 lost, 0 duplicated, same end states as `full-5` (`kill-compare-5.txt`) |
| 4 | The failure log is clear: fixed with a test, or accepted by the owners | **Pass** | 20 distinct ids from Task 10: 19 fixed with a test (`fixed_by` in the logs), 1 accepted (`paused:S7`, by the user on the owners' behalf). The final runs log only that one |
| 5 | The three phone walkthroughs find nothing that blocks a student | **Pass, with a limit** | Task 10's walkthroughs found 3 `blocks` (2 root causes); all are fixed (`78ce040`, `6fe27b6`). **The walkthroughs were not played again in a browser after the fix pass.** The screen fixes have Vitest tests, and batch B took 375 px screenshots against a mocked API (`~/s9-rehearsal/walkthroughs-2`). The owners' OK for the fake sign-in path was not seen |
| 6 | The billed run finishes within its cap and gives a cost per student below D7 | **Pass** | 2026-10-29, `~/s9-rehearsal/billed`: S1 only, caps 1.5/1/1/0.5 = $4 (the user: "as low as possible"). S1 reached `ready_to_submit` and `visa_ready` in 5 rehearsal days. **Total spend $0.49**, no model errors, no guard stop. Failure log: one driver false positive, `duplicate:draft_per_request` (§3 below). The first attempt, blocked by the network policy, spent $0 |
| 7 | The usual checks pass | **Pass** | See §1: `tests/os`, legacy, standalone (module off), Tach, the single head, Vitest, `tsc`, the OS-enabled build |

**Gate accepted** on 2026-10-30 by the user on the owners' behalf, with D7 confirmed (ruling 34).

**Cost figure for D7: $0.30 per student, plus $0.20 of shared research** (`scripts.os_costs`, tenant
`rehearsal-billed`). Even with all the research charged to one student, that is **$0.49 against D7's $10 per student per
year**.

| Part | Model | Calls | Cost |
|---|---|---|---|
| Documents (S1's own) | gpt-5.4 | 10 | $0.081 |
| Statements: Writer | gpt-5.4 | 12 | $0.109 |
| Statements: Critic | gpt-5.4 | 12 | $0.105 |
| Research (shared, 2 programmes) | gpt-5.4-mini | 17 | $0.196 |
| Replan | – | 0 | $0 |

Limits:
- **One student, the plain path.** Events, replans and a third programme would add some cost.
- **Research is shared.** Its cost falls per student as more students pick the same programmes.
- **`semester_start` came from the fictional seed** (ruling 31), not from research.

**Findings from the billed run** (fictional data; neither blocks 9a):
1. **The Critic never accepted a statement.** Each of the 6 Writer runs for the SOP and the CV ended with the Critic
   asking follow-ups. Each asked for the exact programme and university name and for programme features: S1's SOP is a
   bundle statement with no single programme. The driver answered each time, so each artifact got 6 versions before
   S1 approved one. This costs little ($0.21 for both) but is poor for a real student. For 9b: give the Writer and
   Critic the bundle's programme names, or tell the Critic that a bundle statement is generic on purpose.
2. **`duplicate:draft_per_request` is a driver false positive.** The check assumes one Writer version per draft request,
   which holds offline (the canned Critic always accepts). With a real Critic, every follow-up answer starts a new
   workflow (new inputs, new ID; invariant 8 holds), so the count is expected. For 9b: count follow-up answers as
   requests in the check.

**Found while building `--billed` (Task 12):** the four caps are **monthly on rehearsal time** (`month_spend` counts
from the start of the clock's month), and a billed rehearsal crosses several rehearsal months (S5 takes about 170
rehearsal days). So the caps alone would allow $15 again in each rehearsal month. The driver therefore has a
whole-run guard, checked after every wait for the worker: it stops the run at **$12** spent (the caps' sum minus the
larger of $1 and 20 %), after a wait that timed out (spend in flight unknown), or if the spend cannot be read. **Worst
case:** $12 plus the work in flight during one wait, so under $15 unless one wait's work costs more than $3. The stop
is recorded as an admin step (`billed_stop: ...`), not a failure. The owners should know that the spec's "hard cap
enforced by the monthly caps" holds per month only.

## 4. Rulings (binding unless the owners change them; each is in its PR)

**From the spec (§12, #155):** 9a/9b split; fictional students first; the $15 cap is a proposal; consent blocks start
and upload, a placeholder is refused outside rehearsal; offline AI needs rehearsal mode; the four old minors chosen;
"stuck" is 30 rehearsal days; no cron in rehearsal; the driver mounts the API in its own app; mark 1 is checked at two
points; Resend refusals get a new status `failed`.

**From the plan (#155):** (1) `os_0014` split into `os_0014`/`os_0015`/`os_0016`; (2) offline document answers keyed by
the SHA-256 of the bytes the model sees, computed with the pipeline's own functions; (3) API in-process, worker as a
subprocess; (4) the short rehearsal may land as a strict xfail, removed in Task 11; (5) `--billed` refuses unless the
four caps are set and sum to at most $15.

**Controller rulings (the ledger), in plain words:**
1. `--billed` is added in Task 12, not Task 9 (#164 stayed offline; built here).
2. Task 1 records only fictional, non-secret sign-in values, only in `rehearsal.md` (#156).
3. After each PR, wait for the owners' merge before the next task (process; later replaced by ruling 16).
4. Task 2 also fixes the three database-stamped times that rules read (daily replan limit, monthly spend, fact
   `checked_at`), so they follow the shared clock (#157).
5. The 24-hour programme-swap window moves to the shared clock (#157).
6. `counsellor_intake` is not in the tick; the Counsellor module is off for the pilot (#158).
7. A tick runs every job even after one fails, records each final failure, and reports `{ran, failed}` (#158).
8. The driver writes a fresh `documents.yaml` before each run and names a missing answer by recomputing its key (#159,
   carried into #164).
9. Pillow is not pinned in the shared `requirements.txt`; a loud test and the fresh answers cover it (#159).
10. The consent calls in `api.ts` take no `workspaceId`, like every other OS call (#160).
11. The menu group is its own OS component in the phone drawer; the desktop rail is not changed in 9a (#161).
12. Resend: `blocked` and `failed` are final; 5xx and network errors retry as DBOS steps; the address is logged only
    as a hash (#162).
13. Outbox recipients are student refs, not emails; no lookup is built in 9a; the rehearsal keeps `log` (#162).
14. No error column; a Resend 4xx code goes to the WARNING log only (#162).
15. 408 and 429 retry like 5xx instead of becoming `failed` (#162).
16. The controller merges its own PRs once review is clean and CI green; shared files still wait for the Counsellor
    team; never `dev`/`main` (the user's choice A, 2026-10-27).
17. The date-bound rehearsal tests are fixed in Task 11, not Task 9 (#164; done in #166 with `os_0017`).
18. Task 9 fixes the impossible duplicate check and its minors itself (#164).
19. Until Task 11, a late start is a loud named failure (`start_late`) rather than silent drift (#164).
20. The walkthroughs use the existing fake sign-in, one student playing S1, S3, S9 in turn on clean databases (#165).
21. Task 11 is split into batches A to D in one PR (#166).
22. F1: the visa date is derived from the programme's start date minus a playbook offset, with provenance, explained
    to the student (the user's choice B, #166).
23. That start is a new researched fact `semester_start`; the visa date is 6 weeks before it (the user's option A,
    #166). *The 6 weeks are superseded by ruling 35.*
24. F4 (`paused:S7`) is accepted as designed (S7-D9), by the user on the owners' behalf, 2026-10-28 (#166).
25. All 8 wording findings are fixed in Task 11 (the user's choice A, #166).
26. Paying and "applied" ticks come after approval: approval means "the contents are right" (#166).
27. The removal message wording (`rejected_kept`) is kept as it is (#166).
28. The 6-week date is the **apply-by** date for `visa_apply` (2 days to apply); the 90-day processing time is only an
    estimate in the text (the user's option A, #166). *Still the apply-by date; its figure is now 15 weeks (ruling
    35).*
29. The billed run is approved: S1, S3, S5, cap $15 (5/4/4/2), the owners set a budgeted key; the key is never
    printed, logged or committed (the user on the owners' behalf, 2026-10-29; this branch).
30. (Task 12, final design confirmed by the controller in fix round 1) A billed run also has a whole-run budget
    guard, because the caps are monthly on rehearsal time: checked after every wait for the worker, it stops at $12
    of $15 (margin: the larger of $1 and 20 %), after a timed-out wait, or on a spend query error; the stop is an
    admin step in the report, not a product failure, and stopped students get no `not_finished` (#167).
31. The billed run is reduced to **S1 only, caps 1.5/1/1/0.5 = $4** (the user: "as low as possible"). One full
    student journey gives the per-student figure D7 needs. It keeps the fictional `semester_start` seed: real
    research of it would add cost and could leave `visa_apply` waiting, which would stall the run. Real
    `semester_start` research is a 9b entry condition (§7).
32. `--billed` checks first that OpenAI can be reached (one `GET /v1/models`) and refuses with exit 2 if not. The
    first attempt ran 2 h against a blocked network (#168).
33. With rehearsal off, startup is refused while the tenant has a rehearsal clock row, so rehearsal data never
    becomes a pilot database. An unreachable database when the API is mounted is logged, not refused (#168).
34. D7 (Q5, $10 per student per year) is **confirmed** against the billed run's $0.49, and the **9a gate is
    accepted**: the user on the owners' behalf, 2026-10-30.
35. **The visa apply-by date** (9b entry condition 1, the user's decision, 2026-10-30): the semester start minus the
    processing time (`visa_processing_days`, 90) minus a 2-week buffer, rounded up to whole weeks because the note
    says `{weeks}`: **15 weeks, 105 days** (`visa_before_semester_days` in the playbook, invariant 12). The notes
    say why: "Apply by {due}: 15 weeks before your semester starts on {date}, so that the visa (about 90 days) can
    arrive in time." `germany_master.v1` is edited in place again: still no real students (invariant 10)
    (`os/s9b-visa-lead`).
36. **A passed apply-by date** (e.g. a July admission for an October start): the step says "Apply now, as soon as you
    can", warns that the visa may arrive after the semester starts and says how many days are left (the anchor's
    `note_passed` / `note_passed_earliest`). Its due date is the **semester start itself**, not today and not the
    passed date. The passed date would make the step overdue on the day it becomes possible (a daily escalation
    reminder, `deadline_at_risk`, an at-risk plan); "today" would move every day, so the step would always be due
    within 48 hours (twice-daily reminders) with negative slack (a new `deadline_at_risk` each day). The semester
    start is stable, is the last day applying still makes sense, gives normal slack-based reminders, and pulls
    nothing before the application deadlines. "Passed" means the apply-by day is before the compile day (the day
    itself still counts). The note's day count refreshes in place on each recompile (citations are not structural,
    so no revision); the switch itself is one revision (`os/s9b-visa-lead`).
37. **Task 11C kept:** 15 weeks before an October start (mid June) falls before typical application deadlines
    (15 July), so the date alone would pull the admission result and the applications weeks early. The visa step's
    dependency on `admission_result` is `pull: false` (a new playbook field): it still waits for the admission (a
    hard edge for the kernel), but its date does not pull it earlier. The visa preparation steps (blocked account,
    insurance, visa file) are still pulled by it. The regression test keeps its realistic dates (`os/s9b-visa-lead`).

**Other PR rulings:**
- #156: no sign-in workaround was built; the existing test entry point is only documented.
- #157: plain audit stamps written by the database stay real time.
- #158: `documents_retry` is ticked only on a worker with the documents pipeline configured.
- #159: research is blocked at the page gateway in offline mode; a missing answer is logged, not stored; the API
  refuses to start on a bad `OS_MODEL_MODE`.
- #160: tests agree to a test-only terms file; a rehearsal consent to the placeholder never counts once rehearsal is
  off; the terms loader is its own file.
- #162: the Resend key never reaches stored errors (`ProviderUnavailable` carries no httpx cause).
- #163: a row with several links goes to one bucket only; a cost on a deleted document is unlinked.
- #164: no `app/os` changes in the driver task; four extra document types drawn per student; students use the 3
  programmes with facts.
- #165: deviations disclosed (Playwright headless Chromium outside the project; S9's visa file built for the
  preselected programme); severities of `admission_card_unnamed` (`blocks`) and `no_menu_on_os_pages` (`workaround`).
- #166: the `germany_master.v1` playbook and research profile were edited in place (pre-pilot, no real plans); pack
  configs v1 → v2 rebuild every pack and visa file once; the rehearsal start is allowed only while the tenant has no
  plans.

## 5. Failure summary (Task 10's 20 ids)

| id | severity | outcome |
|---|---|---|
| F3 `http:S9:GET /statements:500` | blocks | fixed by `78ce040` |
| `walk:S3:statements_page_500` | blocks | fixed by `78ce040` (same cause as F3) |
| `walk:S9:cannot_change_approved_sop` | blocks | fixed by `78ce040` (same cause as F3) |
| `walk:S3:admission_card_unnamed` | blocks | fixed by `6fe27b6` |
| F1 `fact_missing:visa_target_date` | workaround | fixed by `9206ccc`, `4c8cd51`, `2f82149` (apply-by date from `semester_start`) |
| F2 `left_open:S3:removed_programme` | workaround | fixed by `78ce040`, `256fe9c` |
| F4 `paused:S7` | workaround | **owner-accepted**: "Accepted as designed (S7-D9) by the user on the owners' behalf, 2026-10-28" |
| `walk:S1:no_menu_on_os_pages` | workaround | fixed by `6fe27b6` |
| `walk:S1:inbox_programme_unnamed` | workaround | fixed by `6fe27b6` |
| `walk:S1:nothing_to_do_while_blocked` | workaround | fixed by `9206ccc` |
| `walk:S1:visa_admitted_label_one_only` | workaround | fixed by `6fe27b6` |
| `walk:S3:removed_programme_still_shown` | workaround | fixed by `6fe27b6` |
| `walk:S1:chip_unknown_says_being_researched` | wording | fixed by `6fe27b6` |
| `walk:S1:statement_programmes_raw_refs` | wording | fixed by `6fe27b6` |
| `walk:S1:datasheet_label_overlap` | wording | fixed by `6fe27b6` |
| `walk:S1:visa_how_to_apply_programme_text` | wording | fixed by `6fe27b6` |
| `walk:S1:plan_updated_notice_empty` | wording | fixed by `6fe27b6` |
| `walk:S1:documents_read_needs_tap` | wording | fixed by `6fe27b6` |
| `walk:S1:done_after_upload` | wording | fixed by `6fe27b6` |
| `walk:S1:ticks_before_approve` | wording | fixed by `6fe27b6` (wording), then the ticks moved after approval in `2748b1b` |

The `fixed_by` and `owner_accepted` fields are in `~/s9-rehearsal/full-1`, `kill-1` and `walkthroughs`
`failures.yaml`.

## 6. Open items for the owners

From spec §10, updated:
1. **Q1 the billed run:** approved by the user on the owners' behalf on 2026-10-29, reduced to S1 and $4 (ruling
   31). **Done** on 2026-10-29: $0.49 (§3). For the pilot, set a hard spend limit on the OpenAI project that owns
   the key: the driver's guard was a soft backstop, and the pilot has only the monthly caps.
2. **Q2 the pilot terms text** (data location, how long files are kept): still open. Until then the placeholder
   cannot be accepted outside rehearsal mode. A qualified review is a 9b item.
3. **Q3 where the pilot server lives** (its own server from `pai-os`, or the real merge first): open. The rule "never
   open or prepare a `pai-os` → `dev` PR" stands.
4. **Q4 S8-D3** (the pilot opens when Slice 8 passes on the PAI OS side): still to confirm. Real students also wait for
   the 9a gate, which waits for mark 6.
5. **Q5 D7** ($10 per student per year): the billed run measured **$0.49 for one student**, all research included
   (§3). **Confirmed** by the user on the owners' behalf, 2026-10-30 (ruling 34).

Raised during 9a:
6. **Visa timing:** `visa_before_semester_days` was 6 weeks (an apply-by date), while a visa usually takes about 90
   days. **Resolved** 2026-10-30 (the user): 15 weeks, with an "Apply now" warning once the date has passed
   (rulings 35 to 37).
7. **Email recipients:** outbox recipients are student refs, not addresses. Resend needs a student → email lookup
   (through a port, invariant 11) before the pilot; until then every row would be `blocked`.
8. **Walkthrough sign-in:** the owners' OK for the fake sign-in path (one fixed student) was never seen. If refused,
   the walkthroughs are redone with a Supabase project.
9. **Desktop menu link:** the "Study abroad plan" group is only in the phone drawer; a desktop link is a small
   follow-up in a shared file (`nav-rail.tsx`).
10. **"After approval" and the pack-config v2 rebuild:** moving to v2 rebuilt every pack and visa file once and sent
    approved ones back through review. Only test data exists now; any future config version bump does the same to
    real students (and 3 or more approvals in a day can hit the daily pause).
11. **Removal message wording** (`rejected_kept`) was kept as it is; the owners may still want it changed.

**Deferred minors** (not fixed; for a later pass):
- Docs (Task 1): the "expected" log error line is from the run, not checked in code; the `createdb` password sits in a
  comment; the Playwright `page.evaluate` wrapper is not in a code block.
- Clock check (Task 2): it misses `datetime as dt; dt.now()` and `datetime.today()` (none in the code today).
- Tick (Task 3): the tenant prefix check is theoretical with a `:` in a tenant id.
- Offline AI (Task 4): `offline.py` parses live prompt formats (`Write {phrase},`, `Rubric:`, `<<<PLAN>>>`); tests
  catch drift.
- Consent (Task 5): an upload failure on `os-documents` makes an extra `getOsConsent` call; `agreeOsConsent` copies
  `requestJson`'s auth/401 logic.
- Menu (Task 6): the tooltip repeats the label; no active-route highlight in the drawer.
- Resend (Task 7): `httpx.Client` is never closed (process lifetime); `OS_EMAIL_SENDER` is not normalised. Watch
  `test_confirmed_fact_completes_task_and_redates_plan` as possibly flaky.
- Costs (Task 8): an import placed late in `router.py`; no test for a two-link row or a cross-tenant link.
- Fix pass (Task 11): the kernel should not create empty "plan updated" notices; some long lines; the real-date test
  does not cover the `direct_apply` branch; "admitted excludes others" is untested at service level; the locale test
  skips in CI; a pre-approval tick sent through the API shows as a locked checked box; the `no_candidate:visa`
  wording when every programme is removed; v1 playbook text edited in place (display only); the driver records
  `after:<key>` before its PUT.
- Rehearsal coverage: students without an event finish in 1 to 2 rehearsal days (steps start when their dependencies
  are done), and only 3 of the 29 seeded programmes have the facts an application step needs.
- Slice 8's minors are Counsellor-only (the module is off) and stay listed in `slice-8-handoff.md`.

## 7. Next steps

**To close 9a:** the owners confirm D7 (Q5) against the billed run's figure (§3) and accept the gate. **Done**
2026-10-30: the user, on the owners' behalf, confirmed D7 and accepted the gate (ruling 34). The billed run
has now tested real research page fetches and the `--billed` path end to end. Optionally replay the three
walkthroughs in a browser on the fixed code.

**The final whole-slice review (2026-10-29)** found the work ready for 9b planning, with 0 Critical. Its cheap
findings were fixed in #168. Three findings are **9b entry conditions**, to be settled before any real student:
1. **The visa apply-by figure.** Applying 6 weeks before the semester contradicts the ~90-day processing time shown
   in the same note. The owners choose `visa_before_semester_days`. **Resolved** 2026-10-30 (the user's decision):
   15 weeks (105 days), "Apply now" once passed, no pull on the admission (rulings 35 to 37, `os/s9b-visa-lead`).
2. **Real research of `semester_start`,** plus an admin runbook for supplying it when research can't find it.
3. **Usable email:** a recipient lookup port; real templates (today the body is the raw payload); and 401/403/422
   from Resend treated as configuration errors that stop and alert, not as rows marked `failed`.

**9b, the real pilot (spec §11, its own full spec once 9a passes):**
- **Before students:** the pilot server (Q3) with `OS_ENABLED`, its own `OS_WORKER_ID` per replica, `OS_ADMIN_TOKEN`,
  rehearsal mode **off**; monitoring and alerts (uptime, errors, worker health, spend); the terms text with a qualified
  review; the Resend domain, key and allow-list (and the recipient lookup, item 7); the owners' hand-checks (Germany
  grade rounding `truncate`, TU Chemnitz Automotive `application_route`, student-requested programmes); D7 confirmed.
- **Running it:** 10 to 20 students for winter semester 2027 (D3), told it is a pilot; a weekly failure review; fixes
  through the normal PR flow; playbook gaps applied as upgrades (Spike 5's pilot part); cost watched against D7
  (Spike 6).
- **Gate:** parent §1 criterion 1: every plan runs to submission for the chosen programmes, every failure logged and
  fixed.
