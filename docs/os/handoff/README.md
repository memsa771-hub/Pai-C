# PAI OS handoff — end of Slice 0 build (2026-10-15)

**A new session reads this file first.** It holds everything needed to finish Slice 0 and start
Slice 1 without the earlier conversations. Detail lives in the other files of this folder:

| File | What it is |
|---|---|
| `README.md` (this file) | State, rules, decisions, next steps |
| `slice-0-sdd-ledger.md` | Task-by-task log of Slice 0: every pre-flight check, review finding, fix round and ruling |
| `slice-0-task-7-rulings.md` | The binding design rulings R1–R9 for the Spike 3 chaos run |
| `slice-0-task-7-implementer-report.md` | Task 7 build report: TDD evidence, test runs, rehearsal numbers, fix rounds |

Source documents (authority order: spec > plan > rulings):
- Spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (invariants §3.1, slices §6, process §7)
- Slice 0 plan: `docs/superpowers/plans/2026-10-12-pai-os-slice-0.md`
- OS rules: `backend/app/os/CLAUDE.md` (13 invariants) and root `CLAUDE.md` (working rules)
- FigJam review board: https://www.figma.com/board/sEWRgciL9Quwmklh492qUW

---

## 1. Where things stand

- **Slice 0 Tasks 1–7 are merged into `pai-os`.** Head `f1e9e96` (Task 7 = PR #36, merged 2026-10-16, CI green, approved by @MusawirKtk).
- **Task 7 is merged** (PR #36).
  - PR: https://github.com/memsa771-hub/Pai-C/pull/36.
  - Checks: tach ✅, single Alembic head check ✅, `tests/os` 57 passed, no orphan worker processes.
- **The Spike 3 report says "PENDING the OpenAI run".** The billed pass-bar run has not been done (§4).
- All follow-up PRs are merged:
  - #30 pydantic pin `~=2.14.1` (into dev)
  - #31 pytest-asyncio in `requirements-dev.txt`
  - #33 RouteContract fixes
  - #34 dev → pai-os (merge commit)
  - #35 `legacy` CI job made blocking
- This handoff sits on branch `chore/s0-handoff` (docs only, from `pai-os`). Merge it with a small PR, or keep the branch until Slice 1 starts.

### What Slice 0 built (all under `backend/` unless noted)

| Task | PR | What |
|---|---|---|
| 1 | (273bbd2) | `app/os/` skeleton: `settings.py` (`OsSettings`, `load_settings`), `CLAUDE.md` invariants, `tach.toml` (`app.os` depends on nothing), `tests/os/` |
| 2 | #23, fixed by #33 | `app/os/contracts/route_contract.py` (RouteContract, ProgrammeChoice, IntakeRef; `extra="forbid"`; refs stripped and non-empty; `dedupe_key`), frozen JSON schema `route_contract.v1.schema.json` |
| 3 | #25 | `app/os/db.py` (`OS_SCHEMA="os"`, `OsBase`, `make_engine`); Alembic branch `os` (`alembic/versions_os/os_0001_schema.py`); `alembic.ini` `version_locations` + `path_separator = space`; `env.py` with both metadatas and an `include_name` filter (default schema + `os`); **every deploy uses `alembic upgrade heads`** (plural); `scripts/check_alembic_heads.py` |
| 4 | #26 | `scripts/os_inventory.py`, which generates `docs/os/old-os-inventory.md`. It gives a fate to all 81 old-OS modules (keep 54, read-only 18, retire 9); a drift test keeps the markdown current |
| 5 | #27 | `.github/workflows/ci.yml`: job `os` (Python 3.12, postgres:16, tach, heads check, `pytest tests/os`, guard against silent DB skips) and job `legacy` (the Counsellor suite, blocking since #35). Also `.github/pull_request_template.md` and `.github/CODEOWNERS`. A deliberate boundary violation was blocked by CI (PR #28, closed) |
| 6 | #29 | `spikes/spike3/loop.py` + `schema.sql` + `pages/`: the core loop. Kernel `mark_ready` → outbox → enqueue (`task_id:attempt`) → DBOS queue → `run_attempt` workflow (`load_page` → Pydantic AI agent with `DBOSDurability` → `record_result` → `complete_task`) → `reconcile` |
| 7 | #36 | `spikes/spike3/chaos.py` (driver) and `worker.py`, `tests/os/test_spike3_chaos.py` (marker `chaos`, runs in CI), `docs/os/spikes/spike3-report.md`. `loop.py` changes: kernel side through `DBOSClient`, `worker` column, terminal workflow statuses → `failed/workflow_error`, `application_version="spike3"` |

### Slice 0 gate (spec §6, plan "Done when")

| Gate item | Status |
|---|---|
| `pytest tests/os` green in CI, `tach check` green, heads check green | ✅ on `pai-os` including Task 7 (PR #36 CI: `os` + `legacy` green) |
| CI demonstrably blocked a deliberate boundary violation | ✅ PR #28 (tach failed on `app.os` → `<root>`) |
| Old-OS inventory has a fate for every row | ✅ 81/81, sign-off recorded in `os_inventory.py` |
| `spike3-report.md` says PASS against the pass bar, signed by both developers | ❌ **open**: OpenAI run + sign-off (§4) |

---

## 2. How we work (the user's rules — follow exactly)

- **Process per task:** superpowers:subagent-driven-development.
  - Order: implementer → task reviewer → fix rounds → scoped re-review.
  - Keep a ledger in `.superpowers/sdd/<plan>/progress.md`. It is git-ignored, so copy it into `docs/os/handoff/` at session end.
  - One branch per task, `os/s<N>-t<M>-<name>`, cut from `pai-os`. Touch only that task's files.
- **Before every push:** from `backend/`, run `tach check`, `python scripts/check_alembic_heads.py` and `python -m pytest tests/os -v -rs`. Show the full output and the changed files.
- **Push, then stop.** Open a PR or merge only when the user says so. The user usually opens and merges PRs.
  - Task PRs are squash-merged.
  - `dev` → `pai-os` syncs use a **merge commit**.
  - `pai-os` → `dev` happens only at slice gates, tagged `os-slice-N`.
- **Never stack PRs.** Squash-merging the base strands the stacked PR; that happened with #32 and needed the #35 re-land.
- **Shared files go to `dev` first** in their own small PR, then `dev` → `pai-os`. Shared files are requirements, Alembic env, compose and CI that affect the Counsellor.
  - Exception: `requirements-dev.txt` and `ci.yml` exist only on `pai-os`, so they change there.
- **CLAUDE.md rules:**
  - Never paste API keys or real student data.
  - One component per PR.
  - OS code only in `backend/app/os`.
  - Shared files need a reviewer from each team.
- **If a step is unclear or a test can't pass as written, stop and ask; don't improvise.** The user may delegate a decision ("do what you think is better"). Then decide, explain why, and record a `Ruling:` line in the ledger.
- **After each task:** a short summary of what was built, how, and what's left. Be quick and efficient; the user has limited credits.
- **Commits** end with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: <session url>`.
  PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)` plus the session URL.
- **People:**
  - OS developers: @10Faheem, @MusawirKtk. They approve PRs; both sign the Spike 3 report.
  - Counsellor lead and repo admin: @memsa771-hub. This is the user, and PRs made from sessions show as theirs.
  - The Counsellor lead delegated the inventory sign-off to the user, who delegated it to Claude (2026-10-14).
- **Repo settings:**
  - Ruleset "Required CI and review" requires check `os` and a PR on `pai-os`.
  - **To do:** add `legacy` as a required check on `pai-os`.
  - `os` must not be required on `dev`/`main`, because they have no `tests/os`; the user fixed this.

## 3. Environment

### 3a. Local session (the user's machine) — the next session runs here
The next session is a **local** Claude Code session on the user's computer, not the cloud.
OpenAI is reachable there, so that session can run the Spike 3 OpenAI pass-bar run itself (§4.2).

**OS:** macOS or Linux. On Windows, use **WSL2** (Ubuntu): the chaos harness uses `signal.SIGKILL` and
`os.getppid()`, and Windows has neither, so the chaos test and run fail on native Windows.

One-time setup, done by the user in a terminal **before** starting `claude`:
1. **Repo:** `git clone https://github.com/memsa771-hub/Pai-C.git` (or `git pull` in an existing clone), then
   `git fetch origin pai-os chore/s0-handoff`.
2. **Python 3.12** (CI's version; 3.13 also works). In `backend/`, make a virtual env:
   `python -m venv .venv`, then activate it (`source .venv/bin/activate`), then
   `pip install -r requirements.txt -r requirements-dev.txt`.
3. **Postgres 16**, local or Docker. The simplest is Docker:
   `docker run -d --name os-pg -p 5433:5432 -e POSTGRES_PASSWORD=os -e POSTGRES_DB=os_test postgres:16`.
   - Test database: `OS_TEST_DATABASE_URL=postgresql://postgres:os@127.0.0.1:5433/os_test`
   - Scratch database for the chaos run: `OS_DATABASE_URL=postgresql://postgres:os@127.0.0.1:5433/os_test`.
     The run drops schema `dbos_chaos` and empties `spike3`, so never point it at a real database.
4. **Key:** set `OS_OPENAI_API_KEY` in that same terminal (`export OS_OPENAI_API_KEY=...`), then start `claude` from the repo root.
   The session inherits the variable. **Never paste the key into the chat.** Ideally use a key from
   a separate PAI OS OpenAI project that has a budget limit.
5. Optional: `export OS_MODEL_CHEAP=gpt-5.4-mini`. This is already the default.

Checks the session runs before anything else, from `backend/` with the venv active:
`tach check`, `python scripts/check_alembic_heads.py`, `python -m pytest tests/os -v -rs`.
All must pass (57 tests on `pai-os` at `f1e9e96`).

### 3b. Cloud container (where Slice 0 was built), for reference

- **Postgres 16:** the `postgresql-16` package is in the image. The data directory is not, so a fresh container needs:
  ```
  mkdir -p /var/tmp/os-pg && chown postgres /var/tmp/os-pg
  su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/os-pg/data -A trust"
  su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/os-pg/data -l /var/tmp/os-pg/log -o '-p 5433 -k /tmp' -w start"
  su postgres -c "psql -h /tmp -p 5433 -c 'CREATE DATABASE os_test'"
  export OS_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5433/os_test
  ```
  It sometimes stops; restart it with the `pg_ctl ... start` line.
- **Python:**
  - Install: `pip install -r backend/requirements.txt -r backend/requirements-dev.txt`.
  - The container has Python 3.13 and CI uses 3.12, so avoid 3.13-only syntax.
  - Key pins: dbos 3.2.0, pydantic-ai-slim[openai] 2.55.0, pydantic ~=2.14.1, tach 0.35.3, pytest-asyncio 1.4.0.
- **Network:** `api.openai.com` is **blocked** by this cloud environment's network policy (proxy 403). Billed OpenAI runs can't happen here unless the user adds the host under Network access → Allowed domains.
- **Keys:** never ask for a key in chat.
  - The user pasted the Counsellor `.env` twice. Its values were not used, stored or committed, and the user was told to rotate them.
  - The OS key is `OS_OPENAI_API_KEY`. It goes in a separate OpenAI project with a budget, set on the user's machine or as an environment secret.
  - The session's permission system also blocks pulling keys out of chat history.

## 4. Next steps to finish Slice 0 (in order)

1. ~~Merge PR #36~~ — done 2026-10-16 (`f1e9e96`). If CI fails, fix it per the drive-to-green rules.
   - The chaos test takes about 30–60 s in CI.
   - If CI shows flaky kill timing, check `kills >= 3` and the 1.5 s model delay in the test.
2. **User: run the OpenAI pass-bar run** on a machine that can reach OpenAI, with Postgres 16 and the requirements installed. From `backend/`:
   ```
   OS_DATABASE_URL=postgresql://USER@HOST:PORT/DB OS_OPENAI_API_KEY=<OS dev key> \
     python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model openai --timeout 1800
   ```
   - It uses `OS_MODEL_CHEAP`, default `gpt-5.4-mini`.
   - It drops and recreates schema `dbos_chaos` and empties `spike3` in that database, so use a scratch database.
   - It prints a JSON `ChaosReport` and `pass bar: PASS|FAIL (...)`, and exits 1 on FAIL. On FAIL the worker logs are kept and their path is printed.
3. **Fill in `docs/os/spikes/spike3-report.md`** "Pass-bar run" section from the printed JSON (numbers only, never the key):
   - the cost from the OpenAI usage page;
   - the failures and their causes;
   - the verdict.

   On FAIL: stop, find the cause (worker logs, `spike3.tasks.failure_reason`), fix, re-run.
   - A `duplicated > 0` that comes from a same-process DBOS step retry is a false FAIL. Both rows then carry the same `worker` label, and the log shows "Step being automatically retried". See the report's note.
4. **Both OS developers sign the report** in its PR.
5. **Slice gate:**
   - PR `pai-os` → `dev`; both teams review because shared files changed.
   - Merge it, then tag `os-slice-0`.
   - Per `spikes/spike3/README.md`, the `backend/spikes/` folder is throwaway. Delete it in its own PR after the report is accepted, but carry the lessons in §6 into Slice 1.

## 5. Starting Slice 1 ("Plan with no AI")

Spec §6:
- **Builds:** kernel, states, scheduler, enqueue/reconcile, inbox, outbox, Germany playbook, compiler, workers, playbook-upgrade revision, fake routes.
- **Done when:** a test student gets a correct dated plan and inbox, a crash loses nothing, and fake routes run unchanged.

Before any Slice 1 code:
1. Slice 0 gate passed (§4). Per the plan: "No Slice 1 work starts until the report says PASS and both developers sign it."
2. **Spike 5, part 1 (before Slice 1):** a playbook walkthrough. Every step of the Germany playbook cites an official page, checked by the reviewer (spec §5 table).
3. **Write the Slice 1 spec, then the plan** (spec §5): superpowers:brainstorming → writing-plans, then this same subagent-driven-development loop. Each slice spec includes its student screens (mobile-first) and a simple wireframe (review F4). Tables live in schema `os`, every table carries `tenant_id` (spec §4.1), and migrations go on the `os` Alembic branch.

## 6. Decisions and lessons that carry into Slice 1

**DBOS / core loop (proven in Spike 3; use these in the real workers):**
- **Stable executor ID per worker replica.**
  - Set `executor_id` or `DBOS__VMID`. A restarted replica must reuse its ID, because DBOS only recovers `PENDING` workflows for its own executor ID.
  - Never let live workers share the default `"local"`. In a deliberately broken control run, sharing it gave 9 duplicates.
  - For containers, use a stable per-replica ID such as a StatefulSet ordinal or compose service index.
- **The kernel/API process never executes workflows.** It enqueues and reads status through `dbos.DBOSClient`. A launched DBOS always dequeues DBOS's internal recovery queue, even with `listen_queues`.
- **Set an explicit `application_version`** in the DBOS config of every process, so client-enqueued and recovered workflows are dequeued by every worker.
- **Reconcile must map terminal ERROR / CANCELLED / MAX_RECOVERY_ATTEMPTS_EXCEEDED to `failed` (`workflow_error`).** Otherwise the task is silently lost.
- **Workflow ID `task_id:attempt` is the idempotency key** (client enqueue reuse policy "return-existing"). Every step write is idempotent (invariant 8).
- **Use `DBOSDurability(model_step_config=StepConfig(retries_allowed=True, max_attempts=3))`** as an agent capability, not the deprecated `DBOSAgent`.
  - OpenAI client `max_retries=0`.
  - Agent `retries={"tools": 0, "output": 2}` (invariant 7).
  - Model requests become steps of the calling workflow.
- **Build the agent before `DBOS.launch()`.** Register workflows/steps per registry, because `DBOS.destroy(destroy_registry=True)` invalidates the old wrappers.
- **Measuring duplicates:** count body executions (append-only `step_runs`/`model_calls` with a worker label), not result rows, which the primary key makes unique anyway.

**Old-OS inventory preserve notes (`docs/os/old-os-inventory.md`):**
- `app.deadlines`, `.service` and `routers.deadlines` are **read-only until Slice 1**; Slice 1 replaces them.
- `services.workflow`, `routers.workflows` and `routers.tasks` are read-only until Slices 1 and 6. They are live plumbing for the application workspace and workflow-bound threads.
- `qualification_recognition` (retire) holds sourced packs (DAAD, uni-assist, HEC, APS with URLs). **Copy them into the Slice 1 Germany playbook / Knowledge before deleting.**
- `gap_assessment` (retire) is reference material for Slice 1 eligibility checks.
- The Counsellor research chain and documents ingest are **kept**. Revisit when the Slice 8 spec decides whether the Counsellor reads OS Knowledge.
- Retire = fate on paper only. Switch-off and deletion happen after the pilot, in their own PRs.

**Open decisions / inputs:**
- D7 cost ceiling ($10/student/year, alert at $8) is still **"Proposed — confirm"** (spec §11).
- An OpenAI project for PAI OS with a monthly budget is needed (spec §9).

## 7. Known issues and deferred items (not blocking Slice 0)

- **Bug (Counsellor side, out of OS scope):** `backend/app/routers/fetch.py:665` passes `_resolve_bf_key`'s `(key, source)` tuple as `api_key` to `BrowserManager.render_page_text`, so the JS render tier is likely broken. Needs its own task or PR to `dev`.
- **Stale doc:** `docs/counselor/CLEANUP_AUDIT.md:123` still says compose runs `alembic upgrade head`; it should be `heads`.
- **CODEOWNERS can't enforce "one reviewer from each team";** that rule is enforced by convention.
- **Deferred minors per task** are in the ledger (`Task N: minor (deferred)` lines). Notable ones:
  - Task 2: RouteContract nested-model freezing; `.upper()` on non-ASCII.
  - Task 3: no downgrade test; no test that the heads check fails on forked heads.
  - Task 4: reachability doesn't follow `include_router` prefixes or in-process ASGI calls.
- **Spike 3 measurement caveat:** a legal same-process DBOS step retry counts as `duplicated`, which gives a false FAIL, never a false PASS. `kills_in_flight` and `interrupted_workflows` are approximate; `recovered_attempts` and `duplicated` are exact.

## 8. Open items for the user

- [x] Merge the Task 7 PR #36 (done).
- [ ] Run the OpenAI pass-bar run (§4.2), fill in the report, and get both developers' sign-off.
- [ ] Add `legacy` as a required status check in the `pai-os` ruleset.
- [ ] Create the PAI OS OpenAI project with a budget and set `OS_OPENAI_API_KEY` (never in chat).
- [ ] Rotate the keys from the `.env` pasted in chat (OpenAI, Tavily, Supabase, Resend, DB password).
- [ ] Delete branch `os/s0-t7-spike3-chaos` now, and `chore/s0-handoff` once this folder is merged into `pai-os` (other leftover branches are already gone; `dev-backup` and `pai-c-backup` are kept on purpose).
- [ ] Confirm D7.

## 9. Prompt for the next session (local)

Do the §3a setup first. Then start `claude` in the repo root and paste:

> Continue PAI OS. First run `git fetch origin pai-os chore/s0-handoff` and read
> `docs/os/handoff/README.md` from branch `chore/s0-handoff`
> (`git show origin/chore/s0-handoff:docs/os/handoff/README.md`), all of it. Read
> `slice-0-sdd-ledger.md` in the same folder when you need history. Follow the working rules in §2
> exactly. This is a local session: check the §3a setup (venv, Postgres, `OS_TEST_DATABASE_URL`,
> `OS_DATABASE_URL`, and whether `OS_OPENAI_API_KEY` is set, without printing it), run the §3a checks,
> then tell me in a few lines where Slice 0 stands and what the next step is, and wait for my go.
