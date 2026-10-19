# PAI OS Slice 1 (Plan with no AI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A test student gets a correct, dated plan and inbox for the Germany master's route, a worker
crash loses nothing, and two fake routes run unchanged.

**Architecture:** A pure compiler turns RouteContract + playbook YAML + Knowledge facts into a dated
`PlanDraft`. A kernel service is the only writer of plan state, and writes events and enqueue requests
in the same transaction. DBOS runs only task attempts (the Spike 3 loop), and scheduled jobs (the
reconciler, the deadline engine and reminders) send email through an idempotent outbox.

**Tech Stack:** Python 3.12, SQLAlchemy 2 Core (psycopg2), Alembic (`os` branch), PostgreSQL 16, DBOS
3.2.0, Pydantic 2.14, PyYAML (comes with dbos), FastAPI, Next.js 16 + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-18-pai-os-slice-1-design.md` (parent:
`docs/superpowers/specs/2026-10-12-pai-os-design.md`). The Germany content comes from
`docs/os/spikes/spike5-germany-playbook.md` (PR #38).

## Global Constraints

- Product code only in `backend/app/os/`. Tach: `app.os` depends on nothing, and root code may import
  `app.os`.
- No country names, currencies, document names or attestation bodies in `app/os/**/*.py`
  (invariant 12). Such terms live only in YAML.
- Every timestamp column is `DateTime(timezone=True)`. Every Python datetime is timezone-aware
  (`zoneinfo`). A deadline is end of day, `23:59:59`, in the anchor's timezone (invariant 13).
- Every table carries `tenant_id text not null`. Settings `OS_TENANT_ID` defaults to `"pai"`.
- Only `app/os/kernel/` writes `os_plans`, `os_tasks`, `os_task_edges` and `os_plan_revisions`
  (invariant 1).
- Every `task_type` has exactly one owner module (invariant 2).
- Retries (invariant 7): DBOS step config `retries_allowed=True, max_attempts=3`, and no other retry
  loops.
- Side effects (invariant 8): writes a re-run step could repeat use a unique key and
  `ON CONFLICT DO NOTHING`.
- DBOS: queue `"os"`, workflow name `"os.run_attempt"`, workflow ID `f"{task_id}:{attempt}"`,
  `application_version="os-1"`, system schema from `OS_DBOS_SYSTEM_SCHEMA` (default `"dbos"`; tests use
  `"dbos_os_test"`). The kernel side uses `DBOSClient` only. Workers need `OS_WORKER_ID`, and
  `"local"` is refused.
- Postgres tests use `OS_TEST_DATABASE_URL` and skip when it is unset. CI always sets it.
- Branches: `os/s1-tN-<name>`. Task 1 is cut from `pai-os`, and each later task from the previous
  task's branch (stacked, at the user's request). Push and open no PR until the earlier ones merge;
  rebase onto `pai-os` after each squash merge.
- Before every push, from `backend/`: `tach check`, `python scripts/check_alembic_heads.py` and
  `python -m pytest tests/os -v -rs`, all green, 0 skipped.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings made while planning

- **R-P1:** `anchor` supports only `{fact: <field>}`. Spec §4.1's `{task: ...}` example is covered by
  hard `depends_on` edges, because successors already constrain `latest_finish`.
- **R-P2:** Student tasks use generic types `student.provide`, `student.act`, `student.choose` and
  `student.approve`, owned by module `inbox`. Work types are `knowledge.confirm_fact` (owner
  `knowledge.manual`) and `system.milestone` (owner `milestone`, done as soon as it runs).
- **R-P3:** "Citations required" is a playbook flag, `require_citations: true`. That keeps the rule out
  of country-specific code. A task may use `citation_from_fact: <field>` instead (the Spike 5
  per-programme steps).
- **R-P4:** A fact with status ≠ `confirmed` may have an empty quote. A `confirmed` fact needs a
  non-empty quote and URL. Shortlist values are seeded `unconfirmed` with the note "lead from the
  developer shortlist; not re-read".

## Review Focus

1. A student completes the same inbox item twice (double tap): the second call returns the same 200,
   with no second transition and no 500 → Task 6 `test_complete_twice_is_noop`, Task 9
   `test_complete_inbox_twice_200`.
2. A deadline on a daylight-saving change day (2027-03-28, Europe/Berlin) is 23:59:59 local, with the
   right UTC offset → Task 5 `test_end_of_day_on_dst_change`.
3. A contract programme with no facts at all still gives a plan: its tasks are `blocked`
   (`fact_missing:deadline_close`) and a `confirm_fact` task exists → Task 5
   `test_programme_without_facts_blocks`, Task 9 `test_post_plan_unknown_programme_201`.
4. The same contract is posted twice at the same moment, giving exactly one plan (the unique
   constraint; the loser returns the existing plan) → Task 6 `test_concurrent_create_one_plan`.
5. A fact is corrected after some tasks have started: only unstarted tasks change dates, and the
   revision records the skipped ones → Task 8 `test_fact_change_keeps_started_tasks`.

---

### Task 1: Remove the Spike 3 code

**Files:**
- Delete: `backend/spikes/`, `backend/tests/os/test_spike3_chaos.py`,
  `backend/tests/os/test_spike3_loop.py`
- Modify: `backend/tests/os/conftest.py` (`fresh_db` drops and recreates `dbos_os_test` instead of
  `dbos_test` and `spike3`),
  `backend/pytest.ini` (`chaos` marker text: "OS runner crash test (worker subprocesses killed with
  SIGKILL); part of the default suite")
- Keep: `docs/os/spikes/spike3-report.md`

- [ ] **Step 1:** Delete the files. `grep -rn "spikes" backend/ --include=*.py --include=*.ini --include=*.toml` prints nothing.
- [ ] **Step 2:** Run the pre-push checks. Expected: `46 passed`, 0 skipped.
- [ ] **Step 3:** Commit `chore(os): remove Spike 3 code after the report passed`.

### Task 2: Tables, migration `os_0002`, settings, DB fixtures

**Files:**
- Create: `backend/app/os/models.py`, `backend/alembic/versions_os/os_0002_slice1_tables.py`,
  `backend/tests/os/test_models.py`
- Modify: `backend/app/os/settings.py`, `backend/tests/os/test_settings.py`,
  `backend/tests/os/conftest.py`

**Interfaces:**
- Produces:
  - `OsSettings` gains `tenant_id: str = "pai"` (`OS_TENANT_ID`), `admin_token: str | None`
    (`OS_ADMIN_TOKEN`), `email_sender: str = "log"` (`OS_EMAIL_SENDER`) and `worker_id: str | None`
    (`OS_WORKER_ID`).
  - `app/os/models.py`: SQLAlchemy Core `Table` objects on `OsBase.metadata`, named `plans`, `tasks`,
    `task_edges`, `plan_revisions`, `playbook_pins`, `enqueue_requests`, `task_attempts`, `events`,
    `modules`, `outbox`, `knowledge_facts`. Their table names are `os_<name>`, and their columns are
    exactly spec §4.10, §4.2 and §4.8. Every table has a `bigint identity` primary key `id` (except
    `modules`, whose key is `module`) and a `tenant_id`.
  - Unique: `os_plans(tenant_id, source, external_ref)`; `os_tasks(plan_id, instance_key)`;
    `os_enqueue_requests(task_id, attempt)`; `os_task_attempts(task_id, attempt)`;
    `os_outbox(tenant_id, idempotency_key)`;
    `os_knowledge_facts(tenant_id, scope, ref, field, intake_year)`;
    `os_plan_revisions(plan_id, number)`.
  - Check: `os_tasks.state` in the 10 spec states.
  - Fixtures in `conftest.py`:
    - `os_db(pg_url, fresh_db) -> str`, session-scoped: runs `run_alembic(["upgrade", "os@head"], pg_url)`
      and returns the URL.
    - `engine(os_db) -> Engine`, session-scoped.
    - `clean(engine)`, function-scoped: `TRUNCATE` every `os_*` table `RESTART IDENTITY CASCADE`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_datetime_column_is_timezone_aware():
    cols = [c for t in OsBase.metadata.tables.values() for c in t.columns if isinstance(c.type, DateTime)]
    assert cols and all(c.type.timezone for c in cols)

def test_every_table_has_tenant_id():
    assert all("tenant_id" in t.c for t in OsBase.metadata.tables.values())

def test_migration_matches_models(engine):
    with engine.connect() as conn:
        mc = MigrationContext.configure(conn, opts={"include_schemas": True, "include_name": include_name})
        assert compare_metadata(mc, OsBase.metadata) == []

def test_tenant_and_admin_settings():
    s = load_settings({"DATABASE_URL": "x", "OS_ADMIN_TOKEN": "t"})
    assert (s.tenant_id, s.admin_token, s.email_sender, s.worker_id) == ("pai", "t", "log", None)
```
(`include_name` is the filter from `alembic/env.py`: default schema + `os`. Compare only `os` tables:
filter the diff to entries whose table schema is `os`.)

- [ ] **Step 2:** `python -m pytest tests/os/test_models.py tests/os/test_settings.py -v` → FAIL (import errors).
- [ ] **Step 3:** Implement the settings fields, `models.py`, and `os_0002` (`down_revision = "os_0001"`,
  `op.create_table` per table; downgrade drops them in reverse). The migration must not import `app.os`
  (copy the definitions).
- [ ] **Step 4:** Tests → PASS. `alembic heads` lists `os_0002 (os) (head)`, and the heads check is green.
- [ ] **Step 5:** Commit `feat(os): slice 1 tables and migration os_0002`.

### Task 3: Playbook models and loader, plus the two fake playbooks

**Files:**
- Create: `backend/app/os/playbooks/__init__.py`, `models.py`, `loader.py`,
  `backend/tests/os/playbooks/ireland_master.v1.yaml`, `backend/tests/os/playbooks/pakistan_bs.v1.yaml`,
  `backend/tests/os/test_playbooks.py`

**Interfaces:**
- Produces (`app.os.playbooks`):
  - `Citation(source: str, url: AnyHttpUrl)`, `Dependency(key: str, hard: bool = True)`.
  - `Condition(fact: str, in_: list[str] | None = Field(None, alias="in"), present: bool | None = None)`,
    with exactly one of `in_` or `present`.
  - `Anchor(fact: str)`, and `LeadTime(days: int | None = None, constant: str | None = None)` with
    exactly one set.
  - `TaskTemplate`: `template_key`, `task_type`, `title`, `kind: Literal["work", "student"]`,
    `inbox_kind: Literal["provide", "approve", "act", "choose"] | None` (required if and only if
    `kind == "student"`), `depends_on: list[Dependency] = []`,
    `fan_out: Literal["none", "programme"] = "none"`, `condition: Condition | None`,
    `anchor: Anchor | None`, `lead_time: LeadTime | None`, `duration_days: int = Field(1, ge=0)`,
    `fallback: Literal["skip", "student"] = "skip"`, `protected: bool = False`,
    `citations: list[Citation] = []`, `citation_from_fact: str | None = None`.
  - `Constant(value: int | str, citations: list[Citation], estimate: bool = False)`.
  - `Route(origin: str, destination: str, level: str)`.
  - `Playbook`: `key`, `version: int`, `route`, `default_timezone`, `require_citations: bool = False`,
    `constants: dict[str, Constant] = {}`, `tasks: list[TaskTemplate]`. `extra="forbid"` on every
    model.
  - `class PlaybookError(ValueError)`.
  - `load_playbook(path: Path) -> Playbook` and `load_playbook_dir(dir: Path) -> dict[tuple[str, int], Playbook]`.
  - `select_playbook(books, origin, destination, level) -> Playbook`: the highest version for the
    route. Raises `PlaybookError("no playbook for <o>-><d> <level>")`.
- Fake playbooks:
  - `ireland_master.v1`: route `PK -> IE master`, 2 tasks (`apply`: student.act fan_out programme,
    anchor `deadline_close`; `visa`: student.act, depends on `apply`).
  - `pakistan_bs.v1`: route `PK -> PK bachelor`, tasks `entry_test` (student.act), `merit_list`
    (student.choose, depends on `entry_test`, fan_out programme, anchor `merit_list_date`), and no
    visa.

- [ ] **Step 1: Write the failing tests**

```python
def test_fake_playbooks_load():
    books = load_playbook_dir(FAKE_DIR)
    assert set(books) == {("ireland_master", 1), ("pakistan_bs", 1)}

@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["tasks"][1]["depends_on"].append({"key": "nope"}), "unknown dependency 'nope'"),
    (lambda d: d["tasks"][0].pop("inbox_kind"), "student task needs inbox_kind"),
    (lambda d: d["tasks"].append(dict(d["tasks"][0])), "duplicate template_key"),
    (lambda d: d.update(default_timezone="Mars/Base"), "unknown timezone"),
    (lambda d: d["tasks"][0].update(lead_time={"constant": "missing"}), "unknown constant 'missing'"),
    (lambda d: d.update(require_citations=True), "needs a citation"),
])
def test_invalid_playbook_rejected(tmp_path, mutate, msg): ...  # loads ireland yaml, mutates, writes, expects PlaybookError(match=msg)

def test_citation_from_fact_satisfies_requirement(tmp_path): ...  # require_citations=True and every task has citation_from_fact → loads

def test_select_playbook_highest_version(): ...  # adds a v2 copy → select returns version 2
```
- [ ] **Step 2:** `python -m pytest tests/os/test_playbooks.py -v` → FAIL.
- [ ] **Step 3:** Implement the models with the validators above. The loader wraps
  `ValidationError` and YAML errors as `PlaybookError` naming the file.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(os): playbook models and loader, fake routes`.

### Task 4: Knowledge port, SQL store, seed loader

**Files:**
- Create: `backend/app/os/knowledge/__init__.py`, `port.py`, `store.py`, `seed.py`,
  `backend/tests/os/test_knowledge.py`

**Interfaces:**
- Consumes: `models.knowledge_facts`, and the `engine` and `clean` fixtures (Task 2).
- Produces (`app.os.knowledge`):
  - `@dataclass(frozen=True) Fact`: `value: Any`, `quote: str`, `url: str`, `checked_at: datetime`,
    `intake_year: int`, `status: Literal["confirmed", "unconfirmed", "stale"]`,
    `conflict_note: str | None = None`, `id: int | None = None`. `__post_init__` raises `ValueError`
    when `status == "confirmed"` and the quote or URL is empty (R-P4).
  - `class KnowledgePort(Protocol)`:
    `programme_facts(refs, fields, intake_year) -> dict[tuple[str, str], Fact]` and
    `route_facts(route_key, fields, intake_year) -> dict[str, Fact]`.
  - `SqlKnowledge(engine, tenant_id)` implements the port, plus
    `upsert(scope: Literal["route", "programme"], ref: str, field: str, fact: Fact) -> int` (on
    conflict, update) and
    `confirm(fact_id, *, value, quote, url, status, conflict_note=None) -> Fact`.
  - `load_seed(path: Path, store: SqlKnowledge) -> int`. The YAML is
    `{intake_year, route_key, route: {field: fact}, programmes: {ref: {field: fact}}}`. It returns the
    row count, and running it again changes nothing.
  - **Date facts:** `value = {"date": "YYYY-MM-DD", "tz": "Area/City"}`, with `tz` optional.

- [ ] **Step 1: Write the failing tests**

```python
def test_confirmed_fact_needs_quote_and_url():
    with pytest.raises(ValueError, match="confirmed fact needs a quote and url"):
        Fact(value=1, quote="", url="", checked_at=NOW, intake_year=2027, status="confirmed")

def test_upsert_and_read(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-07-15"}, "q", "https://u", NOW, 2027, "confirmed"))
    assert kb.programme_facts(["p1"], ["deadline_close"], 2027)[("p1", "deadline_close")].value == {"date": "2027-07-15"}

def test_other_intake_year_not_returned(engine, clean): ...  # upsert year 2026 → empty result for 2027

def test_seed_is_idempotent(engine, clean, tmp_path):
    assert load_seed(SEED, kb) == load_seed(SEED, kb)  # same count; table row count unchanged

def test_confirm_updates_status(engine, clean): ...  # unconfirmed → confirm(..., status="confirmed") → read back confirmed
```
- [ ] **Step 2:** `python -m pytest tests/os/test_knowledge.py -v` → FAIL.
- [ ] **Step 3:** Implement. Use `insert(...).on_conflict_do_update` (postgresql dialect).
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(os): knowledge port, store and seed loader`.

### Task 5: Compiler (pure)

**Files:**
- Create: `backend/app/os/compiler/__init__.py`, `conditions.py`, `schedule.py`, `compile.py`,
  `backend/tests/os/test_compiler.py`

**Interfaces:**
- Consumes: `Playbook`, `TaskTemplate` (Task 3); `Fact` (Task 4); `RouteContract` (Slice 0).
- Produces (`app.os.compiler`):
  - `end_of_day(d: date, tz: str) -> datetime`: 23:59:59 local, aware.
  - `@dataclass(frozen=True) DraftTask`: `instance_key`, `template_key`, `task_type`, `kind`,
    `inbox_kind`, `programme_ref: str | None`, `title`,
    `depends_on: tuple[tuple[str, bool], ...]` (instance keys, hard), `duration_days`,
    `earliest_start: datetime`, `latest_start: datetime | None`, `latest_finish: datetime | None`,
    `due_tz: str`, `provisional: bool`, `estimated: bool` (true when its lead time or duration comes
    from a `Constant` with `estimate: true`), `blocked_reason: str | None`, `slack_days: int | None`,
    `critical: bool`, `citations: tuple[dict, ...]`, `fact_refs: tuple[tuple[str, str, str], ...]`
    (scope, ref, field).
  - `@dataclass(frozen=True) PlanDraft`: `playbook_key`, `playbook_version`,
    `tasks: tuple[DraftTask, ...]` (sorted by `instance_key`), `at_risk: bool`.
  - `class CompileError(ValueError)`.
  - `needed_fields(playbook) -> tuple[set[str], set[str]]`: the (route fields, programme fields) the
    playbook's conditions, anchors and `citation_from_fact` refer to.
  - `compile_plan(contract, playbook, route_facts: Mapping[str, Fact],
    programme_facts: Mapping[tuple[str, str], Fact], today: date,
    disabled_types: frozenset[str] = frozenset()) -> PlanDraft`.
  - A task whose `task_type` is in `disabled_types` applies its `fallback` (the parent's
    `module_disabled`): `skip` drops it, and its successors treat it as done. `student` turns it into a
    `student.act` task with the same key.
- **Instance keys:** `template_key`, or `template_key@programme_ref` for fan-out tasks.
  `confirm_fact` tasks are `confirm_fact@<ref>:<field>`, with `task_type="knowledge.confirm_fact"`,
  `kind="work"`, `ref = route_key` for route facts, and no dependencies.
- **Fact lookup:** a fan-out task reads programme facts for its programme. A non-fan-out task reads
  route facts.
- **Fact status:** a `confirmed` fact gives a firm date. Anything else gives `provisional=True` plus a
  `confirm_fact` task. A missing anchor fact gives `blocked_reason=f"fact_missing:{field}"` plus a
  `confirm_fact` task. A condition on a missing fact counts as true, plus `provisional`.
- **Scheduling algorithm** (not determined by the signature):

```text
order = topological order of hard+soft edges; a cycle → CompileError("cycle: a -> b -> a")
backward, in reverse order: cands = [end_of_day(anchor) - lead_days] if anchored and fact usable,
          + [s.latest_start for s in hard successors with latest_start]
          latest_finish = min(cands) or None; latest_start = latest_finish - duration_days days
forward, in order: earliest_start = max(start_of_day(today, tz), p.earliest_start + p.duration_days
          days for hard predecessors p)
slack_days = (latest_start - earliest_start).days when latest_start is set, else None
critical = slack_days == min(slack over tasks with slack); at_risk = any slack_days < 0
```
- `due_tz`: the anchor fact's `tz`, else `playbook.default_timezone`. `lead_days`: `lead_time.days`,
  or the constant's int value.

- [ ] **Step 1: Write the failing tests** (they use the fake Ireland playbook and in-test facts):

```python
def test_fan_out_and_dates():
    d = compile_plan(contract(["p1", "p2"]), IE, {}, facts(p1="2027-07-15", p2="2027-06-01"), date(2027, 3, 1))
    apply_p1 = task(d, "apply@p1")
    assert apply_p1.latest_finish == datetime(2027, 7, 15, 23, 59, 59, tzinfo=ZoneInfo("Europe/Dublin"))
    assert {t.instance_key for t in d.tasks} >= {"apply@p1", "apply@p2", "visa"}

def test_end_of_day_on_dst_change():
    eod = end_of_day(date(2027, 3, 28), "Europe/Berlin")
    assert (eod.hour, eod.minute, eod.second) == (23, 59, 59) and eod.utcoffset() == timedelta(hours=2)

def test_unconfirmed_fact_gives_provisional_and_confirm_task():
    d = compile_plan(contract(["p1"]), IE, {}, facts(p1="2027-07-15", status="unconfirmed"), TODAY)
    assert task(d, "apply@p1").provisional and task(d, "confirm_fact@p1:deadline_close").task_type == "knowledge.confirm_fact"

def test_programme_without_facts_blocks():
    d = compile_plan(contract(["p1"]), IE, {}, {}, TODAY)
    assert task(d, "apply@p1").blocked_reason == "fact_missing:deadline_close"
    assert task(d, "confirm_fact@p1:deadline_close")

def test_cycle_rejected(): ...       # playbook with a <-> b hard deps → CompileError(match="cycle")
def test_negative_slack_at_risk(): ...  # deadline before today → at_risk True and slack_days < 0
def test_condition_filters(): ...    # condition {fact: application_route, in: [direct]} with value "uni_assist" → task absent
def test_same_input_same_output(): ... # compile twice → equal drafts
def test_constant_lead_time(): ...   # lead_time {constant: x} with value 56 → latest_finish = deadline - 56 days
def test_disabled_type_fallback(): ... # disabled_types={"system.milestone"}: fallback skip → task absent, successor still scheduled; fallback student → student.act
```
- [ ] **Step 2:** `python -m pytest tests/os/test_compiler.py -v` → FAIL.
- [ ] **Step 3:** Implement `conditions.py` (`evaluate(cond, fact) -> bool | None`), `schedule.py`
  (`end_of_day`, `start_of_day`, `schedule(tasks, today, tz)`), and `compile.py`. No database, clock or
  randomness.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(os): plan compiler with backward scheduling`.

### Task 6: Kernel, state machine, revisions

**Files:**
- Create: `backend/app/os/kernel/__init__.py`, `states.py`, `kernel.py`, `revisions.py`,
  `backend/tests/os/test_states.py`, `backend/tests/os/test_kernel.py`,
  `backend/tests/os/test_invariants.py`

**Interfaces:**
- Consumes: `PlanDraft`, `DraftTask` (Task 5); `models.*` (Task 2); `RouteContract`.
- Produces (`app.os.kernel`):
  - `class TaskState(StrEnum)`, with the 10 states. `ALLOWED: Mapping[TaskState, frozenset[TaskState]]`
    is exactly spec §4.4. `TERMINAL = {done, skipped, cancelled}`. `class IllegalTransition(ValueError)`.
    `check_transition(frm, to) -> None`.
  - `@dataclass(frozen=True) PlanRef(plan_id: int, revision: int, created: bool)`.
  - `@dataclass(frozen=True) Outcome`: `status: Literal["done", "failed", "input_missing",
    "needs_review"]`, `result: dict = {}`, `reason: str | None = None`.
  - `Kernel(engine, tenant_id: str, clock: Callable[[], datetime])`, with these methods, each running
    in **one transaction**:
    - `create_plan(contract, draft) -> PlanRef`: identity is (tenant, source, external_ref), compared by
      `contract_sha256` of the canonical JSON (`json.dumps(model_dump(mode="json"), sort_keys=True)`).
      Same content returns `created=False`. Different content calls `revise`. Losing the unique-key
      race returns the winner's plan.
    - `revise(plan_id, cause: str, draft) -> int` (the new revision number) and
      `upgrade_playbook(plan_id, draft) -> int` (revise with cause `playbook_upgrade:<key>@<v>`, then
      update the pin).
    - `mark_running(task_id, attempt) -> bool` and `apply_result(task_id, attempt, outcome) -> None`
      (stale attempts are ignored).
    - `complete_student_task(task_id, student_ref, payload: dict) -> bool` (False if already done,
      PermissionError for the wrong student) and `complete_review(task_id, result: dict) -> None`.
    - `retry(task_id) -> int` (the new attempt).
  - After every call, `_promote(conn, plan_id)` moves `pending` tasks whose hard dependencies are all
    in `done` or `skipped` to `ready`. Student tasks then go straight to `waiting_student`, and work
    tasks get an `os_enqueue_requests` row. Tasks with `blocked_reason` go to `blocked` instead.
  - **Events** (`os_events.type`): `plan_created`, `plan_revised`, `task_state` (payload from/to),
    `slack_low` (when `draft.at_risk`), and `plan_updated_notice`.
  - **Revision diff** (`revisions.diff(old_tasks, draft) -> RevisionDiff(added, removed, changed,
    skipped_started)`):
    - A task is *started* when its state is not in {pending, ready, blocked}.
    - Removed or changed tasks are applied only if not started. Started ones are recorded in
      `skipped_started`.
    - `protected` tasks are never removed.
    - A non-empty diff adds the student task `plan_updated@r<n>` (`student.act`, inbox_kind `act`).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("frm,to", ALL_PAIRS)  # every (state, state) pair
def test_transition_table(frm, to):
    if to in ALLOWED[frm]: check_transition(frm, to)
    else: pytest.raises(IllegalTransition, check_transition, frm, to)

def test_create_plan_writes_tasks_events_and_requests(engine, clean): ...  # counts match draft; ready work tasks have enqueue rows; revision 1
def test_create_twice_same_content_is_noop(engine, clean): ...   # second PlanRef.created is False, same plan_id, still 1 revision
def test_changed_contract_creates_revision(engine, clean): ...   # revision 2, one plan row
def test_concurrent_create_one_plan(engine, clean): ...          # two threads create_plan same contract → one os_plans row, both return same plan_id
def test_complete_twice_is_noop(engine, clean): ...              # first True, second False; one task_state event
def test_wrong_student_cannot_complete(engine, clean): ...       # PermissionError
def test_rollback_leaves_nothing(engine, clean): ...             # monkeypatch event insert to raise → no plan/task/request rows
def test_upgrade_keeps_started_tasks(engine, clean): ...         # task A running; v2 changes A and adds B → A unchanged, B inserted, diff.skipped_started == ["A"]
def test_dependency_done_promotes_successor(engine, clean): ...  # complete apply → visa becomes waiting_student
```
`tests/os/test_invariants.py`:
```python
def test_only_kernel_writes_plan_tables(): ...   # AST/regex over app/os/**/*.py outside kernel/: no insert/update/delete on plans, tasks, task_edges, plan_revisions
def test_no_country_terms_in_python(): ...       # deny-list (country names and ISO codes from the playbooks, "uni-assist", "HEC", "EUR", "PKR") not in app/os/**/*.py
```
- [ ] **Step 2:** `python -m pytest tests/os/test_states.py tests/os/test_kernel.py tests/os/test_invariants.py -v` → FAIL.
- [ ] **Step 3:** Implement. Concurrency: `INSERT ... ON CONFLICT (tenant_id, source, external_ref) DO
  NOTHING RETURNING id`; if nothing is returned, select the existing row. Lock the plan row
  (`SELECT ... FOR UPDATE`) in `revise`, `apply_result` and `complete_*`.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(os): kernel, task states and plan revisions`.

### Task 7: Runner (registry, enqueue, reconcile, DBOS workflow, worker), plus the crash test

**Files:**
- Create: `backend/app/os/runner/__init__.py`, `registry.py`, `modules.py`, `enqueue.py`,
  `reconcile.py`, `workflow.py`, `worker.py`, `backend/tests/os/runner_helpers.py`,
  `backend/tests/os/test_runner.py`, `backend/tests/os/test_crash.py`

**Interfaces:**
- Consumes: `Kernel`, `Outcome` (Task 6); settings (Task 2); playbooks (Task 3).
- Produces (`app.os.runner`):
  - `@dataclass(frozen=True) TaskContext(task_id, attempt, task_type, plan_id, programme_ref, payload: dict)`.
  - `@dataclass(frozen=True) Module(name: str, owns: frozenset[str], handler: Callable[[TaskContext], Outcome] | None)`
    (`None` means student-owned and never executed).
  - `Registry`: `register(m)` raises `ValueError("task_type '<t>' already owned by '<m>'")`;
    `owner(task_type) -> Module` raises `KeyError`; `validate(playbooks)` raises `ValueError` listing
    unowned types.
  - `default_registry() -> Registry` registers `inbox` (the 4 student types, no handler), `milestone`
    (`system.milestone`, returns done) and `knowledge.manual` (`knowledge.confirm_fact`, returns
    `needs_review`; Task 8 replaces the handler).
  - `dbos_config(settings, executor_id: str) -> DBOSConfig`: name `"pai-os"`, version `"os-1"`. It
    raises `ValueError` when `executor_id` is falsy or `"local"`.
  - `register_workflow(engine, settings, registry, kernel) -> None` registers `os.run_attempt`
    (steps `os.load`, `os.handle` with retry config, and `os.apply`) and queue `"os"` with
    `worker_concurrency=4`. It must be called before `DBOS.launch()`.
  - `enqueue_pending(engine, client: DBOSClient) -> int` uses the client with app version `"os-1"`
    and "return-existing" reuse, then marks requests sent.
  - `reconcile(engine, client, kernel) -> dict[str, int]` with keys `reenqueued`, `present` and
    `failed_workflows`, and the Spike 3 semantics (ERROR, CANCELLED and MAX_RECOVERY_ATTEMPTS_EXCEEDED
    → `kernel.apply_result(..., Outcome("failed", reason="workflow_error"))`).
  - `worker.main(argv=None) -> int` reads settings, refuses a missing `OS_WORKER_ID`, and loads extra
    modules from `OS_EXTRA_MODULES` (comma-separated `pkg.mod:NAME`, test use only). It registers, then
    launches, then blocks until SIGTERM.
  - The scheduled `os.reconcile` runs every 5 minutes (`@DBOS.scheduled("*/5 * * * *")`). Task 8 adds
    the hourly jobs.
- `conftest.dbos_worker(engine)` (function-scoped) launches DBOS in-process with `default_registry()`
  plus `SLEEP_MODULE`, schema `dbos_os_test`, executor ID `"test-w0"`, and yields
  `(client: DBOSClient, kernel: Kernel)`. On teardown it runs `DBOS.destroy(destroy_registry=True)`.
- `runner_helpers.SLEEP_MODULE`: owns `test.sleep` and sleeps `payload["seconds"]` (default 1.5)
  inside its step, then returns done. It writes one row per execution to a test table
  `os_test_runs(task_id, attempt, worker)` with `worker` from `OS_WORKER_ID`.

- [ ] **Step 1: Write the failing tests**

```python
def test_double_owner_rejected(): ...                  # ValueError(match="already owned")
def test_unowned_playbook_type_rejected(): ...         # IE playbook + registry without inbox → ValueError listing student.act
def test_local_executor_id_refused(): ...              # dbos_config(s, "local") → ValueError
def test_milestone_runs_to_done(dbos_worker, engine, clean): ...       # in-process DBOS (schema dbos_os_test); plan with a milestone; enqueue_pending → task done
def test_enqueue_twice_runs_once(dbos_worker, engine, clean): ...      # mark request unsent and enqueue again → one workflow, one attempt row
def test_reconcile_reenqueues_lost_request(dbos_worker, engine, clean): ...  # ready task, no workflow → reenqueued == 1, then done
def test_reconcile_fails_errored_workflow(dbos_worker, engine, clean): ...   # handler raises past retries → failed, reason workflow_error
```
`test_crash.py` (marker `chaos`): 20 `test.sleep` tasks with 3 worker subprocesses
(`python -m app.os.runner.worker` with `OS_WORKER_ID=w<i>` and
`OS_EXTRA_MODULES=tests.os.runner_helpers:SLEEP_MODULE`). It SIGKILLs a random worker every 2 s and
restarts it with the same ID, with a 180 s timeout. Assert: every task is `done`; the os_test_runs
re-runs for an attempt happen only after a kill of the earlier row's worker; at least 3 kills;
`os_task_attempts` has one row per task.

- [ ] **Step 2:** `python -m pytest tests/os/test_runner.py tests/os/test_crash.py -v` → FAIL.
- [ ] **Step 3:** Implement. Follow the Slice 0 handoff §6 DBOS lessons. Build the registry before
  `DBOS.launch()`, and call `DBOS.destroy(destroy_registry=True)` between test fixtures. Workers exit
  when the parent PID changes, as in Spike 3.
- [ ] **Step 4:** Tests → PASS, and run the crash test 3 times in a row.
- [ ] **Step 5:** Commit `feat(os): task runner on DBOS with crash test`.

### Task 8: Deadline engine, reminders, `knowledge.manual`, outbox

**Files:**
- Create: `backend/app/os/workers/__init__.py`, `deadline_engine.py`, `reminders.py`, `manual.py`,
  `backend/app/os/outbox/__init__.py`, `outbox.py`, `senders.py`, `backend/app/os/service.py`,
  `backend/tests/os/test_outbox.py`, `backend/tests/os/test_workers.py`
- Modify: `backend/app/os/runner/modules.py` (the `knowledge.manual` handler) and
  `backend/app/os/runner/worker.py` (the hourly schedules)

**Interfaces:**
- Consumes: `Kernel` (Task 6), `compile_plan`, `needed_fields` (Task 5), `SqlKnowledge` (Task 4),
  `load_playbook_dir`, `select_playbook` (Task 3).
- Produces:
  - `service.PlanService(engine, settings, kernel, knowledge, playbooks, today: Callable[[], date])`
    with `start_plan(contract) -> PlanRef` (select → facts → compile → `kernel.create_plan`) and
    `recompile(plan_id, cause) -> int | None` (None when the draft is unchanged). Both pass the
    `task_type`s of modules with `os_modules.enabled = false` as `disabled_types`.
  - `outbox.Outbox(engine, tenant_id)`:
    `add(key, channel, recipient, template, payload) -> bool` (False when the key exists) and
    `deliver(sender, limit=100) -> int`.
  - `senders.Sender(Protocol).send(msg: OutboxMessage) -> None`; `LogSender` logs at INFO and writes
    an `email_logged` event; `make_sender(settings) -> Sender` (only `"log"` in Slice 1, otherwise
    `ValueError`).
  - `reminders.reminder_slot(now: datetime, due_at: datetime, slack_days: int | None) -> str | None`,
    a pure function using the cadence below.
  - `reminders.run_reminders(engine, outbox, now) -> int`: for each `waiting_student` task with
    `due_at`, add key `reminder:{task_id}:{slot}` with recipient `student_ref` and template
    `inbox_reminder`.
  - `deadline_engine.run(service, engine) -> int`: recompile every active plan with cause
    `deadline_recompute`, returning the number of plans revised.
  - `manual.confirm_fact(service, knowledge, kernel, fact_id, **fields) -> None`: updates the fact,
    completes the matching open `confirm_fact` task (`complete_review`), and calls `recompile` for
    plans that reference the fact, with cause `fact_changed`.
  - Worker schedules: `os.deadline_engine` and `os.reminders` hourly (`"0 * * * *"`), plus
    `os.deliver_outbox` every minute.
- **Cadence** (the parent spec's §3.2 inbox table; `left = due_at - now`):

```text
left <= 0            -> f"esc:{now:%Y-%m-%d}"  (also emits event "escalate")
left < 48 h          -> f"h12:{now:%Y-%m-%d}:{now.hour // 12}"
slack 2..7 days      -> f"d:{now:%Y-%m-%d}"
slack 7..14 days     -> f"d3:{now.toordinal() // 3}"
slack > 14 days      -> f"w:{now:%G-%V}"
slack None           -> None
```

- [ ] **Step 1: Write the failing tests**

```python
def test_same_key_sends_once(engine, clean): ...           # add twice → second False; deliver → LogSender called once
def test_reminder_slots(): ...                              # table of (now, due_at, slack) → expected slot strings above
def test_reminders_rerun_same_slot_no_new_rows(engine, clean): ...
def test_fact_change_keeps_started_tasks(engine, clean): ... # Review Focus 5: one task running, fact corrected → only unstarted tasks re-dated; revision diff.skipped_started lists the running one
def test_confirm_fact_completes_task_and_firms_date(engine, clean): ...  # unconfirmed deadline → confirm → task provisional False, confirm_fact task done
def test_deadline_engine_noop_when_unchanged(engine, clean): ...         # returns 0, no new revision
def test_module_disabled_applies_fallback(engine, clean): ...           # disable "milestone" in os_modules → recompile gives a revision without the milestone task
```
- [ ] **Step 2:** `python -m pytest tests/os/test_outbox.py tests/os/test_workers.py -v` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat(os): deadline engine, reminders, manual fact confirm, outbox`.

### Task 9: API and auth port; mount in `app/main.py` (shared file)

**Files:**
- Create: `backend/app/os/api/__init__.py`, `deps.py`, `router.py`, `backend/tests/os/test_api.py`
- Modify: `backend/app/main.py`, which mounts the router only when `OS_ENABLED`, and overrides
  `current_student_ref` with the Counsellor's existing signed-in-user dependency (find the one that
  `app/routers/deadlines.py` uses) → `str(user.id)`.

**Interfaces:**
- Consumes: `PlanService` (Task 8), `Kernel` (Task 6), `manual.confirm_fact` (Task 8).
- Produces:
  - `deps.current_student_ref() -> str`. The default raises 401; `main.py` overrides it.
  - `deps.require_admin(authorization: str = Header(...))` checks `Bearer <OS_ADMIN_TOKEN>` with
    `hmac.compare_digest`, and gives 401 if unset or wrong.
  - `router.build_router(get_services: Callable[[], Services]) -> APIRouter`. The endpoints are spec
    §4.9, with the prefix added by the caller (`/v1/os`).
  - Responses: `PlanOut(plan_id, revision, status, tasks: list[TaskOut])`;
    `TaskOut(id, instance_key, title, kind, inbox_kind, state, due_at, due_tz, provisional, estimated,
    slack_days, critical, citations)`; `InboxOut(items: list[TaskOut])`, sorted by `due_at`, nulls
    last.

- [ ] **Step 1: Write the failing tests** (FastAPI `TestClient` on an app built from `build_router`
  with test overrides):

```python
def test_post_plan_requires_admin_token(api): assert api.post("/v1/os/plans", json=C).status_code == 401
def test_post_plan_invalid_contract_422(api_admin): assert api_admin.post("/v1/os/plans", json={**C, "origin_country": "PAK"}).status_code == 422
def test_post_plan_idempotent(api_admin): ...         # 201 then 200 with the same plan_id
def test_post_plan_unknown_programme_201(api_admin): ...  # Review Focus 3: tasks blocked with fact_missing
def test_student_sees_only_own_inbox(api_student): ... # other student's items absent
def test_complete_inbox_twice_200(api_student): ...   # Review Focus 1
def test_confirm_fact_admin_only(api_student, api_admin): ...
def test_router_not_mounted_when_disabled(): ...       # app from main with OS_ENABLED unset → /v1/os/plans 404
```
- [ ] **Step 2:** `python -m pytest tests/os/test_api.py -v` → FAIL.
- [ ] **Step 3:** Implement. The `main.py` change is the only shared-file edit on `pai-os`. Note in
  the commit that it needs a Counsellor reviewer.
- [ ] **Step 4:** Tests → PASS, and `python -m pytest tests -q -x --ignore=tests/os` (the legacy
  suite) is still green.
- [ ] **Step 5:** Commit `feat(os): plan and inbox API behind OS_ENABLED`.

### Task 10: Germany playbook v1, seed, golden test student

**Files:**
- Create: `backend/app/os/playbooks/germany_master.v1.yaml`,
  `backend/app/os/knowledge/seed/germany_ws2027.yaml`, `backend/tests/os/golden/test_student_plan.json`,
  `backend/tests/os/test_golden.py`

**Interfaces:**
- Consumes: everything above.
- **Playbook content:** the Spike 5 phases A–D, `require_citations: true`, and
  `default_timezone: Europe/Berlin`. Each step's `citations` are the Spike 5 source IDs and URLs.
  The template keys are, in order:
  - Phase A: `choose_programmes` (choose), `hec_attestation`, `school_certificates`,
    `min_passing_grade_letter`, `grading_system_doc` (provide), `english_test` (act),
    `admission_test` (act, fan-out, condition `{fact: admission_test, present: true}`,
    `citation_from_fact`), `application_documents` (provide, fan-out, `citation_from_fact:
    required_documents`).
  - Phase B: `uni_assist_apply` (act, fan-out, condition
    `{fact: application_route, in: [uni_assist, uni_assist_vpd]}`, anchor `deadline_close`, lead
    constant `uni_assist_lead_days: 56`, which is S6 and an estimate), `direct_apply` (act, fan-out,
    condition `in: [direct, uni_assist_vpd]`, anchor `deadline_close`, `citation_from_fact:
    portal_url`), `applications_submitted` (milestone), `admission_result` (choose, fan-out,
    `citation_from_fact: decision_date`).
  - Phase C: `blocked_account`, `travel_insurance`, `visa_apply` (act, anchor `visa_target_date`
    route fact, `duration_days` from constant `visa_processing_days`, which is S11 and an estimate).
  - Phase D: `register_address`, `health_insurance`, `enrol` (`citation_from_fact:
    enrolment_deadline`), `residence_permit`.
  - Dependencies follow Spike 5's "Depends on" lines.
- **Seed:** route facts from Spike 5 (all non-procedural amounts `unconfirmed`, `visa_target_date`
  absent, so it blocks with a confirm task). Programme facts for shortlist rows 2, 5 and 6 (TU Chemnitz
  Embedded Systems, OVGU EEIT, BTU AI) with `deadline_close`, `application_route` and
  `english_requirement`, all `unconfirmed` (R-P4).
- **Test student:** `student_ref="test-student-1"`, PK → DE master, those 3 programmes, WS 2027,
  today `2027-02-01`.

- [ ] **Step 1: Write the failing tests**

```python
def test_germany_playbook_loads_with_registry(): ...   # load + default_registry().validate → no error
def test_golden_test_student(engine, clean):
    ref = service.start_plan(TEST_STUDENT)
    assert normalised(plan_json(ref.plan_id)) == json.loads(GOLDEN.read_text())
def test_fake_routes_run_unchanged(engine, clean, dbos_worker): ...  # both fake playbooks start_plan + complete all student tasks → plan done; no app/os change needed
```
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3:** Write the YAML. Generate the golden file once with `UPDATE_GOLDEN=1`, **read it** and
  check its dates by hand against the seed (end of day Berlin, 56 days before the deadline for
  uni-assist), then commit it.
- [ ] **Step 4:** Tests → PASS, plus the whole suite.
- [ ] **Step 5:** Commit `feat(os): Germany master playbook v1, seed and golden test student`.

### Task 11: Inbox page (frontend); worker service and dependencies (shared-file PR to `dev`)

**Files:**
- Create: `frontend/app/os/inbox/page.tsx`, `frontend/components/os/inbox-list.tsx`,
  `frontend/lib/os-api.ts`, `frontend/components/os/inbox-list.test.tsx`
- Modify: `frontend/lib/config.ts` (`export const OS_UI_ENABLED = process.env.NEXT_PUBLIC_OS_ENABLED === 'true';`)
- Shared-file PR to `dev`, separately: `docker-compose.prod.yml` adds service `os-worker`
  (`python -m app.os.runner.worker`, `OS_WORKER_ID=os-worker-1`, same image as `worker`); the backend
  env gains `OS_ENABLED`, `OS_ADMIN_TOKEN` and `OS_EMAIL_SENDER=log`; `backend/requirements.txt` adds
  `pyyaml>=6` and `tzdata` explicitly.

**Interfaces:**
- Consumes: `GET /v1/os/inbox` and `POST /v1/os/inbox/{id}/complete` (Task 9), called with the same
  auth as `frontend/lib/api.ts`.
- Produces: `InboxList({ items, onComplete })`, a pure component that groups items into
  `Overdue` / `This week` / `Later` relative to a `now` prop.

- [ ] **Step 1: Write the failing test** (Vitest + React Testing Library, if the repo has it;
  otherwise test the pure `groupItems(items, now)` function):

```ts
it('groups by due date and shows labels and sources', () => {
  // overdue item, item due in 3 days (provisional), item without due_at
  // expect headings Overdue / This week / Later in order; "provisional" label; source link href = citation url; due shows "(Berlin)"
});
```
- [ ] **Step 2:** `cd frontend && npx vitest run components/os` → FAIL.
- [ ] **Step 3:** Implement. Mobile-first, it works at 360 px, and it renders `null` plus a redirect
  when `!OS_UI_ENABLED`.
- [ ] **Step 4:** Tests → PASS, and `npm run build` succeeds.
- [ ] **Step 5:** Commit `feat(os): student inbox page behind NEXT_PUBLIC_OS_ENABLED`. Then the
  separate `dev` branch `chore/os-worker-compose` for the shared files.

---

## Done when (Slice 1 gate, spec §6)

- `test_golden_test_student` passes: a correct dated plan and inbox.
- `test_crash.py` passes 3 runs in a row: a crash loses nothing.
- `test_fake_routes_run_unchanged` passes: the fake routes run unchanged.
- `tach check`, the heads check and `pytest tests/os` are green in CI. The legacy suite is green.
