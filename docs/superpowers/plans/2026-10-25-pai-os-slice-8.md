# PAI OS Slice 8: the Counsellor connection, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PAI OS and the PAI Counsellor connect through three versioned channels (route in, summary out, escalations
out) plus a programme-list read function, built and tested now and switched off for real students.

**Architecture:** New `app/os/ports/` (the only OS code the host calls for Slice 8), `app/os/contracts/` v1 models
with frozen schema files, and `app/os/adapters/{counsellor,standalone}/`. The host's glue
(`backend/app/pai_os_bridge.py`) reads the Counsellor's export and hands it to PAI OS; the OS worker plans it. Every
support case goes through a new `EscalationSink`; a Counsellor adapter also sends route problems through the outbox,
and the glue delivers them. A disabled `os_modules` row switches all of it off.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic (`os` branch), PostgreSQL 16, DBOS, Pydantic v2, Next.js + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-25-pai-os-slice-8-design.md`

## Global Constraints

- `app/os` imports nothing from the host or the Counsellor (invariant 11, `tach check`). Only
  `backend/app/pai_os_bridge.py` and `app/main.py` touch both.
- The Counsellor module row (`counsellor`, `enabled = false`) is inserted by `os_0013`. Off: exports stay `pending`,
  nothing goes to the Counsellor, standalone behaviour is unchanged (S8-D2).
- `RouteContract` v1 and `route_contract.v1.schema.json` are frozen: do not change them.
- `external_ref = "{journey_id}:{destination_country}:{level}"`; `source = "counsellor"` (S8-D8).
- Refusal reasons, exactly: `not_authorized`, `invalid_export`, `route_not_supported`, `unknown_programme`,
  `self_serve_plan_open`, `plan_closed` (S8-D10).
- Escalation reasons, exactly: `not_eligible`, `all_rejected`, `deadline_passed`, `blocking_gap`, `other` (S8-D12).
- Summary states, exactly: `finished`, `paused`, `needs_student`, `on_track`; `next_deadlines` holds at most 3.
- The export holds 1–5 ranked programmes; `level` ∈ `foundation|bachelor|master|phd`; countries are ISO alpha-2.
- No country, portal or currency terms in `app/os/adapters/**/*.py`, `app/os/ports/**/*.py`, `app/os/summary.py`
  (invariant 12; extend the red-flag test). Notes per reason live in `adapters/counsellor/notes.yaml`.
- Only the kernel writes plan state (invariant 1; extend the kernel-write test to `app/os/adapters/**`).
- Fake playbooks (`tests/os/playbooks/`) are shared Slice 1 fixtures: never edit them. Fictional data only.
- One PR per task into `pai-os`, merged in order. Shared files (`app/main.py`, `frontend/lib/api.ts`) need
  @memsa771-hub. Never open a `pai-os` → `dev` PR. `merge-test` is local only: never push it.
- Before every push: `tach check`, `python scripts/check_alembic_heads.py`, full `pytest tests/os`; the legacy suite
  when `main.py`, the glue or a shared file changes; the frontend checks when `frontend/` changes.

## Review Focus

1. **A new intake on the same route** (only the intake year or the places change) must revise the plan and keep its
   done tasks, never start a second plan. → `test_same_route_is_revision_keeps_done_tasks` (Task 4).
2. **Two API replicas submitting the same decision at once** give one intake row and one plan.
   → `test_concurrent_submit_one_row` (Task 5).
3. **Switching the module on with several pending decisions for one student** processes them in `chosen_at` order,
   so the newest decision is the plan that remains. → `test_pending_in_order_after_switch_on` (Task 5).
4. **A route problem on a self-serve plan while the module is on** is never sent to the Counsellor.
   → `test_self_serve_case_not_sent` (Task 7).
5. **A student whose old Counsellor plan was closed** gets the new plan's summary; with only closed plans the summary
   is `None`. → `test_summary_skips_closed_plans` (Task 6).

---

### Task 1: Tables and the module row

**Files:**
- Create: `alembic/versions_os/os_0013_slice8_counsellor.py`, `app/os/adapters/__init__.py`,
  `app/os/adapters/counsellor/__init__.py`, `app/os/adapters/counsellor/store.py`,
  `app/os/adapters/counsellor/manifest.py`
- Modify: `app/os/models.py`, `tests/os/test_models.py` (table list)
- Test: `tests/os/test_counsellor_store.py`

**Interfaces (produces):**
- `os_counsellor_intake(id, tenant_id, decision_id, student_ref, journey_id, export jsonb, export_sha256, chosen_at,
  status pending|planned|revised|replaced|refused, reason null, plan_id null FK SET NULL, counsellor_status null,
  created_at, processed_at null)`, unique (`tenant_id`, `decision_id`).
- `os_counsellor_sweep(tenant_id pk, mark jsonb, updated_at)`.
- `os_plans.status` allows `closed`. `os_support_cases` gains `counsellor_status` (`pending|sent|refused`, null) and
  `counsellor_reason` (null). Row (`counsellor`, `false`) in `os_modules`.
- `IntakeStore(engine, tenant)`: `add(export: dict, sha: str) -> bool` (False on a duplicate `decision_id`),
  `pending(limit=100) -> list[Intake]` (ordered by `student_ref`, `chosen_at`), `finish(id, status, reason=None,
  plan_id=None)`, `get(decision_id)`, `set_counsellor_status(decision_id, status)`.
- `SweepStore`: `mark() -> dict | None`, `set_mark(mark: dict)`.
- `manifest.py`: `NAME = "counsellor"`, `is_enabled(engine, tenant) -> bool`.

- [ ] **Step 1: Failing tests:** `test_migration_up_down_up` (down to `os_0012`: new tables, columns and the row are
  gone and `closed` is refused; up again); `test_module_row_off_by_default` (`is_enabled` → False);
  `test_intake_duplicate_decision_ignored`; `test_pending_ordered_per_student`; `test_sweep_mark_roundtrip`;
  `test_tenant_isolation`.
- [ ] **Step 2: Run** `pytest tests/os/test_counsellor_store.py -v`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** the migration (self-contained, like `os_0012`), models and stores.
- [ ] **Step 4: Run** it, `tests/os/test_models.py` and `python scripts/check_alembic_heads.py`. Expected: PASS, one
  `os` head `os_0013`.
- [ ] **Step 5: Commit** `feat(os): Counsellor intake tables and module row (Slice 8 Task 1)`.

### Task 2: Ports and the standalone escalation adapter

**Files:**
- Create: `app/os/ports/__init__.py`, `app/os/ports/escalation.py`, `app/os/adapters/standalone/__init__.py`,
  `app/os/adapters/standalone/escalation.py`
- Modify: `app/os/replan/apply.py` (`support()` calls the sink), `app/os/api/services.py` (`Services.escalations`),
  `tests/os/test_invariants.py` (kernel-write and red-flag scope)
- Test: `tests/os/test_escalation_port.py`

**Interfaces (produces):**
- `class EscalationSink(Protocol)`: `escalate(plan_id: int, event_ids: list[int], reason: str,
  proposal_id: int | None = None) -> int` (the case id).
- `StandaloneSink(engine, tenant, student_of)`: today's behaviour moved from `Replanner.support` (reuse a case
  already open for the first event, else `SupportStore.open`).
- `CompositeSink(sinks: list)`: calls each in order and returns the first's case id.
- `ports.configure(services)` / `ports.services()` (raises `OsUnavailable` when the OS is not mounted).

- [ ] **Step 1: Failing tests:** `test_standalone_sink_opens_case`; `test_sink_reuses_case_for_event`;
  `test_replanner_support_goes_through_sink` (a fake sink records the call);
  `test_ports_unavailable_when_not_mounted`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement**; `Replanner.support` delegates to `services.escalations` with no other change.
- [ ] **Step 4: Run** the new tests and the whole Slice 7 set (`pytest tests/os -k "replan or support or
  supervisor" -v`). Expected: PASS, no Slice 7 test changed.
- [ ] **Step 5: Commit** `feat(os): EscalationSink port and standalone adapter (Slice 8 Task 2)`.

### Task 3: Contracts

**Files:**
- Create: `app/os/contracts/decision_record.py`, `plan_summary.py`, `escalation.py`, `programme_list.py`, their
  `*.v1.schema.json`, `app/os/contracts/samples/*.json`, `scripts/export_os_schemas.py`
- Test: `tests/os/contracts/test_frozen.py`, `tests/os/contracts/test_decision_record.py`

**Interfaces (produces):**
- `DecisionRecordV1` (fields as spec §2.1; `programmes` `min_length=1, max_length=5`; `authorized_at: datetime |
  None`; `nationality: str | None` (ISO alpha-2)); `.external_ref -> str`; `.to_route_contract() -> RouteContract`.
- `PlanSummaryV1`, `Deadline(title, template_key, programme_ref | None, due_at, due_tz)`, `WaitingItem` (same
  fields), `BlockedItem(title, template_key, reason)`; `EscalationV1(schema, key, journey_id, student_ref, reason,
  note, raised_at)`; `ProgrammeListV1(route_key, intake, programmes: [ProgrammeEntry(programme_ref, university, name,
  facts_confirmed: bool)])`.
- Each model's `schema` field is a `Literal` (`"pai.decision_record.v1"`, `"pai.plan_summary.v1"`,
  `"pai.escalation.v1"`, `"pai.programme_list.v1"`).
- Samples (fictional): `export_valid_de.json`, `export_same_route_new_places.json`, `export_new_country.json`,
  `export_not_authorized.json`, `export_unknown_programme.json`, `export_pk_pk.json`, `summary.json`,
  `escalation.json`, each listed in `samples/expected.yaml` with its result (`planned`, `revised`, `replaced`, or a
  refusal reason).

- [ ] **Step 1: Failing tests:** `test_schema_files_match_models` (each committed file equals
  `Model.model_json_schema()`); `test_route_contract_untouched` (its schema file is byte-identical to `pai-os`'s);
  `test_external_ref_format`; `test_to_route_contract_counsellor_source`; `test_six_places_rejected`;
  `test_nationality_optional_and_not_in_route_contract`; `test_samples_validate`.
- [ ] **Step 2: Run** `pytest tests/os/contracts -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the models, the exporter script, the schema files and the samples.
- [ ] **Step 4: Run** it. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): frozen v1 contracts for the Counsellor connection (Slice 8 Task 3)`.

### Task 4: Route in, the adapter

**Files:**
- Create: `app/os/adapters/counsellor/intake.py`
- Modify: `app/os/kernel/kernel.py` (`close_plan`), `app/os/kernel/states.py` (`closed`)
- Test: `tests/os/test_counsellor_intake.py`

**Interfaces:**
- Consumes: `IntakeStore`, `DecisionRecordV1`, `PlanService.start_plan`, `Kernel.change_contract`,
  `select_playbook`, `ProgrammeStore.active(route_key)`, `EscalationSink`.
- Produces: `Kernel.close_plan(plan_id: int, cause: str) -> int` (plan `closed`, open tasks `cancelled`, one revision);
  `process(services, intake: Intake) -> IntakeResult(status, reason, plan_id)` following spec §2.3 steps 2–7
  (named `IntakeResult` because `app.os.kernel.Outcome` already exists);
  `REFUSALS` (the six reasons); the first four escalate `other` by journey (Task 7 sends it; here: an intake
  `counsellor_status = pending`).

- [ ] **Step 1: Failing tests** (Germany playbook and the fake routes, fictional exports from Task 3):
  `test_valid_export_starts_plan` (source `counsellor`, the S8-D8 `external_ref`);
  `test_same_route_is_revision_keeps_done_tasks`; `test_new_country_closes_old_plan_and_starts_new` (old plan
  `closed`, its open tasks `cancelled`, cause `superseded:<id>`); `test_route_closed_refused_plan_closed`
  (+ support case); `test_not_authorized`; `test_invalid_export`; `test_route_not_supported_pk_pk`;
  `test_unknown_programme`; `test_self_serve_plan_open_refused_with_case`;
  `test_first_four_refusals_marked_for_counsellor`; `test_fake_routes_plan_unchanged` (Ireland and Pakistan BS
  exports plan like their self-serve contracts).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `close_plan` (under the plan lock, like `_revise`) and `process`.
- [ ] **Step 4: Run** them and `tests/os/test_invariants.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): Counsellor decision to plan (Slice 8 Task 4)`.

### Task 5: Route in, submit and the intake job

**Files:**
- Create: `app/os/ports/plan_source.py`, `app/os/adapters/counsellor/run.py`
- Modify: `app/os/runner/worker.py` (register), `app/os/api/mount.py` (`ports.configure`)
- Test: `tests/os/test_counsellor_submit.py`, `tests/os/test_counsellor_run.py`

**Interfaces (produces):**
- `submit_counsellor_decision(export: dict) -> Literal["stored", "duplicate", "module_off"]` (stores even when off,
  then reports `module_off`; computes `export_sha256` of the canonical JSON); `sweep_mark()`, `set_sweep_mark(mark)`.
- Workflow `counsellor.intake` with ID `counsellor:{tenant}:{decision_id}`; job `counsellor_intake`, cron
  `* * * * *`, enqueues one workflow per pending row when the module is on.

- [ ] **Step 1: Failing tests:** `test_submit_stores_once`; `test_concurrent_submit_one_row` (two threads, same
  export); `test_module_off_keeps_pending`; `test_pending_in_order_after_switch_on`; `test_job_enqueues_each_once`
  (`dbos_worker` fixture).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement**; the workflow calls Task 4's `process` in one step and `finish` in the next.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): Counsellor intake job and submit port (Slice 8 Task 5)`.

### Task 6: Summary and programme list

**Files:**
- Create: `app/os/summary.py`, `app/os/ports/plan_query.py`
- Test: `tests/os/test_plan_summary.py`, `tests/os/test_programme_list.py`

**Interfaces (produces):**
- `build_summary(engine, tenant, student_ref, today) -> PlanSummaryV1 | None` (the newest plan whose status is not
  `done` or `closed`; if none, the newest `done` plan gives `finished`; else `None`); step titles as the inbox shows
  them (`queries.task_out`); `BlockedItem.reason` = `blocked_reason` when it matches `^[a-z_]+$`, else `"blocked"`.
- `plan_summary(student_ref)`, `programme_list(route_key, intake: IntakeRef) -> ProgrammeListV1` (active programmes;
  `facts_confirmed` = every compiler-needed programme fact is `confirmed` for that intake year).

- [ ] **Step 1: Failing tests:** `test_state_on_track`; `test_state_needs_student_open_item`;
  `test_state_needs_student_pending_proposal`; `test_state_paused_changes_paused`; `test_state_finished`;
  `test_next_deadlines_three_with_tz`; `test_no_free_text` (a planted document value and support note never appear
  in the JSON); `test_summary_skips_closed_plans`; `test_programme_list_confirmed_flag`; `test_summary_validates`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): plan summary and programme list for the Counsellor (Slice 8 Task 6)`.

### Task 7: Escalations to the Counsellor

**Files:**
- Create: `app/os/adapters/counsellor/escalation.py`, `app/os/adapters/counsellor/notes.yaml`
- Modify: `app/os/ports/escalation.py` (`pending_counsellor_escalations`, `mark_counsellor_delivery`),
  `app/os/api/services.py` (composite sink), `app/os/api/replan.py` (support list fields),
  `frontend/lib/os-replan.ts`, `frontend/components/os/support-list.tsx`, `frontend/lib/api.ts` (shared)
- Test: `tests/os/test_counsellor_escalation.py`, `frontend/components/os/replan.test.tsx`

**Interfaces (produces):**
- `CounsellorSink(engine, tenant, notes)`: after the standalone case, if the module is on, the plan's `source` is
  `counsellor` and the trigger maps to a reason (spec §2.5 table, by the first event's type), writes an outbox row
  (channel `counsellor`, key `escalation:{case_id}`, payload `EscalationV1`) and sets the case's `counsellor_status =
  pending`. Intake refusals: key `escalation:intake:{decision_id}`, reason `other`.
- `pending_counsellor_escalations() -> list[EscalationV1]`; `mark_counsellor_delivery(key, status: "sent"|"refused",
  reason: str | None)` marks the outbox row and the case or intake row.
- `notes.yaml`: one fixed English sentence per reason; loaded and checked at mount (all five present).

- [ ] **Step 1: Failing tests:** one per reason (`test_route_invalid_is_not_eligible`, `test_all_rejected`,
  `test_deadline_passed`, `test_blocking_gap`, `test_intake_refusal_is_other`); `test_system_problems_not_sent`
  (limit, task failed twice, Supervisor unavailable); `test_self_serve_case_not_sent`;
  `test_intake_support_cases_not_sent` (`self_serve_plan_open` and `plan_closed` cases have no event, so no reason,
  so nothing goes to the Counsellor); `test_module_off_not_sent`;
  `test_sent_once` (the same case twice → one outbox row); `test_note_never_supervisor_reason`;
  `test_refused_delivery_keeps_case_open`; Vitest `shows sent to the Counsellor`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement**; the support page shows "Sent to the Counsellor" / "Refused by the Counsellor".
- [ ] **Step 4: Run** them, the full `tests/os`, and the frontend checks (`npx vitest run`, `npx tsc --noEmit`,
  `NEXT_PUBLIC_OS_ENABLED=true npm run build`). Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): escalations to the Counsellor (Slice 8 Task 7)`.

### Task 8: The glue

**Files:**
- Create: `backend/app/pai_os_bridge.py`
- Modify: `backend/app/main.py` (start the sweep in the lifespan; shared)
- Test: `backend/tests/test_pai_os_bridge.py` (host suite)

**Interfaces:**
- Consumes: `submit_counsellor_decision`, `sweep_mark`, `set_sweep_mark`, `pending_counsellor_escalations`,
  `mark_counsellor_delivery`.
- Produces: `decision_changed(workspace_id: str) -> str | None`; `current_export(db, workspace_id) -> dict | None`
  (imports the Counsellor's export function `app.pai_c.os_export.decision_record_v1` when it exists, else `None`);
  `sweep_once(db) -> dict` (counts); `start_sweep()` (an asyncio task every 300 s, via `asyncio.to_thread`).
  `sweep_once` reads `pai_decision_records` rows with `chosen_at` after the mark, submits each student's current
  export, then delivers pending escalations through the app's own ASGI transport to `POST /v1/escalations` with
  `X-PAI-Service-Token`: 200 → `sent`; 404/409/422 → `refused` with the status; 503 or no token → left pending.
  When the OS is not mounted, every function returns without doing anything.

- [ ] **Step 1: Failing tests:** `test_no_export_yet_is_none`; `test_decision_changed_submits_export` (a stub
  export function); `test_sweep_submits_since_mark_and_moves_it`; `test_escalation_reaches_counsellor_endpoint`
  (the real `/v1/escalations` with a test token: journey moves to `DIRECTION`); `test_counsellor_409_marks_refused`;
  `test_no_token_leaves_pending`; `test_os_not_mounted_noop`; `test_module_off_by_default_end_to_end`.
- [ ] **Step 2: Run** `env -u OS_TEST_DATABASE_URL python -m pytest tests/test_pai_os_bridge.py -v -p no:tach`.
  Expected: FAIL.
- [ ] **Step 3: Implement**; `main.py` starts `start_sweep()` only when `mount_os` returned True.
- [ ] **Step 4: Run** it, `tach check`, and the full legacy suite. Expected: PASS (the existing failures noted in
  spec §12 are on `pai-c` only, not `pai-os`).
- [ ] **Step 5: Re-run on `merge-test`:** cherry-pick the task commits onto local `merge-test`, run
  `tests/test_pai_os_bridge.py` and `tests/os/contracts` there. Expected: PASS. Never push `merge-test`.
- [ ] **Step 6: Commit** (on the task branch) `feat: PAI OS bridge for the Counsellor (Slice 8 Task 8)`.

### Task 9: Gate, crash test, hand-over, handoff

**Files:**
- Create: `tests/os/test_slice8_gate.py`, `tests/os/test_crash_counsellor_intake.py`,
  `docs/os/handoff/counsellor-handover.md`, `docs/os/handoff/slice-8-handoff.md`

- [ ] **Step 1: Failing tests:** `test_end_to_end_module_on` (fictional export → plan → `plan_summary` →
  a `route_invalid` event → an `EscalationV1` pending for the Counsellor); `test_standalone_suite_module_off`
  (self-serve start, replan and support case as in Slice 7; nothing written to `os_counsellor_*` or channel
  `counsellor`); `test_crash_during_counsellor_intake` (SIGKILL the worker between `process` and `finish`: one plan,
  one intake row `planned`; Linux CI, as the other crash tests).
- [ ] **Step 2: Run** them. Expected: FAIL until the fixtures exist; then PASS.
- [ ] **Step 3: Write** `counsellor-handover.md` from spec §11 (the 8 steps, the four schema files, the samples, the
  tests they must pass, the CI job to copy), and `slice-8-handoff.md` (as the Slice 7 handoff: state, rulings,
  deferred minors, owners' items from spec §10).
- [ ] **Step 4: Run** every check: `tach check`, the heads check, full `pytest tests/os`, the legacy suite, the
  frontend checks, and Task 8 Step 5 on `merge-test`. Expected: PASS.
- [ ] **Step 5: Commit** `test(os): Slice 8 gate, crash test, Counsellor hand-over and handoff (Slice 8 Task 9)`.
- [ ] **Step 6: Final review:** one fresh reviewer on the most capable model over the whole slice; then one fix pass
  (each Critical or Important finding gets a RED→GREEN test on the branch that introduced it; Minors are listed in
  the handoff).
