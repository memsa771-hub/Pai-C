# PAI OS handoff: end of the Slice 1 build (2026-10-19)

**A new session reads this file first, all of it.** It continues the Slice 0 handoff
(`docs/os/handoff/README.md`, on `pai-os` once PR #39 merges, or `git show origin/chore/s0-handoff:docs/os/handoff/README.md`),
which still holds the general rules, people and Slice 0 history. Where the two disagree, this file is newer.

Authority order: parent spec > Slice 1 spec > plan > ledger rulings > this handoff.

## 0. Start here (the next session's first steps)

1. Do the environment setup (§4) and run the checks (§6). Expect them all green.
2. Check the PR stack (§2). Merge it **in order**, rebasing as described there, only when the user
   says so. The user decides on merges and gates. Ask them about §9.
3. Then continue with §10: the slice gates, then Spike 1 and the Slice 2 spec.

## 1. Where things stand

- **Slice 0:** all tasks are merged into `pai-os`. Spike 3 PASS (#37 merged).
  - Still open: the slice gate, i.e. a PR from `pai-os` into `dev`, tagged `os-slice-0`. Its text is
    prepared but not opened, because the permission check blocked opening a PR into `dev` without the
    user's explicit go.
  - PR #39 (Slice 0 handoff docs into `pai-os`) is open.
- **Spike 5 part 1** (Germany playbook walkthrough): PR #38 into `pai-os`.
  - @10Faheem reviewed it: PASS with notes. The notes are applied.
  - Open item A1: the developers say HEC e-Attestation is accepted, but there is no official source yet.
- **Slice 1 ("Plan with no AI"):** all 11 plan tasks are built (TDD, inline execution), plus a final
  whole-branch review by a fresh reviewer and one fix pass.
  - The review found 2 Critical and 7 Important issues; all are fixed with RED→GREEN tests.
  - 19 minors are deferred (§8.3).
  - After the review, the user asked for M3 (tenant filters) and M14 (a schedule-fires test). Both are
    done, along with a review of `main.py` and the guard test.
  - Everything is pushed. PRs: see §2.
- **Production readiness:** see `docs/os/slice-1-readiness.md`. In short: the engine is ready, but it
  is not ready for students. Email is mock (log only), the data is unconfirmed, and the durations are
  estimates.

## 2. Branches and PRs (stacked, merge in this order)

Every Slice 1 branch is cut from the one before it, so each PR shows only its own task.

| Order | PR | Branch | Base | What |
|---|---|---|---|---|
| — | #39 | `chore/s0-handoff` | `pai-os` | Slice 0 handoff docs (independent) |
| — | #38 | `os/s1-spike5-germany-playbook` | `pai-os` | Spike 5 walkthrough (independent) |
| 1 | #40 | `os/s1-spec` | `pai-os` | Slice 1 spec + plan |
| 2 | #41 | `os/s1-t1-remove-spikes` | `os/s1-spec` | Task 1: remove Spike 3 code |
| 3 | #42 | `os/s1-t2-tables` | t1 | Task 2: tables, `os_0002` |
| 4 | #43 | `os/s1-t3-playbooks` | t2 | Task 3: playbooks |
| 5 | #44 | `os/s1-t4-knowledge` | t3 | Task 4: Knowledge |
| 6 | #45 | `os/s1-t5-compiler` | t4 | Task 5: compiler |
| 7 | #46 | `os/s1-t6-kernel` | t5 | Task 6: kernel |
| 8 | #47 | `os/s1-t7-runner` | t6 | Task 7: runner + crash test (+ Counsellor guard-test scoping, a shared file) |
| 9 | #48 | `os/s1-t8-workers` | t7 | Task 8: workers, outbox, service |
| 10 | #49 | `os/s1-t9-api` | t8 | Task 9: API + `main.py` mount (shared file) |
| 11 | #50 | `os/s1-t10-germany` | t9 | Task 10: Germany playbook, seed, golden |
| 12 | #51 | `os/s1-t11-inbox` | t10 | Task 11: inbox page (`api.ts`, `config.ts` shared) |
| 13 | #52 | `os/s1-t12-review-fixes` | t11 | Review fixes, tenancy, schedule test, admin header, these docs |

**How to merge a stacked chain without stranding changes** (the #32 lesson): merge the lowest PR into
`pai-os` (squash). Then, for the next PR:
1. `git fetch`.
2. `git rebase --onto origin/pai-os <old tip of the merged branch> <next branch>`.
3. Force-push with `--force-with-lease`.
4. Retarget the PR's base to `pai-os` (GitHub API PATCH `/pulls/{n}` with `{"base": "pai-os"}`).
5. Wait for CI, then merge.

Repeat up the chain. The alternative is merge commits (no rebase needed). Ask the user which.

Other branches:
- `chore/os-worker-compose` (from `dev`, commit 8e36fef): the `os-worker` compose service behind
  profile `os`, OS env switches, and explicit `pyyaml`. These are shared files. **Merge only after**
  `pai-os` reaches `dev` at the gate, then make sure the merged compose keeps `alembic upgrade heads`
  (review M19).
- `backup/pre-restack/*`: **local** tags only (not pushed) with the stack tips from before the guard
  fix moved into Task 7. Safe to delete.

## 3. Working rules (this user, this project)

- Follow the Slice 0 handoff §2. The rules most used in this session:
  - **Run the pre-push checks before every push**, from `backend/`: `tach check`,
    `python scripts/check_alembic_heads.py` and `python -m pytest tests/os -v -rs` (0 skipped).
  - **Push, then stop.** Open PRs or merge only when the user says so. PRs into `dev` need the user's
    explicit go; the permission check enforces this.
  - Never stack PRs without a merge plan (see §2).
  - Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (no session URL is
    available locally). PR bodies follow `.github/pull_request_template.md` and end with
    `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
  - Shared files need a reviewer from each team. In Slice 1 these are `backend/app/main.py`,
    `backend/tests/test_system_capabilities.py`, `frontend/lib/api.ts`, `frontend/lib/config.ts`, and
    everything on `chore/os-worker-compose`.
- **This user wants speed.** They said "don't wait on reviews; we merge in order later", and they
  approved defaults quickly. Keep messages short, act without check-ins, and ask only when a decision is
  theirs (merges, gates, money, keys).
- Process for code: superpowers brainstorming → spec → writing-plans → **executing-plans (inline,
  chosen for speed)** with TDD, one ledger, then a final fresh-reviewer pass on the most capable model,
  then one fix pass.
- Never print secrets. The OpenAI key the user pasted is in `~/.pai-os-key` (WSL, mode 600). It is the
  **Counsellor's** key, not a budgeted PAI OS project key. The user must rotate it and the other keys
  they pasted (Tavily, Resend, DB password). Delete the file when no longer needed.

## 4. Environment (local, the user's Windows machine)

- **Repo:** WSL2 distro `Ubuntu-24.04`, checkout `/home/musawir/Pai-C`
  (Windows UNC path `\\wsl.localhost\Ubuntu-24.04\home\musawir\Pai-C`). The Claude session ran on
  Windows and drove WSL with `wsl -d Ubuntu-24.04 -- bash <script>`.
  - Write multi-command steps as `.sh` files: PowerShell mangles quotes, pipes and `$` inside
    `bash -c "..."`.
- **Python:** `backend/.venv` (Python 3.12.3), with requirements and requirements-dev installed.
- **Postgres 16:** Docker container `os-pg` (`-p 5433:5432`, password `os`, database `os_test`).
  - Docker Desktop **stops on its own now and then**. Restart it with
    `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`, then `docker start os-pg`.
  - WSL integration for `Ubuntu-24.04` is enabled in Docker's `settings-store.json` (a backup is
    alongside it).
- **Env for tests:**
  ```bash
  export OS_TEST_DATABASE_URL=postgresql://postgres:os@127.0.0.1:5433/os_test
  export OS_DATABASE_URL=$OS_TEST_DATABASE_URL
  ```
- **Git push:** WSL has no stored GitHub credential. Push through the Windows credential manager:
  ```bash
  git -c credential.helper= -c "credential.helper=/mnt/c/Program\ Files/Git/mingw64/bin/git-credential-manager.exe" push
  ```
  The Windows Git identity is `MusawirKtk`, also set as the repo's local identity in WSL.
- **GitHub API / PRs:** there is no `gh` CLI. Get the token in PowerShell with
  `"protocol=https`nhost=github.com`n`n" | & "C:\Program Files\Git\mingw64\bin\git-credential-manager.exe" get`
  (`password=` line, never printed), then `Invoke-RestMethod` against `api.github.com/repos/memsa771-hub/Pai-C`.
- **Frontend:** no Node in WSL. Test it in a Windows copy:
  1. `robocopy` the `frontend` folder to `%TEMP%\pai-fe` (excluding `node_modules`).
  2. `npm ci` there.
  3. Run `npx vitest run`, `npx tsc --noEmit` and `npm run build` (with `NEXT_PUBLIC_OS_ENABLED=true`).
- **Windows long paths:** the session scratchpad path is longer than 260 characters. Windows Python
  needs `\\?\` prefixes there; WSL paths (`/mnt/c/...`) work fine.

## 5. What Slice 1 built (map of `backend/app/os/`)

| Package | What it does |
|---|---|
| `models.py` + `alembic/versions_os/os_0002_slice1_tables.py` | 11 tables in schema `os`: plans, tasks (with `estimated`, `protected`, `skipped_draft`), edges, revisions, pins, enqueue requests, attempts, events, modules, outbox, knowledge facts. Every table has `tenant_id`; every timestamp is timezone-aware |
| `playbooks/` | Pydantic models and a YAML loader. `germany_master.v1.yaml` has 19 cited steps (from Spike 5) with 5 estimate constants. Fake routes are in `tests/os/playbooks/` |
| `knowledge/` | `KnowledgePort`, `SqlKnowledge` (upsert, get, confirm), YAML seed `seed/germany_ws2027.yaml` (12 facts, all unconfirmed) |
| `compiler/` | Pure `compile_plan()`: conditions, fan-out, anchors → end of day in the timezone, lead and duration constants, `confirm_fact` tasks for unconfirmed or missing facts, cycle check, backward and forward pass, slack, critical path, `disabled_types` fallback, the anchor-fact citation first |
| `kernel/` | `Kernel`, the **only** writer of plan tables. Covers create (idempotent by contract SHA, race-safe), revise (structural diff; a started difference is reported once via `skipped_draft`; cancelled rows are renamed `key#cN`; stale drafts are refused with `based_on`), upgrade, `mark_running`, `apply_result`, `complete_student_task` / `complete_review`, `retry`, and promotion |
| `runner/` | `Registry`, the default modules (`inbox`, `milestone`, `knowledge.manual`), `enqueue_pending` and `reconcile` (DBOS client only), the `os.run_attempt` workflow (load → handle → apply steps), `register_job` with DBOS `apply_schedules`, and `worker.py` (validates playbooks against the registry, launches, enqueues every second) |
| `workers/` | `deadline_engine` (hourly recompute with per-plan failure isolation), `reminders` (cadence slots → outbox), `manual` (`confirm_fact`, `supply_fact`, `open_confirm_tasks`), `jobs.py` (worker schedule factories) |
| `outbox/` | Idempotent `Outbox` and `LogSender` (the only sender) |
| `service.py` | `PlanService`: select or pin the playbook, read facts, compile, call the kernel. Also `recompile` (with a StaleDraft retry), `upgrade`, `check_fact_value` |
| `api/` | Admin calls send **`X-OS-Admin-Token: <OS_ADMIN_TOKEN>`**, not `Authorization`: the Counsellor's `PaiSessionBoundaryMiddleware` rewrites `Authorization` on every `/v1/` request. Router at `/v1/os`: `POST/GET /plans`, `POST /plans/{id}/upgrade`, `GET /inbox`, `POST /inbox/{id}/complete` (write auth), `POST /facts/{id}/confirm`, `POST /facts`, `GET /facts/open`. Also `mount_os()` (eager startup validation) and the ports `current_student_ref` / `current_student_ref_for_write` |

- **Host side (`backend/app/main.py`):** mounts the OS API when `OS_ENABLED`. It maps the signed-in
  student to their **workspace id** through `app.application_workspace.access._auth`: read for GET,
  `write=True` for POST. That module is **read-only old OS** and retires in Slice 6, so the OS student
  port will need its own mapping then.
- **Frontend:**
  - Page `frontend/app/[workspaceId]/os-inbox/page.tsx`.
  - Component `components/os/inbox-list.tsx` and helpers in `lib/os-inbox.ts`.
  - `workspaceApi.getOsInbox` / `completeOsInboxItem`, which use a new `requestJson()` with no
    `{data}` envelope.
  - The flag `OS_UI_ENABLED` (`NEXT_PUBLIC_OS_ENABLED`).

Key decisions (all in the ledger with their costs):
- S1-D1…D6: scope is core plus one inbox screen; Knowledge is a hand-seeded table; plans start from an
  admin endpoint; email is outbox plus a log sender; approach A (kernel service plus DBOS for attempts
  only); Knowledge keeps 3 statuses plus a `conflict_note`.
- Plan rulings R-P1…R-P4.
- Per-task rulings for Tasks 1–11.
- The final-review rulings.

## 6. How to run everything

From `backend/`, with the venv active and the env from §4:

```bash
tach check
python scripts/check_alembic_heads.py
python -m pytest tests/os -v -rs
```

Expected: 0 skipped and **271 passed** on `os/s1-t12-review-fixes`.

- **Legacy (Counsellor) suite:** unset the OS env vars, then
  `python -m pytest tests -q -p no:tach --ignore=tests/os`. Expected **1006 passed**, 3 skipped
  (1002 plus the 4 new bridge tests).
- **Crash tests:** `python -m pytest tests/os/test_crash.py`. These are worker subprocesses killed with
  SIGKILL, plus a test that the worker enqueues by itself.
- **Golden plan:** `UPDATE_GOLDEN=1 python -m pytest tests/os/test_golden.py::test_golden_test_student`
  rewrites it. **Always diff and check the dates by hand before committing.**

Results on the integrated tree (`pai-os` + #39 + #38 + the full Slice 1 stack, merged in a throwaway
worktree, 2026-10-19), all green. The script is reproduced in §6.1.

| Check | Result |
|---|---|
| Merge order `pai-os` ← #39 ← #38 ← #52 (whole stack) | no conflicts; 95 files changed vs `pai-os` |
| `alembic upgrade heads` on an empty DB → `downgrade os@-1` → `upgrade heads` | all exit 0; 11 `os` tables |
| `tach check`, heads check | green |
| OS suite (CI env: only `OS_TEST_DATABASE_URL`) | 271 passed |
| Crash recovery (`test_crash.py`), 3 extra runs | 2/2 passed each run |
| Legacy Counsellor suite | 1006 passed, 3 skipped |
| `app.main` with `OS_ENABLED=true`, real middleware | no token 401, `X-OS-Admin-Token` 200, unknown workspace 404 |
| Real worker (`OS_WORKER_ID=smoke-w1`) against the integrated DB + golden student | started, ran all 16 `confirm_fact` work tasks to `waiting_review`, 11 inbox items open, 0 errors in its log, clean exit on SIGTERM; schedules registered: `os.reconcile`, `os.deadline_engine`, `os.reminders`, `os.deliver_outbox` |

The first integration run found **two real bugs** that the branch suites had missed, and both are fixed:
- The test helper relied on `OS_DATABASE_URL`, which CI never sets.
- The admin bearer was stripped by the Counsellor's session middleware, so the admin token now uses
  its own header.

### 6.1 Reproducing the integrated check

From a throwaway worktree:
1. `git worktree add --detach /tmp/integ origin/pai-os`.
2. Merge `origin/chore/s0-handoff`, `origin/os/s1-spike5-germany-playbook` and
   `origin/os/s1-t12-review-fixes` (no fast-forward).
3. From `/tmp/integ/backend`, with the repo's venv:
   - Create an empty database: `docker exec os-pg psql -U postgres -c "CREATE DATABASE os_integ"`.
   - Run `DATABASE_URL=…/os_integ python -m alembic upgrade heads`, then `downgrade os@-1`, then
     `upgrade heads` again.
   - Run the suites as in §6.
   - Start `OS_DATABASE_URL=…/os_integ OS_WORKER_ID=smoke-w1 python -m app.os.runner.worker`. Then, in
     Python, `load_seed(...)` and `make_services(...).plans.start_plan(TEST_STUDENT)`, and watch the
     `confirm_fact` tasks reach `waiting_review`.
4. Afterwards, `git worktree remove -f /tmp/integ`.

## 7. Production readiness

See `docs/os/slice-1-readiness.md`. In short:
- **Ready:** the compiler, kernel, runner, crash recovery, schedules, tenancy, API and migrations.
- **Mock:** email (log only).
- **Estimates:** five durations, including a 90-day visa buffer.
- **Unconfirmed:** every programme fact and the 2027 amounts. `visa_target_date` is missing on
  purpose, so the visa phase stays blocked until it is supplied.

## 8. Not implemented / left out of Slice 1

### 8.1 Out by decision (spec S1-D1 and parent §6)

- **Workers:**
  - Grade converter, funds calculator and checklist validator: moved to Slices 3 and 6.
  - Renderer: Slice 6.
  - Freshness sweeper: Slice 2.
- **Delivery and data:**
  - Real email (Resend), allow-list and address resolution: before the pilot.
  - Research agent, Docling and the trust checks: Slice 2.
- **Student-facing:**
  - Document upload: Slice 3.
  - Student self-start: Slice 4.
- **Rules and the Counsellor:**
  - Revision limits, rules and the Supervisor: Slice 7. Escalation events are written, but nothing acts
    on them.
  - Counsellor adapter / EscalationSink: Slice 8.
- **Tables not built:** `os_budgets`, `os_outcomes`, `os_agent_runs`, `os_human_tasks`,
  `os_approvals`, `os_artifacts` and `os_artifact_versions`.

### 8.2 Gaps found while building (not in any slice yet)

- The inbox page has **no navigation link** in the Counsellor UI; it is reachable only by URL. There
  is no i18n.
- **No admin UI.** Facts are confirmed or supplied through the API only.
- **No observability:** no metrics or Phoenix tracing, and no spend or audit log.
- The deadline engine is hourly only, not triggered by events (M5).
- Only 3 of the 30 shortlist programmes are seeded.
- Spike 5 A6 (certified copies, a conditional step) has no playbook step.
- `enrol` is not per programme (M13).
- The API process uses its own SQLAlchemy engine and does not copy the Counsellor's
  Supabase-pooler-specific engine options (`app/database.py`). Check this before deploying against
  the pooler (port 6543).

### 8.3 Deferred review minors (from the ledger)

| # | Minor |
|---|---|
| M1 | The invariant-1 check is a line regex; make it an AST check |
| M2 | `slack_low` is emitted on every recompute; emit it only on the change |
| M4 | Outbox head-of-line blocking; count failures and give up after N |
| M5 | No `fact_changed` event |
| M6 | No deploy seed command; seeding should be insert-only |
| M7 | `os_modules` primary key is not per tenant |
| M8 | Missing indexes |
| M9 | A work task's `input_missing` never shows in the inbox |
| M10 | "Choose" items have no options |
| M11 | The inbox page path differs from the spec |
| M12 | `GET /plans/{id}` is admin-only |
| M13 | Playbook content gaps |
| M15 | Edge cases around blocking |
| M16 | No rule for bumping the DBOS app version |
| M17 | Fact confirmation ignores the intake year |
| M18 | The reminder recipient is a workspace id |
| M19 | Keep `alembic upgrade heads` at the gate |

M3 (tenant filters) and M14 (schedule-fires test) are **done**.

## 9. Decisions waiting for the user

1. **Final target branch and gate.** Is the Slice 1 stack's target `pai-os`, with the Slice 0 gate
   (`pai-os` into `dev`, tag `os-slice-0`) first and a Slice 1 gate (tag `os-slice-1`) later? Should
   the stack merge with squash and rebase-retarget, or with merge commits?
2. Opening the Slice 0 gate PR into `dev`. The text is ready, but it was blocked without their
   explicit go.
3. The source for the HEC e-Attestation answer (A1), so it can be marked confirmed.
4. D7 cost ceiling ($10 per student per year) is still "Proposed — confirm".
5. Rotate the pasted keys, and create the PAI OS OpenAI project with a budget.

## 10. Next work, in order

1. Merge the chain (§2) and pass the Slice 0 gate, then the Slice 1 gate. Each gate merges into `dev`
   with a reviewer from each team, then gets its tag. Then merge `chore/os-worker-compose`.
2. **Before any pilot use:** the items in readiness §6, starting with real email and confirming the
   seeded facts.
3. **Spike 1** (research of the 30 programmes, ≥95% correct and ≥70% confirmed): use the per-programme
   field list in the Spike 5 doc §3 and `PAI-OS-Programme-Shortlist-WS2027.xlsx` (on the user's
   desktop, not in the repo).
4. **Slice 2 spec** (Knowledge: research agent, trust rules, Docling, source/status display). It must
   decide whether to add a `conflict` status, and it builds on `os_knowledge_facts` and
   `SqlKnowledge`.

## 11. References

- **Specs:**
  - Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md`
  - Slice 1: `docs/superpowers/specs/2026-10-18-pai-os-slice-1-design.md`
- **Plans:**
  - Slice 1: `docs/superpowers/plans/2026-10-18-pai-os-slice-1.md`
  - Slice 0: `docs/superpowers/plans/2026-10-12-pai-os-slice-0.md`
- **Ledger** (every ruling, review finding and fix): `docs/os/handoff/slice-1-sdd-ledger.md`
- **Readiness:** `docs/os/slice-1-readiness.md`
- **Spike 5:** `docs/os/spikes/spike5-germany-playbook.md` (PR #38). **Spike 3 report:**
  `docs/os/spikes/spike3-report.md`.
- **Old-OS inventory:** `docs/os/old-os-inventory.md`
- **Rules:** `CLAUDE.md`, `backend/app/os/CLAUDE.md` (13 invariants)
- **FigJam board:** https://www.figma.com/board/sEWRgciL9Quwmklh492qUW
