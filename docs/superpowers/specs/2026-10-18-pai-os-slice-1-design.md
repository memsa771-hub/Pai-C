# PAI OS Slice 1: Plan with no AI — Design Spec

Status: draft for review · 2026-10-18 · Parent spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md`
(the parent wins on any conflict). Inputs: the Spike 5 walkthrough
`docs/os/spikes/spike5-germany-playbook.md` (PR #38), the Slice 0 handoff §6 lessons (PR #39) and the
Spike 3 report (PASS).

## 1. Outcome

A test student gets a correct, dated plan and inbox for the Germany master's route. A worker crash
loses nothing. The two fake routes run without code changes (parent §6, Slice 1 "Done when").

There is no AI in this slice. Everything here is rule-based code, playbook data and hand-seeded
Knowledge.

## 2. Decisions taken in brainstorming (2026-10-18)

| # | Decision | Choice |
|---|---|---|
| S1-D1 | Scope | Core plus one inbox screen. The grade converter, funds calculator and checklist validator move to the slices that first use them (3 and 6). The renderer stays in Slice 6. The freshness sweeper comes in Slice 2. |
| S1-D2 | Knowledge before Slice 2 | A small `os_knowledge_facts` table behind the Knowledge port, seeded by hand. |
| S1-D3 | How a plan starts | A protected admin endpoint that takes a RouteContract (PlanSource, standalone adapter). The student UI to start a route comes in Slice 4. |
| S1-D4 | Email | Outbox plus a logging sender. Real Resend sending is switched on before the pilot, with the staging allow-list. |
| S1-D5 | Architecture | Approach A: a kernel service is the sole writer of plan state, and DBOS runs only the task attempts (the Spike 3 loop). Event sourcing and plan-as-workflow were rejected as slower and against the kernel rule. |
| S1-D6 | Knowledge status | The parent's three statuses stay (`confirmed`, `unconfirmed`, `stale`). A fact on which two official sources disagree is stored as `unconfirmed` with a `conflict_note` (the Spike 5 open point). |

**Out of this slice:** AI agents; the research agent and the freshness sweeper (Slice 2); document
upload and extraction (Slice 3); the self-serve start (Slice 4); statements, the pack and the visa file
(Slices 5 and 6); the rules engine, the Supervisor and the daily revision limits (Slice 7); the
Counsellor adapter (Slice 8). These tables also wait for the slices that use them: `os_budgets`,
`os_outcomes`, `os_agent_runs`, `os_human_tasks` (inbox items are `os_tasks` rows, §4.5),
`os_approvals`, `os_artifacts` and `os_artifact_versions`.

## 3. Layout

All product code lives in `backend/app/os/`. Tach allows `app.os` to depend on nothing; root code
(`app/main.py`) may import `app.os`.

```
app/os/
  playbooks/            models.py (Pydantic), loader.py, germany_master.v1.yaml
  knowledge/            port.py (KnowledgePort), store.py (SQL), seed/germany_ws2027.yaml
  compiler/             compile.py (pure), schedule.py, conditions.py
  kernel/               states.py, kernel.py (sole writer), revisions.py
  runner/               registry.py, enqueue.py, reconcile.py, workflow.py (DBOS), worker.py (process)
  workers/              deadline_engine.py, reminders.py, manual.py
  outbox/               outbox.py, senders.py (LogSender)
  api/                  router.py, deps.py (ports for auth and the session)
  models.py             SQLAlchemy tables (OsBase, schema "os")
alembic/versions_os/    os_0002_slice1_tables.py
tests/os/playbooks/     ireland_master.v1.yaml, pakistan_bs.v1.yaml (the fake routes, D5)
frontend/app/os/inbox/  page.tsx (behind NEXT_PUBLIC_OS_ENABLED)
```

## 4. Components

### 4.1 Playbooks

Playbooks are versioned YAML files, loaded and validated at startup. An invalid playbook stops the
startup.

- **Top level:** `key`, `version`, `route` (origin, destination, level), `default_timezone`, `constants`
  (named values with a citation, for example `uni_assist_min_weeks_before_deadline: 8`), `tasks`.
- **Each task:**
  - `template_key` (unique), `task_type` (must have a registered owner, §4.4), `title`, and
    `kind` (`work` or `student`). A `student` task also has an `inbox_kind`: `provide`, `approve`,
    `act` or `choose`.
  - `depends_on`: a list of `{key, hard: true|false}`.
  - `fan_out`: `none` or `programme`.
  - `condition`: a small structured test, for example
    `{fact: application_route, in: [uni_assist, uni_assist_vpd]}`. It is not a free-text expression,
    so nothing is `eval`'d.
  - `anchor`: the date the task is scheduled back from, for example `{fact: deadline_close}` or
    `{task: visa_apply}`.
  - `lead_time`: `{days: N}` or `{constant: name}`.
  - `duration_days`: an estimate, always labelled as an estimate.
  - `fallback`: what happens if the owner module is off.
  - `protected`: a bool.
  - `citations`: a list of `{source, url}`.
- **The Germany playbook** encodes the Spike 5 phases A–D. The loader refuses any Germany step without
  at least one citation, except the steps that Spike 5 marks per-programme (A8, B3, D3). Those cite
  the programme's Knowledge fact instead.
- **Invariant 12:** country names, currencies, document names and attestation bodies appear only in
  YAML, never in Python. A red-flag test searches `app/os/**/*.py` for a deny-list of such terms.

### 4.2 Knowledge port and seed store

- **`KnowledgePort`:**
  - `facts(programme_refs, fields, intake) -> dict[(programme_ref, field), Fact]`.
  - `route_facts(route_key, fields, intake) -> dict[field, Fact]`, for route-level facts such as
    the blocked-account amount.
- **`Fact`:** `value`, `quote`, `url`, `checked_at`, `intake_year`, `status`, and an optional
  `conflict_note`.
- **Table `os_knowledge_facts`:** `tenant_id`, `scope` (`route` or `programme`), `ref`, `field`,
  `intake_year`, `value` (JSONB), `quote`, `url`, `checked_at`, `status`, `conflict_note`. It is unique
  on (tenant_id, scope, ref, field, intake_year).
- **Seed:** `knowledge/seed/germany_ws2027.yaml` holds the route facts from Spike 5 and the programme
  facts for three shortlist programmes. Every seeded value carries its quote and URL. Values not
  published for WS 2027/28 are seeded as `unconfirmed`. Loading the seed is idempotent.
- Slice 2's research agent writes to the same table through the same port, so the compiler does not
  change.

### 4.3 Compiler (pure: no database access, no clock, no randomness)

`compile_plan(contract, playbook, facts, today) -> PlanDraft`. The steps:

1. **Filter** tasks by `condition`. A condition on a missing fact counts as true, and the task gets a
   `provisional` mark.
2. **Fan out** programme tasks, one per `contract.programmes` entry. The instance key is
   `template_key@programme_ref`.
3. **Resolve anchors.**
   - A `confirmed` fact gives a firm date.
   - An `unconfirmed` fact gives a `provisional` date plus a `confirm_fact` task, owned by
     `knowledge.manual` in Slice 1 and by the research agent from Slice 2.
   - A missing fact leaves the task `blocked` with reason `fact_missing:<field>`, plus a
     `confirm_fact` task.
4. **Build the graph.** Cycles are rejected with the cycle in the message.
5. **Schedule backwards.**
   - A deadline is end of day in the anchor's timezone: from the fact, else the playbook's
     `default_timezone` (invariant 13). All datetimes are timezone-aware.
   - `latest_finish` = min(anchor − lead_time, the `latest_start` of each hard successor), and
     `latest_start` = `latest_finish` − `duration_days`.
   - A forward pass from `today` gives `earliest_start`. `slack` = `latest_start` − `earliest_start`.
6. **Critical path:** the tasks with minimum slack. Negative slack marks the plan `at_risk`. It is
   still created, and a `slack_low` event is emitted.

The same input always gives the same `PlanDraft`, which is what the golden tests rely on.

### 4.4 Kernel, states and revisions

- **States:** `pending`, `ready`, `running`, `waiting_student`, `waiting_review`, `done`, `failed`,
  `skipped`, `cancelled`, plus `blocked` with a `blocked_reason`.
- **Allowed transitions** (anything else raises `IllegalTransition`):
  - `pending` → `ready` (when all hard dependencies are `done` or `skipped`), `skipped`, `blocked` or
    `cancelled`.
  - `ready` → `running` for work tasks, `waiting_student` for student tasks, or `cancelled`.
  - `running` → `done`, `failed`, `waiting_student` (input missing) or `waiting_review`.
  - `waiting_student` and `waiting_review` → `ready` or `done`.
  - `failed` → `ready`, only through `kernel.retry`, which increments the attempt.
  - `blocked` → `ready` when the reason clears.
  - Every non-terminal state → `cancelled` through a revision.
- **API:** `create_plan(draft, contract)`, `apply_result(task_id, attempt, result)`,
  `complete_student_task(task_id, student_ref, payload)`, `retry(task_id)`,
  `revise(plan_id, cause, new_draft)` and `upgrade_playbook(plan_id, to_version)`.
- **Every call runs in one transaction.** It updates rows, writes a numbered `os_plan_revisions` row
  for structural changes (with its cause), writes `os_events` rows, and inserts `os_enqueue_requests`
  for tasks that became ready (the dual-write rule).
- **Plan identity** is (tenant_id, source, external_ref). Re-posting identical contract content is a
  no-op that returns the existing plan, matched by a SHA-256 of the canonical JSON. Different content
  creates a revision, never a second plan.
- **Revisions** (parent §4.3):
  - New tasks are inserted.
  - Tasks that are removed or changed are applied only if they have not started (`pending`, `ready`
    or `blocked`). A started task keeps its version and the revision records the skip.
  - `protected` tasks are never removed.
  - The student sees a "your plan was updated" item.
- **Invariant 1 check:** a test parses `app/os/**/*.py` and fails if any module outside `kernel/`
  issues INSERT, UPDATE or DELETE on `os_plans`, `os_tasks`, `os_task_edges` or
  `os_plan_revisions`.

### 4.5 Inbox

Student tasks are `os_tasks` rows with `kind = student` and an `inbox_kind`. They sit in
`waiting_student` while open. PlanQuery serves them sorted by due date. There is no separate inbox
table in Slice 1.

### 4.6 Runner (the Spike 3 loop, made production-shaped)

- **Registry:** every `task_type` maps to exactly one owner module (invariant 2). Startup and a CI test
  fail on an unowned or doubly owned type. `os_modules` holds the on/off row per module, and a
  disabled module triggers the playbook `fallback` through a revision.
- **Enqueue and reconcile** follow the Spike 3 rules:
  - The kernel side uses `DBOSClient` only and never executes workflows.
  - The workflow ID is `task_id:attempt`, enqueued with "return-existing".
  - Every process sets an explicit `application_version`.
  - The enqueuer marks requests sent. The reconciler runs every 5 minutes and repairs any mismatch in
    either direction, mapping terminal ERROR, CANCELLED and MAX_RECOVERY_ATTEMPTS_EXCEEDED to
    `failed` (`workflow_error`).
- **Workflow `os.run_attempt`:** load inputs → call the owner module's handler → `kernel.apply_result`.
  Steps are idempotent (invariant 8). Network retries happen only as DBOS step retries (invariant 7).
- **Worker process:** `python -m app.os.runner.worker`. It needs a stable executor ID per replica
  (`OS_WORKER_ID`, for example a compose service index) and never uses the shared default `"local"`.
  It is a separate container (parent §7). The compose change is a shared-file PR to `dev` (§8, task 11).
- **Scheduled jobs** (the reconciler every 5 minutes, the deadline engine and reminders hourly) are
  DBOS scheduled workflows in the worker process. DBOS runs each tick once across replicas. They write
  plan state only through the kernel.

### 4.7 Workers (Slice 1)

- **`deadline_engine`:** a DBOS scheduled workflow that runs hourly, and also on a `fact_changed` or
  `plan_revised` event. It recomputes dates and slack through the compiler's scheduler and applies
  changes through `kernel.revise`. Slack at or below 0 emits `slack_low`.
- **`reminders`:** runs hourly and computes which open student tasks are due a reminder, using the
  parent's cadence: more than 14 days of slack weekly, 7–14 every 3 days, 2–7 daily, under 48 h twice
  daily, and 0 escalates (the escalation event is logged; Slice 7 acts on it). Each reminder is an
  outbox row keyed `reminder:{task_id}:{slot}`, where the slot is the cadence window, so a re-run
  never sends twice.
- **`knowledge.manual`:** owns `confirm_fact` tasks in Slice 1. An admin confirms or corrects a fact
  through the API, which updates `os_knowledge_facts` and emits `fact_changed`.

### 4.8 Outbox

- **Table `os_outbox`:** `tenant_id`, `idempotency_key` (unique), `channel` (`email`), `recipient`,
  `template`, `payload`, `status` (`pending`, `sent` or `skipped`), `attempts`, `sent_at`.
- A DBOS step delivers pending rows through a `Sender` interface. A key that is already sent is
  skipped. Slice 1 ships `LogSender`, which writes to the log and to `os_events`.
  `OS_EMAIL_SENDER=log|resend` selects the sender. `resend` and the staging allow-list come before the
  pilot.

### 4.9 API (mounted by `app/main.py` under `/v1/os`, only when `OS_ENABLED`)

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /v1/os/plans` | admin token `OS_ADMIN_TOKEN` | PlanSource: a RouteContract in, the plan out (idempotent) |
| `GET /v1/os/plans/{plan_id}` | admin, or the plan's student | PlanQuery: tasks, dates, slack, status |
| `GET /v1/os/inbox` | student | Open student tasks for the signed-in student |
| `POST /v1/os/inbox/{task_id}/complete` | student | Completes a provide, act or choose item (payload for `choose`) |
| `POST /v1/os/facts/{fact_id}/confirm` | admin | Confirms or corrects a seeded fact (`knowledge.manual`) |
| `POST /v1/os/plans/{plan_id}/upgrade` | admin | Applies a newer playbook version as a revision |

Student identity comes through a port: `app/os/api/deps.py` declares
`current_student_ref() -> str`, and `app/main.py` overrides it with a function that maps the
Counsellor's signed-in Supabase user to `student_ref`. The OS never imports Counsellor auth (Tach).

### 4.10 Tables (Alembic `os` branch, migration `os_0002`; every table carries `tenant_id`)

- `os_plans`: `id`, `tenant_id`, `source`, `external_ref`, `student_ref`, `contract` (JSONB),
  `contract_sha256`, `status` (`active`, `at_risk`, `paused` or `done`), `current_revision`. Unique on
  (tenant_id, source, external_ref).
- `os_tasks`: `id`, `plan_id`, `instance_key`, `template_key`, `task_type`, `kind`, `inbox_kind`,
  `programme_ref`, `state`, `blocked_reason`, `attempt`, `earliest_start`, `latest_start`,
  `latest_finish`, `due_at` (timezone-aware), `due_tz`, `provisional`, `slack_days`,
  `critical`, `citations` (JSONB), `playbook_version`, `result` (JSONB). Unique on (plan_id,
  instance_key).
- `os_task_edges` (`from_task`, `to_task`, `hard`); `os_plan_revisions` (`plan_id`, `number`,
  `cause`, `diff`); `os_playbook_pins` (`plan_id`, `playbook_key`, `version`).
- `os_enqueue_requests` (`task_id`, `attempt`, `sent`); `os_task_attempts` (`task_id`, `attempt`,
  `workflow_id`, `status`, `started_at`, `ended_at`).
- `os_events` (`plan_id`, `task_id`, `type`, `payload`, `at`); `os_modules` (`module`, `enabled`).
- `os_outbox` (§4.8); `os_knowledge_facts` (§4.2).

### 4.11 Student screen (mobile-first)

`frontend/app/os/inbox/page.tsx` is shown only when `NEXT_PUBLIC_OS_ENABLED=true`. It calls
`GET /v1/os/inbox`.

```
┌ Your next steps ──────────────────┐
│ OVERDUE                           │
│ ● Provide · HEC e-Attestation     │
│   due 12 Mar 2027, 23:59 (Berlin) │
│   source: hec.gov.pk ↗     [Done] │
│ THIS WEEK                         │
│ ● Act · Book an IELTS test        │
│   due 20 Mar · estimated     [Done]│
│ LATER                             │
│ ● Choose · Confirm your programmes│
│   3 options ▾             [Confirm]│
└───────────────────────────────────┘
```

- Items are grouped as Overdue, This week and Later.
- Each item shows its inbox kind, title, due date with the timezone, a `provisional` or `estimated`
  label when it applies, and its official source link (parent success criterion 2, invariant 3).
- There is one action per item. "Provide" items only mark done in Slice 1; upload comes in Slice 3.
- The page works at 360 px width.

## 5. Error handling (Slice 1 subset of parent §4.4)

| Failure | Handling | Ends in |
|---|---|---|
| transient | DBOS step retry with backoff, max 3 | `running` resumes |
| `worker_crash` | DBOS resume on the same executor ID and app version | `running` |
| `input_missing` | provide item for the student | `waiting_student` |
| `module_disabled` | playbook `fallback` via `kernel.revise` | plan revision |
| `requirement_changed` | `fact_changed` → deadline engine recompute → `kernel.revise` | plan revision |
| `workflow_error` | reconciler maps the terminal DBOS status | `failed` (admin `retry`) |
| invalid contract | 422 with the validation reason | not created |
| invalid playbook | startup fails, naming the file and the field | not started |

## 6. Testing and acceptance

Tests are written first (TDD). From `backend/`: `tach check`, the heads check and
`pytest tests/os -v -rs` run in CI job `os` on every PR.

1. **Golden test student (acceptance):** a Pakistani BS CS graduate, three seeded programmes, WS
   2027/28, and a frozen `today`. `compile_plan` plus `create_plan` gives tasks, dates, slack and inbox
   items that match `tests/os/golden/test_student_plan.json`.
2. **Fake routes (D5):** `ireland_master.v1` (two steps) and `pakistan_bs.v1` (entry test, merit-list
   round, no visa) compile and run end to end with no change to `app/os` code.
3. **State machine:** a table-driven test over every allowed and every forbidden transition.
4. **Compiler:** cycle rejection, end of day in the anchor's timezone, provisional dates and
   `confirm_fact` tasks for unconfirmed facts, `blocked` for missing facts, and negative slack giving
   `at_risk`.
5. **Kernel:** `create_plan` is idempotent for identical content; changed content creates a revision;
   a playbook upgrade inserts new tasks and leaves started tasks alone; events and enqueue requests are
   written in the same transaction (a forced rollback test).
6. **Invariant checks:** kernel-only writes (1), registry ownership (2), the country-term red-flag
   search (12), and timezone-aware datetimes on every date column (13).
7. **Outbox:** the same idempotency key twice sends once; a reminder re-run in the same cadence slot
   adds no row.
8. **Crash test:** SIGKILL workers while the golden plan runs. No task is lost or duplicated. This is
   the Spike 3 method on the real runner, small enough for CI.
9. **API:** contract validation (422), admin-token checks, and a student who sees only their own
   inbox.
10. **Inbox page:** a Vitest component test for grouping, labels and source links.

## 7. Invariants touched

1, 2, 3 (each fact-based date carries its Knowledge citation, and each step carries its playbook
citation), 7, 8, 10 (pins and upgrades), 11 (Tach), 12, 13. Invariants 4, 5, 6 and 9 do not apply:
there are no agents and no outbound student artifacts in Slice 1.

## 8. Build order (for the plan; one branch and PR per task, off `pai-os`)

1. Remove `backend/spikes/` and its tests and fixtures (handoff §4.5). Its lessons are carried here.
2. Tables and migration `os_0002`, with the timezone-awareness test.
3. Playbook models, loader and the citation rule; the two fake playbooks.
4. Knowledge port, store and seed.
5. Compiler (pure), with the compiler tests.
6. Kernel, state machine and revisions, with the kernel-write test.
7. Runner: registry, enqueue, reconcile, workflow and worker; the crash test.
8. Workers: the deadline engine, reminders and `knowledge.manual`; the outbox and `LogSender`.
9. API and the auth port; `app/main.py` mount (shared file: needs a Counsellor reviewer).
10. Germany playbook v1 (from Spike 5) and the golden test student.
11. Inbox page (frontend) and its Vitest test; the `os-worker` compose service (shared file, PR to
    `dev` first).

## 9. Open points carried from Spike 5

- **A1:** the developers report that uni-assist accepts the HEC e-Attestation Certificate. The seeded
  fact stays `unconfirmed` until a source is attached.
- **Visa lead time:** unknown. The Germany playbook uses a cited, estimated `duration_days`, and the
  inbox labels it `estimated`. A confirm task asks for a real figure.
- **2027 amounts** (blocked account, fees) are seeded `unconfirmed`. Slice 2's freshness sweeper
  re-checks them.
