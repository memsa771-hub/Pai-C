# SDD ledger — plan: docs/superpowers/plans/2026-10-12-pai-os-slice-0.md
Scope this session: Task 2 only (user instruction). Task 1 merged as 273bbd2. Spec: docs/superpowers/specs/2026-10-12-pai-os-design.md (reachable).
Env: Python 3.13 in container (plan says 3.12); pytest + tach==0.35.3 pip-installed. Baseline: tests/os 5 passed, tach clean.

## Pre-flight scan (Task 2)
| Rows | Produces / consumes | Finding |
|---|---|---|
| T1 vs T2 | T1: app/os/__init__.py, tach.toml (app.os depends_on=[]), tests/os/. T2 adds app/os/contracts/* + tests/os/test_route_contract.py | No shared file. T2 imports only pydantic (external) — inside tach boundary. OK |
| T2 vs T3-T7 | No later task references RouteContract/contracts | None |
| T2 self-consistency | Tests vs interface | "at least 1" = pydantic min_length msg (needs Field(min_length=1)); "source"/"Extra inputs" = pydantic defaults; "two-letter"/"duplicate programme"/"ranks must be 1..n" = custom msgs from Step 3. Dup-ref check must run before rank check (dup test has ranks 1,2 → fine either way). Test snippet omits imports and SCHEMA_PATH — implementer supplies them. Consistent. |
| T2 self-consistency | Files list vs steps | Step 3 says generate schema "once" — no generator script in Files list → one-off command, not a committed script. Consistent. |
| T2 vs spec 3.1 inv. 12 | No country literals in code | Test data "PK"/"DE" in tests only; product code must not contain country codes. |
Observation (no ruling, plan followed literally): interface states extra="forbid"/frozen only for RouteContract, not ProgrammeChoice/IntakeRef.
Task 2: complete (commits 273bbd2..cfb4e84, review clean — spec ✅, quality Approved)
Task 2: open finding (Important, not fixed) — external_ref/student_ref accept empty strings → dedupe_key "source::1" collides — Ruling: not fixed; plan defines them as bare str and user said don't improvise — surfaced to user — cost if wrong: one small follow-up commit + schema regen
Task 2: minor (deferred): country pattern not in frozen schema; .upper() non-ASCII ("ß"→"SS"); nested models not frozen/extra=forbid, list field shallow-frozen; thin tests for intake/rank/level bounds; test line length
Final whole-branch review skipped: branch diff == Task 2 diff, already reviewed (scope: Task 2 only).
Pushed os/s0-t2-route-contract at cfb4e84.

## Task 3 (session 2) — branch os/s0-t3-db-area from pai-os dba2e28 (dev merged via PR #24)
Env: full requirements.txt installed (dev's new tests/conftest.py imports app.memory). Test PG16 at postgresql://postgres@127.0.0.1:5433/os_test (/var/tmp/os-pg). Alembic 1.20.0, SQLAlchemy 2.1.4. Main alembic: single head 106, base 074. Alembic CLI needs PYTHONPATH=. (use `python -m alembic` from backend/).
| Rows | Finding |
|---|---|
| T3 vs T1 | consumes OsSettings/load_settings unchanged; tach: app/os/db.py may import only sqlalchemy; env.py (root) may import app.os. OK |
| T3 self: fresh_db vs test_os_branch_upgrade_creates_schema | fresh_db "drops and recreates" os → test passes even if migration does nothing (vacuous). If it only drops os, alembic_version (public) keeps os_0001 → 2nd local run: upgrade no-op → test fails. → ASK USER |
| T3 self: alembic.ini version_locations space-separated | Alembic 1.20 emits DeprecationWarning (no path_separator) on every load → noisy test output. Fix = add `path_separator = space`. → ASK USER |
| T3 self: os_0001 downgrade "drops only if empty" | plain DROP SCHEMA IF EXISTS os (RESTRICT) satisfies it. → confirm with user |
User decisions (asked, 2026-10-13): (1) fresh_db drops `os` CASCADE + deletes os-branch rows from public.alembic_version; drops & recreates dbos_test, spike3 empty. (2) alembic.ini gets `path_separator = space`. (3) os_0001 downgrade = plain `DROP SCHEMA IF EXISTS os` (RESTRICT; errors if non-empty).
Task 3 BASE: dba2e28
Task 3 impl: 45bc128 (implementer DONE). Controller checks: `upgrade heads` on empty DB → 106 + os_0001, schema os present ✅. `upgrade head` (singular) now FAILS "Multiple head revisions".
Task 3: outside-scope finding — backend/scripts/eval/docker-compose.offline.yml:41 `entrypoint: [alembic, upgrade, head]` (Counsellor offline eval stack) will break after Task 3; README.md:96 says `alembic upgrade head`. Not in Task 3 file list → surface to user, not fixed.
Task 3 review (45bc128): spec ✅ vs brief+decisions; quality Needs fixes — 2 Important (both verified by controller):
  I1 docker-compose.offline.yml:41 + README.md:96 still `upgrade head` → breaks with 2 heads. USER DECISION: fix both in this PR (`heads`).
  I2 (plan-mandated) env.py include_schemas=True unfiltered → autogenerate proposes dropping dbos.* tables (verified via `alembic check`). USER DECISION: add include_name filter (default schema + os).
Task 3: minor (deferred): no test that main() returns 1 on forked heads; `from conftest import` fragility; path_separator=space breaks if checkout path has a space; lineage via depends_on edge case; run_alembic CalledProcessError lacks stderr; no downgrade test.
Controller verified ⚠️: existing DB at 106 + `upgrade heads` applies only os_0001 ✅.
Task 3: fix round 1/5 (2 addressed, 0 open — I1 offline compose+README heads; I2 include_name filter; commits 45bc128..7470025). Controller re-verified alembic check: DB at both heads, ran to comparison, 0 dbos ops.
Task 3: minor (deferred): docs/counselor/CLEANUP_AUDIT.md:123 still says "Compose invokes alembic upgrade head" (stale doc).
Task 3: complete (commits dba2e28..7470025, review clean after 1 fix round). Pushed os/s0-t3-db-area.
Task 3: merged into pai-os as 7bb9ae6 (PR #25, squash)

## Pre-Task 4 decisions (user, 2026-10-13)
Fate rules (user-assigned to controller): keep only if important for PAI. If used by Counsellor (directly OR indirectly): if a pai-os slice 0–7 builds the same capability → read-only until that slice ships, then retire; if not in slices 0–7 and necessary → keep. Only used by old OS → retire, unless really important → ASK user with explanation.
Columns: add whatever is needed for that rule (e.g. reachable-from-Counsellor transitive, replacing slice). No DB-table inventory (later-slice tables replace old ones).
Scope: plan's watched list + routers/services that only serve those features (list each addition with reason; flag unclear ones).
Retire timing: fates on paper only in Task 4; switch-off/delete later per spec (after pilot, own PRs).
Fate storage: in os_inventory.py (module → fate, reason, replacing slice); markdown generated; test fails if any module lacks a fate.
FigJam (PAI OS Final Plan Review): https://www.figma.com/board/sEWRgciL9Quwmklh492qUW — linked in spec header.
Frontend calls v1/operator/runs, v1/deadlines, v1/tasks (frontend/lib/api.ts) → count Counsellor screens calling old-OS routes as indirect use.

## Task 4 — branch os/s0-t4-old-os-inventory from pai-os 35dd7d6 (dev 6d6d17a included). BASE 35dd7d6
Pre-flight: external importers of watched modules include Counsellor-shared code: app.memory.{handlers,retriever,vault_intake}→documents, app.memory.permissions→services.operator, app.inference.client→plugins, app.pai_c.*→plugins/research/documents, app.security.event_identity→services.operator, app.runtime.task_runtime→capabilities,jobs, app.routers.{deadlines→deadlines, files→documents, roadmaps→research}, app.application_workspace.plans→deadlines. Frontend lib/api.ts calls v1/operator/runs, v1/deadlines, v1/tasks.
Plan: step A implementer = mechanics (script, columns, plan test, empty FATES); step B analyst (opus) = fate proposal per user rule; step C implementer = fill FATES + completeness test + regenerate md. Then review.
Ruling: md column order keeps plan's 4 columns first & contiguous; extra columns appended after — plan test asserts that header text.
Task 4 step A: 3bb1ec0 (DONE_WITH_CONCERNS): 262 rows (bug: rows not filtered to watched modules); 250/262 reachable because app.services.pai lazily imports app.main (composition root, imports every router).
Ruling: reachability BFS does not expand through app.main (composition root); limitation noted in the md (in-process HTTP calls from app.services.pai via ASGI aren't traced by imports) — analyst checks those by reading code — cost if wrong: a module the Counsellor reaches only via app.main→router could be under-flagged; analyst step mitigates.
Task 4 step B: analyst proposal at task-4-fates-proposal.md (keep 16 / read-only 31 / retire 8; 5 ask-owner; 15 shared pieces; 6 scope additions; 5 uncertain).
User decisions: (a) Counsellor research chain (the 26 'read-only Slice 2 partial' rows) → KEEP; revisit when the Slice 8 spec decides if the Counsellor reads OS Knowledge. (b) deadlines (app.deadlines, .service, routers.deadlines) → READ-ONLY until Slice 1.
User delegated Q3 + Q4 to controller:
Ruling: scholarship_discovery → retire — v1 scope (spec §2 'In v1') lists no scholarship feature and no slice builds one; code stays in git history — cost if wrong: restore from git.
Ruling: routers.escalations → retire — nothing calls it today; Slice 8 EscalationSink can reuse it from git if wanted, and retire only happens after the pilot (after Slice 8) — cost if wrong: small.
Ruling: qualification_recognition → retire, BUT its sourced packs (DAAD, uni-assist, HEC, APS + URLs) must be copied into the Slice 1 Germany playbook/Knowledge before deletion (recorded as a preserve note) — cost if wrong: none (data kept).
Ruling: gap_assessment → retire; noted as reference for Slice 1 eligibility checks.
Ruling: scope additions: app.runtime.task_runtime → keep (Counsellor job dispatch); agent tools (routers.tasks, tools.builtin.tasks, routers.workflows, services.workflow, routers.timers, routers.todos, routers.browser, tools.builtin.browser, app.browser*) → retire unless regen shows real Counsellor use; app.application_workspace*, routers.application_workspace, routers.routines → read-only until Slice 6 (live student feature replaced by Slices 1 & 6; same logic as user's deadlines decision) — cost if wrong: rows re-labelled.
Ruling: documents ingest rows (classify, extractor, handlers, ocr, parsers, untrusted) → KEEP, not read-only — same logic as user's research decision (Slice 3 only partly replaces; Counsellor recall/'I read your file'/profile feed depend on them); revisit at Slice 3 spec — cost if wrong: re-label at Slice 3.
Task 4 review (d53c17c): spec partly ✅ (all 81 fates match rulings; gate met); quality Needs fixes — 3 Important:
  I1 COUNSELLOR_LEAD_SIGNED_OFF claims a sign-off that hasn't happened (services.workflow retire while used_by_counsellor=yes).
  I2 retire reasons for timers/todos/tasks/browser/workflows say "no Counsellor use" but Counsellor chat screen polls /v1/timers + /v1/todos (thread-status-bar) and workspace-context fetches tasks/workflows/routines/todos/browser globally; application-operations.tsx (read-only group) calls /v1/tasks,/v1/workflows.
  I3 frontend_calls false negative for routers.application_workspace (re-exported router).
Ruling (I2): fates stay retire — Counsellor screens only poll/fetch these (empty for Counsellor sessions); no Counsellor function depends on them and no slice builds them; reasons corrected; frontend call sites become preserve notes ("remove before switch-off"); rows join a rendered "pending Counsellor lead sign-off" list — cost if wrong: re-label to keep later.
Ruling (I1): services.workflow stays retire but in RETIRE_PENDING_COUNSELLOR_LEAD_SIGNOFF (in the script, rendered in md), test asserts Counsellor-used retire rows ⊆ that set.
Ruling (I3): follow one level of `from X import router` re-export (use X's APIRouter prefix + decorators); document remaining limits (include_router prefixes, api_route/add_api_route, annotated assignment, column names api.ts not screens) in intro Limits.
Fix round also takes cheap Minors: M2 extra preserve notes, M3 intro note, M4 markdown drift test, M5 import fallback e.name. Deferred minors: M1 one-sentence rule for KEPT notes/fragments, M6 package imported_by lists children, M7 counselor root startswith, M8 no shortest-path/path= tests.
Task 4: fix round 1/5 (I1, I2, I3 + M2, M4, M5 addressed, 0 open; commits d53c17c..f6eda59). Re-review clean.
Task 4: minor (deferred): app.browser* rows' reasons say "Pending Counsellor lead sign-off" but aren't in the set; relative re-export resolution assumes non-package importer; unverified claim "deep Counsellor never calls tools" — Counsellor lead to confirm at sign-off; M1 one-sentence reasons; M6/M7/M8.
Task 4: complete (commits 35dd7d6..f6eda59, review clean after 1 fix round). Pushed os/s0-t4-old-os-inventory.

## Task 4 follow-up (2026-10-14): owner says Counsellor lead delegated sign-off to the owner; owner delegated the decision on the sign-off modules to controller ("critically analyse, decide, explain").
Evidence gathered (controller):
- services/pai.py:52-54 comment: "the deep Counselor never calls tools itself"; every Counsellor caller narrows allowed_tools to {"operator.delegate"} (mirror.py:208, research/jobs.py:39,155, routers/roadmaps.py:107,258). tasks.list is never invoked.
- Nothing in backend creates TimerRecord/todos; only agents via HTTP POST /v1/timers, PUT /v1/todos. Counsellor never does.
- frontend/lib/config.ts:36-46: task board + workflows "held back for a later Placement AI release"; agents still create tasks server-side.
- application_workspace/operations.py:10,36-59 links requirements to KanbanTask + Workflow; calendar.py, serializers.py read KanbanTask; workspaces.py binds threads to workflows; events.py:391 + posting.py:222-238 + integrations call advance_workflow.
- NOT traced by imports: plugins/program_research (KEPT) → tool web.fetch → tools/builtin/web.py POST /v1/fetch → routers/fetch.py:36,45 → app.browser.manager (+credentials.redact, egress) and routers.browser._resolve_bf_key. Kept research only invokes web.fetch/web.search/web.institution_registry (checked all tools.invoke in plugins/research/operator/capabilities).
Ruling: services.workflow, routers.workflows, routers.tasks: retire → READ-ONLY until Slices 1 and 6 — live plumbing of the read-only application workspace and workflow-bound threads — cost if wrong: they live longer than needed.
Ruling: app.browser, .manager, .egress, .credentials, .maintenance, routers.browser: retire → KEEP — /v1/fetch render path used by kept Counsellor research (web.fetch); routers.browser kept for _resolve_bf_key; interactive shared-tab endpoints + stored-credential flows not needed → split candidate — cost if wrong: dead surface kept.
Ruling: tools.builtin.browser stays RETIRE (Operator-only tab control; spec inv 6/§10). tools.builtin.tasks, routers.timers, routers.todos stay RETIRE (no Counsellor feature depends; screens only poll empty lists; no slice builds agent timers/todos).
Ruling: sign-off — set renamed COUNSELLOR_TOUCHING_RETIRES = {tools.builtin.tasks, routers.timers, routers.todos}; "Signed off 2026-10-14: Counsellor lead delegated to owner, owner delegated to Claude"; "Pending…" removed from reasons.
Expected counts: keep 54, read-only 18, retire 9 (81).
Task 4 follow-up: 90e1469 applied all 2026-10-14 rulings (keep 54 / read-only 18 / retire 9); scoped re-review clean; pushed.
Out-of-scope bug found: routers/fetch.py:665 passes _resolve_bf_key's (key, source) tuple as api_key to BrowserManager.render_page_text → JS render tier likely broken. Not Task 4 scope → suggested as separate task.
Task 4: merged into pai-os as 3cf7529 (PR #26, squash)

## Task 5 — branch os/s0-t5-ci from pai-os 3cf7529 (dev in pai-os). BASE 3cf7529
Handles: OS devs @10Faheem @MusawirKtk; Counsellor lead @memsa771-hub (also repo admin; PRs from this session are authored by memsa771-hub).
Pre-flight: tests/os need tach binary (requirements-dev), frontend/ dir (drift test), full requirements.txt (Counsellor tests/conftest imports app.memory). CI check name must be `os` (job id os, no different name). Step 4 (draft violation PR + branch protection) is done by controller on GitHub after the PR exists; ruleset by admin.
Ruling: CODEOWNERS also assigns /backend/tach.toml to the OS developers — it is the OS boundary file and otherwise has no owner — cost if wrong: one extra line.
Task 5 impl: 9e00caf. Review: spec ✅, quality Approved; 1 Important (design limit): CODEOWNERS can't enforce one-reviewer-per-team; comment over-promises.
Ruling: option (c) now — reword CODEOWNERS comment honestly (any listed owner satisfies; cross-team rule by convention/PR review); present (a) "lead-only owner on shared files + 2 approvals" to user at ruleset time — cost if wrong: comment only.
Fix round 1 also takes Minors: #2 silent-skip guard (step asserting OS_TEST_DATABASE_URL set + -rs), #4 per-SHA concurrency for push, #5 template plain yes/no lines. Deferred: #3 legacy display / reruns tests/os, #6 >= version drift (pre-existing).
Task 5: fix round 1/5 (CODEOWNERS note, skip guard, per-commit push concurrency, template lines — all addressed; 9e00caf..82fcc0f). Re-review clean. Pushed; PR #27 opened (memsa771-hub/Pai-C#27), subscribed; first CI run in progress. Safety-net check-in trig_015k1na9tRK88ALhFn2dMb5G at 07:15Z.
Task 5 CI: first run on PR #27 — os ✅ (39 passed, py3.12, PG16); legacy ❌ 210 failed: Counsellor async tests need pytest-asyncio (undeclared). Fix 43169d4: legacy job installs pytest-asyncio==1.4.0 (local full suite 1040 passed). Re-run: os ✅ legacy ✅.
Task 5 Step 4 proof: draft PR #28 (base os/s0-t5-ci): 97269d3 violation → os ❌ at tach ("Module 'app.os' cannot depend on '<root>'"); a5fa946 removed → os ✅ (legacy ✅ = 2nd green in a row). PR #28 closed with comment, branch deleted, unsubscribed.
Task 5: complete (commits 3cf7529..43169d4 on PR #27, review clean after 1 fix round + CI fix). Remaining (user/admin): ruleset requiring `os` on pai-os/dev/main; legacy may be made blocking (green twice).
Task 5 CI: first run on PR #27 — os ✅ (39 passed, py3.12, PG16); legacy ❌ 210 failed: Counsellor async tests need pytest-asyncio (undeclared). Fix 43169d4: legacy job installs pytest-asyncio==1.4.0 (local full suite 1040 passed). Re-run: os ✅ legacy ✅.
Task 5 Step 4 proof: draft PR #28 (base os/s0-t5-ci): 97269d3 violation → os ❌ at tach ("Module 'app.os' cannot depend on '<root>'"); a5fa946 removed → os ✅ (legacy ✅ = 2nd green in a row). PR #28 closed with comment, unsubscribed. Remote branch delete refused (403) — user to delete os/s0-t5-ci-proof via GitHub.
Task 5: complete (PR #27, commits 3cf7529..43169d4, review clean after 1 fix round + CI fix). Remaining (user/admin): merge #27; ruleset requiring `os` on pai-os/dev/main; legacy may be made blocking (green twice).
Task 5: merged into pai-os (PR #27) — 367cdd5 ci: os job, PR template, CODEOWNERS (Slice 0 Task 5) (#27)

## Pre-Task 6 notes (2026-10-15)
User: ruleset "Required CI and review" active on pai-os, dev, main (requires `os` + PR). Write access granted. Branch cleanup by user.
Controller flagged to user: (1) `os` required on dev/main blocks all PRs there — dev has no .github, no tach.toml, no tests/os → os never reports/would fail; recommend `os` required only on pai-os. (2) ci.yml only on pai-os → CI follow-ups must PR to pai-os (pytest-asyncio removal only after dev→pai-os brings requirements-dev); removing continue-on-error ≠ blocking unless `legacy` added to required checks; pydantic~=2.14 allows 2.15 → use ~=2.14.1.
Follow-ups after Task 6 (user-decided): deps PR to dev (pytest-asyncio==1.4.0 in requirements-dev, pydantic pin), CI PR (legacy blocking), dev→pai-os PR; RouteContract fix PR to pai-os (refs stripped+non-empty, nested extra=forbid, regen v1 schema in place, tests).

## Task 6 — branch os/s0-t6-spike3-loop from pai-os 367cdd5. BASE 367cdd5
DAAD pages: user-provided 5 files, verified against DAAD 2026-10-15 (uploads dir).
Pre-flight T6: APIs verified in dbos 3.2.0 / pydantic-ai-slim 2.55.0 (DBOSConfig incl. dbos_system_schema+system_database_url; DBOS.destroy(destroy_registry=); Queue.enqueue; SetWorkflowID; DBOSAgent(wrapped,name,model_step_config); StepConfig(retries_allowed,max_attempts,...); Agent(retries=dict) accepted; TestModel(custom_output_args); WrapperModel; OpenAIChatModel/OpenAIProvider).
| Rows | Finding |
|---|---|
| T6 vs T3 | consumes pg_url/fresh_db (session; drops+recreates spike3, dbos_test) — conn fixture applies schema.sql + truncates per test. OK |
| T6 vs T7 | T7 worker.py "configures DBOS exactly as Task 6" + reuses loop functions → loop.py must expose config/agent builders. Told implementer. |
| T6 self | invalid-quote test expects model_calls==3: ModelRetry → new model request steps; DBOS step retries only on exceptions inside a step; UnexpectedModelBehavior surfaces at workflow level → caught → failed/invalid_output. Consistent. |
| T6 self | DBOS is a process singleton; two runtimes (good/bad quote) in one session → destroy(destroy_registry=True) between fixtures. |
Task 6 impl: 8209e09 (DONE_WITH_CONCERNS: DBOSAgent deprecated→DBOSDurability; counter uses private pydantic_ai._run_context helper; shared executor id 'local' across workers (T7); reconcile ignores ERROR/CANCELLED/MAX_RECOVERY workflows (T7 'lost'); child workflow ids {id}:{attempt}-N)
Task 6 review (8209e09): spec ✅; impl code approved; Needs fixes (tests). Important: I1 (plan-mandated) enqueue-twice & race asserts vacuous (PKs make counts 0/1) — can't detect double execution; I2 (plan-mandated) DBOSAgent deprecated (TODO v3 remove) → spike proves deprecated shape. Minor: race not shown to happen; start outside try cascades; workflows leak between fixtures (destroy timeout 0); broad warning filter; psycopg3 transitive dep.
Ruling: I1 — ADD assertions (bodies kept; extra lines): model_calls==1 and one load_page step_run per task in enqueue-twice + race tests; race test asserts both sides acted (enqueue returned 1, reconcile reenqueued 1 or equivalent observable) — cost if wrong: flaky race assert → relax to "at least one".
Ruling: I2 — switch to DBOSDurability capability inside run_attempt now (deviation from brief's DBOSAgent): deprecated API slated for removal; spike must prove production shape; switching after T7 voids its PASS — cost if wrong: small revert.
Deferred to Task 7 (ledger): reconcile must map terminal non-SUCCESS workflows (ERROR/CANCELLED/MAX_RECOVERY) to failed/workflow_error else "0 lost" at risk; executor id strategy (shared "local" vs per-worker DBOS__VMID); "duplicated" metric must count body executions (model_calls/step_runs/run_attempt workflows), not results rows.
Task 6: fix round 1/5 (I1, I2, minors addressed; 8209e09..3a09b28). Re-review clean. Pushed.
Task 6: complete — PR #29 green on GitHub (os 44 passed py3.12/PG16, legacy green). commits 367cdd5..3a09b28. Waiting on user merge. Check-in trig_01NYVdU8YZgR8ENfSsUeACGE.
Task 6: merged into pai-os (PR #29) — be96f40 spike(os): Spike 3 core loop with idempotent steps (Slice 0 Task 6) (#29)

## Follow-ups after Task 6 (2026-10-15)
User pasted an env with live secrets (Counsellor OpenAI, Tavily, Resend, DB password) → told to rotate; not used/stored.
A: PR #30 chore/pin-pydantic → dev (pydantic~=2.14.1; dry-run resolves with dbos 3.2.0 + pydantic-ai-slim 2.55.0). mergeable_state=blocked: ruleset requires `os` on dev (can't run there). User must fix ruleset.
Ruling: pytest-asyncio goes to requirements-dev.txt on pai-os (file doesn't exist on dev; adding it on dev → add/add conflict at dev→pai-os) — cost if wrong: none.
B: PR #31 chore/os-dev-deps → pai-os (requirements-dev + drop inline install). C: PR #32 chore/legacy-blocking stacked on #31 (retarget to pai-os after #31 merges). D: dev→pai-os after A. E: RouteContract fix → branch os/routecontract-fixes.
E: PR #33 os/routecontract-fixes → pai-os (e560010; 51 passed; controller-reviewed diff). Check-in armed for #30-#33.
A #30 merged to dev (4a1160b). D: PR #34 dev→pai-os opened (trial merge clean, 44 passed, tach green).
B #31 merged to pai-os (e036ffe). C #32 merged into its stacked base chore/os-dev-deps AFTER #31 squash → change stranded; re-landed as PR #35 (chore/legacy-blocking → pai-os). Lesson: don't stack PRs for squash-merge repos.

- 2026-10-15T12:25:55Z follow-ups done: #34 merged (merge commit 55f7dc8), #35 merged (da38f02). pai-os verified: tach green, tests/os 51 passed. Next: Task 7 on user go.

## Task 7 (2026-10-15) — branch os/s0-t7-spike3-chaos from pai-os da38f02 (BASE da38f02)
Pre-flight: Task 7 consumes Task 6 (loop.py) — gaps found: executor ids, driver must not execute, terminal statuses, duplicate metric, vacuous chaos with instant TestModel, OpenAI run needs user key. Rulings R1–R9 in task-7-context.md:
Ruling: R1 slot-stable executor ids, replacement reuses slot id — DBOS recovery only recovers its own executor id — cost if wrong: dead slot's workflows stuck (test would show lost>0).
Ruling: R2 driver uses DBOSClient, never executes workflows; loop.enqueue_pending/reconcile get optional client — cost if wrong: small refactor.
Ruling: R3 explicit application_version in dbos_config — cost: none.
Ruling: R4 reconcile maps ERROR/CANCELLED/MAX_RECOVERY to failed/workflow_error — cost: none.
Ruling: R5 duplicated = re-runs whose earlier run's worker was not killed (worker column on step_runs/model_calls) — cost if wrong: metric definition debated in report.
Ruling: R6 slow FunctionModel + worker_concurrency so kills hit in-flight work; test asserts recovery happened — cost: longer CI test.
Ruling: R8 chaos marker registered, runs in CI by default — cost: CI time.
Ruling: R9 OpenAI pass-bar run is the user's; report verdict PENDING until then — cost: none.
Task 7: implementer dispatched (opus) 2026-10-15T12:42:05Z
Task 7: implementer DONE_WITH_CONCERNS cb85e6d,8e5cc78 (56 passed; chaos 3x green; rehearsal PASS; step_reruns 0 → test asserts recovered_attempts)
Task 7: pushed 8e5cc78 (pre-review, for safety); task reviewer dispatched (opus)
Task 7: review → Needs fixes. I1: CLI pass_bar_failures doesn't require kills/recovery (vacuous PASS possible). Minors M1–M11.
Ruling: fix round 1 includes I1 + minors M1,M3,M4,M5,M6,M8,M9(default delay 1.5s),M10,M11 — user asked for no known issues; all small — cost: a slightly bigger fix diff.
Ruling: M2 (same-process DBOS step retry counted as duplicated) kept as R5 says; report must state it can only cause a false FAIL, and how to tell — cost if wrong: a false FAIL to investigate.
Ruling: M7 (run_chaos length) — extract measurement helper only if trivial; else deferred minor — cost: readability of throwaway code.
Task 7: fix round 1/5 implemented a9e6dd7 (I1+M1-M11; 57 passed); pushed; re-review dispatched
Task 7: fix round 1/5 re-review: all 12 addressed, 0 open (8e5cc78..a9e6dd7). New minors: log dir path not printed when run_chaos raises; _measure client type nit → sent to implementer as follow-up.
Ruling: no separate final whole-branch review — branch is only Task 7, which got a full opus task review + re-review; Tasks 1–6 were reviewed and merged — cost if wrong: a cross-task issue slips to the slice-gate PR review.
Task 7: follow-up 2256b45 (log dir printed on crash; client assert) — controller verified diff; controller run: tach ✅, heads ✅, tests/os 57 passed, no orphan workers. Task 7: complete (commits da38f02..2256b45, review clean after 1 fix round + follow-up). Pushed.
Ruling: M2 kept (same-process step retry counts as duplicated → false FAIL only; documented) — cost if wrong: a false FAIL to investigate via worker logs.
User asked to use the pasted Counsellor key for the OpenAI run: blocked — session classifier denied credential extraction, and api.openai.com is denied by the environment network policy (proxy 403). Key not stored anywhere. OpenAI pass-bar run left to the user (command in spike3-report.md).
Handoff: docs/os/handoff/ on branch chore/s0-handoff (from pai-os), includes this ledger, Task 7 rulings + report.
