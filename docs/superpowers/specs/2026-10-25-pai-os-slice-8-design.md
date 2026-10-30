# PAI OS Slice 8: the Counsellor connection (design)

Date: 2026-10-25. Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (§1 success criterion 5, §3 "Ports
(v1: three)", §3.2 RouteContract, §4.4 `route_invalid`, §5 contract tests, §6 Slice 8, §7 team process;
invariants 1, 4, 8, 9, 11, 12). FigJam boards: PAI OS review board (`sEWRgciL9Quwmklh492qUW`, "Ways in", "Phases and
gates", "Code and teams") and the Counsellor's locked board (`NjVJfdxERWfRHPycy1wDkF`, §11 "PAI C and PAI OS
contract"). Builds on Slices 1–7 on `pai-os`. Findings behind this spec: the Counsellor code on `pai-c`
(`e4ca3f5`), the Counsellor team's answers of 2026-10-25, and a local trial merge of `pai-c` into `pai-os` (§12).

**Goal.** PAI OS and the PAI Counsellor (PAI C) connect through three versioned channels, built and tested now and
**switched off** for real students until both sides are ready:
- **route in:** a Counsellor decision record becomes a PAI OS plan (PlanSource);
- **summary out:** PAI OS tells the Counsellor how the plan is going (PlanQuery);
- **escalations out:** PAI OS tells the Counsellor when a route can't work (EscalationSink).

PAI OS also gives the Counsellor one read function, its programme list, so the places a student chooses carry PAI OS
programme IDs.

**Why switched off.** PAI C counsels Matric/O-level and FSc/A-level students towards bachelor's paths. PAI OS v1 runs
one real route, Pakistan → master's in Germany (bachelor's graduates). A real Counsellor decision would match no
playbook today. The owners' order (2026-10-25): build Slice 8 now, run the Slice 9 pilot standalone (self-serve), add
the Counsellor's routes after the pilot (BS in Pakistan first), then switch the connection on.

**Done when (the Slice 8 gate, PAI OS side; S8-D3):**
- every branch passes CI on its own: Tach, the single-head check, `tests/os`, the Counsellor (legacy) suite, and the
  frontend tests, `tsc` and the OS-enabled build;
- the contract tests pass (§8), and the whole PAI OS suite passes with the Counsellor module off (parent §1 criterion 5);
- the fake Ireland and Pakistan BS routes run unchanged (invariant 12);
- an end-to-end test with fictional records and the module on passes: export → plan → summary → escalation;
- a crash test: a decision is planned exactly once when the worker dies mid-intake;
- the glue tests pass again on the local `merge-test` branch against the newest Counsellor code, apart from the
  problems that already exist on `pai-c` (§12);
- the hand-over document for the Counsellor team is written (§11).

## 1. Decisions (brainstorm, 2026-10-24/25)

| # | Topic | Decision |
|---|---|---|
| S8-D1 | Scope | Three channels only: route in, summary out, escalations out, plus the programme-list read function the Counsellor asked for. OS→student questions through the Counsellor and outcome updates (applied, admitted, rejected) come in a later slice (user, 2026-10-25). |
| S8-D2 | Off switch | The Counsellor adapter is a **module** with a manifest and an `os_modules` row, as the parent spec gives every adapter (Slice 1 §4.6). Its row `counsellor` is inserted **disabled** by `os_0013`. It owns no task types. While it is off: submitted exports are stored and ignored, the sweep submits nothing, the Counsellor escalation adapter is skipped, and the summary and programme-list functions still answer (for tests). Standalone PAI OS behaves exactly as today. |
| S8-D3 | Pilot gate | **The pilot opens when Slice 8 passes on the PAI OS side** (the "Done when" list above). The Counsellor side (§11) is its own gate before the module is switched on. This amends the PAI OS board ("Gate: Slice 8 passes"; Slice 8 done = "Both teams' contract tests pass") and D3's slip rule. **For the owners to confirm (§10 Q1).** |
| S8-D4 | Who builds what | PAI OS builds its side and the **glue** (§2.7). The Counsellor team builds the export, the student's hand-off consent, "Where to study" from the PAI OS programme list, the five escalation reasons, and the shared CI job on `pai-c`. PAI OS writes them a hand-over document and gives it to them when PAI OS is complete; the field list was checked with them early (2026-10-25, "agreed in principle"). |
| S8-D5 | Decision record export v1 | A frozen JSON document the Counsellor builds from its decision record, the chosen roadmap and the student's Vault: IDs and codes only, never the Truth Map or free text. Fields in §2.1. Agreed in principle by the Counsellor team, with their four changes: origin is "Stated" (not always "Confirmed"), an optional `nationality`, any term name (`fall`, `spring`), 1–5 ranked places. |
| S8-D6 | Delivery | **The host hands the export to PAI OS; PAI OS never reads Counsellor tables.** After a choice the Counsellor calls the glue, which reads the export and submits it through the PlanSource port (one insert, no planning in the request). A glue sweep every 5 minutes in the API process re-submits decisions changed since its last mark, so a lost nudge never loses a choice. The PAI OS worker plans submitted exports. Reason: the worker is its own process and never loads host code (Tach), so it cannot call the glue. Submitting the same decision twice is harmless (S8-D9). |
| S8-D7 | Consent | The Counsellor's board says "selection and handoff need student authorization". The export carries `authorized_at`; without it the decision is refused (`not_authorized`). |
| S8-D8 | Plan reference and route changes | `external_ref = "{journey_id}:{destination_country}:{level}"`. **Same route** (new places, new order, new intake): the same plan, changed through `Kernel.change_contract` (a revision, like a Slice 4 swap). **New country or level:** the student's open Counsellor plan is **closed** (new plan status `closed`, its open tasks `cancelled`, revision cause `superseded:<new plan id>`), and a new plan starts. A closed plan is never reopened: a decision for a route whose plan was closed is refused (`plan_closed`) and opens a support case. |
| S8-D9 | Idempotent | Each export is stored once per `decision_id` (unique). A decision already planned or refused is skipped. The intake workflow ID is `counsellor:{tenant}:{decision_id}`, and every write it makes checks the intake row first (invariant 8). |
| S8-D10 | Refusals | Closed reasons: `not_authorized`, `invalid_export` (fails the schema), `route_not_supported` (no playbook for origin, destination, level; e.g. PK→PK today), `unknown_programme` (a place not in the PAI OS programme list), `self_serve_plan_open`, `plan_closed`. Every refusal is recorded on the intake row. The first four should never arrive (the Counsellor offers only plannable places), so each also escalates with reason `other` (S8-D12). |
| S8-D11 | Self-serve overlap | A student with an open self-serve plan: the Counsellor decision is refused (`self_serve_plan_open`) and a support case opens, so a person decides. PAI OS never replaces a plan the student is working on (user, 2026-10-25). |
| S8-D12 | Escalations | One port, `EscalationSink`; every place that opens a support case today calls it (the Slice 7 spec S7-D10 promised the port; the code calls `SupportStore.open` directly). **Standalone adapter** (always): the support case, as today. **Counsellor adapter** (module on, plans whose source is `counsellor`, route problems only): also tells the Counsellor through the outbox. Reasons and their triggers in §2.5. System problems (a task failing twice, the daily-change limit, the Supervisor unavailable, over budget or invalid, every operation refused, a stale draft) stay in the support inbox only. |
| S8-D13 | Summary | `PlanSummary v1`, built from the plan on every read, never stored, newest open plan, five parts (§2.4). No document values, answers, statement text, admin notes or Supervisor reasons; step names come from the playbook. In-process only, no HTTP endpoint. |
| S8-D14 | Programme list | `programme_list(route_key, intake)` returns the PAI OS programmes for a route and intake: ID, university, name, and whether the facts the compiler needs are confirmed. Read-only, from the existing programme registry and Knowledge. |
| S8-D15 | Contracts | Frozen v1 JSON schema files generated from the models, fictional samples with expected results, and frozen-file tests (§2.6). A change is a new v2 file with a migration path and both teams' sign-off (both boards). |
| S8-D16 | Out of scope | OS→student requests and outcome updates (later slice); new student screens (the Counsellor shows the summary in its own Plan screen); real pre-bachelor routes (after the pilot, a v2 scope change for the owners, parent §2); the Counsellor's side (§11); the real `pai-c` → `dev` merge. |

## 2. Components

### 2.1 Contracts (`app/os/contracts/`)

- **`decision_record.py`:** `DecisionRecordV1` (Pydantic, `extra="forbid"`, frozen):
  `schema = "pai.decision_record.v1"`, `decision_id`, `journey_id`, `student_ref` (the workspace ID, already the OS
  student ref), `chosen_at`, `authorized_at` (optional in the model so a missing consent is refused with a reason,
  not a schema error), `origin_country` and `destination_country` (ISO 3166-1 alpha-2, as `RouteContract`),
  `nationality` (optional ISO code; stored only in the export, not used in v1), `level` (`foundation` | `bachelor` |
  `master` | `phd`), `target_intake` (`IntakeRef`: any lowercase term, year), `programmes` (1–5 ranked
  `ProgrammeChoice`). `to_route_contract()` builds `RouteContract` v1 (unchanged and frozen) with
  `source = "counsellor"` and the `external_ref` of S8-D8.
- **`plan_summary.py`:** `PlanSummaryV1` (§2.4). **`escalation.py`:** `EscalationV1` (`schema`, `case_id`,
  `journey_id`, `student_ref`, `reason`, `note`, `raised_at`). **`programme_list.py`:** `ProgrammeListV1`.
- Each has a `<name>.v1.schema.json` beside `route_contract.v1.schema.json`, and fictional samples in
  `contracts/samples/` (§8).

### 2.2 Ports (`app/os/ports/`, new; parent §3 "Ports (v1: three)")

- **`plan_source.py`:** `submit_counsellor_decision(export: dict) -> str` stores the export as a pending intake row
  and returns `stored` | `duplicate` | `module_off`; `sweep_mark()` / `set_sweep_mark(mark)` keep the glue's sweep
  position.
- **`plan_query.py`:** `plan_summary(student_ref) -> PlanSummaryV1 | None`; `programme_list(route_key, intake) ->
  ProgrammeListV1`.
- **`escalation.py`:** the `EscalationSink` protocol (`escalate(plan_id, event_ids, reason, proposal_id=None) ->
  case_id`); `pending_counsellor_escalations()` and `mark_counsellor_delivery(key, status)` for the glue (the key is
  the outbox key of §2.5).
- The ports are the only OS code the host may call for Slice 8. They are built at mount time (`mount_os`) and need no
  host import (invariant 11).

### 2.3 Route in (`app/os/adapters/counsellor/intake.py`)

The worker's `counsellor.intake` job (a DBOS scheduled workflow every minute, plus one per stored export) takes each
pending intake row, in `chosen_at` order per student:
1. module off → leave it pending;
2. validate `DecisionRecordV1` → `invalid_export`; no `authorized_at` → `not_authorized`;
3. `select_playbook(origin, destination, level)` fails → `route_not_supported`;
4. any `programme_ref` not in the route's programme registry → `unknown_programme`;
5. the student has an open `self_serve` plan → `self_serve_plan_open` (+ support case);
6. a plan with this `external_ref` exists: open → `change_contract` (revision `counsellor:<decision_id>`);
   closed → `plan_closed` (+ support case);
7. otherwise: close the student's other open `counsellor` plan (S8-D8), then `PlanService.start_plan`.
The intake row records the outcome (`planned`, `revised`, `replaced`, `refused` + reason) and the plan. Every plan
change goes through the kernel (invariant 1).

### 2.4 Summary (`app/os/summary.py`)

`PlanSummaryV1`: `schema = "pai.plan_summary.v1"`, `student_ref`, `plan_id`, `route` (origin, destination, level,
intake), `built_at`, and:
- **`state`:** `finished` (plan `done`) | `paused` (plan `paused` or `changes_paused`) | `needs_student` (an open
  student item, or a proposal waiting for the student) | `on_track`;
- **`next_deadlines`:** the next 3 future due dates: step name, `template_key`, `programme_ref`, `due_at` with its time
  zone (invariant 13);
- **`waiting_on_student`:** open student items: step name, `template_key`, `programme_ref`, `due_at`;
- **`blocked`:** blocked steps: step name, `template_key`, a reason code;
- **`support_case_open`:** true or false.
Step names are the playbook's titles. The plan is the student's newest open plan (the Slice 5 rule); no open plan →
`None`.

### 2.5 Escalations (`app/os/adapters/standalone/escalation.py`, `app/os/adapters/counsellor/escalation.py`)

- `replan/apply.py` and the intake call `EscalationSink.escalate` instead of `SupportStore.open`. A composite sink
  runs the standalone adapter (support case, unchanged), then the Counsellor adapter.
- The Counsellor adapter maps the triggering event to a reason, and only for route problems on `counsellor` plans:

| Reason | Trigger (existing events, Slice 7) |
|---|---|
| `not_eligible` | `route_invalid` (the plan no longer compiles) |
| `all_rejected` | `admission_rejected` with no programme left and no swap suggestion |
| `deadline_passed` | `deadline_at_risk` on a programme deadline that replanning could not fix |
| `blocking_gap` | `escalate` (a required student step at zero slack) or `document_missing` that reaches it |
| `other` | an intake refusal of S8-D10's first four, or another route-level hand-over |

- It writes an outbox row (channel `counsellor`, key `escalation:{case_id}`, invariant 8) with an `EscalationV1`
  payload. An intake refusal of S8-D10's first four has no plan and no support case: it is sent by journey with key
  `escalation:intake:{decision_id}`, and its delivery is marked on the intake row. `self_serve_plan_open` and
  `plan_closed` open their support case on the existing plan (the self-serve or the closed one). The note is a fixed sentence per reason from `adapters/counsellor/notes.yaml` (invariant 12), never
  student or document text, never the Supervisor's reason.
- The glue's sweep delivers pending `counsellor` rows to the Counsellor's escalation code in the same app and marks
  each `sent` or `refused` (e.g. the journey is no longer at a decision stage). A refusal is recorded on the support
  case, which stays open. No retry code beyond the existing ones (invariant 7).
- Nothing new pauses or cancels the plan; the Counsellor decides with the student, and a new decision comes back in
  through §2.3.

### 2.6 Manifest and switch

`app/os/adapters/counsellor/manifest.py`: name `counsellor`, owns no task types, emits `counsellor_intake`
events, fallback `standalone`. `is_enabled(engine, tenant)` reads its `os_modules` row.

### 2.7 The glue (`backend/app/pai_os_bridge.py`, host code, shared)

The only file that touches both products. Wired in `app/main.py` (shared: Counsellor reviewer). It:
- `decision_changed(workspace_id)`: the Counsellor calls it after a choice; it reads that student's export and calls
  `submit_counsellor_decision`;
- `current_export(workspace_id)`: until the Counsellor builds its export, returns `None` ("not ready for PAI OS");
- runs a 5-minute sweep task in the API process (started from `main.py`'s lifespan): exports changed since the
  sweep mark, then pending `counsellor` escalations to the Counsellor's escalation code;
- reads only the Counsellor's decision record and export function; PAI OS never sees Counsellor tables
  (PAI OS board: "Counsellor-owned data reached only through interface files").
Several API replicas may sweep at once; S8-D9 makes repeats harmless.

## 3. Tables (Alembic `os` branch, `os_0013`; every table has `tenant_id`)

- **`os_counsellor_intake`:** `decision_id` (unique per tenant), `student_ref`, `journey_id`, `export` (JSONB),
  `export_sha256`, `chosen_at`, `status` (`pending`, `planned`, `revised`, `replaced`, `refused`), `reason`,
  `plan_id`, `counsellor_status` (as on support cases, for a refusal sent by journey), `created_at`,
  `processed_at`.
- **`os_counsellor_sweep`:** one row: `mark` (the last `chosen_at` and decision ID seen), `updated_at`.
- **`os_plans.status`** gains `closed`. **`os_support_cases`** gains `counsellor_status` (`null`, `pending`, `sent`,
  `refused`) and `counsellor_reason`.
- **`os_modules`:** the row (`counsellor`, `enabled = false`).

## 4. API

No new public endpoints. The admin support list (`GET /v1/os/admin/support`) gains `counsellor_status` and
`counsellor_reason` per case.

## 5. Screens

No new student screens (S8-D16). The admin support page (`/<workspace>/os-admin/support`) shows "Sent to the
Counsellor", "Refused by the Counsellor" or nothing per case. `frontend/lib/api.ts` is shared: Counsellor review.

## 6. Error handling

| Failure | Handling |
|---|---|
| Export fails the schema, or no consent | Refused with its reason; escalates `other` to the Counsellor |
| Route or programme PAI OS can't plan | Refused; escalates `other` to the Counsellor |
| Self-serve plan open; route previously closed | Refused; support case |
| Compile fails on a valid export (`CompileError`) | Refused `route_not_supported`, or for a revision the existing `route_invalid` event (Slice 7) |
| Worker crash during intake | DBOS resumes; the intake row's status makes every write once (crash test, §8) |
| Lost nudge | The glue sweep re-submits within 5 minutes |
| Counsellor refuses an escalation | `counsellor_status = refused` on the case; the case stays open |
| Module off | Exports stay `pending`; nothing goes to the Counsellor |

## 7. Invariants touched

- **1:** every plan change (start, revise, close) goes through the kernel.
- **4:** the Counsellor's origin is the student's own statement ("Stated"), not an agent proposal; profile rules
  are unchanged.
- **8:** intake keyed by `decision_id`; escalations keyed by case in the outbox.
- **9:** no agent sees Counsellor data; the Supervisor still sees structured plan state only.
- **11:** no Counsellor import in `app/os` (Tach); the glue is host code.
- **12:** reasons and notes in YAML; no country terms in Python; the fake routes run unchanged.
- **13:** summary deadlines carry their time zones.

## 8. Testing

- **Contract tests** (`tests/os/contracts/`): each v1 schema file matches its model (frozen); each sample export
  gives its expected result: valid Germany choice → plan; same route, new places → revision; new country → old plan
  closed and a new plan; not authorized, unknown programme, PK→PK, self-serve open, route closed → the refusal; a
  sample summary and escalation validate. They run in the `os` CI job on every PR.
- **Unit tests:** the reason mapping; the summary's four states; the programme list; composite sink with the module
  off and on; `EscalationSink` keeps every Slice 7 support-case test green.
- **Glue tests** (the host suite): `current_export` answers `None` until the export exists; an escalation reaches the
  Counsellor's real escalation code by journey; the module is off by default; re-run on `merge-test` against
  `pai-c` code.
- **Gate:** an end-to-end test with fictional records and the module on; the intake crash test; the full suites with
  the module off; the fake routes unchanged.
- Fictional data only; no real student data or keys anywhere.

## 9. Build order (one PR per task, each targeting `pai-os`, merged in order)

0. This spec and its plan (one PR).
1. `os_0013`: intake, sweep mark, `closed` plan status, support-case columns, the module row.
2. Ports and the standalone adapter: `EscalationSink` in front of `SupportStore` (no behaviour change).
3. Contracts: the four v1 models, schema files, samples, frozen tests.
4. Route in: the adapter (export → `RouteContract`, refusals, revisions, closing, self-serve refusal).
5. Route in: the `counsellor.intake` job in the worker; `submit_counsellor_decision`; module-off behaviour.
6. Summary and programme list.
7. Escalations to the Counsellor: reason mapping, outbox, notes YAML, delivery marks; the admin support page
   (`api.ts` shared: Counsellor review).
8. The glue (`app/pai_os_bridge.py`) and its `main.py` wiring (shared: Counsellor review); glue tests; re-run on
   `merge-test`.
9. Gate: end-to-end test, crash test, the Counsellor hand-over document, the Slice 8 handoff.
Then one fresh final reviewer on the most capable model and one fix pass; every decision taken without the owners is
a Ruling in its PR.

## 10. Open questions for the owners

1. **The pilot gate (S8-D3):** confirm that the pilot opens when Slice 8 passes on the PAI OS side, with the
   Counsellor side as its own gate before switching on (amends the board and D3).
2. **Scope change for later:** Matric/FSc/O-A level → BS in Pakistan (and other routes) after the pilot is outside
   v1 (parent §2). Record it as a v2 decision when the time comes.
3. **The real merge:** where production setup lives now that `pai-c` deleted `docker-compose.prod.yml` (the OS worker
   and migration steps move there), and when `pai-c` and `pai-os` meet.
4. **The old-OS inventory** must be refreshed at the real merge: 22 listed modules are deleted on `pai-c`, and 4 new
   Counsellor modules need a fate (`app.documents.owner`, `app.plugins.path_explainer`,
   `app.plugins.program_search`, `app.research.seasons`) with the Counsellor lead's sign-off.

## 11. The Counsellor side (hand-over document, written in Task 9)

For the Counsellor team, given when PAI OS is complete; their gate before switching the module on:
1. Build the export (`decision_record.v1`): origin from the Vault (`location.current_country`, as an ISO code,
   "Stated"), optional nationality (`identity.nationality`, code only), structured destination, level and intake.
2. Ask the student's consent for the hand-off and set `authorized_at`.
3. At "Where to study", offer places for plannable routes from `programme_list`; mark others "PAI OS can't plan this"
   and keep them out of the export; 1–5 ranked places per decision.
4. Call `decision_changed(workspace_id)` after a choice.
5. Accept the five escalation reasons at their escalation intake.
6. Show `plan_summary` on the Plan (J) screen, in the Counsellor's voice.
7. Add the shared CI job to `pai-c` and make their contract tests pass.
8. Fix what already fails on `pai-c` alone (§12).

## 12. Trial merge findings (local branch `merge-test`, never pushed, 2026-10-25)

`pai-c` (`e4ca3f5`) merged into `pai-os` (`c5c7ee2`): 6 files clashed (`CLAUDE.md`, `README.md`, `app/main.py`
imports, `frontend/lib/api.ts`, `frontend/lib/config.ts`, `docker-compose.prod.yml`). Fixes needed at the real merge:
the OS student ref rebuilt on the host's Firebase access rule (`application_workspace` is deleted on `pai-c`), 7 OS
calls in `api.ts` on `authHeaders()`, the OS frontend tests mocking the Firebase token, the OS bridge tests re-pinned
(the session middleware is gone). Results after the fixes: `tests/os` 1084 passed, 5 failed (the inventory, §10 Q4);
the host suite 1567 passed, 1 failed (`test_os_route_detachment`, `/v1/fetch`: it fails on `pai-c` alone too);
frontend 206 tests passed, the OS-enabled build passed, `tsc` has 4 errors in two Counsellor test files that are the
same on `pai-c` alone.
