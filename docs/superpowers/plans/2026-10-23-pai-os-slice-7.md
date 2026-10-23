# PAI OS Slice 7: replanning, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running plan changes itself the right way when something happens: rules for known events, the Supervisor
for the rest, kernel checks on every operation, student acceptance for big changes, limits, and a support inbox.

**Architecture:** New package `app/os/replan/` (events, operations, rules, checks, Supervisor, `os.replan` DBOS
workflow). Operations become plan overrides that the compiler applies on every compile, written through a new kernel
revision call. Proposals and support cases are tables; the inbox and an admin page show them.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic (`os` branch), PostgreSQL 16, DBOS, Pydantic AI (FunctionModel in
tests), Next.js + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-23-pai-os-slice-7-design.md` (in #131)

## Global Constraints

- Only the kernel writes `os_tasks`, `os_task_edges`, `os_plan_revisions` and plan status (invariant 1; the
  kernel-write test covers `app/os/replan/**`).
- The Supervisor is a tool-less actor, strong tier, input = structured plan state only (invariant 9); output repair
  at most 2 (invariant 7); no other retry code.
- Limits: 10 operations per wake; 3 replan revisions per plan per UTC day; the 4th pauses changes (S7-D9).
- Big = `swap_programme`; `cancel_task`/`skip_task` on a critical task or on all of one programme's tasks;
  `add_task` of student work longer than 1 day; a playbook upgrade. Everything else is small (S7-D7).
- A big proposal expires after 7 days, or 1 day before the earliest `latest_finish` it affects, whichever is first.
- No country, portal or currency terms in `app/os/replan/**/*.py` (invariant 12; red-flag test).
- Fake playbooks (`tests/os/playbooks/`) are shared Slice 1 fixtures: never edit them.
- One PR per task, each targeting `pai-os`, merged in order. `frontend/lib/api.ts` is shared (Counsellor reviewer).
- Before every push: `tach check` and the full `pytest tests/os`; the legacy suite when the runner, a shared file or
  `main.py` changes.

## Review Focus

1. **A recompile after a replan** (the nightly deadline engine) must keep skips, cancels, adds and reorders, and
   never resurrect a cancelled programme's tasks. → `test_overrides_survive_recompile` (Task 2).
2. **The same event delivered twice** (a detector runs again, a worker crash) gives one proposal and one revision.
   → `test_same_event_once` (Task 7).
3. **A proposal accepted after the plan changed under it** (another revision, a swap, an expiry) is refused with
   `409`, never applied to a different plan state. → `test_accept_stale_proposal_409` (Task 8).
4. **The Supervisor proposing a task that does not exist, or touching a started or protected task**, is refused by
   the kernel; the other operations still apply. → `test_refused_op_dropped_rest_applied` (Task 3).
5. **The daily limit across both sources** (rules and Supervisor) counts only replan revisions, not student swaps,
   and pausing stops later events from changing anything until an admin resolves the case.
   → `test_limit_counts_replan_only_and_pause_holds` (Task 7).

---

### Task 1: Tables and stores

**Files:**
- Create: `alembic/versions_os/os_0012_slice7_replan.py`, `app/os/replan/__init__.py`, `app/os/replan/store.py`
- Modify: `app/os/models.py`, `tests/os/test_models.py` (table list)
- Test: `tests/os/test_replan_store.py`

**Interfaces (produces):**
- Tables (all with `tenant_id`): `os_proposals(id, plan_id, event_ids jsonb, source rules|supervisor, ops jsonb,
  refused jsonb, big bool, status applied|pending|accepted|declined|expired|refused, revision int null,
  expires_at, created_at, answered_at)`; `os_plan_overrides(id, plan_id, proposal_id, op, target, payload jsonb,
  active bool, created_at)`; `os_support_cases(id, plan_id, student_ref, reason, event_ids jsonb, proposal_id null,
  status open|resolved, resolution text, created_at, resolved_at)`; `os_plans.changes_paused bool default false`;
  `os_agent_runs.plan_id` (FK, `SET NULL`) with unique (`plan_id`, `reading`).
- `ProposalStore(engine, tenant)`: `create(plan_id, event_ids, source, ops, refused, big, expires_at) -> int`,
  `get(id)`, `pending_for(student_ref)`, `set_status(id, status, revision=None)`, `for_event(event_id)`.
- `OverrideStore`: `active(plan_id) -> list[Override]`, `add(plan_id, proposal_id, op, target, payload)`.
- `SupportStore`: `open(plan_id, student_ref, reason, event_ids, proposal_id=None) -> int`,
  `list(status=None)`, `get(id)`, `resolve(id, note) -> int` (returns plan_id).

- [ ] **Step 1: Failing tests:** `test_migration_up_down_up` (down to `os_0011`: the three tables and the two
  columns are gone; up again); `test_proposal_store_roundtrip`; `test_override_store_active_only`;
  `test_support_open_resolve`; `test_tenant_isolation` (another tenant sees no rows).
- [ ] **Step 2: Run** `pytest tests/os/test_replan_store.py -v`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** the migration (self-contained, like `os_0011`), models and stores.
- [ ] **Step 4: Run** it, plus `test_models.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): replan tables and stores (Slice 7 Task 1)`.

### Task 2: Operations and compiler overrides

**Files:**
- Create: `app/os/replan/ops.py`
- Modify: `app/os/compiler/compile.py`, `app/os/service.py`
- Test: `tests/os/test_replan_ops.py`

**Interfaces (produces):**
- `ops.py`: Pydantic models with `reason: str` (1..200 chars) and a `op` literal: `AddTask(template_key,
  programme_ref=None)`, `SkipTask(instance_key)`, `CancelTask(instance_key)`, `CancelProgramme(programme_ref)`,
  `Reprioritise(instance_key, before)`, `SwapProgramme(out_ref, in_ref)`, `RequestFromStudent(instance_key,
  message)`, `Escalate()`. `Op = Annotated[Union[...], Field(discriminator="op")]`; `Ops = list[Op]` max 10.
  `is_big(op, plan_tasks: Mapping[str, TaskRow]) -> bool` per Global Constraints.
- `Override(op, target, payload)`; `to_overrides(op) -> list[Override]` for add/skip/cancel/cancel_programme/
  reprioritise (others are not overrides).
- `compile_plan(..., overrides: Sequence[Override] = ())`: after expanding instances and before scheduling:
  - `skip`/`cancel` remove the instance; edges to it from surviving tasks are dropped;
  - `cancel_programme` removes every instance with that `programme_ref`;
  - `add` adds a template instance with key `<template>[@ref]#<n>` (n = 2, 3 … by count), its template's
    `depends_on`, and an extra hard edge from every not-yet-started dependent of the template's base instance;
  - `reprioritise` adds a soft edge `before` → depends on `instance_key`.
- `PlanService.compile(contract, playbook, plan_id: int | None = None)` loads `OverrideStore.active(plan_id)` and
  passes them; `recompile` and `upgrade` pass their `plan_id`.

- [ ] **Step 1: Failing tests:** `test_skip_removes_and_drops_edges`; `test_cancel_programme_removes_all`;
  `test_add_task_second_instance_holds_dependents` (re-adding `review_visa_file` gives `review_visa_file#2` and
  `visa_apply` depends on it); `test_reprioritise_adds_soft_edge`; **`test_overrides_survive_recompile`** (start
  a Germany plan, add a cancel_programme override, run `PlanService.recompile`: the programme's tasks stay gone);
  `test_is_big_classification` (one case per Global Constraints line); `test_ops_reject_unknown_op_and_11_ops`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it, plus `test_golden.py`, `test_compiler*.py`, `test_service*.py`. Expected: PASS (no
  overrides = the golden plan unchanged).
- [ ] **Step 5: Commit** `feat(os): replan operations and compiler overrides (Slice 7 Task 2)`.

### Task 3: Kernel checks and applying overrides

**Files:**
- Create: `app/os/replan/checks.py`
- Modify: `app/os/kernel/kernel.py`
- Test: `tests/os/test_replan_checks.py`

**Interfaces (produces):**
- `checks.check_operations(current: PlanDraft, candidate: PlanDraft, ops, task_rows, playbook, confirmed:
  Callable[[str], bool]) -> tuple[list[Op], list[dict]]` (kept, refused with `{"op", "why"}`). Refuse when: the
  template is not in `playbook`; the target is protected or started (`is_started`); a surviving task has a hard
  edge to a removed one and is not removed too; a critical task's `latest_finish` in `candidate` is later than in
  `current` and later than its deadline; a swapped-in programme fails `confirmed(ref)`. After a refusal the rest is
  checked again without it (fixed point).
- `Kernel.apply_replan(plan_id, proposal_id, draft, based_on) -> int | None`: `_revise` with cause
  `replan:<proposal_id>`, under the plan lock, `StaleDraft` if `based_on` differs.
- `Kernel.set_changes_paused(plan_id, paused: bool)`; `Kernel.replan_revisions_today(plan_id) -> int` (causes
  starting `replan:` since UTC midnight).

- [ ] **Step 1: Failing tests:** one test per refusal reason; **`test_refused_op_dropped_rest_applied`**;
  `test_apply_replan_numbered_revision_and_stale`; `test_pause_flag`; `test_replan_revisions_today_counts_cause`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it, plus the kernel and kernel-write tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): kernel checks for replan operations (Slice 7 Task 3)`.

### Task 4: Events and detectors

**Files:**
- Create: `app/os/replan/events.py`
- Modify: `app/os/kernel/kernel.py` (`apply_result`, `complete_student_task`), `app/os/workers/deadline_engine.py`,
  `app/os/workers/reminders.py`, `app/os/service.py` (`playbook_newer`), `app/os/packs/approval.py`
  (`approved_changed`)
- Test: `tests/os/test_replan_events.py`

**Interfaces (produces):**
- `EVENT_TYPES = ("admission_rejected", "deadline_at_risk", "document_missing", "task_failed", "playbook_newer",
  "escalate", "approved_changed", "route_invalid")`.
- `record(conn, tenant, plan_id, type, payload, dedupe: str) -> int | None`: inserts into `os_events` unless an
  event with the same `(plan_id, type, payload.dedupe)` exists; returns the id or None.
- `pending(engine, tenant, plan_id=None) -> list[Event]`: events of these types with no proposal or support case.
- Detectors: the kernel records `task_failed` (dedupe `task:<id>:<attempt>`) and `admission_rejected` (dedupe
  `task:<id>`) inside its own transaction; the deadline engine records `deadline_at_risk` (dedupe
  `<instance_key>:<latest_finish date>`); reminders record `document_missing` for a `provide` item past due (dedupe
  `<task id>:<due date>`) next to the existing `escalate`; `PlanService.check_newer(plan_id)` records
  `playbook_newer` (dedupe `<key>@<version>`); a review task whose approval was superseded records
  `approved_changed` (dedupe `<artifact id>:<version>`); the deadline engine records `route_invalid` when a plan's
  recompile raises `CompileError` (dedupe `<contract sha>:<error>`), instead of only logging it.

- [ ] **Step 1: Failing tests:** one per detector, each also asserting the second run records nothing.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it, plus the kernel, reminders and deadline-engine tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): replan events and detectors (Slice 7 Task 4)`.

### Task 5: Rules

**Files:**
- Create: `app/os/replan/rules.py`, `app/os/replan/config.py`, `app/os/replan/<route>.yaml` for Germany
  (`min_programmes: 1`); the fake routes use the default.
- Test: `tests/os/test_replan_rules.py`

**Interfaces (produces):**
- `PlanState` (dataclass): plan id, route key, contract, tasks (`TaskRow`: instance key, template, programme,
  state, kind, critical, protected, latest_finish, slack), live programmes, swap suggestions per programme (from
  `app/os/routes/builder.py`'s suggestion function).
- `Handover(reason: str)`.
- `rules_for(event, state, cfg) -> list[Op] | Handover`, exactly as spec §2 "rules.py" lists, with these
  reasons (shown to the student):
  - rejection: "The programme did not admit you: its remaining steps are removed."
  - swap: "You have fewer programmes than planned: this one is a close match."
  - reprioritise: "This step is on the critical path for a deadline."
  - request: "This is needed to keep your plan on time."
  - failed twice: "A step failed twice: a person will look at it."
  - upgrade: "There is a newer version of your route's guide."
  - re-review: "The file you approved changed: please approve it again."

- [ ] **Step 1: Failing tests:** one per event type (expected ops and reasons), on hand-built `PlanState`s for
  Germany and a fake route; `test_rejection_without_suggestions_hands_over`; `test_no_route_terms_in_replan`
  (red-flag search over `app/os/replan/**/*.py`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): replan rules (Slice 7 Task 5)`.

### Task 6: The Supervisor

**Files:**
- Create: `app/os/agents/supervisor.v1.yaml` (zone actor, tier strong, tools [], output `replan_ops`, limits
  `max_readings: 1`, `timeout_s: 120`, `spend_usd_per_wake: 0.20`, retries output 2), `app/os/replan/supervisor.py`
- Test: `tests/os/test_replan_supervisor.py`

**Interfaces (produces):**
- `supervisor_input(state, events, refused) -> str`: a JSON block of structured fields only (no titles typed by
  the student, no page or document text, no free text), with the operation schema.
- `build_supervisor(model, spec) -> Agent` (output type `SupervisorOut(ops: Ops, summary: str)`), built like
  `statements/agents.build_agents` (DBOS durability, output retries from the spec).
- `propose(agent, spec, state, events, refused) -> AgentResult` (`output`, `error`, `usage`).

- [ ] **Step 1: Failing tests (FunctionModel):** `test_input_has_no_free_text` (a plan whose task title and an
  event payload carry a marker string: the marker is absent from the prompt); `test_valid_ops_returned`;
  `test_invalid_output_repaired_then_error_after_2`; `test_more_than_10_ops_invalid`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): the Supervisor agent (Slice 7 Task 6)`.

### Task 7: The `os.replan` workflow

**Files:**
- Create: `app/os/replan/run.py`, `app/os/replan/apply.py`
- Modify: `app/os/runner/worker.py` (register `os.replan`; the Supervisor only with a key or
  `OS_TEST_REPLAN_MODEL`), `app/os/workers/jobs.py` (a `replan` job every 5 minutes enqueuing `pending` events)
- Test: `tests/os/test_replan_run.py`

**Interfaces (produces):**
- `replan_workflow_id(tenant, plan_id, event_id) -> "replan:{tenant}:{plan}:{event}"`;
  `enqueue_replan(client, tenant, plan_id, event_id) -> str`.
- `register_replan(engine, settings, plans: PlanService, kernel, supervisor: tuple[Agent, AgentSpec] | None)`.
- Steps: `load` (state + event), `decide` (rules, else the Supervisor, else a support case), `check` (Task 3), `limit`
  (10 ops; daily count; paused), `apply` (small: overrides + `apply_replan`; big: proposal `pending` with expiry),
  `support` (open a case). Each write is keyed by the proposal id; the proposal row is created first, keyed by
  the event (`ProposalStore.for_event`).
- `accept(engine, plans, kernel, tenant, student, proposal_id) -> int` and `decline(...)` in `apply.py`: accept
  re-checks against the current plan and refuses (`ProposalStale`) if any op is now refused or the contract changed.
- `expire_due(engine, tenant, now) -> int` (run by the replan job).

- [ ] **Step 1: Failing tests (DBOS in process, Germany plan):** rejection end to end (programme tasks cancelled,
  revision cause `replan:<id>`); a big swap becomes `pending` with the right `expires_at`; a hand-over with the fake
  Supervisor applies its ops; no Supervisor → support case; **`test_same_event_once`** (enqueue twice and fork the
  workflow: one proposal, one revision); **`test_limit_counts_replan_only_and_pause_holds`**; `test_expire_due`;
  `test_replan_replay_idempotent`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it, then the full OS suite and the legacy suite (the runner is touched). Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): the os.replan workflow, limits and proposals (Slice 7 Task 7)`.

### Task 8: API

**Files:**
- Create: `app/os/api/replan.py` (`add_replan_routes`)
- Modify: `app/os/api/router.py` (mount; the inbox response gains `proposals`; the plan read gains
  `changes_paused`), `app/os/api/queries.py`
- Test: `tests/os/test_api_replan.py`

Routes as spec §4. The inbox lists the student's `pending` proposals (id, ops in words, reasons, expires_at) beside
`items` and `notes`, the way Slice 4 lists eligibility notes (no inbox task row: the kernel's tasks are plan steps).
`GET /plans/{id}/changes` lists `replan:` revisions (newest first, with the proposal's reasons) and pending
proposals. Admin routes use `require_admin`.

- [ ] **Step 1: Failing tests:** `test_inbox_lists_pending_proposal`; `test_accept_applies_200`; `test_decline`;
  **`test_accept_stale_proposal_409`**; `test_accept_expired_409`; `test_other_student_404`;
  `test_changes_list`; `test_admin_list_resolve_unpause`; `test_admin_requires_admin_403`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it, plus every `test_api*.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): replan API (Slice 7 Task 8)`.

### Task 9: Screens

**Files:**
- Create: `frontend/components/os/proposal-card.tsx`, `frontend/components/os/changes-list.tsx`,
  `frontend/app/[workspaceId]/os-admin/support/page.tsx`, `frontend/lib/os-replan.ts`,
  `frontend/components/os/replan.test.tsx`
- Modify: `frontend/lib/api.ts` (**shared**: `acceptOsProposal`, `declineOsProposal`, `getOsPlanChanges`,
  `getOsSupportCases`, `resolveOsSupportCase`), `frontend/app/[workspaceId]/os-inbox/page.tsx` (proposal cards,
  paused banner), the plan page (changes list)

Copy: the card "We suggest:" + each op in words (`opText`) + "Why:" + reasons, [Accept] [Decline], "Answer by
<date>"; the banner "Changes are paused while a person checks your plan."

- [ ] **Step 1: Failing Vitest tests:** `opText` for every op; the card (text, both buttons, the expiry); the
  banner; the changes list (newest first); the admin page list and resolve form; 360 px.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run`, `npx tsc --noEmit`, and the OS-enabled build. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): replan screens (Slice 7 Task 9)`. The PR names a Counsellor reviewer.

### Task 10: Gate, crash test, evaluation harness, final review, handoff

**Files:**
- Create: `tests/os/test_slice7_gate.py`, `tests/os/replan_cases.yaml` (the scripted events and expected changes),
  `scripts/os_supervisor_eval.py` (billed; reads `tests/os/supervisor_eval.yaml`, 20 fictional hand-over cases),
  `docs/os/handoff/slice-7-handoff.md`
- Modify: `tests/os/test_crash.py` (`test_crash_during_replan`)

- [ ] **Step 1: Failing tests:** `test_slice7_gate` (parametrised over `replan_cases.yaml`: Germany and both fake
  routes; every event through `os.replan` gives the expected end state; Supervisor cases use a FunctionModel that
  replays recorded outputs); `test_fake_routes_unchanged_without_events`; `test_crash_during_replan` (Linux CI).
- [ ] **Step 2: Run.** Expected: FAIL until the cases file is complete.
- [ ] **Step 3: Complete the cases.** The evaluation script refuses to run without `--i-have-the-owners-ok` and
  prints cost; it is **not run** in this task.
- [ ] **Step 4: Run** the full OS suite, the legacy suite and the frontend checks. Expected: PASS.
- [ ] **Step 5:** One fresh final reviewer on the most capable model over all Slice 7 commits, with the spec, this
  plan and Review Focus. One fix pass, each Critical or Important finding RED→GREEN on the branch that introduced it.
  Minors deferred.
- [ ] **Step 6: Commit** the gate, fixes and handoff; open the PRs (each targeting `pai-os`).
