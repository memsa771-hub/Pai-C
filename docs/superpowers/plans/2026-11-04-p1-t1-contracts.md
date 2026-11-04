# P1-T1: contracts v2, fake intermediate route, flags — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the P1 contracts (v2 beside the frozen v1 files), a fake PK intermediate test route, and the off-by-default connection flags with an owner switch, without changing any behaviour.

**Architecture:** New Pydantic models in `backend/app/os/contracts/` with committed JSON schemas and samples, frozen by tests exactly like v1. Flags are plain settings in `backend/app/config.py`; one helper `part_on()` combines a flag with the OS `counsellor` module switch read through the bridge. Nothing calls the new contracts or flags yet (T2 onward).

**Tech Stack:** Python 3.13, Pydantic v2, SQLAlchemy Core (OS), pytest (legacy suite on SQLite; `tests/os` on Postgres).

**Spec:** `docs/superpowers/specs/2026-11-04-p1-connection-core-design.md` (§3.9, P1-D8, P1-D9, P1-D10, P1-D12; §5 row T1). Master: `docs/superpowers/specs/2026-11-03-pai-connect-design.md` §9.1.

## Global Constraints

- v1 files never change: `decision_record.py`, `route_contract.py`, `escalation.py`, `plan_summary.py`, `programme_list.py` and their `*.v1.schema.json` (tests/os/contracts/test_frozen.py).
- Every contract: `ConfigDict(extra="forbid", frozen=True, populate_by_name=True)`, a `schema_` field aliased `schema` with a `Literal` constant `pai.<name>.v<N>`, codes and IDs only. The only free text allowed is a step `title` from the playbook (P1-D12) and the escalation `note` (fixed sentence, as v1).
- No country, institution, exam or qualification names in `backend/app/os` Python (R-58; `tests/os/test_invariants.py`). Fake routes live in `backend/tests/os/`.
- Flags default off. With every flag off, behaviour is unchanged.
- Tag new tests `@pytest.mark.req("R-xx")`; set `built: true` only for R-41 in `docs/requirements/connection.yaml` (the only R-ID this task completes).
- Run `tach check` and `pytest tests/os` before pushing OS code. Never run `tests/os` and the legacy suite at the same time (shared Postgres).
- Commit messages end with the session's attribution lines.

## Review Focus

1. A `withdrawn` decision with no places and no intake must validate; a `chosen` one with `os_supported=true` and no places must fail. → Task 1 tests.
2. Duplicate places or ranks not 1..n must fail in every contract that carries places (decision v2, choice_request). → Tasks 1 and 3 tests.
3. `level: "intermediate"` must be accepted by v2 and still rejected by v1. → Task 1 test.
4. `part_on()` must be false when the OS is not mounted (legacy suite, no OS DB) even if the flag is on. → Task 5 test.
5. Adding a fake playbook must not break tests that list every route; an exact-set assertion is extended, never loosened. → Task 4 step.

---

### Task 1: `decision_record.v2` and `route_contract.v2`

**Files:**
- Create: `backend/app/os/contracts/route_contract_v2.py`, `backend/app/os/contracts/route_contract.v2.schema.json`
- Create: `backend/app/os/contracts/decision_record_v2.py`, `backend/app/os/contracts/decision_record.v2.schema.json`
- Create: `backend/tests/os/contracts/test_contracts_v2.py`

**Interfaces:**
- Produces (`route_contract_v2.py`): `Level = Literal["intermediate", "foundation", "bachelor", "master", "phd"]`; `class RouteContractV2` = v1 `RouteContract` fields with `contract_version: Literal["2"]` and `level: Level`; property `dedupe_key -> str` (`f"{source}:{external_ref}:{contract_version}"`). Reuse `ProgrammeChoice` and `IntakeRef` imported from `route_contract.py`.
- Produces (`decision_record_v2.py`): `class DecisionRecordV2` with fields: `schema_` (`"pai.decision_record.v2"`), `decision_id`, `journey_id`, `student_ref` (min_length 1), `decision_version: int` (ge 1), `status: Literal["chosen", "withdrawn"]`, `chosen_at: AwareDatetime`, `authorized_at: AwareDatetime | None = None`, `guardian_required: bool = False`, `guardian_authorized_at: AwareDatetime | None = None`, `origin_country`, `destination_country`, `nationality: str | None = None` (ISO-2 via v1's `iso_country`), `level: Level`, `path_ref: str | None = None`, `os_supported: bool`, `target_intake: IntakeRef | None = None`, `programmes: list[ProgrammeChoice] = []` (max 5). Property `external_ref` (same format as v1). Method `to_route_contract() -> RouteContractV2` (raises `ValueError` when `status == "withdrawn"` or `os_supported` is false).

- [ ] **Step 1: Write the failing tests** in `test_contracts_v2.py` (module mark `pytestmark = pytest.mark.req("R-41")`), with a helper `export_v2(**over)` built from the v1 test helper's values plus `schema="pai.decision_record.v2"`, `decision_version=1`, `status="chosen"`, `os_supported=True`:
  - `test_v2_accepts_intermediate_v1_rejects_it`: `DecisionRecordV2(level="intermediate")` validates; `DecisionRecordV1.model_validate({...v1 export, "level": "intermediate"})` raises `ValidationError`.
  - `test_withdrawn_needs_no_places_or_intake`: `status="withdrawn", programmes=[], target_intake=None` validates; `to_route_contract()` raises `ValueError`.
  - `test_chosen_supported_needs_places_and_intake`: `programmes=[]` raises; `target_intake=None` raises.
  - `test_chosen_unsupported_allows_no_places`: `os_supported=False, programmes=[]` validates.
  - `test_places_unique_and_ranked`: duplicate ref raises; ranks `[1, 3]` raises; six places raise.
  - `test_version_starts_at_one`: `decision_version=0` raises.
  - `test_route_contract_v2_from_decision`: `to_route_contract()` gives `contract_version == "2"`, `source == "counsellor"`, `level == "intermediate"` for an intermediate export, `external_ref == "j-1:PK:intermediate"` when destination is PK.
  - `test_extra_fields_forbidden`: an unknown key raises.

- [ ] **Step 2: Run them to see them fail**
  Run (from `backend/`): `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider tests/os/contracts/test_contracts_v2.py`
  Expected: errors importing `route_contract_v2` / `decision_record_v2`.

- [ ] **Step 3: Implement both modules.** Validators in `DecisionRecordV2` (`model_validator(mode="after")`): places unique and ranked 1..n (as v1); if `status == "chosen"` and `os_supported`, require `programmes` (≥ 1) and `target_intake`. Docstrings say: P1 spec §3.9, v1 untouched; `guardian_required` is decided by the Counsellor (P1-D10).

- [ ] **Step 4: Write the schema files** — add both models to `backend/scripts/export_os_schemas.py` (Task 3 Step 4 extends the same table; write it as `{"<file stem>": Model}` e.g. `"decision_record.v2": DecisionRecordV2`, and keep writing the four v1 files with identical content) and run `python scripts/export_os_schemas.py`. Then `git diff --stat backend/app/os/contracts/*.v1.schema.json` must be empty.

- [ ] **Step 5: Run the tests** — same command. Expected: PASS. Also `pytest -q tests/os/contracts` PASS (v1 frozen tests untouched).

- [ ] **Step 6: Commit** `feat(os): decision_record.v2 and route_contract.v2 (R-41)`.

### Task 2: `escalation.v2` and `plan_view.v1`

**Files:**
- Create: `backend/app/os/contracts/escalation_v2.py`, `escalation.v2.schema.json`
- Create: `backend/app/os/contracts/plan_view.py`, `plan_view.v1.schema.json`
- Modify: `backend/tests/os/contracts/test_contracts_v2.py`

**Interfaces:**
- Consumes: `Level`, `IntakeRef` (Task 1 / v1).
- Produces: `EscalationV2` = v1 `EscalationV1` fields (same five reasons, same note limits) with schema `"pai.escalation.v2"` plus `decision_version: int | None` (ge 1).
- Produces (`plan_view.py`), all frozen/forbid:
  - `Code = Annotated[str, Field(pattern=r"^[a-z_]+$")]`
  - `PlanRoute`: `route_key: str`, `origin_country`, `destination_country`, `level: Level`, `target_intake: IntakeRef`
  - `ConsentState`: `student: Literal["given", "missing"]`, `guardian: Literal["not_needed", "given", "missing"]`
  - `StepNeed`: `kind: Literal["fact", "document"]`, `ref: str` (pattern `^[a-z_][a-z0-9_.]*$`), `evidence: Literal["stated", "shown", "confirmed"]`
  - `PlanStep`: `task_id: int`, `instance_key: str`, `template_key: str`, `title: str` (playbook route data), `owner: Literal["student", "pai"]`, `status: Literal["pending", "ready", "running", "waiting_student", "waiting_review", "done", "failed", "skipped", "cancelled", "blocked"]` (the kernel states, `app/os/kernel/states.py`), `blocked_reason: Code | None`, `inbox_kind: Literal["provide", "approve", "act", "choose"] | None`, `programme_ref: str | None`, `due_at: AwareDatetime | None`, `due_tz: str | None`, `depends_on: list[str]` (instance keys), `provisional: bool`, `estimated: bool`, `needs: list[StepNeed]`
  - `PlanRequest`: `request_id: int`, `need: StepNeed`, `status: Literal["open", "answered"]`, `due_at`, `due_tz`
  - `DocumentNeed`: `doc_type: Code`, `status: Literal["missing", "uploaded", "confirmed"]`
  - `PlanChange`: `revision: int`, `at: AwareDatetime`, `cause: Code`, `kind: Literal["added", "removed", "moved", "done", "revised"]`, `instance_key: str | None`
  - `PlanViewV1`: schema `"pai.plan_view.v1"`, `student_ref`, `state: Literal["empty", "active", "needs_student", "paused", "stopped", "finished"]`, `stop_reason: Code | None`, `plan_id: int | None`, `decision_version: int | None`, `revision: int | None`, `route: PlanRoute | None`, `pages: list[Code]`, `consent: ConsentState | None`, `steps: list[PlanStep]`, `requests: list[PlanRequest]`, `documents_needed: list[DocumentNeed]`, `changes: list[PlanChange]`, `proposals_waiting: int` (ge 0)

- [ ] **Step 1: Write the failing tests** (mark R-41):
  - `test_escalation_v2_keeps_five_reasons`: the five reasons validate; `"route_not_possible"` raises; `decision_version=None` allowed.
  - `test_plan_view_empty_state`: `state="empty"` with no plan, route, steps validates; `state="empty"` with `plan_id=1` raises; `state="active"` with `plan_id=None` raises.
  - `test_plan_view_codes_not_text`: `blocked_reason="waiting on marks"` raises; `cause="counsellor"` validates.
  - `test_plan_view_step_status_matches_kernel`: the `PlanStep.status` literal set equals `{s.value for s in app.os.kernel.states.TaskState}` (read from that enum, do not copy).
- [ ] **Step 2: Run, see them fail** (same command as Task 1).
- [ ] **Step 3: Implement.** `PlanViewV1` validator: `state == "empty"` ⇔ `plan_id is None`; when not empty, `route` and `revision` are required. `stop_reason` only when `state == "stopped"`.
- [ ] **Step 4: Add both to the export script, run it**, confirm v1 schema files unchanged.
- [ ] **Step 5: Run tests** — PASS.
- [ ] **Step 6: Commit** `feat(os): escalation.v2 and plan_view.v1 contracts (R-41)`.

### Task 3: `os_event.v1`, `choice_request.v1`, `student_facts.v1`, `vault_event.v1`, samples and frozen tests

**Files:**
- Create: `backend/app/os/contracts/os_event.py`, `choice_request.py`, `student_facts.py`, `vault_event.py` and their `*.v1.schema.json`
- Create: `backend/app/os/contracts/samples/v2/` with `decision_chosen_de.json`, `decision_withdrawn_de.json`, `decision_unsupported_pk_inter.json`, `escalation_v2.json`, `plan_view_empty.json`, `plan_view_de.json`, `os_event.json`, `choice_request.json`, `student_facts.json`, `vault_event.json`, `valid.yaml`
- Create: `backend/tests/os/contracts/test_frozen_v2.py`
- Modify: `backend/tests/os/contracts/test_contracts_v2.py`, `backend/scripts/export_os_schemas.py`

**Interfaces:**
- Produces:
  - `OsEventV1`: schema `"pai.os_event.v1"`, `key: str` (min 1, the outbox key), `student_ref`, `plan_id: int | None`, `decision_version: int | None`, `kind: Literal["plan_created", "plan_revised", "plan_paused", "plan_stopped", "plan_finished", "step_done", "student_needed", "deadline_at_risk", "proposal_waiting"]`, `instance_key: str | None`, `at: AwareDatetime`
  - `ChoiceRequestV1`: schema `"pai.choice_request.v1"`, `key`, `student_ref`, `journey_id`, `proposal_id: int`, `based_on_version: int` (ge 1), `programmes: list[ProgrammeChoice] | None` (1..5, unique, ranked 1..n), `target_intake: IntakeRef | None`, `requested_at: AwareDatetime`; at least one of `programmes` / `target_intake` required.
  - `StudentFact`: `key: str` (pattern `^[a-z_]+(\.[a-z0-9_]+)*$`), `value: str | int | float | bool | list[str] | dict[str, str | int | float | bool | None] | None`, `evidence: Literal["stated", "shown", "confirmed", "unknown"]`, `vault_version: int` (ge 0). `StudentFactsV1`: schema `"pai.student_facts.v1"`, `student_ref`, `vault_version: int` (ge 0), `built_at: AwareDatetime`, `eligible_levels: list[Level]`, `facts: list[StudentFact]` (keys unique).
  - `VaultEventV1`: schema `"pai.vault_event.v1"`, `key`, `student_ref`, `vault_version: int` (ge 1), `kind: Literal["fact_changed"]`, `keys: list[str]` (min 1, same key pattern), `at: AwareDatetime`.
  - `samples/v2/valid.yaml`: a list of `{file: <name>, contract: <stem>}`, e.g. `{file: plan_view_de.json, contract: plan_view.v1}`.

- [ ] **Step 1: Write the failing tests** (mark R-41):
  - In `test_contracts_v2.py`: `test_choice_request_needs_a_change` (neither field → raises; only intake → ok); `test_choice_request_places_ranked` (ranks `[2]` raises); `test_student_facts_unique_keys` (two facts with the same key raise); `test_student_fact_inferred_is_not_an_evidence_level` (`evidence="inferred"` raises); `test_vault_event_needs_keys` (`keys=[]` raises).
  - In `test_frozen_v2.py`: parametrized `test_v2_schema_files_match_models` over every new model and its file stem (`decision_record.v2`, `route_contract.v2`, `escalation.v2`, `plan_view.v1`, `os_event.v1`, `choice_request.v1`, `student_facts.v1`, `vault_event.v1`), comparing `model_json_schema()` to the committed file with the message "changed: add a new version file instead"; `test_v2_schema_literals` (each schema const is `pai.<name>.v<N>`); `test_samples_validate` (every entry of `samples/v2/valid.yaml` validates as its contract; the file list equals the directory's `*.json`).
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement the four modules.** Docstring of each names master §9.1 and "frozen: a change is a new version file".
- [ ] **Step 4: Add them to the export script, run it**; v1 schema files unchanged.
- [ ] **Step 5: Write the samples** — fictional; the Germany samples use the existing seed refs `tu-chemnitz-embedded-systems` and `ovgu-eeit` and the journey `j-sample-1` / student `ws-sample-1` as the v1 samples do; `decision_unsupported_pk_inter.json` is PK→PK `intermediate`, `os_supported: false`, no places. `student_facts.json` uses generic keys (e.g. `education.level`, `marks.total`, `constraint.excluded_fields`) — no Pakistani words in the sample (it sits under `app/os`).
- [ ] **Step 6: Run** `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider tests/os/contracts tests/os/test_invariants.py` — PASS.
- [ ] **Step 7: Commit** `feat(os): os_event, choice_request, student_facts, vault_event contracts and v2 samples (R-41)`.

### Task 4: Fake PK intermediate route

**Files:**
- Create: `backend/tests/os/playbooks/pakistan_inter.v1.yaml`
- Create (only if a test needs a pack per playbook): `backend/tests/os/fixtures/packs/pakistan_inter.yaml`
- Create: `backend/tests/os/test_fake_intermediate_route.py`

**Interfaces:**
- Produces: playbook key `pakistan_inter`, version 1, `route: {origin: PK, destination: PK, level: intermediate}`, `default_timezone: Asia/Karachi`, no visa step. T5, T8 and T9 use it.

- [ ] **Step 1: Write the failing test** `test_fake_intermediate_route_loads` (mark R-41): `load_playbook_dir(<tests/os/playbooks>)` contains `("pakistan_inter", 1)`; `select_playbook(books, "PK", "PK", "intermediate").key == "pakistan_inter"`; no task `template_key` contains `visa`.
- [ ] **Step 2: Run, see it fail.**
- [ ] **Step 3: Write the playbook**, modelled on `pakistan_bs.v1.yaml`: a header comment "Fake local route (P1 spec §3.8, R-41): fictional, for tests only"; two student tasks — `admission_form` (`student.act`, inbox `act`, 1 day) and `merit_list` (`student.choose`, inbox `choose`, fan_out programme, depends on `admission_form`, anchor fact `merit_list_date`, 2 days). Eligibility as in `pakistan_bs` with only `ssc_certificate.marks_obtained` (weight 1.0, total `ssc_certificate.marks_total`), no test requirement.
- [ ] **Step 4: Run the whole OS suite alone**: `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider tests/os`. If a test that lists every route by exact set fails, add `pakistan_inter` to its expected set (extend, never loosen). If a test fails because a v1 `RouteContract` rejects `intermediate`, **stop and report BLOCKED** with the test name (that change belongs to T2).
- [ ] **Step 5: Commit** `test(os): fake PK intermediate route (R-41)`.

### Task 5: Connection flags, `part_on()`, and the owner switch

**Files:**
- Modify: `backend/app/config.py` (after `PAI_OS_SERVICE_TOKEN`)
- Modify: `backend/app/pai_os_bridge.py` (new function)
- Modify: `backend/app/os/adapters/counsellor/manifest.py` (new function)
- Create: `backend/app/pai_c/connect/__init__.py`, `backend/app/pai_c/connect/flags.py`
- Create: `backend/scripts/connect_switch.py`
- Create: `backend/tests/test_connect_flags.py` (legacy suite), `backend/tests/os/test_connect_switch.py`

**Interfaces:**
- Produces (`config.py`): six `bool` settings read like `PAI_ENABLED` (`os.environ.get(NAME, "false").lower() in ("true", "1", "yes")`): `CONNECT_HANDOFF`, `CONNECT_ROADMAP_FROM_PLANVIEW`, `CONNECT_CHECKINS_FROM_PLANVIEW`, `CONNECT_STUDENT_FACTS`, `CONNECT_ONE_UPLOAD`, `CONNECT_MY_PLAN`, with a comment citing P1-D9.
- Produces (`manifest.py`): `set_enabled(engine: Engine, tenant_id: str, enabled: bool) -> None` — inserts or updates the `os_modules` row `counsellor` for the tenant.
- Produces (`pai_os_bridge.py`): `counsellor_module_on() -> bool` — `plan_source.counsellor_enabled()`; `False` on `ports.OsUnavailable`; logs and returns `False` on any other exception.
- Produces (`pai_c/connect/flags.py`): `PARTS: tuple[str, ...]` (the six names); `part_on(name: str) -> bool` — `KeyError` for a name not in `PARTS`; true only when `getattr(config, name)` is true and `pai_os_bridge.counsellor_module_on()` is true (import the bridge inside the function).
- Produces (`scripts/connect_switch.py`): `python scripts/connect_switch.py status|on|off` — builds the OS engine from `app.os.settings.load_settings()` and `app.os.db.make_engine`, prints `counsellor module: on|off` and each flag's value from `config` (never any secret), and for `on`/`off` calls `manifest.set_enabled`. `main(argv: list[str], engine: Engine | None = None) -> int` for tests.

- [ ] **Step 1: Write the failing tests:**
  - `tests/test_connect_flags.py` (mark R-59; R-41 is not this task's): `test_flags_default_off` (each name in `PARTS` is `False` on `config` with no env set); `test_part_on_needs_module` (monkeypatch `config.CONNECT_HANDOFF = True`; with `counsellor_module_on` patched to `False` → `part_on("CONNECT_HANDOFF") is False`; patched `True` → `True`); `test_part_on_false_without_os` (flag on, no OS mounted, real bridge → `False`); `test_unknown_part_raises`.
  - `tests/os/test_connect_switch.py` (mark R-59, uses the `engine` and `clean` fixtures): `test_switch_on_off` (`main(["on"], engine)` → `manifest.is_enabled(engine, "pai") is True`; `main(["off"], engine)` → `False`; `main(["status"], engine)` returns 0 and prints `counsellor module: off`); `test_switch_rejects_unknown_command` (returns 2).
- [ ] **Step 2: Run, see them fail:** `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider tests/test_connect_flags.py`, then (alone) `... tests/os/test_connect_switch.py`.
- [ ] **Step 3: Implement** the settings, `set_enabled`, `counsellor_module_on`, `flags.py` and the script.
- [ ] **Step 4: Run** both test files — PASS. Then `tach check` (from `backend/`) — no errors. Then, from the repo root, `python scripts/check_freeze.py --base origin/pai-connect` — passes (only non-model settings changed in `config.py`).
- [ ] **Step 5: Commit** `feat(connect): off-by-default connection flags and the module switch (P1-D9)`.

### Task 6: Traceability and full check

**Files:**
- Modify: `docs/requirements/connection.yaml` (`R-41: built: true`)

- [ ] **Step 1:** Set `built: true` on R-41.
- [ ] **Step 2: Run** (repo root) `python scripts/check_traceability.py` — exit 0; `python scripts/check_traceability.py --report P1` lists R-41 with its tests.
- [ ] **Step 3: Run the suites one after the other** (from `backend/`): `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider` (legacy) then `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider tests/os`; frontend untouched. Both PASS; report the counts.
- [ ] **Step 4: Commit** `chore(connect): R-41 built (P1-T1)`.
