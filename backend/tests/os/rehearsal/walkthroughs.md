# Phone walkthroughs (Slice 9a spec §2.6)

Three of the twelve fictional students, S1, S3 and S9, are played by hand (by a Claude agent) in a browser at phone
width against the local API, worker and frontend, with rehearsal mode and offline AI on. These are not repeatable
tests. The aim is to see what a person on a phone would see, and to log anything that blocks, is wrong or is unclear.

Fictional data only: the student's documents are the driver's sample bundles (`students.yaml` `bundle`) plus the four
pages the driver draws for them (minimum passing grade letter, admission letter, blocked account, insurance). Never
use a real document. Screenshots and the failure log go outside the repo (`~/s9-rehearsal/walkthroughs/`).

## Set-up (each student on a clean database)

1. Follow `docs/os/rehearsal.md`, "Walkthrough sign-in": an empty database, the API through
   `scripts.offline_startup_app:app` with `PAI_OFFLINE_STARTUP_CHECK=1`, the frontend with
   `NEXT_PUBLIC_OS_ENABLED=true`. Add on the API and on the worker: `OS_REHEARSAL=on`, `OS_MODEL_MODE=offline`,
   `OS_OFFLINE_ANSWERS_DIR` (a temporary folder made the way the driver makes it: `build_answers` with the student's
   extra pages), `OS_ADMIN_TOKEN` (any fictional value), `OS_EMAIL_SENDER=log`, `OS_DATABASE_URL`.
2. Load the programme registry and the seeded facts into the database (as the driver's `_clean` does).
3. Start the worker: `python -m app.os.runner.worker` from `backend/`, same environment.
4. Move the clock to 1 Dec 2026: `POST /v1/os/admin/rehearsal/advance {"days": N}` (at most 60 per call).
5. Sign in with the fake token (step 5 of "Walkthrough sign-in"). The entry point gives one fixed student, so the
   three walkthroughs run one after the other, each on a fresh database.
6. Browser: 375 px wide, touch. Move between pages with the menu if there is one; note it if there is not.

"Tick" below means: `POST /v1/os/admin/rehearsal/advance {"days": 1}` (or the days given), then
`POST /v1/os/admin/rehearsal/tick` and wait until `GET …/tick/{id}` says `done`. Wait a few seconds after a tick
before reading a page: the worker may still be finishing what the tick started.

## What to note at every step

- **blocks**: the student cannot go on, or would do something wrong they cannot undo.
- **wrong**: the page says something untrue or acts against what the student chose (log as `workaround` if there is
  a way round, else `blocks`).
- **unclear**: wording, labels or layout that would confuse a student at 375 px (log as `wording`).
- Also: anything wider than 375 px (horizontal scrolling), text running into other text, buttons that are hard to
  reach.

Each finding goes into the walkthrough failure log with id `walk:<student>:<short name>`, the step, what was expected,
what happened, and a severity (`blocks` | `workaround` | `wording`). One screenshot per step, named
`<student>-<nn>-<step>.png`.

## The steps (all three students)

| # | Step | Page | Then |
|---|---|---|---|
| 1 | Start: open the start page | `os-start` | |
| 2 | Consent: read the pilot terms, tap "I agree" | `os-start` | |
| 3 | Choose the student's programmes (`students.yaml`), best first; tap "Start my plan" | `os-start` | inbox opens |
| 4 | Upload: the six bundle documents and the minimum passing grade letter, each with its type | `os-documents` | wait until each is read |
| 5 | Check what was read, document by document; "Confirm all" | `os-documents` | |
| 6 | Answer the interview (`students.yaml` `interview`) | `os-statements` | |
| 7 | "Write my statement", "Write my CV"; open each draft, read it, "Approve this version" | `os-statements` | tick |
| 8 | Upload the blocked account and insurance pages; confirm them. In the inbox tap "Done" on the steps the student has done (tests, attestation, certificates, blocked account, insurance) | `os-documents`, `os-inbox` | |
| 9 | Each pack: "A few more details" (contact details from `students.yaml`), tick the checklist items, "Approve pack" | `os-pack` | tick |
| 10 | Ready to submit: each programme's submit step waits. Tap "Done" ("I submitted it") | `os-inbox` | tick 2 days |
| 11 | Admission results as `students.yaml` says | `os-inbox` | tick |
| 12 | Read a suggestion and accept it; read "What changed" | `os-inbox` | tick |
| 13 | Upload and confirm the admission letter; the visa file: choose the programme, details, ticks, "Approve visa file" | `os-documents`, `os-visa` | tick |
| 14 | Visa file ready: `visa_apply` waits in the inbox. If it does not, and the plan waits on `visa_target_date`, supply it as the admin (`POST /v1/os/facts`, as the driver does) and log it | `os-inbox` | tick |

## Per student

### S1 (no event)

Programmes: ovgu-eeit, tu-chemnitz-embedded-systems. Bundle 1. Admitted by both; visa file for ovgu-eeit. No
suggestion is expected, so step 12 only reads "What changed" (expected: nothing, or only what the plan did). Note
whether two cards for the same kind of step can be told apart.

### S3 (rejected by one programme)

Programmes: ovgu-eeit, btu-artificial-intelligence. Bundle 5. Step 11: "Admitted" for ovgu-eeit, **"Not admitted" for
btu-artificial-intelligence**. Make sure, before tapping, that the card is the right programme's. Step 12: a
suggestion to remove the rejected programme's steps (or to swap, if below the minimum) appears; read the reason,
accept it, then check "What changed", the packs page, the programmes page and the visa file's programme list.

### S9 (changes an approved statement)

Programmes: tu-chemnitz-embedded-systems, ovgu-eeit. Bundle 1. Admitted by both; visa file for
tu-chemnitz-embedded-systems (choose it in the visa file's "For" list). After step 9 (both packs approved): open the
statement page, open the approved SOP, add `students.yaml` `sop_addition`, save, approve the new version, then tick.
Expected: each pack's review step comes back in the inbox and the packs show as changed; approve them again. Then
carry on from step 10.
