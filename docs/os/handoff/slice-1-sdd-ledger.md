# SDD ledger — plan: docs/superpowers/plans/2026-10-18-pai-os-slice-1.md
Spec: docs/superpowers/specs/2026-10-18-pai-os-slice-1-design.md (reachable on os/s1-spec). Executor: inline (executing-plans), user asked for speed, no per-task review; final whole-branch review at the end.
Ruling: Task 1 branch is cut from os/s1-spec (not pai-os) so the plan and spec travel with the stacked chain — merge order becomes spec PR first — cost if wrong: one rebase.
Ruling: no separate worktree; work in ~/Pai-C on stacked branches os/s1-tN-* (user's only checkout, never on pai-os/dev/main) — cost if wrong: none (branches isolate the work).

## Pre-flight scan
| Rows | Produces / consumes | Finding |
|---|---|---|
| T2→T4..T10 | models.* tables, engine/clean fixtures | consistent names (os_<name>) |
| T3→T5,T7,T10 | Playbook/TaskTemplate/Constant(estimate) | T5 uses Constant.estimate for DraftTask.estimated — present in T3 |
| T4→T5,T8 | Fact, SqlKnowledge.confirm | consistent |
| T5→T6,T8 | PlanDraft/DraftTask, compile_plan(disabled_types) | T6 stores DraftTask fields; os_tasks needs `estimated` column → Ruling below |
| T6→T7,T8,T9 | Kernel, Outcome, complete_review | consistent |
| T7→T8,T10 | Registry, dbos_worker fixture, worker schedules | consistent |
| T8→T9 | PlanService, confirm_fact | consistent |
Ruling: os_tasks gains `estimated boolean not null default false` (spec §4.10 lists `provisional` but the screen §4.11 and TaskOut need `estimated`) — cost if wrong: one column.
Task 1: complete (commits 343e86f..3b8356a, tests: bash -c 'cd backend && python -m pytest tests/os -q' → 46 passed in 24.49s)
Task 2: Ruling: os_tasks also gets protected boolean (revisions must never remove protected tasks, spec 4.4) and os_modules keeps primary key module alone with a tenant_id column (as the plan says) — cost if wrong: one migration.
Task 2: complete (commits 3b8356a..0be4f38, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 53 passed in 9.00s)
Task 3: Ruling: TaskTemplate gets duration_constant (Task 10 needs visa duration from a cited estimate constant; plan Task 10 says so but Task 3 omitted the field) — cost if wrong: one field.
Task 3: complete (commits 0be4f38..dd2507a, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 64 passed in 11.31s)
Task 4: Ruling: SqlKnowledge also has get(fact_id) -> (scope, ref, field, Fact), needed by Task 8 confirm_fact to find plans that reference the fact — cost if wrong: one method.
Task 4: complete (commits dd2507a..a2fa32a, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 75 passed in 10.58s)
Task 5: Ruling: a condition that is false on an UNCONFIRMED fact drops the task but still adds a confirm_fact task (the decision stays checkable); DraftTask also carries protected (Task 6 revisions need it) — cost if wrong: a task appears only after the fact is confirmed.
Task 5: complete (commits a2fa32a..83f588c, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 91 passed in 10.98s)
Task 6: Ruling: (1) ready -> blocked is allowed (a revision can remove a ready task's input; spec table lacked it); (2) revise returns None when nothing structural changed, and earliest_start/slack/critical/citations are refreshed in place without a revision (they drift daily with 'today'); (3) upgrade_playbook always records a revision (explicit upgrades are logged) — cost if wrong: a table entry and one return type.
Task 6: complete (commits 83f588c..035f30d, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 212 passed in 12.45s)
Task 7: Ruling: (1) DBOS 3.2 has no @DBOS.scheduled; jobs use DBOS.apply_schedules (stored schedules, deterministic IDs = one run per tick across replicas) via register_job; (2) dbos_worker resets the DBOS test schema per test because clean restarts IDs and workflow IDs are task_id:attempt; (3) crash-test runs table lives in public schema so the os migration comparison stays exact; (4) crash test uses 3 s tasks and a kill every 1.5 s after one early run failed (most likely too few kills; 18/18 passes after) — cost if wrong: a flaky CI test, revisit timing.
Task 7: complete (commits 035f30d..1acadb2, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 221 passed in 52.86s)
Task 8: Ruling: (1) an open inbox item (student task in waiting_student) is NOT started, so fact changes re-date it; a work task waiting for input is started (found by test_fact_change_keeps_started_tasks; spec 4.4 'not started' read as 'student has not acted') — cost if wrong: open items would show stale deadlines; (2) PlanService takes a registry (disabled modules -> task types) and pins: an existing plan re-compiles with its pinned playbook, new plans use the newest; (3) worker jobs live in app/os/workers/jobs.py and the worker imports them late (workers depend on the runner) — cost if wrong: small refactor.
Task 8: complete (commits 1acadb2..d940da8, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 239 passed in 46.69s)
Task 9: Ruling: (1) GET /v1/os/plans/{id} is admin-only (students see their tasks through GET /inbox) because FastAPI cannot try admin auth then fall back to the host's student dependency cleanly; (2) main.py maps the signed-in student to their workspace id via app.application_workspace.access._auth, a READ-ONLY old-OS module (inventory) - when that module retires (Slice 6) the OS student port needs its own mapping; (3) main.py is a shared file (needs a Counsellor reviewer); the inventory doc regenerates with app.main as a new importer of access — cost if wrong: one endpoint and a small bridge function.
Task 9: complete (commits d940da8..72bdb7d, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 254 passed in 62.95s (0:01:02))
Task 10: Ruling: (1) the playbook has 19 steps (the plan's list; the test first said 20, a miscount); (2) no official visa lead time or attestation time exists, so durations come from constants marked estimate: true (visa 90 days is a developer planning buffer, labelled 'estimated' in the inbox), and visa_target_date is deliberately unseeded so visa_apply is blocked with a confirm_fact task (Spike 5 C5); (3) programme facts are seeded unconfirmed from the shortlist (R-P4), so all programme dates are provisional; (4) fake-route test needs no DBOS worker (only student tasks) — cost if wrong: estimates must be replaced when research returns real figures.
Task 10: complete (commits 72bdb7d..205fe06, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 254 passed in 69.32s (0:01:09))
Task 11: Ruling: legacy guards tests/test_system_capabilities.py (only runtime/task_runtime.py may enqueue) failed since Task 7 because they scan app/os too; scoped them to Counsellor code (skip app/os) with a probe proving they still catch violations. This is a Counsellor test file: needs a Counsellor reviewer, and the fix must move into the Task 7 PR when PRs are opened (or t7..t10 legacy CI is red) — cost if wrong: guard misses an OS-side misuse (Tach + OS tests cover that).
Task 11: frontend verified in a Windows copy (no Node in WSL): vitest lib/os-inbox + components/os 6/6; a mutation (overdue grouping removed) failed both files; full frontend suite 10 files 29/29; tsc --noEmit clean; next build with NEXT_PUBLIC_OS_ENABLED=true OK (route /[workspaceId]/os-inbox). Ruling: tests were written alongside the code, so failure was proven by mutation instead of a red run first; api.ts gets requestJson() because the OS API has no {data} envelope (shared Counsellor file) — cost if wrong: small client refactor.
Task 11: complete (commits 205fe06..48f8aa6, tests: bash -c 'cd backend && python -m pytest tests/os -q -p no:tach' → 254 passed in 48.49s)
Final review: fresh reviewer (opus), range 343e86f..48f8aa6 + 8e36fef. Verdict "With fixes": 2 Critical, 7 Important, 19 Minor. Re-graded by effect; all C/I entered one fix pass on branch os/s1-t12-review-fixes (commit 880af2a). Suite 266/266, tach + heads green, crash tests 3/3 runs.
Final: fixed C1 (every recompute after a started/done task differed made a new revision + inbox notice) — test_recompute_twice_after_started_change_is_noop, test_done_task_that_differs_never_revises_again RED->GREEN, suite 266/266
Final: fixed C2 (a cancelled task could never come back; dependents stalled) — test_remove_then_readd_programme RED->GREEN, suite 266/266
Final: fixed I1 (no enqueuer in production) — test_worker_enqueues_by_itself RED->GREEN; crash test no longer enqueues/reconciles by hand, suite 266/266
Final: fixed I2 (missing facts could not be supplied) — test_admin_supplies_missing_fact_unblocks RED->GREEN (POST /v1/os/facts, GET /v1/os/facts/open), suite 266/266
Final: fixed I3 (bad value stored before check; one bad plan halted the deadline engine) — test_bad_date_rejected_and_not_stored, test_deadline_engine_isolates_failing_plan RED->GREEN, suite 266/266
Final: fixed I4 (stale draft could overwrite a newer revision) — test_revise_rejects_stale_contract RED->GREEN, suite 266/266
Final: fixed I5 (dates from a fact did not cite the fact) — test_anchor_fact_citation_first RED->GREEN; golden regenerated, only 3 uni_assist_apply citation lists changed, suite 266/266
Final: fixed I6 (completing an inbox item used read-level host auth) — test_complete_uses_write_dependency RED->GREEN (current_student_ref_for_write, main.py write=True), suite 266/266
Final: fixed I7 (invalid playbook / unowned type did not stop startup) — test_mount_os_fails_on_invalid_playbook, test_worker_build_validates_registry RED->GREEN, suite 266/266
Final: Ruling: C1 fix stores a token of the reported draft version on os_tasks.skipped_draft (added to os_0002 in place, since no migration has been deployed or merged) — cost if wrong: one column / migration edit before merge.
Final: Ruling: C2 fix renames a cancelled row's instance_key to <key>#c<revision> so the key can be re-used; cancelled stays terminal (no spec change) — cost if wrong: history rows carry renamed keys.
Final: Ruling: the worker's enqueue loop logs and continues on an exception each second; it is a polling sweep, not a retry of one side effect (invariant 7 read accordingly) — cost if wrong: replace with a DBOS-scheduled step.
Final: minor (deferred): M1 invariant-1 check is a line regex (misses aliases like T = models.tasks; pg_insert); use an AST check
Final: minor (deferred): M2 slack_low emitted on every recompute of an at-risk plan; emit on the transition only
Final: minor (deferred): M3 POST /plans/{id}/upgrade on an unknown plan now 404 via KeyError path, but PlanService reads elsewhere lack tenant filters
Final: minor (deferred): M4 outbox head-of-line blocking on a failing send; count failures, give up after N, pass idempotency key to the provider (before Resend)
Final: minor (deferred): M5 no fact_changed event; deadline engine not event-triggered
Final: minor (deferred): M6 no deploy-time seed command; seeding should be insert-only so it never overwrites confirmed facts
Final: minor (deferred): M7 os_modules primary key is module alone (multi-tenant needs (tenant_id, module))
Final: minor (deferred): M8 missing indexes (os_tasks(tenant_id,state), GIN fact_refs, partial sent/status, task_edges(to_task))
Final: minor (deferred): M9 work task input_missing -> waiting_student never shown in inbox and not resolvable (latent: no Slice 1 handler returns it)
Final: minor (deferred): M10 choose items send no payload/options
Final: minor (deferred): M11 inbox page path is app/[workspaceId]/os-inbox, not app/os/inbox (workspace is the student ref)
Final: minor (deferred): M12 GET /plans/{id} admin-only (student path via inbox)
Final: minor (deferred): M13 playbook: enrol should be per-programme citing enrolment_deadline; Spike 5 A6 certified copies has no conditional step
Final: minor (deferred): M14 no test proves a DBOS schedule fires
Final: minor (deferred): M15 waiting_student task gaining a blocked_reason stays in the inbox; ready work task gaining an unmet hard dep still runs
Final: minor (deferred): M16 APP_VERSION 'os-1' has no bump rule (bump whenever workflow/step code changes)
Final: minor (deferred): M17 confirm_fact matching ignores intake_year
Final: minor (deferred): M18 reminder recipient is a workspace id, not an email (resolve before Resend)
Final: minor (deferred): M19 at the gate merge, keep 'alembic upgrade heads' (dev still says head)
Final: Ruling: reviewer's "declined to judge" items (email delivery, multi-tenant, frontend re-run, content accuracy, host auth internals, scale, crash flakiness, guard scoping) stand as declined: each is out of Slice 1 scope or already verified elsewhere (frontend 29/29 + build, crash 3/3, guard probe) — cost if wrong: surfaced at the Slice 1 gate review.
Final: legacy Counsellor suite after the fix pass: 1002 passed, 3 skipped (app.main imports; /v1/os not mounted without OS_ENABLED).

Post-review work (2026-10-19, user request):
Final: review of main.py and tests/test_system_capabilities.py: guard scoping correct (probe proves it still catches Counsellor code); main.py bridge had no test and dropped the host's error message -> tests/test_os_bridge.py RED->GREEN; notes: depends on private access._auth (read-only module), OS engine ignores the Counsellor's Supabase-pooler engine options.
Final: fixed M3 tenant filters (service pin lookup, enqueue_pending, worker task load) — tests/os/test_tenancy.py RED->GREEN; plan upgrade on an unknown plan is 404.
Final: added M14 schedule-fires test — tests/os/test_schedule.py (once-a-second DBOS schedule via register_job; a mutation that skips apply_schedules makes it fail).
Final: integrated tree found 2 real bugs, both fixed: (1) tests/os/runner_helpers.py read OS_DATABASE_URL, which CI never sets -> fixed on Task 7 (f03ae23), checks now run with CI's env only; (2) PaiSessionBoundaryMiddleware rewrites Authorization on every /v1/ request, so the OS admin bearer never arrived -> admin token moved to header X-OS-Admin-Token, test through the real middleware RED->GREEN.
Final: Ruling: the guard-test fix and the helper fix were moved into the Task 7 branch and t8..t12 rebased (force-with-lease; content identical apart from the fixes; local backup tags backup/pre-restack*) so every stacked PR is green — cost if wrong: none (no PRs existed yet).
Final: PRs #40..#52 opened as a stack (each based on the previous branch); merge plan in docs/os/handoff/slice-1-handoff.md §2.
