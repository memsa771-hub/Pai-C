# PAI OS Slice 7: replanning (design)

Date: 2026-10-23. Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (§3 "Rules and Supervisor", the agent
table row "Supervisor: actor, strong, typed proposals, kernel validation, student acceptance", §4.4 error handling,
review F7, invariants 1, 5, 7, 8, 9, 10, 12; §6 Slice 7). Builds on Slices 1–6b on `pai-os`. Owners: **follow the
parent spec**, Supervisor included (2026-10-23).

**Goal.** When something happens to a running plan (a rejection, a deadline at risk, a missing document, a failed
task, a newer playbook, an escalation, a changed approved file), the plan changes the right way, by itself:
- **rules** handle the known events;
- the **Supervisor** (an AI actor) proposes typed operations for the rest;
- the **kernel** checks every operation and stays the only writer of plan state (invariant 1);
- **big changes need the student's acceptance**; small ones apply and are shown as "what changed";
- the **limits** hold (10 operations per wake, 3 revisions per plan per day). Beyond them changes pause, the student
  is told, and the case goes to the **support inbox**.

**Done when:**
- every scripted event gives the right change (rules in CI; the Supervisor in CI with a fake model);
- the Supervisor evaluation passes (billed, only with the owners' OK: §8);
- a crash during a replan loses and duplicates nothing;
- the fake Ireland and Pakistan BS routes run unchanged (invariant 12).

## 1. Decisions

| # | Topic | Decision |
|---|---|---|
| S7-D1 | Scope | Rules **and** the Supervisor, as the parent spec says (owners, 2026-10-23). |
| S7-D2 | Events | A closed list, each recorded in `os_events`: `admission_rejected` (an `admission_result` completed with `{"choice": "rejected"}`), `deadline_at_risk` (the deadline engine finds a critical task with slack < 0, or the plan turns `at_risk`), `document_missing` (a `provide` item past its due date), `task_failed` (a task ends `failed`, including `budget_exceeded`), `playbook_newer` (a newer playbook version exists for the plan's route), `escalate` (already logged by the reminders worker), `approved_changed` (an artifact whose approval completed a review task gets a new current version, e.g. the visa programme changed), `route_invalid`. Each event wakes one `os.replan` workflow for its plan. |
| S7-D3 | Rules first | Pure rules (`app/os/replan/rules.py`) map an event to operations. Rules always run first; the Supervisor sees only events no rule handled, or a rule's explicit hand-over. Rules are generic: templates, counts and limits come from the playbook and `replan` config, never from Python (invariant 12). |
| S7-D4 | Operations | One typed union, shared by rules and the Supervisor: `add_task(template_key, programme_ref?)`, `skip_task(instance_key)`, `cancel_task(instance_key)`, `reprioritise(instance_key, before)`, `swap_programme(out_ref, in_ref)`, `request_from_student(template_key or instance_key, message)`, `escalate(reason)`. Every operation carries a one-line `reason` shown to the student. |
| S7-D5 | Persistence | Skips, cancels, adds and priority changes are **plan overrides** (`os_plan_overrides`), applied by the compiler on every compile, so a later recompile (the deadline engine, a fact change) keeps them. `swap_programme` is the Slice 4 contract change. `request_from_student` re-raises an inbox item. `escalate` opens a support case. Applying overrides is a kernel revision with cause `replan:<proposal id>` (invariants 1, 10). |
| S7-D6 | Kernel checks | `Kernel.check_operations(plan_id, ops)` compiles the candidate plan and refuses an operation when: the template does not exist in the pinned playbook; it touches a protected or started task; a dependent task loses its only input; another critical task's latest finish moves past its deadline; a swapped-in programme lacks confirmed facts for the compiler's needed fields. A refused operation is dropped with its reason logged; the rest of the proposal is checked again without it. |
| S7-D7 | Small vs big | **Big** (needs the student's acceptance): `swap_programme`, `cancel_task` or `skip_task` on a critical task or a whole programme's tasks, `add_task` that adds student work of more than one day, and a playbook upgrade. **Small** (applies at once, shown as "what changed"): `reprioritise`, `request_from_student`, `escalate`, and the rest. A big proposal is an inbox `choose` item (Accept / Decline) that expires after 7 days, or 1 day before the earliest deadline it affects. Declined or expired: nothing changes and the event is marked handled. |
| S7-D8 | Supervisor | A tool-less **actor** on the strong tier (`agents/supervisor.v1.yaml`), Pydantic AI. Input: structured plan state only (tasks with state, dates, slack, programme, critical flag; fact statuses; the triggering events; the operations the kernel already refused). **No raw outside content** (invariant 9): no page text, no document text, no free text the student typed. Output: at most 10 operations with reasons, or `escalate`. Output repair at most 2 attempts (invariant 7). Spend per wake is capped (`spend_usd_per_wake`), logged in `os_agent_runs`. No key or no budget: the case goes to the support inbox. |
| S7-D9 | Limits | At most 10 operations per wake (extra ones dropped and logged) and 3 replan revisions per plan per UTC day. The 4th: the plan's `changes_paused` flag is set, the student sees "Changes are paused while a person checks your plan", and a support case opens (review F7). Only resolving the case clears the flag. Student-driven changes (swap, self-serve edits) do not count towards the limit. |
| S7-D10 | Support inbox | `os_support_cases` (plan, reason, events, proposal, status `open` → `resolved`, resolution note). Written through the `EscalationSink` port; the standalone adapter writes the table (the Counsellor adapter is Slice 8). An admin API and a minimal admin page list, read and resolve cases. Resolving can unpause the plan. |
| S7-D11 | Visa change (6b open item 1) | `approved_changed` on a done review task: the rule adds the review task again (`add_task`, a new instance `review_visa_file#2`) and holds its dependents until it is approved. This is small (the student caused it). For the owners to confirm (§11 Q1). |
| S7-D12 | Idempotent | One `os.replan` workflow per (plan, event id). Every write carries the proposal id; a repeated step finds its write already made (invariant 8). |
| S7-D13 | Out of scope | Counsellor escalation (Slice 8), email notifications for proposals (the existing reminders and outbox only), learning from accepted or declined proposals, and portal automation (never). |

## 2. Components (`app/os/replan/`, new)

- **`events.py`:** the event types, `record(engine, tenant, plan_id, type, payload)`, and the detectors that run in
  the existing workers (deadline engine, reminders, freshness) and on kernel results (`apply_result` failed,
  `complete_student_task` for `admission_result`, the 6b approval path). Each detector writes an event once
  (dedupe key in the payload).
- **`ops.py`:** the operation union (Pydantic), the small/big classification (S7-D7).
- **`rules.py`:** pure `rules_for(event, plan_state, playbook, config) -> list[Op] | Handover`.
  - `admission_rejected`: cancel the programme's remaining tasks; if the plan has fewer live programmes than the
    route's `replan.min_programmes` (per-route config, default 1; the RouteContract is unchanged), propose `swap_programme` with the Slice 4 swap suggestions.
  - `deadline_at_risk`: `reprioritise` the critical path ahead of non-critical student work; if still at risk,
    `request_from_student` (the blocking item) and, if the deadline is for a programme, hand over to the Supervisor.
  - `document_missing`: `request_from_student` on the item.
  - `task_failed`: one retry through `Kernel.retry` (no operation); a second failure: `escalate`.
  - `playbook_newer`: a big proposal to upgrade.
  - `approved_changed`: S7-D11.
  - `escalate`, `route_invalid`, and anything else: hand over to the Supervisor.
- **`supervisor.py`:** builds the structured input, calls the agent, validates the output.
- **`checks.py`:** the kernel's operation checks (S7-D6), called through `Kernel.check_operations`.
- **`apply.py`:** writes overrides and contract changes as one kernel revision; creates the proposal's inbox item
  when big; opens support cases.
- **`run.py`:** the `os.replan` DBOS workflow: `load` → `rules` → `supervisor` (only on hand-over) → `check` →
  `limit` → `apply` or `propose` → `done`. Steps return ids and small JSON, never plan blobs.
- **Compiler:** `compile_plan(..., overrides=())` applies skip, cancel, add and priority overrides after
  expanding the playbook.
- **Kernel:** `check_operations`, `apply_overrides(plan_id, proposal_id, draft)`, the `changes_paused` flag.

## 3. Tables (Alembic `os` branch, `os_0012`; every table has `tenant_id`)

- **`os_proposals`:** plan, event ids, source (`rules` \| `supervisor`), operations (JSON), refused (JSON), big,
  status (`applied`, `pending`, `accepted`, `declined`, `expired`, `refused`), inbox task id, expires_at.
- **`os_plan_overrides`:** plan, proposal id, op, target (instance key or template key + programme), payload,
  active.
- **`os_support_cases`:** plan, student, reason, events, proposal id, status, resolution, resolved_at.
- **`os_plans.changes_paused`** (boolean, default false).

## 4. API

| Method and path | Purpose |
|---|---|
| `GET /v1/os/plans/{id}/changes` | The student's "what changed" list: applied revisions with reasons, pending proposals |
| `POST /v1/os/proposals/{id}/accept` / `decline` | The student's answer (write access); `409` if expired or already answered |
| `GET /v1/os/admin/support` | Open and recent cases (admin) |
| `POST /v1/os/admin/support/{id}/resolve` | `{note, unpause}` (admin) |

The inbox lists a pending proposal as a `choose` item; the plan read shows `changes_paused`.

## 5. Screens (mobile-first, 360 px; behind `NEXT_PUBLIC_OS_ENABLED`)

- **Inbox proposal card:** "We suggest: <operations in words>. Why: <reasons>." [Accept] [Decline], with the
  expiry date.
- **What changed:** on the plan page, newest first: what changed, why, and when.
- **Paused banner:** "Changes are paused while a person checks your plan."
- **Admin support inbox:** `/<workspace>/os-admin/support`: list, open a case (plan summary, events, proposal),
  resolve with a note.

## 6. Error handling

| Failure | Handling |
|---|---|
| Supervisor unavailable, no key, over budget | Support case; nothing changes |
| Supervisor output invalid after 2 repairs | Support case |
| Every operation refused by the kernel | Proposal `refused`; support case |
| Contract changed during the replan (`StaleDraft`) | Recompile from the new contract, at most 3 times, then support case |
| Plan paused | Events are recorded but not acted on until resolved |
| Proposal expired | Nothing changes; the event is marked handled; the next event may propose again |
| Worker crash | DBOS resumes; writes keyed by proposal id are not repeated |

## 7. Invariants touched

- **1:** only the kernel changes tasks and plan structure; replan writes overrides and calls kernel revisions.
- **5:** nothing is sent for the student; accepting a proposal changes their plan only.
- **7:** step retries and at most 2 output repairs; no other retry code.
- **8:** one workflow per (plan, event); writes keyed by proposal id.
- **9:** the Supervisor sees structured state only.
- **10:** a playbook upgrade is always an explicit, accepted revision.
- **12:** no route terms in `app/os/replan/**`; red-flag test.

## 8. Testing

- **Unit:** each rule on fixed plan states; the operation classification; each kernel check (pass and refuse);
  compiler overrides survive a recompile; the limits.
- **Scripted events (the gate):** a table of events on the Germany test plan and the fake routes, each with its
  expected operations and end state, run end to end through `os.replan` (rules in CI; Supervisor cases with a
  fake model returning recorded outputs).
- **Crash:** `test_crash_during_replan` (SIGKILL; Linux CI).
- **API and screens:** accept, decline, expiry, `409`s, admin resolve and unpause; Vitest for the cards, the
  banner and the admin page; 360 px.
- **Supervisor evaluation (billed; owners' OK first):** 20 scripted hand-over cases with expected operations. Pass:
  ≥ 18 give operations the reviewer marks right, and 0 that the kernel would refuse after repair. Cost and outputs
  recorded in the PR; no student data (fictional plans only).

## 9. Build order (one PR per task, each targeting `pai-os`, merged in order)

1. Tables `os_0012`, models, stores.
2. Operations and the compiler overrides.
3. Kernel checks and `apply_overrides`, `changes_paused`.
4. Events and detectors.
5. Rules.
6. The Supervisor agent (fake model in tests).
7. The `os.replan` workflow, limits, proposals, support cases.
8. API.
9. Screens (`frontend/lib/api.ts` is shared: Counsellor reviewer).
10. Gate, crash test, evaluation harness, final review, handoff.

## 10. Open questions for the owners

1. Confirm S7-D11: a changed approved file re-adds its review step (recommended in the 6b handoff).
2. 6b: may an unconfirmed funds amount be approved after the student ticks "I checked it"? (Not in this slice;
   recommended as a 6b follow-up.)
3. Run the billed Supervisor evaluation (§8): about 20 strong-tier calls, well under $5.
