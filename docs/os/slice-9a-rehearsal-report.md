# Slice 9a rehearsal report (Task 10)

Date: 2026-10-28. Branch `os/s9-t10-rehearsals` (from `pai-os` at `3094c9f`). Offline AI, rehearsal mode, the 12
fictional students of `backend/tests/os/rehearsal/students.yaml`. Counts and states only; no personal data. The run
folders (`~/s9-rehearsal/full-1`, `kill-1`, `walkthroughs`) stay outside the repo (spec §2.5).

## Summary

| run | command (from `backend/`) | runtime | end states | failures |
|---|---|---|---|---|
| Full | `python -m tests.os.rehearsal.run --students all --out ~/s9-rehearsal/full-1` | 447 s | 12 of 12 `visa_ready`; 12 ready to submit, 12 visa file ready | 4 (blocks 1, workaround 3) |
| Kill | `python -m tests.os.rehearsal.run --students all --kill --out ~/s9-rehearsal/kill-1` | 604 s, 54 worker SIGKILLs | the same as the full run | the same 4 ids |
| Walkthroughs | S1, S3, S9 by hand, headless Chromium at 375 px (`walkthroughs.md`) | about 10 min each once the stack ran | S1 and S3 reached both end points; S9 reached both, but its scripted event could not be played | 16 (blocks 3, workaround 5, wording 8) |

**All failures (distinct ids): 20. blocks 4, workaround 8, wording 8.** The 4 `blocks` entries come from **2 root
causes**: F3 (`http:S9:GET /statements:500`, also behind `walk:S3:statements_page_500` and
`walk:S9:cannot_change_approved_sop`) and the unnamed admission-result cards (`walk:S3:admission_card_unnamed`). Both driver runs exit 1 because the failure
log is not empty (expected while F1 to F4 are open).

## End states (full run; the kill run matched)

| student | state | rehearsal days (full / kill) | end points | event |
|---|---|---|---|---|
| S1 | visa_ready | 2 / 1 | ready to submit, visa ready | - |
| S2 | visa_ready | 2 / 1 | both | mismatch father's name: ok |
| S3 | visa_ready | 2 / 1 | both | rejected: ok |
| S4 | visa_ready | 2 / 1 | both | mismatch date of birth: ok |
| S5 | visa_ready | 170 / 171 | both | missing document: ok |
| S6 | visa_ready | 2 / 1 | both | - |
| S7 | visa_ready | 142 / 140 | both | late: ok |
| S8 | visa_ready | 2 / 1 | both | - |
| S9 | visa_ready | 2 / 1 | both | approved changed: ok |
| S10 | visa_ready | 2 / 1 | both | - |
| S11 | visa_ready | 11 / 9 | both | ignore big: ok |
| S12 | visa_ready | 2 / 1 | both | - |

Admin steps in both runs: `visa_target_date` (F1).

## Kill comparison

Compared `full-1/report.json` with `kill-1/report.json` per student (state, end points reached, event outcomes) and
the two failure logs' ids:

- 12 of 12 students: same state, same end points, same event outcomes. **Match.**
- Failure ids: identical (the four below). No `lost_tasks` entry (0 lost) and no `duplicate:*` entry (0 duplicated:
  the driver's six duplicate checks found nothing after 54 kills).
- Rehearsal days differ by 1 to 2 days: the kill run draws extra random numbers (kill points) from the same seed, so
  its day steps differ. Not a failure.

## Failures

### From the driver (both runs)

| id | severity | one line |
|---|---|---|
| F3 `http:S9:GET /statements:500` | blocks | Once a pack exists, the statements list includes pack and visa artifacts and fails response validation (500) |
| F1 `fact_missing:visa_target_date` | workaround | `visa_apply` waits on `visa_target_date`, which no source gives; the admin supplies a rehearsal value |
| F2 `left_open:S3:removed_programme` | workaround | Removing a rejected programme leaves its 5 `confirm_fact` steps open (`waiting_review`) |
| F4 `paused:S7` | workaround | S7's plan hits the daily limit of 3 automatic changes; one event waits for a person (possibly by design, S7-D9) |

### From the walkthroughs (`~/s9-rehearsal/walkthroughs/failures.yaml`)

| id | severity | one line |
|---|---|---|
| `walk:S3:admission_card_unnamed` | blocks | Two identical "Tell us this programme's admission result" cards with no programme name. Blocks because a wrong tap on "Not admitted" is recorded at once, with no confirmation, the card then leaves the inbox so the result cannot be changed there, and the plan goes on to suggest removing the programme that admitted the student |
| `walk:S3:statements_page_500` | blocks | Same cause as F3. The statements page shows "Could not load your statements" once a pack exists (same cause as F3); seen for S3 and S9, not only S9 |
| `walk:S9:cannot_change_approved_sop` | blocks | Same cause as F3. S9's scripted event (change an approved SOP) cannot be done in the browser, because of F3 |
| `walk:S1:no_menu_on_os_pages` | workaround | The OS pages have no menu or header at 375 px; the "Study abroad plan" links are only in the host drawer, whose home page first shows the host onboarding form; pages were reached by URL. `workaround` because the host drawer has the links, but the OS pages themselves offer no way back to it; it would be `blocks` if that drawer cannot be reached from the OS pages on a phone |
| `walk:S1:inbox_programme_unnamed` | workaround | Per-programme inbox steps show as identical cards with no programme name; only the "programme facts" link hints which |
| `walk:S1:nothing_to_do_while_blocked` | workaround | After the visa file is approved the inbox says "Nothing to do right now" while the plan waits on F1 |
| `walk:S1:visa_admitted_label_one_only` | workaround | With two admissions, only one programme is marked "(admitted)" and the visa file is built for it without asking (behaviour, not only wording) |
| `walk:S3:removed_programme_still_shown` | workaround | After the removal is accepted, the removed programme's pack still shows "approved" and the programmes page and visa "For" list still offer it (with F2) |
| `walk:S1:chip_unknown_says_being_researched` | wording | All programmes on the start page say "being researched", including the 3 that have facts (verdict unknown before documents) |
| `walk:S1:statement_programmes_raw_refs` | wording | The statements page lists programmes by internal ref, not by name |
| `walk:S1:datasheet_label_overlap` | wording | In the data sheet at 375 px the "IELTS TRF number" label and value run together |
| `walk:S1:visa_how_to_apply_programme_text` | wording | The visa file's "How to apply" speaks of "this programme" and "the university" |
| `walk:S1:plan_updated_notice_empty` | wording | "Your plan was updated" appears while "What changed" says "No changes yet." |
| `walk:S1:documents_read_needs_tap` | wording | A read document says only "read"; nothing says to tap it to check the values; some labels are technical ("Mrz line1") |
| `walk:S1:done_after_upload` | wording | Provide steps keep a "Done" button after their documents are uploaded and confirmed |
| `walk:S1:ticks_before_approve` | wording | "Paid the application fee" and the visa "Applied" / "Paid" ticks sit before approval; unclear whether they are needed first |

## How the walkthroughs ran

- Stack: the API through `scripts.offline_startup_app:app` (`PAI_OFFLINE_STARTUP_CHECK=1`, `OS_ENABLED=true`) with
  `OS_REHEARSAL=on`, `OS_MODEL_MODE=offline`, a temporary `OS_OFFLINE_ANSWERS_DIR` built as the driver builds it,
  a fictional `OS_ADMIN_TOKEN`, `OS_EMAIL_SENDER=log`; the worker (`python -m app.os.runner.worker`, same environment);
  the frontend dev server with `NEXT_PUBLIC_OS_ENABLED=true`. Every piece ran in this container; both processes logged
  the "REHEARSAL MODE" warning.
- Sign-in: the fake token of the offline entry point. It gives **one fixed student**, so S1, S3 and S9 were played in
  turn, each on a fresh database (controller ruling; the user chose this recommendation). **The owners' explicit OK
  for this sign-in path (spec §2.6, `rehearsal.md` "Walkthrough sign-in") was not seen.**
- Browser: Playwright's headless Chromium at 375 x 812, touch, from a scratch script outside the repo (not added to
  the project). No page was wider than 375 px. The Next.js dev-tools button overlapped checklist boxes and caught a
  tap; it was hidden for the rest of the run (dev server only, not a product finding).
- Time moved with the admin `advance` and `tick` calls between steps; `visa_target_date` was supplied as the admin, as
  the driver does (F1).
- **Deviations from spec.** (a) The walkthroughs used Playwright's headless Chromium, driven from scratch scripts
  outside the project, while spec §2.6 / S9-D5 says no Playwright and a built-in browser (the controller's brief asked
  for Playwright here; Playwright was not added to the project). (b) S9's visa file was built for its preselected
  programme (ovgu-eeit), not tu-chemnitz-embedded-systems as `walkthroughs.md` asks: the page preselects the first
  programme answered "Admitted" and builds the file for it at once; the walkthrough did not change the "For" list
  before approving. This is what `walk:S1:visa_admitted_label_one_only` describes.
- Not findings (rehearsal only): approval dates and "What changed" dates show the real date (plain audit stamps stay
  real time, `rehearsal.md`); the offline drafts are template text.

## Notes

- **Fast students.** Students without an event finish in 1 to 2 rehearsal days: every step starts as soon as its
  dependencies are done, so nothing waits for the calendar (deadlines are months away). Only S5 (170 days), S7 (about
  140) and S11 (about 10) take longer, because their events wait on time. The rehearsal therefore says little about
  how the plan behaves over months for an ordinary student.
- **Three programmes.** Only 3 of the 29 seeded programmes (ovgu-eeit, tu-chemnitz-embedded-systems,
  btu-artificial-intelligence) have the facts an application step needs, so all 12 students use those three. The
  start page offers all 29; the other 26 have no facts (`walk:S1:chip_unknown_says_being_researched`).

## After the fix pass (Task 11)

Date: 2026-10-29. Branch `os/s9-t11-fixes`: batch A `78ce040` and `256fe9c` (backend), batch B `6fe27b6` (screens),
batch C `9206ccc` (F1 and three review follow-ups), then two review fix rounds: `4c8cd51` (provisional visa date only
from programmes still in the running) and the apply-by commit (below). Same 12 fictional students, offline AI,
rehearsal mode.

**Visa date (the user's option A).** The visa step's due date is the **apply-by** date: 6 weeks
(`visa_before_semester_days`) before the semester start of the programme the visa file is for. The step takes 2 days
(the act of applying). The 90-day processing time (`visa_processing_days`) is shown only as an estimate in the step's
note ("Apply by 20 August 2027: 6 weeks before your semester starts on 1 October 2027. A visa usually takes about 90
days."), never as a scheduling input. The first form of F1's fix used the 90 days as the step's duration, which pulled
every application and admission result months before its own deadline (found in review; a regression test now guards
it).

### Re-run

| run | command (from `backend/`) | runtime | end states | failures |
|---|---|---|---|---|
| Full | `python -m tests.os.rehearsal.run --students all --out ~/s9-rehearsal/full-4` | 465 s | 12 of 12 `visa_ready`; 12 ready to submit, 12 visa file ready; every scripted event `:ok` | 1: `paused:S7` (owner-accepted) |
| Kill | `python -m tests.os.rehearsal.run --students all --kill --out ~/s9-rehearsal/kill-4` | 667 s, 54 worker SIGKILLs | the same as the full run | the same 1 id |

(The runs on `9206ccc`, `full-3` and `kill-3`, gave the same results; the numbers above are from the final code.)

- **Admin steps: none.** The driver no longer supplies `visa_target_date`. The visa step's date now comes from the visa
  programme's `semester_start`; the rehearsal loads fictional semester starts as test data
  (`backend/tests/os/rehearsal/semester_starts.yaml`, `example.invalid` URLs), since offline research finds nothing.
- **Kill comparison** (`~/s9-rehearsal/kill-compare-4.txt`): 12 of 12 students have the same state, end points and
  event outcomes; the failure ids are identical; no `lost_tasks` and no `duplicate:*` entry. Rehearsal days differ by
  0 to 4 (the kill run draws extra random numbers). **Match.**
- Both driver runs exit 1 only because `paused:S7` stays in the log. That entry is accepted (below).
- The short rehearsal in CI (S1, S3, S5) now passes with **no xfail**.

### Outcome of each original failure

The `fixed_by` and `owner_accepted` fields are recorded in `~/s9-rehearsal/full-1`, `kill-1` and `walkthroughs`
`failures.yaml`.

| id | outcome |
|---|---|
| F3 `http:S9:GET /statements:500` | fixed by `78ce040` |
| F1 `fact_missing:visa_target_date` | fixed by `9206ccc` (with `4c8cd51` and the apply-by commit): the playbook derives the visa step's apply-by date (6 weeks, `visa_before_semester_days`) from the researched `semester_start` of the programme the visa file is for |
| F2 `left_open:S3:removed_programme` | fixed by `78ce040`, hardened in `256fe9c` |
| F4 `paused:S7` | owner-accepted: "Accepted as designed (S7-D9) by the user on the owners' behalf, 2026-10-28" |
| `walk:S3:admission_card_unnamed` | fixed by `6fe27b6` |
| `walk:S3:statements_page_500` | fixed by `78ce040` (same cause as F3) |
| `walk:S9:cannot_change_approved_sop` | fixed by `78ce040` (same cause as F3) |
| `walk:S1:no_menu_on_os_pages` | fixed by `6fe27b6` |
| `walk:S1:inbox_programme_unnamed` | fixed by `6fe27b6` |
| `walk:S1:nothing_to_do_while_blocked` | fixed by `9206ccc`: a step blocked on a missing fact is listed under "Waiting" with what it waits for |
| `walk:S1:visa_admitted_label_one_only` | fixed by `6fe27b6` |
| `walk:S3:removed_programme_still_shown` | fixed by `6fe27b6` (with F2) |
| `walk:S1:chip_unknown_says_being_researched` | fixed by `6fe27b6` |
| `walk:S1:statement_programmes_raw_refs` | fixed by `6fe27b6` |
| `walk:S1:datasheet_label_overlap` | fixed by `6fe27b6` |
| `walk:S1:visa_how_to_apply_programme_text` | fixed by `6fe27b6` |
| `walk:S1:plan_updated_notice_empty` | fixed by `6fe27b6` |
| `walk:S1:documents_read_needs_tap` | fixed by `6fe27b6` |
| `walk:S1:done_after_upload` | fixed by `6fe27b6` (wording) |
| `walk:S1:ticks_before_approve` | fixed by `6fe27b6` (wording) |

The walkthroughs were not played again in a browser after the fix pass. The screen fixes are covered by component
tests and by the batch B screenshots at 375 px (`~/s9-rehearsal/walkthroughs-2`).

## Gate (Task 12)

**Gate:** marks 1 to 5 and 7 pass on the final code (`full-5`, and `kill-5` with 50 kills: 12 of 12 both end points,
7 of 7 events, 0 lost or duplicated, only `paused:S7`, owner-accepted; `kill-compare-5.txt` matches). Mark 6, the
billed run, is approved but not yet run: it waits for `OS_OPENAI_API_KEY`. The walkthroughs were not replayed in a
browser after the fix pass. See `docs/os/handoff/slice-9a-handoff.md` §3.
