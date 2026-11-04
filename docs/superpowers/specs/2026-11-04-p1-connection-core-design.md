# P1: connection core (phase spec)

Status: **draft for owner review** · 2026-11-04 · Owner: MSAQLAIN
Master spec: `docs/superpowers/specs/2026-11-03-pai-connect-design.md` (§3, §4, §6, §9, §10, §11, §12 row P1).
P0 handoff: `docs/connect/handoff/p0-handoff.md`. Visual overview: https://www.figma.com/board/X25QOs43qaDABBYEmzUPxk

**In one paragraph.** Today the Counsellor and PAI OS are not connected: a choice saves only a field, nothing sends
it to the OS, the OS keeps its own copy of the student's marks, there are two upload systems, and the roadmap shows
the Counsellor's own checklist. P1 connects them. A choice becomes a numbered version (places, intake, consent
included) that reaches the OS safely; the OS reads the student's facts only from the Vault; one upload button feeds
both; missing or conflicting data becomes plan steps; the roadmap shows the OS plan; "My plan" is always visible
with pages and words from the route. Everything sits behind switches that are off by default, so with them off the
app behaves exactly as today.

**What the student sees in P1.** Only routes with an OS playbook get an OS plan: the Germany master's and the test
routes. Pakistani routes (MBBS, BS, intermediate) get their playbooks in P3 and P4; until then they keep the old
checklist, labelled "PAI can't run this plan yet" (master §4, row 6.14).

## 1. Requirements this phase covers

R-01–R-22, R-41, R-43–R-46, R-50–R-55, R-59, R-78–R-80. Where each is built is in §5; the proof is in §7.
Not in P1 (master §6 note): rows 6.10, 6.20 (full proof), 6.23–6.25 are tested in P2. R-20 builds its mechanism in
P1 with a test calendar; the official calendars arrive in P2.

## 2. Decisions

### 2.1 Owner decisions (MSAQLAIN, 2026-11-04, in chat)

| # | Decision |
|---|---|
| P1-D1 | **One phase spec; one implementation plan per task group**, written just before that group is built. |
| P1-D2 | **One upload store: the Counsellor file store** (`files` table, `app/files/storage.py`). The OS keeps every document feature (types, checks, reader, cross-checks, confirmation, packs, visa file, consent gate, tenant isolation); only the file bytes come from the Counsellor store by document ID. The OS's own byte table (`os_document_files`) stays for the standalone mode (Counsellor module off). OS-made pack files stay in the OS. |
| P1-D3 | **Consent text: Claude drafts, the owner approves in chat.** Texts live in a data file marked `approved: false` until the owner approves; while not approved, the consent screens work only in rehearsal and tests, never for real students. Legal review stays in P5. |
| P1-D4 | **Marks: total plus optional Part-I and Part-II** in the same `education` record. Onboarding asks for the parts only when the student has a Part-I result. Stored totals stay valid. |
| P1-D5 | **Age unknown at the choice step: the choice screen asks for the date of birth** (saved to the Vault as `stated`). If it shows the student is under 18, guardian consent is required before the plan starts. |
| P1-D6 | **Hand-off approach A:** a Counsellor-side outbox table written in the same transaction as the decision; delivery right after commit; a sweep every ≤ 5 minutes as backup. |
| P1-D7 | The design in §3 (choice record, student information, what the student sees and the proof) was approved in three parts in chat. |

### 2.2 Technical decisions (proposed here; approved with this spec)

| # | Decision |
|---|---|
| P1-D8 | **Counsellor-side connection code lives in `backend/app/pai_c/connect/`** (Python and YAML only, never `.md`, so it is outside the frozen paths). Glue that imports `app.os` stays in `backend/app/pai_os_bridge.py` (Tach). |
| P1-D9 | **Flags.** Master switch: the existing OS `os_modules` row `counsellor`. Per-part flags in `backend/app/config.py` (defaults off): `CONNECT_HANDOFF`, `CONNECT_ROADMAP_FROM_PLANVIEW`, `CONNECT_CHECKINS_FROM_PLANVIEW`, `CONNECT_STUDENT_FACTS`, `CONNECT_ONE_UPLOAD`, `CONNECT_MY_PLAN`. A part runs only when the master switch and its own flag are on. A small owner script `backend/scripts/connect_switch.py` shows and sets the master switch (no SQL by hand). The stage H and merit flags of master §10 arrive with P2–P4. |
| P1-D10 | **`guardian_required` is added to `decision_record.v2`** (beyond the master §9.1 list): the Counsellor decides who is under 18 from the Vault; the OS never reads the date of birth. |
| P1-D11 | **Withdrawn consent is a new decision version** with the consent field cleared. The OS **pauses** (not closes) a plan whose decision lacks a required consent (blocked reason `consent_missing`); a later version with consent resumes it. |
| P1-D12 | **Step titles from the playbook count as route data** (R-52), so `plan_view.v1` may carry them. Proposal and Supervisor free-text reasons never cross; `plan_view.v1` carries reason codes only. |
| P1-D13 | **Who decides which levels are open (R-14):** a Counsellor data file maps qualification codes to the levels a student can apply for; the bridge sends the result as `eligible_levels` in `student_facts.v1`. No qualification names in `app/os` (R-58). |
| P1-D14 | **A new Vault change event type in the OS replanner** is named `student_fact_changed` (the name `fact_changed` is taken by Knowledge facts). |
| P1-D15 | **The Vault version** is a per-student counter in a new table `pai_vault_versions`, raised by the reconciler's accept hook (`app/memory/reconciler.py` `register_accept_hook`). |
| P1-D16 | **No frozen file is planned to change in P1.** New Vault types are added through the catalog (`app/memory/catalog/vault_catalog.json`) whose `<choices>` fill the extractor prompt. If a prompt change turns out to be needed (the extractor prompt is described in the frozen `docs/counselor/COUNSELOR_V3_PROMPTS.md`), work stops and the owner is asked for a freeze exception. |

## 3. Design

### 3.1 The choice record and the hand-off (R-02, R-03, R-06, R-12, R-79)

- **Rows are versions.** `pai_route_decisions` gains `decision_version` (per workspace, only goes up, unique with
  `workspace_id`), `status` (`chosen` / `withdrawn`), `level` (incl. `intermediate`), `destination_country`,
  `places` (1–5 with rank; 0–5 when `os_supported` is false), `intake` (term, year), `path_ref`, `os_supported`,
  `authorized_at`, `guardian_required`, `guardian_authorized_at`. Every choose, change, withdraw or consent change
  inserts a new row; old rows are never rewritten. The current choice is the newest row. Checklist ticks
  (`steps_done`) stay only on rows with `os_supported = false` (today's behaviour).
- **Migration.** Existing rows get versions in `(chosen_at, id)` order; a row withdrawn today in place gets a
  following `withdrawn` row. The partial unique index `uq_route_decision_active` is replaced by
  `(workspace_id, decision_version)` unique.
- **Writer.** `RouteDecisionService` (`app/pai_c/roadmap/decisions.py`) keeps its lock (workspace `FOR UPDATE`).
  It writes the row and, when `CONNECT_HANDOFF` is on and the master switch is on, an outbox row in the same
  session. `os_supported` comes from a new OS port call `PlanSource.supports(origin, destination, level)`.
- **Outbox.** New table `pai_os_outbox` (app database): `id`, `workspace_id`, `kind` (`decision` / `vault_event`),
  `key` (unique: `decision:{ws}:{version}` or `vault:{ws}:{version}`), `payload` (the export), `status`
  (`pending` / `delivered` / `not_sent`), `attempts`, `last_error` (code only), `created_at`, `delivered_at`.
  Unsupported decisions are stored `not_sent` (row 6.14: the OS does nothing).
- **Export.** New `app/pai_c/os_export.py` builds `decision_record.v2` from a row (the bridge already imports this
  module name).
- **Delivery.** After the router commits (`routers/roadmap.py` `_write`), the bridge delivers the workspace's
  pending outbox rows through `PlanSource.submit_decision`. The sweep (`pai_os_bridge.start_sweep`, every ≤ 5 min)
  delivers any row still pending and compares, per student, the newest Counsellor version with the newest version
  the OS has; this replaces today's `chosen_at` mark, so withdrawals are swept too.
- **OS intake.** `os_counsellor_intake` gains `decision_version` and `decision_status`. The OS applies a delivery
  only if its version is newer than the newest it applied for that student; older or repeated ones are stored as
  `stale` / `duplicate` and change nothing. `withdrawn` closes the plan with reason `withdrawn`, cancels open
  reminders and adds no tasks (R-06), through the kernel. v1 rows already stored still process as today.
- **Crash safety (R-12).** A crash before commit loses both rows; after commit the sweep delivers; a repeated
  delivery is a duplicate. Proven with the Spike 3 method (kill points between each step).

### 3.2 Stage I screens and consent (R-10, R-79, P1-D3, P1-D5, P1-D10, P1-D11)

- **New screens, not chat turns** (master §10): on the roadmap's chosen field, a "Make this my choice" flow:
  places (1–5, in order; from the OS `programme_list` when the route is supported, else from stage H's list),
  intake, date of birth if the Vault lacks one, and consent. Existing `paths.tsx` consent checkbox is replaced by
  this stored consent.
- **Student consent** writes `authorized_at` with the text version agreed.
- **Guardian consent (under 18).** The student enters a guardian's email; the Counsellor sends a one-time link
  (token stored hashed, expires after 72 hours, single use, audit row in `pai_guardian_consents`: who, when, text
  version, outcome). Opening the link shows the text and "I agree"; agreeing writes a new decision version with
  `guardian_authorized_at`. The email address is personal data: masked in logs, removed by the data-deletion
  path, included in the student's data export. Sending uses the existing Resend sender (`auth_emails`) and
  `rate_limit.allow`.
- **Withdrawing consent** (student, or guardian through a link in the confirmation email) writes a new version
  without it; the OS pauses the plan (P1-D11). The roadmap shows the consent state.
- **Texts** in `backend/app/pai_c/connect/consent_texts.yaml` (`version`, `approved`, text per kind). Not
  approved means rehearsal and tests only. Pilot terms (`app/os/consent/pilot.v1.md`) are a different consent
  and are not touched.

### 3.3 Student facts from the Vault (R-01, R-13–R-16, R-78, R-80)

- **Port.** New `app/os/ports/student_facts.py` with `get(student_ref) -> StudentFactsV1`. Two adapters:
  standalone (reads `os_profile_values`, as today) and Counsellor (in the bridge, built on
  `StudentSnapshotService`). The OS uses the Counsellor adapter when the master switch and `CONNECT_STUDENT_FACTS`
  are on; eligibility (`app/os/eligibility/evaluate.py`) reads through the port only.
- **Contents of `student_facts.v1`:** education level, marks (total, Part-I, Part-II), entry-test scores,
  excluded fields, field order, budget, domicile, place preference, `eligible_levels`; each with its Vault version
  and evidence level (`stated` / `shown` / `confirmed`; Vault `inferred` is sent as unknown).
- **New Vault types** (catalog): `field_order` (ranked field codes) and `place_preference` (local / abroad /
  either, with a fallback rule and named regions as codes). The live-run note "local first, abroad only as a
  fallback" must be stored by it.
- **One source for exclusions (R-78).** The Vault `option` item with status `ruled_out` is the only source. A
  dismissal from the paths screen button now also writes that Vault item (evidence: the student's action). The
  `pai_possibilities.status` stays for the journey screens but no reader treats it as the exclusion.
- **Excluded everywhere (R-15).** Paths, chat cards, roadmap, stage H, the OS programme list and the route
  builder all read the same exclusion. A planned place that breaks a new constraint becomes a proposal, never a
  silent removal.
- **Changes reach the OS.** The accept hook raises the Vault version and writes a `vault_event` outbox row with the
  changed keys; the OS records `student_fact_changed` and replans the plans that used those keys (row 6.8, 6.9).
- **Per-part marks (R-16, R-80, P1-D4).** `education.result` gains optional `part1` and `part2` (marks obtained,
  marks total). Onboarding asks for them only when the student has a Part-I result. Marks known in the Vault are
  never asked again in chat (existing rule).

### 3.4 One upload entry point (R-01, R-16, row 6.7, P1-D2)

- Every upload button (chat, Documents page, Vault page, "My plan" Documents) posts to one endpoint that stores the
  file in the Counsellor store and, when `CONNECT_ONE_UPLOAD` is on, registers an OS document with the same
  document ID and the document type the student picked.
- The OS reads bytes through a new port `DocumentFiles.read(document_id)` (Counsellor adapter in the bridge;
  standalone adapter = `os_document_files`). `app/os/documents/store.py` `file_bytes` is the single change point.
- Facts the OS reads are proposals: after the student confirms them on the existing OS confirm screen, the bridge
  calls the Vault reconciler (`FactProposalSink.propose`) with evidence `shown`, linked to the document ID.
- Deletion deletes in both places; tenant and student isolation are tested on every read.

### 3.5 Missing and wrong data (R-17–R-22)

- **Playbook fields (additive, optional):** a step may declare `needs: [{fact | document, evidence}]`. Germany
  master and the test playbooks gain them in a new playbook version; running plans stay pinned.
- **Missing:** the compiler adds a `provide` step for each missing fact or document, dated backwards from the step
  that needs it; dependent steps are `blocked` with reason `awaiting_fact`; eligibility shows "unknown".
- **Not out yet (R-20):** a `result_expected` step dated from a calendar fact, then a provide step. P1 proves it
  with a test calendar fact; official calendars come in P2.
- **Conflicts (R-21):** document vs Vault (every field), document vs document (existing findings), an impossible
  value (above the total), a student correction. Each gives one `which_is_right` step showing both values and
  sources; dependent steps pause; the answer goes to the Vault through the reconciler.
- **One request per fact (R-19):** new OS table `os_student_requests` with a unique open request per student and
  fact. Shown in the plan, the inbox, email and app notification; answered anywhere closes it everywhere. The
  Counsellor chat request card is not used for OS requests (R-45).
- **No answer (R-22):** reminders, then deadline at risk, then a proposal (drop or swap the place), then an
  escalation when every place is affected.

### 3.6 Roadmap from the plan, and retiring the checklist (R-01, R-04, R-44, R-45)

- **`plan_view.v1`** and `PlanQuery.plan_view(student_ref, decision_version)`: steps with status, due date and time
  zone, owner, dependencies, requests with evidence level, documents needed, revision and "what changed",
  consent state, paused / stopped / finished, and an empty state before a choice.
- **Adapter.** With `CONNECT_ROADMAP_FROM_PLANVIEW` on, `RoadmapEngine.build` fills `RoadmapPage.chosen` from
  `plan_view` in the same shape as today (R-44). A tick on an OS step goes to the OS inbox action; work steps are
  not tickable.
- **Every reader to move** (corrected from master §12; checked file by file):

  | Reader | What it reads today | P1 change |
  |---|---|---|
  | `backend/app/pai_c/roadmap/engine.py` | `route_steps`, `done_keys(decision)`, `serialize` | Chosen route from `plan_view` |
  | `backend/app/pai_c/roadmap/decisions.py` | `_snapshot`, `done_keys`, `set_step` | Ticks only for `os_supported = false` |
  | `backend/app/pai_c/roadmap/timeline.py` | estimate over steps | Dates from `plan_view` |
  | `backend/app/routers/roadmap.py` | `/v1/roadmap`, `/steps` | `/steps` forwards to the OS for OS routes |
  | `backend/app/routers/decision_records.py` | `current` | Adds version, places, intake, consent |
  | `backend/app/pai_c/checkins.py` | active decision id for `chosen_path` | Keyed on decision version; checks `plan_view` (flag `CONNECT_CHECKINS_FROM_PLANVIEW`) |
  | `backend/app/pai_c/journey_sync.py` | `follow_active`, stage on choice | Uses the newest version and status |
  | `backend/app/pai_c/data_export.py` | raw `steps`, `steps_done` | Adds versions, places, intake, consent |
  | `backend/app/pai_c/possibilities.py` (`set_chosen`), `family_talk.py`, `deep/context.py` (read only) | possibility status `chosen` | Unchanged values; `set_chosen` follows the newest version. `deep/context.py` is frozen and not edited |
  | `backend/app/journey/*` | `active_goal`, `decisions` entries | Entries gain the version |
  | `frontend/lib/roadmap.ts`, `frontend/lib/api.ts` (roadmap calls) | `ChosenRoute` shape | Shape kept; optional new fields |
  | `frontend/components/counselor/workspace/roadmap.tsx`, `roadmap-parts.tsx`, `roadmap-steps.tsx`, `roadmap-text.ts` | chosen steps, ticks | Same shape; label for "PAI can't run this plan yet" |
  | `frontend/components/counselor/workspace/use-journey.ts` | `route_chosen`, `route_step_done` | Same signals from the same shape |

  Not readers (master §12 lists them by mistake; they use agent `Workflow.steps` or the onboarding form):
  `routers/tasks.py`, `routers/workflows.py`, `routers/workspaces.py`, `services/workflow.py`,
  `frontend/components/onboarding/onboarding-view.tsx`.
- **Routes the OS can't run** keep the checklist, labelled "PAI can't run this plan yet" (master §4).
- **Events (`os_event.v1`)**: plan created / revised / paused / stopped / finished, step done, student needed,
  deadline at risk, proposal waiting. They reach screens, notifications and email only, never chat (R-45).

### 3.7 Proposals, adoption, the OS builder and escalations (R-07, R-08, R-09, R-11, R-22)

- **Proposals → `choice_request`.** On a Counsellor plan, an accepted proposal that changes the choice (swap or
  cancel a place, change the intake) no longer edits the plan contract. The OS writes a `choice_request.v1` (the
  change and the version it is based on) to its `counsellor` outbox channel; the bridge hands it to the decision
  service, which writes n+1 only if the base version is still current (else the proposal is marked expired and the
  student sees it). Standalone plans keep today's direct edit.
- **Adoption (R-08).** When the master switch is turned on and a student has a self-serve plan, "My plan" offers to
  link it; if the student agrees, the decision service writes a version from the plan contract and the OS adopts
  the plan (source becomes `counsellor`) without rebuilding it.
- **OS builder with the Counsellor on (R-09):** the self-serve start calls `ChoiceSink.request`, which writes
  through the decision service (row 6.13). With the module off it works standalone, as today.
- **Escalations ×5 (R-11):** `routers/escalations.py` accepts `not_eligible`, `all_rejected`, `deadline_passed`,
  `blocking_gap`, `other`; the bridge stops collapsing three of them. It works whenever an active decision exists
  (not only at stages PROPOSED / CHOSEN). The student is taken back to choosing with the reason, shown with the
  existing fixed OS sentences (`adapters/counsellor/notes.yaml`); any new sentence needs the owner's approval.

### 3.8 "My plan" (R-50–R-55)

- `nav.studyAbroadPlan` becomes `nav.myPlan` ("My plan") in `en-US.ts`, `os-nav-group.tsx`, `os-header.tsx`,
  `counselor/workspace/shell.tsx`, `shell-parts.tsx`, `os/plan-card.tsx`, `os/vault-strip.tsx`, and their tests.
- Playbooks declare `pages:`; a new `GET /v1/os/plan` returns the student's pages (and an empty state before a
  choice). The menu shows only those pages; no visa page or plane icon on non-abroad routes.
- Always visible (R-53): the stage H gate in `osOpenAt` is removed for "My plan" itself.
- Step titles, page titles and pack wording come from route data (R-52); every fact shows its source, date checked
  and level (R-54).
- **Label test (R-55):** renders every route (Germany, fake Ireland, fake PK BS and a new fake PK intermediate
  route) and fails on another route's country, body or document name, or on "abroad", "visa" or a plane icon on a
  non-abroad route.

### 3.9 Contracts v2 (R-41, master §9.1)

New files beside the frozen v1 files in `app/os/contracts/`: `decision_record.v2` (adds `decision_version`,
`status`, `level` += `intermediate`, `path_ref`, `guardian_required`, `guardian_authorized_at`, `os_supported`;
a `withdrawn` record needs no places), `route_contract.v2`, `escalation.v2`, `plan_view.v1`, `os_event.v1`,
`choice_request.v1`, `student_facts.v1`, `vault_event.v1`. Each gets a JSON schema, samples and frozen-hash tests
like v1. `programme_facts.v1` and `merit_check.v1` are P2.

## 4. Rules for every P1 task

- Branch `pc/p1-t<N>-<name>` from `pai-connect`, squash-merged by PR. Nothing goes into `pai-merge` until the
  whole plan is done (P0-D14).
- Name the R-IDs in the PR; set `built: true` in `docs/requirements/connection.yaml` in the PR that adds the tests;
  tag tests `@pytest.mark.req("R-xx")` or `// req: R-xx`.
- DB changes only by Alembic: Counsellor tree `backend/alembic/versions/`, OS tree `backend/alembic/versions_os/`;
  one head each.
- No country, institution, exam or qualification names in `app/os` (R-58); `tach check` and `pytest tests/os`
  before pushing OS code. OS and legacy suites run one at a time (shared Postgres).
- With every flag off, the app behaves byte-for-byte as today: each task has a test for that.
- No live model call without the owner's approval and a cost cap. Fictional students only.

## 5. Task groups (in order)

| # | Branch | Builds | R-IDs | Needs |
|---|---|---|---|---|
| T1 | `pc/p1-t1-contracts` | Contracts v2 (§3.9), samples, frozen-hash tests; fake PK intermediate playbook; flags and `connect_switch.py` (P1-D9) | R-41, R-43 (part), R-59 | — |
| T2 | `pc/p1-t2-handoff` | Versioned decision rows, migration, outbox, export, delivery, version sweep, OS apply-only-newer, withdraw → plan stopped, crash test (§3.1) | R-02, R-03, R-06, R-12, R-79 | T1 |
| T3 | `pc/p1-t3-choice-consent` | Stage I screens, places and intake, student and guardian consent, consent pause (§3.2) | R-10, R-79 (screens) | T2 |
| T4 | `pc/p1-t4-student-facts` | `StudentFacts` port and adapters, new Vault types, exclusions from the Vault, Vault version and events, per-part marks, eligible levels (§3.3) | R-01, R-13, R-14, R-15, R-16, R-78, R-80 | T2 |
| T5 | `pc/p1-t5-plan-view` | `plan_view`, roadmap adapter, every reader moved, labelled checklist, OS events (§3.6) | R-01, R-04, R-44, R-45 | T2, T4 |
| T6 | `pc/p1-t6-proposals` | `choice_request`, adoption, OS builder via decision service, escalations ×5 (§3.7) | R-07, R-08, R-09, R-11 | T5 |
| T7 | `pc/p1-t7-one-upload` | One upload entry point, `DocumentFiles` port, fact proposals to the Vault (§3.4) | R-01, R-16 | T4 |
| T8 | `pc/p1-t8-missing-data` | Playbook `needs`, provide / result expected / which is right steps, one request per fact, unanswered ladder (§3.5) | R-17–R-22 | T4, T5, T7 |
| T9 | `pc/p1-t9-my-plan` | "My plan" rename, route pages, always visible, route words, sources on facts, label test (§3.8) | R-50–R-55 | T5 |
| T10 | `pc/p1-t10-gate` | Consistency job and end-of-test check (rules 1–8), §6 row tests, standalone and replay proofs, handoff (§7) | R-04, R-05, R-12, R-43–R-46, R-59 | all |

T3 and T4 can run in parallel after T2; T7 and T9 can run in parallel after T4 / T5.

## 6. Risks

| Risk | Answer |
|---|---|
| The two databases (app ORM session and the OS Core engine) can't share one transaction | The outbox is in the app database (P1-D6); the OS side is idempotent by version |
| Legacy tests run on SQLite with no OS database | The outbox and versions work on SQLite; delivery is stubbed there as today; real delivery is tested in `tests/os` |
| The roadmap or journey screens break when their data source changes | The adapter keeps the `RoadmapPage.chosen` shape; existing roadmap and journey tests run with the flag on and off |
| The compiler's plan hash starts depending on Vault data and churns revisions | Only `needs` steps read Vault facts, through the version; a replan happens only on `student_fact_changed` for a used key |
| Consent text used before it is approved | `approved: false` blocks real students (P1-D3) |
| Scope grows (T7 and T8 are the largest) | Each group has its own plan; anything outside this spec stops for the owner |

## 7. Gate (master §12, P1)

| # | Gate item |
|---|---|
| 1 | Every task merged into `pai-connect` with all CI jobs green |
| 2 | `python scripts/check_traceability.py --gate P1` passes |
| 3 | Every P1 row of master §6 (6.1–6.9, 6.11–6.19, 6.21, 6.22) passes as a scripted test on fictional students (Germany master's, fake PK BS, fake Ireland, fake PK intermediate) |
| 4 | The consistency job (rules 1–8 of master §9.3) finds zero on those students |
| 5 | Crash test: no loss and no duplicate at every kill point (R-12) |
| 6 | Standalone suite passes with the Counsellor module off (R-09, R-59) |
| 7 | Conversation proofs: offline replay unchanged; stage A–I replay with the connection off and on identical apart from fact values (R-46). A live graded run only with the owner's approval and a cost cap |
| 8 | Label test passes (R-55) |
| 9 | `docs/connect/handoff/p1-handoff.md` written; the owner (MSAQLAIN) signs off |

## 8. Open items for later phases

- When a route's playbook arrives (P3, P4), active decisions with `os_supported = false` on that route need a way to
  move to the OS (new version written with the student's agreement); designed with R-81.
- Stage H places from the OS registry (R-49) and merit answers (R-48) are P2–P4.
- Live-run follow-ups not in P1 scope (from the P0 handoff): the Mirror budget band, the "he" in a strength note,
  Mirror timing, duplicate Vault entries, "karunga", the rejection reason in the frozen analysis log, Explore
  committing before research starts.
