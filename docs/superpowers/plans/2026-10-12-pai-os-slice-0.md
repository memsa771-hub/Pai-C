# PAI OS Slice 0 (Foundations + Spike 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the empty, guarded `app/os` package (route contract, database area, boundaries, CI, rules files, old-OS inventory) and prove the core loop (DBOS + Pydantic AI + OpenAI) survives random worker kills with zero lost and zero duplicated tasks.

**Architecture:** New code lives only in `backend/app/os/` (product), `backend/tests/os/` (tests) and `backend/spikes/spike3/` (throwaway spike). A Tach boundary stops `app/os` importing any other app code. OS tables live in a Postgres schema `os` with their own Alembic branch; DBOS keeps its system tables in schema `dbos` of the same database so the existing backup covers them. Spike 3 uses its own schema `spike3` and is deleted after its report is accepted.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, DBOS Transact 3.2.0, Pydantic AI (slim, openai extra) 2.55.0, Tach 0.35.3, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-12-pai-os-design.md` (approved 2026-10-12). Sections used: 3.1 invariants 7, 8, 11, 12; 3.2 RouteContract, enqueue/reconcile, task runner; 5 Spike 3; 6 Slice 0; 7 code location.

## Global Constraints

- Python 3.12 (matches `backend/Dockerfile`). PostgreSQL 16.
- Exact pins: `dbos==3.2.0`, `pydantic-ai-slim[openai]==2.55.0`, `tach==0.35.3` (dev).
- New product code only under `backend/app/os/`. Shared files touched by this plan, each needing one reviewer from each team: `backend/requirements.txt`, `backend/alembic/env.py`, `backend/alembic.ini`, `docker-compose.prod.yml`, root `CLAUDE.md`, `.github/*`.
- `app/os` must not import any other `app.*` module (Tach). Root code may import `app.os`.
- Nothing country-specific in `app/os` (spec invariant 12): no country names, currencies, grade scales, document types or attestation bodies in code.
- Retries (invariant 7): OpenAI-compatible client `max_retries=0`; Pydantic AI `retries={"tools": 0, "output": 2}`; network/service retries only via DBOS step config (`retries_allowed=True, max_attempts=3`).
- Side effects idempotent (invariant 8): any write a re-run step could repeat uses a unique key and `ON CONFLICT DO NOTHING`.
- DBOS system tables: `system_database_url` = the app database URL, `dbos_system_schema="dbos"` in production; tests use `dbos_test`.
- Model names come from settings, never literals in logic: `OS_MODEL_CHEAP` default `gpt-5.4-mini`, `OS_MODEL_STRONG` default `gpt-5.4`. The OS uses its own key `OS_OPENAI_API_KEY` (a separate OpenAI project with a monthly budget), not the Counsellor's key.
- Postgres-backed tests read `OS_TEST_DATABASE_URL` and are skipped when it is unset; CI always sets it.
- Before Task 5: the two developers' GitHub handles (for `CODEOWNERS`).

## Review Focus

1. A worker dies after a step's database write but before DBOS checkpoints the step, so the step runs again → exactly one result row (Task 6, `test_record_result_is_idempotent`).
2. The enqueuer dies after enqueueing but before marking the request sent → re-running it starts no second workflow (Task 6, `test_enqueue_twice_runs_once`).
3. Enqueuer and reconciler act on the same ready task at the same moment → one workflow, one result (Task 6, `test_reconciler_and_enqueuer_race`).
4. A route arrives with lower-case or padded country codes, duplicate programme references, or ranks with gaps → normalised or rejected with a clear message (Task 2).
5. The Counsellor team adds a migration while the OS team adds one → CI fails fast instead of deploy failing (Task 3, `test_one_head_per_branch`).

---

## File Structure

```
CLAUDE.md                                   shared rules for both teams (new)
.github/workflows/ci.yml                    CI (new)
.github/pull_request_template.md            reviewer template (new)
.github/CODEOWNERS                          review ownership (new)
docker-compose.prod.yml                     migrate: "upgrade heads" (modify)
docs/os/old-os-inventory.md                 generated inventory + fate column (new)
docs/os/spikes/spike3-report.md             Spike 3 results (new)
backend/tach.toml                           module boundaries (new)
backend/requirements.txt                    + dbos, pydantic-ai-slim (modify)
backend/requirements-dev.txt                tach, pytest (new)
backend/alembic.ini                         + version_locations (modify)
backend/alembic/env.py                      + OS metadata, schemas (modify)
backend/alembic/versions_os/os_0001_schema.py   creates schema "os" (new)
backend/app/os/__init__.py
backend/app/os/CLAUDE.md                    OS invariants (new)
backend/app/os/settings.py                  OsSettings
backend/app/os/db.py                        OsBase, engine factory
backend/app/os/contracts/route_contract.py  RouteContract v1
backend/app/os/contracts/route_contract.v1.schema.json  frozen JSON schema
backend/scripts/os_inventory.py             builds the inventory from import_graph.py
backend/scripts/check_alembic_heads.py      one head per branch
backend/spikes/spike3/                      throwaway: schema.sql, loop.py, chaos.py, README.md
backend/tests/os/                           conftest.py + tests per task
```

---

### Task 1: OS package, settings, boundaries, rules files

**Files:**
- Create: `backend/app/os/__init__.py`, `backend/app/os/settings.py`, `backend/app/os/CLAUDE.md`, `backend/tach.toml`, `CLAUDE.md`, `backend/requirements-dev.txt`
- Modify: `backend/requirements.txt` (append `dbos==3.2.0`, `pydantic-ai-slim[openai]==2.55.0`)
- Test: `backend/tests/os/test_boundaries.py`, `backend/tests/os/test_settings.py`

**Interfaces:**
- Produces: `OsSettings` frozen dataclass with fields `database_url: str`, `dbos_system_schema: str = "dbos"`, `model_cheap: str = "gpt-5.4-mini"`, `model_strong: str = "gpt-5.4"`, `openai_api_key: str | None`, `os_enabled: bool = False`; `load_settings(env: Mapping[str, str] | None = None) -> OsSettings`. Env names: `OS_DATABASE_URL` (falls back to `DATABASE_URL`), `OS_DBOS_SYSTEM_SCHEMA`, `OS_MODEL_CHEAP`, `OS_MODEL_STRONG`, `OS_OPENAI_API_KEY`, `OS_ENABLED`.

- [ ] **Step 1: Write failing tests**

```python
# test_settings.py
def test_defaults_and_fallback():
    s = load_settings({"DATABASE_URL": "postgresql://u:p@h/db"})
    assert s.database_url == "postgresql://u:p@h/db"
    assert (s.model_cheap, s.model_strong, s.dbos_system_schema, s.os_enabled) == ("gpt-5.4-mini", "gpt-5.4", "dbos", False)

def test_os_database_url_wins():
    s = load_settings({"DATABASE_URL": "a", "OS_DATABASE_URL": "b", "OS_ENABLED": "true"})
    assert s.database_url == "b" and s.os_enabled is True

def test_missing_database_url_raises():
    with pytest.raises(ValueError, match="OS_DATABASE_URL or DATABASE_URL"):
        load_settings({})

# test_boundaries.py  (runs from backend/)
def test_tach_passes():
    assert subprocess.run(["tach", "check"], cwd=BACKEND).returncode == 0

def test_tach_blocks_os_importing_app_code(tmp_violation):
    # fixture writes backend/app/os/_violation.py containing "from app.services import operator"
    # and deletes it in teardown
    r = subprocess.run(["tach", "check"], cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 1 and "cannot depend on '<root>'" in r.stdout
```

- [ ] **Step 2: Run, verify failure** — `cd backend && pytest tests/os/test_settings.py tests/os/test_boundaries.py -v` → FAIL (`app.os` missing, no `tach.toml`).

- [ ] **Step 3: Implement** `load_settings` in `app/os/settings.py` (reads only the env mapping passed or `os.environ`; no imports from `app.config`). Create `backend/tach.toml`:

```toml
source_roots = ["."]
root_module = "dependenciesonly"

[[modules]]
path = "<root>"
depends_on = ["app.os"]

[[modules]]
path = "app.os"
depends_on = []
```

Write `backend/app/os/CLAUDE.md` with the 13 invariants from spec 3.1, verbatim, plus: "Done means the task's tests pass and the PR template is complete." Write root `CLAUDE.md`: never paste keys or real student data into Claude; one component per PR; rebase on `dev` before merge; OS code only in `backend/app/os`; shared files need a reviewer from each team; run `tach check` and `pytest tests/os` before pushing. `requirements-dev.txt`: `tach==0.35.3`, `pytest>=8`.

- [ ] **Step 4: Run tests** → PASS. Also `cd backend && tach check` → "All modules validated".
- [ ] **Step 5: Commit** `feat(os): package skeleton, settings, tach boundary, CLAUDE.md`

---

### Task 2: RouteContract v1

**Files:**
- Create: `backend/app/os/contracts/__init__.py`, `backend/app/os/contracts/route_contract.py`, `backend/app/os/contracts/route_contract.v1.schema.json`
- Test: `backend/tests/os/test_route_contract.py`

**Interfaces:**
- Produces: `class ProgrammeChoice(BaseModel)`: `programme_ref: str` (non-empty, stripped), `rank: int` (≥1). `class IntakeRef(BaseModel)`: `term: str` (pattern `^[a-z_]+$`), `year: int` (2025–2100). `class RouteContract(BaseModel)` (`extra="forbid"`, frozen): `contract_version: Literal["1"]`, `source: Literal["self_serve", "counsellor"]`, `external_ref: str`, `student_ref: str`, `origin_country: str`, `destination_country: str`, `level: Literal["foundation", "bachelor", "master", "phd"]`, `programmes: list[ProgrammeChoice]` (1–10), `target_intake: IntakeRef`; property `dedupe_key -> str` = `f"{source}:{external_ref}:{contract_version}"`. Module function `export_json_schema() -> dict`.

- [ ] **Step 1: Write failing tests**

```python
def valid(**over):
    base = {"contract_version": "1", "source": "self_serve", "external_ref": "ext-1",
            "student_ref": "stu-1", "origin_country": "PK", "destination_country": "DE",
            "level": "master", "target_intake": {"term": "winter", "year": 2027},
            "programmes": [{"programme_ref": "prog-a", "rank": 1}, {"programme_ref": "prog-b", "rank": 2}]}
    return {**base, **over}

def test_valid_contract_and_dedupe_key():
    c = RouteContract.model_validate(valid())
    assert c.dedupe_key == "self_serve:ext-1:1"

def test_country_codes_normalised():
    c = RouteContract.model_validate(valid(origin_country=" pk ", destination_country="de"))
    assert (c.origin_country, c.destination_country) == ("PK", "DE")

def test_same_origin_and_destination_allowed():          # local routes (D5)
    assert RouteContract.model_validate(valid(destination_country="PK")).destination_country == "PK"

@pytest.mark.parametrize("bad,msg", [
    ({"origin_country": "PAK"}, "two-letter"),
    ({"programmes": []}, "at least 1"),
    ({"programmes": [{"programme_ref": "a", "rank": 1}, {"programme_ref": "a", "rank": 2}]}, "duplicate programme"),
    ({"programmes": [{"programme_ref": "a", "rank": 1}, {"programme_ref": "b", "rank": 3}]}, "ranks must be 1..n"),
    ({"source": "partner"}, "source"),
    ({"unexpected": 1}, "Extra inputs"),
])
def test_rejections(bad, msg):
    with pytest.raises(ValidationError, match=msg):
        RouteContract.model_validate(valid(**bad))

def test_schema_is_frozen():
    committed = json.loads(SCHEMA_PATH.read_text())
    assert export_json_schema() == committed, "Contract changed: bump contract_version and add a new schema file"
```

- [ ] **Step 2: Run, verify failure** — `pytest tests/os/test_route_contract.py -v` → FAIL (import error).
- [ ] **Step 3: Implement** the models with field validators (upper-case + strip country codes, require `^[A-Z]{2}$` with message "two-letter ISO 3166-1 code"; model validator for duplicate refs and contiguous ranks). Generate `route_contract.v1.schema.json` once from `export_json_schema()` (sorted keys, 2-space indent) and commit it.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** `feat(os): RouteContract v1 with frozen JSON schema`

---

### Task 3: OS database area and Alembic branch

**Files:**
- Create: `backend/app/os/db.py`, `backend/alembic/versions_os/os_0001_schema.py`, `backend/scripts/check_alembic_heads.py`, `backend/tests/os/conftest.py`
- Modify: `backend/alembic.ini` (`version_locations = %(here)s/alembic/versions %(here)s/alembic/versions_os`), `backend/alembic/env.py` (target metadata list `[Base.metadata, OsBase.metadata]`, `include_schemas=True`), `docker-compose.prod.yml:115` (`["alembic", "upgrade", "heads"]`)
- Test: `backend/tests/os/test_db.py`

**Interfaces:**
- Consumes: `load_settings` (Task 1).
- Produces: `OS_SCHEMA = "os"`; `OsBase` (declarative base with `MetaData(schema="os")`); `make_engine(settings: OsSettings) -> Engine`. Migration `os_0001` with `revision = "os_0001"`, `down_revision = None`, `branch_labels = ("os",)`, creates `CREATE SCHEMA IF NOT EXISTS os` (downgrade drops it only if empty). `check_alembic_heads.main() -> int` returns 0 when there is exactly one head on the `os` branch and exactly one other head, else prints the heads and returns 1.
- Fixtures and helpers (`tests/os/conftest.py`): `pg_url` — skips when `OS_TEST_DATABASE_URL` is unset; `fresh_db(pg_url)` — drops and recreates schemas `os`, `dbos_test`, `spike3` once per session; `run_alembic(args: list[str], url: str) -> None` (runs Alembic from `backend/` with `DATABASE_URL=url`); `schema_exists(url: str, name: str) -> bool`.

- [ ] **Step 1: Write failing tests**

```python
def test_one_head_per_branch():
    assert check_alembic_heads.main() == 0

def test_os_branch_upgrade_creates_schema(fresh_db, pg_url):
    run_alembic(["upgrade", "os@head"], pg_url)
    assert schema_exists(pg_url, "os")

def test_os_base_uses_os_schema():
    assert OsBase.metadata.schema == "os"
```

- [ ] **Step 2: Run, verify failure** → FAIL (no `os` branch).
- [ ] **Step 3: Implement** files above. `os_0001` must not import `app.models`.
- [ ] **Step 4: Run tests** → PASS; also `cd backend && alembic heads` lists `os_0001 (os) (head)` and the main head.
- [ ] **Step 5: Commit** `feat(os): os schema, alembic os branch, upgrade heads` (the compose change is a shared-file change: request a Counsellor reviewer).

---

### Task 4: Old-OS inventory

**Files:**
- Create: `backend/scripts/os_inventory.py`, `docs/os/old-os-inventory.md`
- Test: `backend/tests/os/test_inventory.py`

**Interfaces:**
- Consumes: `graph(root)` from `backend/scripts/import_graph.py` (existing).
- Produces: `build_inventory(app_root: Path) -> list[InventoryRow]` where `InventoryRow` has `module: str`, `imported_by: list[str]`, `used_by_counsellor: bool` (any importer under `app.pai_c` or a router whose name starts with `counselor`), `fate: str = ""`; `render_markdown(rows) -> str`. Watched modules: `app.services.operator`, `app.routers.operator`, `app.capabilities*`, `app.plugins*`, `app.jobs*`, `app.research*`, `app.documents*`, `app.deadlines*`, `app.routers.escalations`, `app.tools.builtin.operator`, `app.tools.builtin.capabilities`.

- [ ] **Step 1: Write failing test** — `build_inventory(APP)` contains a row for `app.services.operator` whose `imported_by` includes `app.routers.operator`; `render_markdown` output has columns `Module | Imported by | Used by Counsellor | Fate (keep / read-only / retire)`.
- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: Implement**, run `python scripts/os_inventory.py > ../docs/os/old-os-inventory.md`.
- [ ] **Step 4: Tests pass.** Then both developers fill the Fate column together (one sitting); any module with `Used by Counsellor = yes` cannot be `retire` without the Counsellor lead's sign-off in the PR.
- [ ] **Step 5: Commit** `docs(os): old OS inventory`

---

### Task 5: CI, PR template, CODEOWNERS

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/pull_request_template.md`, `.github/CODEOWNERS`

**Interfaces:**
- Consumes: Tasks 1–3 commands.

- [ ] **Step 1: Write `ci.yml`** with job `os` on `pull_request` and `push` to `dev`/`main`: Python 3.12; service `postgres:16` (db `os_test`, user/pass `os_test`); env `OS_TEST_DATABASE_URL=postgresql://os_test:os_test@localhost:5432/os_test`; steps: `pip install -r backend/requirements.txt -r backend/requirements-dev.txt`; `cd backend && tach check`; `python scripts/check_alembic_heads.py`; `pytest tests/os -v`. Add job `legacy` running the existing `pytest` suite with `continue-on-error: true` (made blocking once it is green on CI twice in a row).
- [ ] **Step 2: Write the PR template** with the five sections from the reviewer guide: Spec link; What changed (2–3 sentences); Tests (added/changed + passing evidence); How to see it work (≤5 minutes); Rules touched (kernel / tool gateway / agent tools / data format / shared file: yes or no each).
- [ ] **Step 3: Write `CODEOWNERS`**: `/backend/app/os/ @DEV_A @DEV_B`; `/backend/tests/os/ @DEV_A @DEV_B`; shared files (`/backend/requirements*.txt`, `/backend/alembic/`, `/backend/alembic.ini`, `/docker-compose*.yml`, `/CLAUDE.md`, `/.github/`) owned by both OS developers and the Counsellor lead. Replace `@DEV_A @DEV_B` and the Counsellor handle with the handles supplied (Global Constraints).
- [ ] **Step 4: Verify** — open a draft PR containing a deliberate `from app.services import operator` in `backend/app/os/`; the `os` job fails on `tach check`. Remove it; the job passes. Then turn on "Require status checks: os" in branch protection.
- [ ] **Step 5: Commit** `ci: os job, PR template, CODEOWNERS`

---

### Task 6: Spike 3 core loop (throwaway)

**Files:**
- Create: `backend/spikes/__init__.py`, `backend/spikes/spike3/__init__.py`, `backend/spikes/spike3/schema.sql`, `backend/spikes/spike3/loop.py`, `backend/spikes/spike3/pages/*.txt` (5 excerpts), `backend/spikes/spike3/README.md`
- Test: `backend/tests/os/test_spike3_loop.py` (defines fixtures `conn` — psycopg connection to `pg_url` with `schema.sql` applied and tables truncated per test; `dbos_runtime` — configures DBOS, builds the agent with `TestModel` returning a valid quote, `DBOS.launch()`, `DBOS.destroy()` on teardown; `dbos_runtime_bad_quote` — same with an invalid quote; helpers `wait_done`, `wait_settled`, `result_count`, `task_status`, `failure_reason`, `model_calls`, `workflow_count`, `unmark_sent`, `run_concurrently`, `record_result_sql`)
- Add to `backend/tach.toml`: nothing (spikes are outside `app/`).

**Interfaces:**
- Consumes: `load_settings` (Task 1), `pg_url`/`fresh_db` fixtures (Task 3).
- Produces (all in `spikes/spike3/loop.py`):
  - Tables in schema `spike3` (`schema.sql`): `tasks(id text pk, status text check in ('pending','ready','running','done','failed'), attempt int, failure_reason text)`, `model_calls(id bigserial, task_id, attempt, at timestamptz)` (one row per model request, written by a counting wrapper), `enqueue_requests(task_id, attempt, sent bool, pk(task_id, attempt))`, `results(task_id, attempt, output jsonb, valid bool, pk(task_id, attempt))`, `step_runs(id bigserial, task_id, attempt, step text, at timestamptz)` (append-only, counts re-runs).
  - `class ProgrammeFact(BaseModel)`: `field: Literal["deadline", "tuition", "language_requirement"]`, `value: str`, `quote: str`; output validator: `quote` must be a substring of the input page text (raise `ModelRetry` otherwise).
  - `mark_ready(conn, task_id: str) -> None` — one transaction: status `ready`, `attempt += 1`, insert `enqueue_requests` row.
  - `enqueue_pending(conn) -> int` — for each unsent request: `with SetWorkflowID(f"{task_id}:{attempt}"): queue.enqueue(run_attempt, task_id, attempt)`; then mark sent. Returns count.
  - `reconcile(conn) -> dict` — re-enqueues `ready` tasks whose workflow ID is unknown to DBOS; applies results of `SUCCESS` workflows whose task is not `done`; returns counts.
  - `@DBOS.workflow() async def run_attempt(task_id: str, attempt: int) -> None` — steps: `load_page` → `extract` (DBOSAgent, model step config `StepConfig(retries_allowed=True, max_attempts=3)`) → `record_result` (`INSERT ... ON CONFLICT DO NOTHING`, writes a `step_runs` row first) → `complete_task` (status `done` if still `running`/`ready`). If output retries are exhausted (`UnexpectedModelBehavior`), the workflow sets status `failed`, `failure_reason='invalid_output'` and returns normally (the kernel decides what happens next, not a retry).
  - `build_agent(model) -> DBOSAgent` — `Agent(model, output_type=ProgrammeFact, retries={"tools": 0, "output": 2})`; OpenAI via `OpenAIChatModel(settings.model_cheap, provider=OpenAIProvider(openai_client=AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)))`; tests pass a `TestModel` whose `custom_output_args` is a `ProgrammeFact` dict.
  - DBOS config: `{"name": "pai-os-spike3", "system_database_url": pg_url, "dbos_system_schema": "dbos_test"}`.

- [ ] **Step 1: Write failing tests** (TestModel, real Postgres)

```python
def test_happy_path(dbos_runtime, conn):
    mark_ready(conn, "t1"); enqueue_pending(conn); wait_done(conn, "t1")
    assert result_count(conn, "t1") == 1 and task_status(conn, "t1") == "done"

def test_record_result_is_idempotent(conn):
    record_result_sql(conn, "t1", 1, OUTPUT); record_result_sql(conn, "t1", 1, OUTPUT)
    assert result_count(conn, "t1") == 1

def test_enqueue_twice_runs_once(dbos_runtime, conn):
    mark_ready(conn, "t2"); enqueue_pending(conn)
    unmark_sent(conn, "t2")              # simulate crash before marking sent
    enqueue_pending(conn); wait_done(conn, "t2")
    assert workflow_count("t2:1") == 1 and result_count(conn, "t2") == 1

def test_reconciler_and_enqueuer_race(dbos_runtime, conn):
    mark_ready(conn, "t3")
    run_concurrently(lambda: enqueue_pending(conn), lambda: reconcile(conn))
    wait_done(conn, "t3")
    assert workflow_count("t3:1") == 1 and result_count(conn, "t3") == 1

def test_invalid_quote_is_retried_then_fails(dbos_runtime_bad_quote, conn):
    # fixture builds the agent with TestModel(custom_output_args={"field": "deadline",
    #   "value": "15 July", "quote": "text that is not on the page"})
    mark_ready(conn, "t4"); enqueue_pending(conn); wait_settled(conn, "t4")
    assert task_status(conn, "t4") == "failed"
    assert failure_reason(conn, "t4") == "invalid_output"
    assert model_calls(conn, "t4") == 3   # first try + 2 output retries
```

- [ ] **Step 2: Run, verify failure** — `OS_TEST_DATABASE_URL=... pytest tests/os/test_spike3_loop.py -v` → FAIL.
- [ ] **Step 3: Implement `loop.py`** per Interfaces. Page text for tasks comes from 5 fixed excerpts copied from the Spike 1 programme sources (stored in `spikes/spike3/pages/*.txt`, quoting DAAD pages listed in the programme shortlist).
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** `spike(os): spike 3 core loop with idempotent steps`

---

### Task 7: Spike 3 chaos run and report

**Files:**
- Create: `backend/spikes/spike3/chaos.py`, `backend/spikes/spike3/worker.py`, `docs/os/spikes/spike3-report.md`
- Test: `backend/tests/os/test_spike3_chaos.py` (marker `chaos`; small run in CI)

**Interfaces:**
- Consumes: Task 6 functions.
- Produces: `run_chaos(tasks: int, workers: int, kill_every_s: float, model: Literal["test", "openai"], timeout_s: int) -> ChaosReport` with fields `tasks`, `done`, `failed`, `lost` (= tasks − done − failed), `duplicate_results` (rows beyond one per task/attempt; must be 0 by construction, measured anyway), `step_reruns` (from `step_runs`), `valid_outputs`, `model_calls`, `valid_rate`, `kills`, `elapsed_s`. `worker.py`: `main()` configures DBOS exactly as Task 6, builds the agent for the chosen model, calls `DBOS.launch()` and blocks. Workers are subprocesses `python -m spikes.spike3.worker --model {test|openai}` (each calls `DBOS.launch()` and polls the queue); the driver kills a random worker with SIGKILL every `kill_every_s` and starts a replacement; a reconciler runs every 5 s during the test (5 minutes in production; shortened for the spike).

- [ ] **Step 1: Write failing test** — `run_chaos(tasks=20, workers=3, kill_every_s=2, model="test", timeout_s=180)` → `lost == 0`, `duplicate_results == 0`, `kills >= 3`.
- [ ] **Step 2: Run, verify failure.**
- [ ] **Step 3: Implement `chaos.py` and `worker.py`.**
- [ ] **Step 4: Run** the test → PASS. Then the real pass-bar run on staging (or a laptop with Postgres 16): `python -m spikes.spike3.chaos --tasks 100 --workers 4 --kill-every 3 --model openai --timeout 1800` with `OS_OPENAI_API_KEY` set to the dev key.
- [ ] **Step 5: Write `spike3-report.md`**: the pass bar (100 runs with random worker kills: zero lost, zero duplicated; ≥99% valid structured outputs), the full `ChaosReport` numbers for the OpenAI run, cost from the OpenAI project's usage page, observed step re-runs, any failures and their cause, and a pass/fail verdict. If it fails: stop, fix, re-run; no Slice 1 work starts until the report says PASS and both developers sign it in the PR.
- [ ] **Step 6: Commit** `spike(os): spike 3 chaos run and report`

---

## Done when (Slice 0 gate, spec section 6)

- `pytest tests/os` green in CI; `tach check` green; `check_alembic_heads.py` green.
- CI demonstrably blocked a deliberate boundary violation (Task 5 Step 4).
- `spike3-report.md` says PASS against the pass bar, signed by both developers.
- Old-OS inventory has a fate for every row.
