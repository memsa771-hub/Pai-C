# PAI OS Slice 4 (Self-serve start and eligibility) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A student starts their own plan from a route builder. Every programme shows a route-neutral eligibility
card that warns, never blocks, suggests swaps, and updates as the student's documents are confirmed.

**Architecture:**
- Each playbook carries an `eligibility:` block of generic checks and grade methods.
- A pure `evaluate()` turns a programme's facts and the student's profile values into a card, on read.
- Two existing hooks (fact change, document confirm) write change notes.
- The builder starts and swaps plans only through `PlanService` and the kernel.
- Requested programmes join the shared registry and are researched once.

**Tech stack:** as Slices 1–3 (FastAPI, SQLAlchemy Core, Alembic `os` branch, DBOS, Pydantic v2, Next.js +
Vitest). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-21-pai-os-slice-4-design.md` (S4-D1…D11). The owners accepted the §11
proposals: Q1, review in the open-facts view, usable before review; Q2, CGPA 4.0 → 2.0 and percentage → 33,
checked in Task 1; Q3, removing a programme without a swap is allowed while it has no started task.

## Global Constraints

- Everything in the Slice 1–3 global constraints holds:
  - code in `app/os`; Tach; timezone-aware datetimes;
  - `tenant_id` on every table; idempotent side effects;
  - **no country terms in `app/os/**/*.py`** (`tests/os/test_invariants.py`);
  - **no direct `openai` import**.
- **Route-neutral (S4-D2):**
  - Python knows only checks `grade | language | test` and methods `linear_scale | threshold |
    weighted_aggregate`.
  - Every number, fact name and profile key lives in a playbook's `eligibility:` block.
  - Each test of `evaluate` runs on all three routes.
- Eligibility statuses: `likely_meets | likely_below | needs_input | unknown`. The verdict is the worst line, in
  the order `likely_below > needs_input > unknown > likely_meets`.
- **Warn, never block (S4-D5).** Nothing in Slice 4 refuses a programme for eligibility.
- Swaps: same route, the new programme has facts, **at most 3 swaps per plan per day** (S4-D10), and the student's
  OK first.
- Requests: https only, **at most 3 per student per day**, research **once** per programme, then shared (S4-D8).
- At most **10** programmes per plan (`RouteContract`).
- Profile keys are Slice 3's `"<doc_type>.<field>"` (e.g. `transcript.cgpa`, `ielts_trf.overall`).
- Before every push, from `backend/`: `tach check`, `python scripts/check_alembic_heads.py`, `python -m pytest
  tests/os -v -rs` (0 skipped). Also the legacy suite when `app/os/runner`, the kernel, `main.py` or a shared file is
  touched.
- **Branches:** `os/s4-tN-<name>`, each from the latest `pai-os`. A task that needs an unmerged earlier task stacks
  on it and says so in its PR.
- **Never open or prepare a `pai-os` → `dev` PR** (owners: one merge at the very end).
- `frontend/lib/api.ts` is shared: its PR names a Counsellor reviewer.

## Rulings made in this plan

1. **Migration `os_0006`, not `os_0005`.** `os_0005_document_claim` landed with Slice 3's final fixes.
2. **Two small tables for notes instead of one.** The spec has one idempotency table. To write a note when
   a verdict *changes*, the code must know the last verdict a student was told:
   - `os_eligibility_seen` holds that verdict (one row per student and programme);
   - `os_eligibility_notes` holds the notes shown in the inbox, since the inbox otherwise lists only kernel
     tasks.
   Cards themselves are still never stored (S4-D3).
3. **The contract changes through a new kernel method** (`change_contract`), because the kernel is the sole
   writer and `revise` alone cannot change a plan's programmes.
4. **The choose-programmes task is named in the playbook** (`self_serve.choose_task`), not in code, so routes
   without one (the fake routes) start the same way.

## Review Focus

1. **A student on one route must never be evaluated with another route's rules,** even in the same request →
   `test_two_routes_one_request_use_their_own_rules` (Task 3).
2. **A grade exactly at the requirement** (e.g. estimated 2.5, needs 2.5 or better) must be `likely_meets` →
   `test_boundary_meets` (Task 3).
3. **A swap racing a fact change or a second swap** must not lose the contract change: the kernel's `based_on`
   check must hold → `test_swap_stale_contract_retries` (Task 8).
4. **The same programme requested by two students at once** must give one programme and one research run →
   `test_concurrent_requests_one_programme` (Task 5).
5. **A confirmed value with an open Slice 3 finding** (two different CGPAs) must give `needs_input`, never the
   first value → `test_open_finding_blocks_value` (Task 3).

---

### Task 1: Eligibility rules in the playbooks

**Files:**
- Create: `app/os/eligibility/__init__.py`, `app/os/eligibility/rules.py`
- Modify: `app/os/playbooks/models.py` (two optional fields on `Playbook`), `app/os/playbooks/germany_master.v1.yaml`,
  `tests/os/playbooks/ireland_master.v1.yaml`, `tests/os/playbooks/pakistan_bs.v1.yaml`
- Test: `tests/os/test_eligibility_rules.py`

**Interfaces (produces):**
- `GradeScale(best: float, provisional_min_pass: float, value: str, min_pass: str | None = None)`. `value` and
  `min_pass` are profile keys. `min_pass` is the confirmed letter value (Task 4).
- `GradeCheck(method: Literal["linear_scale", "threshold", "weighted_aggregate"], requirement: str, part: str |
  None, better: Literal["lower", "higher"], target: dict | None = None, weights: dict[str, float] | None = None,
  scales: list[str] = [])`.
  - `requirement` is a fact field; `part` is a key inside the fact's value.
  - `target` for `linear_scale` is `{best, worst_pass, decimals, rounding: "truncate" | "round"}`.
  - `weights` for `weighted_aggregate` maps a profile key to its weight.
- `LanguageCheck(language: str, requirement: str, level_key: str | None, scores: dict[str, str], none_values:
  list[str] = ["none"])`. `scores` maps a score key in the fact to a profile key.
- `TestCheck(requirement: str, list_key: str = "any_of")`.
- `EligibilityRules(grade: list[GradeCheck] = [], language: list[LanguageCheck] = [], test: TestCheck | None =
  None, grade_scales: dict[str, GradeScale] = {})`. The grade checks are tried in order; the first whose
  requirement part is present decides.
- `SelfServe(choose_task: str | None = None)`.
- `Playbook` gains `eligibility: EligibilityRules | None = None` and `self_serve: SelfServe | None = None`.
- `check_rules(book: Playbook, fact_fields: set[str] | None, profile_keys: set[str]) -> None` raises
  `PlaybookError` naming the playbook and the unknown field. `fact_fields=None` skips the fact check.
  `app/os/api/mount.py` calls it with the route's research profile fields and the document types' profile keys.

**Configs:**
- **Germany:** two grade checks.
  - `linear_scale` on `grade_requirement.german_max`, `better: lower`, target best 1.0, worst pass 4.0, 1 decimal,
    rounding as the route's source says. **Check uni-assist / KMK before choosing `truncate` or `round`**, and cite
    the source in a YAML comment.
  - `threshold` on `grade_requirement.percent_min`, `better: higher`.
  - Scales: `cgpa_4` (best 4.0, provisional 2.0, `transcript.cgpa`, min pass `min_passing_grade_letter.min_pass`)
    and `percent` (best 100, provisional 33, `transcript.percentage`).
  - Language: English (`english_requirement`, level key `cefr`, scores `ielts: ielts_trf.overall`) and German
    (`german_requirement`, level key `level`, no scores).
  - Test: `admission_test`. `self_serve.choose_task: choose_programmes`.
- **Ireland:** one `threshold` grade check on `grade_requirement.percent_min`, plus English.
- **Pakistan BS:** `weighted_aggregate` (`hssc_certificate.marks_obtained` 0.5 and an `entry_test.score` key
  0.5) against `merit_closing.aggregate`, plus test `entry_test_required`. There is no `entry_test` document type
  yet, so the tests pass `entry_test.score` in `profile_keys`. The fake routes are not loaded at mount.

- [ ] **Step 1: Failing tests:**
  - `test_all_playbooks_load_with_rules` (the 3 routes);
  - `test_unknown_fact_named_at_load`;
  - `test_unknown_profile_key_named_at_load`;
  - `test_unknown_method_refused`;
  - `test_playbook_without_rules_still_loads`.
- [ ] **Step 2: Run them:** `pytest tests/os/test_eligibility_rules.py -v` → FAIL (no module).
- [ ] **Step 3: Implement** the models, the playbook fields, the 3 YAML blocks and `check_rules`, and the call in
  `mount.py`.
- [ ] **Step 4: Run them:** PASS. `test_playbooks.py` and `test_compiler.py` still pass (fake routes unchanged in
  behaviour).
- [ ] **Step 5: Commit:** `feat(os): eligibility rules in the playbooks (Slice 4 Task 1)`.

### Task 2: Grade methods

**Files:** Create `app/os/eligibility/methods.py`. Test `tests/os/test_eligibility_methods.py`.

**Interfaces (produces):**
- `linear_scale(grade: float, scale_best: float, min_pass: float, target_best: float, target_worst_pass: float,
  decimals: int, rounding: str) -> float`, with this formula (the modified Bavarian formula when target 1.0 / 4.0):
  ```
  target_best + (target_worst_pass - target_best) * (scale_best - grade) / (scale_best - min_pass)
  ```
  The result is then truncated or rounded to `decimals`. It is not clamped: a grade below the minimum pass gives
  a value past `target_worst_pass`.
- `meets(have: float, need: float, better: str) -> bool`: `have <= need` for `lower`, `have >= need` for `higher`.
- `weighted_aggregate(values: dict[str, float], weights: dict[str, float]) -> float`.

- [ ] **Step 1: Failing tests:**
  - `test_linear_scale_german_example` (CGPA 3.0 / 4.0, min 2.0 → 2.5);
  - `test_linear_scale_best_and_min` (4.0 → 1.0; 2.0 → 4.0);
  - `test_linear_scale_truncate_vs_round` (3.0 / 4.0, min 2.2 → 2.666…: truncate 2.6, round 2.7);
  - `test_below_min_pass_not_clamped`;
  - `test_meets_both_directions`;
  - `test_weighted_aggregate`;
  - `test_zero_span_scale_refused` (`scale_best == min_pass` → `ValueError`).
- [ ] **Step 2: Run:** FAIL. **Step 3: Implement.** **Step 4: Run:** PASS.
- [ ] **Step 5: Commit:** `feat(os): generic grade methods (Slice 4 Task 2)`.

### Task 3: `evaluate` and route-neutrality

**Files:** Create `app/os/eligibility/evaluate.py`. Test `tests/os/test_eligibility_evaluate.py`.

**Interfaces:**
- Consumes: Task 1 models, Task 2 methods, `knowledge.port.Fact`.
- Produces:
  - `FactRef(field: str, url: str, status: str)`;
  - `Line(check: str, status: str, have: float | str | None, need: float | str | None, provisional: bool, needs:
    list[str], sources: list[FactRef])`. `needs` lists the document types whose confirmation would fill the line;
  - `Card(programme_ref: str, verdict: str, lines: list[Line])`;
  - `evaluate(rules: EligibilityRules, programme_ref: str, facts: dict[str, Fact], profile: dict[str, object],
    held: frozenset[str] = frozenset()) -> Card`.
  - `facts` maps a field name to its `Fact`, from `KnowledgePort.programme_facts`. `profile` maps a key to its
    value, from `ProfileStore.all`. `held` holds the profile keys under an open Slice 3 finding.
- Behaviour:
  - A missing or `None` fact gives `unknown`. A missing profile value, or one in `held`, gives `needs_input`, with
    `needs` = the key's document type. A grade below its scale's minimum still gives a number.
  - `provisional` is true when the scale's `min_pass` profile value is absent and `provisional_min_pass` was used.
  - A language requirement whose level is in `none_values` gives `likely_meets`.
  - A test requirement with an empty list gives `likely_meets`; a non-empty list gives `needs_input` (no test
    documents yet).

- [ ] **Step 1: Failing tests**, each parametrised over the 3 routes where it applies:
  - `test_meets_and_below`;
  - **`test_boundary_meets`**;
  - `test_missing_value_needs_input_names_document`;
  - `test_missing_fact_unknown`;
  - **`test_open_finding_blocks_value`**;
  - `test_provisional_default_flagged`;
  - `test_verdict_is_worst_line`;
  - `test_grade_checks_tried_in_order` (Germany: no `german_max`, has `percent_min` → threshold decides);
  - `test_language_none_meets`;
  - `test_sources_carry_fact_status`;
  - **`test_two_routes_one_request_use_their_own_rules`**;
  - `test_no_country_terms` (the existing red-flag test covers `app/os/eligibility/`; assert it scans the folder).
- [ ] **Step 2: Run:** FAIL. **Step 3: Implement.** **Step 4: Run:** PASS.
- [ ] **Step 5: Commit:** `feat(os): route-neutral eligibility evaluate (Slice 4 Task 3)`.

### Task 4: Minimum-passing-grade letter

**Files:**
- Create: `app/os/documents/types/min_passing_grade_letter.v1.yaml`. Fields: `institution` (text), `scale_best`
  (number), `min_pass` (number), `issue_date` (date); rule `lte [min_pass, scale_best]`.
- Modify: `app/os/playbooks/germany_master.v1.yaml`: the existing `min_passing_grade_letter` task's title says
  it improves the grade estimate.
- Test: `tests/os/test_eligibility_evaluate.py` (add), `tests/os/test_document_types.py` (the type loads).

`evaluate` uses `min_passing_grade_letter.min_pass` only when `min_passing_grade_letter.scale_best` equals the
scale's `best`. Otherwise it stays provisional, and `needs` names the letter.

- [ ] **Step 1: Failing tests:**
  - `test_letter_value_replaces_default` (provisional false, a new number);
  - `test_letter_for_other_scale_ignored`;
  - `test_letter_type_loads_by_config`.
- [ ] **Steps 2–4:** FAIL → implement (YAML only, plus the `evaluate` lookup) → PASS.
- [ ] **Step 5: Commit:** `feat(os): minimum-passing-grade letter type (Slice 4 Task 4)`.

### Task 5: Tables `os_0006` and programme requests

**Files:**
- Create: `alembic/versions_os/os_0006_slice4_self_serve.py`, `app/os/knowledge/requests.py`
- Modify: `app/os/models.py`, `tests/os/test_models.py` (tables list; the Slice 3 downgrade target)
- Test: `tests/os/test_programme_requests.py`

**Tables:**
- `os_programmes.status` check allows `requested`.
- `os_programme_requests(id, tenant_id, student_ref, route_key, url, programme_ref, created_at)`.
- `os_eligibility_seen(tenant_id, student_ref, programme_ref, verdict, updated_at)`, unique (tenant, student,
  programme). The last verdict a note was written for (Task 7).
- `os_eligibility_notes(id, tenant_id, student_ref, programme_ref, verdict, payload JSONB, created_at, read_at)`.

**Interfaces (produces):**
- `RequestLimit(Exception)`.
- `request_programme(engine, tenant_id, student_ref, route_key, university, name, url, *, now: datetime,
  enqueue: Callable[[str], object]) -> tuple[str, bool]` returns (programme_ref, created).
  - The ref is `req-` + the first 12 hex digits of the SHA-256 of the normalised URL.
  - The URL's host becomes `official_domains`.
  - `enqueue` is called only when created. The API passes `lambda ref: enqueue_one(engine, client, tenant, ref,
    intake_year, today)`.
- `visible_programmes(engine, tenant_id, route_key, intake_year) -> list[Programme]`: `active` ones, plus
  `requested` ones that have at least one fact for the year.
- `requested_without_facts(engine, tenant_id) -> list[Programme]`: listed in the admin's `GET /facts/open`
  response (Q1), with "could not be researched yet".
- Students see a `requested` programme labelled **"requested by a student"** (`requested_by_student: true` in
  Task 9's output) until an admin sets it `active`. It is usable before that (Q1).

- [ ] **Step 1: Failing tests:**
  - `test_migration_up_down`;
  - `test_request_creates_and_enqueues_once`;
  - `test_same_url_returns_existing`;
  - `test_same_university_and_name_returns_existing`;
  - **`test_concurrent_requests_one_programme`** (two threads, one row, one enqueue);
  - `test_daily_cap` (4th within 24 h → `RequestLimit`);
  - `test_http_url_refused`;
  - `test_requested_hidden_until_facts`;
  - `test_second_student_sees_it_without_research`;
  - `test_admin_open_facts_lists_unresearched_request`.
- [ ] **Steps 2–4:** FAIL → implement (`ON CONFLICT` on `uq_os_programmes_ref`, so a race is harmless) → PASS.
- [ ] **Step 5: Commit:** `feat(os): programme requests researched once (Slice 4 Task 5)`.

### Task 6: Swap suggestions

**Files:** Create `app/os/eligibility/swaps.py`. Test `tests/os/test_eligibility_swaps.py`.

**Interfaces (produces):**
- `Suggestion(programme_ref: str, confirmed_facts: int)`.
- `suggest(card: Card, candidates: list[tuple[str, Card, int]], chosen: set[str], limit: int = 3) ->
  list[Suggestion]`.
  - Each candidate is (ref, its card, how many confirmed facts it has).
  - It keeps those not chosen whose lines are `likely_meets` for **every check that is not `likely_meets` on
    `card`**, ranked by confirmed facts (descending), then ref.
  - It returns `[]` when `card.verdict == "likely_meets"`.

- [ ] **Step 1: Failing tests:**
  - `test_only_eligible_on_failing_lines`;
  - `test_excludes_chosen`;
  - `test_ranked_by_confirmed_facts`;
  - `test_at_most_three`;
  - `test_none_when_already_meets`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat(os): swap suggestions (Slice 4 Task 6)`.

### Task 7: Change notes from the two hooks

**Files:**
- Create: `app/os/eligibility/notes.py`
- Modify:
  - `app/os/knowledge/changes.py`: `after_fact_change`, for `scope == "programme"`, calls
    `notes.on_fact_change`;
  - `app/os/api/router.py`: after `confirm_document` and after `resolve_finding`, call
    `notes.on_profile_change`;
  - `app/os/api/queries.py` and `schemas.py`: `GET /inbox` returns `notes` (unread) beside `items`;
  - `POST /inbox/notes/{id}/read`.
- Test: `tests/os/test_eligibility_notes.py`

**Interfaces (produces):**
- `cards_for(svc, student_ref: str, plan_id: int) -> dict[str, Card]`: the student's chosen programmes, using the
  plan's **pinned** playbook rules.
- `on_profile_change(svc, student_ref: str) -> int`.
- `on_fact_change(svc, programme_ref: str, intake_year: int) -> int`.
- Both compare each card's verdict with `os_eligibility_seen`. When it differs, they upsert the seen verdict and
  insert one note with payload `{programme_ref, verdict, lines (status, have, need), suggestions}`. They return the
  number of notes written.
- A first evaluation of a programme (no seen row) records its verdict **without** a note.

- [ ] **Step 1: Failing tests:**
  - `test_confirm_changing_verdict_writes_one_note`;
  - `test_replay_writes_none`;
  - `test_first_evaluation_no_note`;
  - `test_fact_change_notifies_every_affected_student`;
  - `test_note_carries_suggestions`;
  - `test_inbox_lists_unread_notes_and_read_hides_it`;
  - `test_uses_pinned_playbook_rules`.
- [ ] **Steps 2–4:** FAIL → implement → PASS. Run the legacy suite (`router.py`).
- [ ] **Step 5: Commit:** `feat(os): eligibility change notes (Slice 4 Task 7)`.

### Task 8: Builder, swap and remove (kernel)

**Files:**
- Create: `app/os/routes/__init__.py`, `app/os/routes/builder.py`
- Modify: `app/os/kernel/kernel.py`, `app/os/service.py`
- Test: `tests/os/test_route_builder.py`

**Interfaces:**
- Kernel (the sole writer): `Kernel.change_contract(plan_id: int, contract: RouteContract, draft: PlanDraft,
  cause: str, based_on: str) -> int | None`.
  - Under the plan lock: check `based_on` (`StaleDraft` otherwise), store the new contract and its SHA-256, then
    `_revise`.
- `PlanService.change_programmes(plan_id: int, programmes: list[ProgrammeChoice], cause: str) -> int | None`
  compiles the new contract with the **pinned** playbook and retries `StaleDraft` up to 3 times, as `recompile`
  does.
- Builder:
  - `SwapLimit(Exception)`; `NotAllowed(Exception)`, with a student-readable reason;
  - `start(svc, student_ref: str, route_key: str, intake: IntakeRef, choices: list[ProgrammeChoice]) -> PlanRef`.
    It builds `RouteContract(source="self_serve", external_ref=f"self:{student_ref}:{route_key}:{intake.term}:
    {intake.year}", ...)` from the playbook's route. It refuses a programme on another route. It completes the
    playbook's `self_serve.choose_task` for this plan, when set, with payload `{"programmes": [...refs]}`;
  - `swap(svc, student_ref: str, plan_id: int, out_ref: str, in_ref: str, now: datetime) -> int | None`. Rank is
    kept. The new programme has facts and is on the same route. At most 3 revisions with cause `swap` in 24 h
    (`SwapLimit`). A protected or started task of `out_ref` → `NotAllowed`;
  - `remove(svc, student_ref, plan_id, ref) -> int | None` (Q3): only if `ref` has no started task and at least
    one programme remains; ranks close up.

- [ ] **Step 1: Failing tests:**
  - `test_start_builds_self_serve_contract`;
  - `test_start_twice_returns_existing`;
  - `test_start_completes_choose_task`;
  - `test_start_without_choose_task_route` (Ireland);
  - `test_other_route_programme_refused`;
  - `test_eleven_programmes_refused`;
  - `test_swap_revises_plan`;
  - `test_swap_keeps_rank`;
  - `test_swap_refused_when_started`;
  - `test_fourth_swap_in_a_day_refused`;
  - **`test_swap_stale_contract_retries`**;
  - `test_remove_last_programme_refused`;
  - `test_only_own_plan`.
- [ ] **Steps 2–4:** FAIL → implement → PASS. Run the legacy suite (kernel).
- [ ] **Step 5: Commit:** `feat(os): self-serve builder, swap and remove (Slice 4 Task 8)`.

### Task 9: The API

**Files:** Modify `app/os/api/router.py`, `schemas.py`, `queries.py`. Test `tests/os/test_api_self_serve.py`.

The endpoints are spec §4 exactly, plus `DELETE /plans/{id}/programmes/{ref}` (Q3):
- `GET /routes`;
- `GET /routes/{route}/programmes?intake=` (cards; requested programmes without facts show `being_researched`);
- `GET /eligibility/{programme_ref}?route=&intake=` (card + `suggest()` from the visible programmes);
- `POST /plans/self` → `201` (new) or `200` (existing), `422` on a builder refusal;
- `POST /plans/{id}/swap` → `200`, or `409 {reason}` on `NotAllowed` / `SwapLimit`;
- `POST /programmes/requests` → `202`, or `429` on `RequestLimit`, `422` on a bad URL.

Writes use `current_student_ref_for_write`.

- [ ] **Step 1: Failing tests:** one per endpoint and status above, plus `test_student_sees_only_own_cards`,
  `test_card_uses_confirmed_profile`.
- [ ] **Steps 2–4:** FAIL → implement → PASS. Run the legacy suite.
- [ ] **Step 5: Commit:** `feat(os): self-serve and eligibility API (Slice 4 Task 9)`.

### Task 10: Screens

**Files:**
- Create: `frontend/app/[workspaceId]/os-start/page.tsx`, `frontend/components/os/route-builder.tsx`,
  `frontend/components/os/eligibility-card.tsx`, `frontend/lib/os-self-serve.ts`,
  `frontend/components/os/route-builder.test.tsx`
- Modify: `frontend/lib/api.ts` (**shared**): `getOsRoutes`, `getOsRouteProgrammes`, `getOsEligibility`,
  `startOsPlan`, `swapOsProgramme`, `removeOsProgramme`, `requestOsProgramme`, `readOsNote`;
  `frontend/components/os/inbox-list.tsx` (notes at the top, with **Swap** and a confirm dialog)

Copy fixed by the spec:
- the provisional sentence: "Estimated with a typical minimum passing grade; upload your university's
  minimum-passing-grade letter for an accurate result.";
- the card footer: "An estimate, not a decision: the university decides.";
- chips: `likely meets`, `check this`, `needs your documents`, `being researched`.

- [ ] **Step 1: Failing Vitest tests:**
  - chips per status;
  - card lines with numbers;
  - the provisional sentence;
  - source links with ✓/⚠;
  - choices capped at 10 and reorderable;
  - swap asks to confirm;
  - the request form shows the `429` message;
  - the note in the inbox;
  - 360 px (no horizontal overflow classes).
- [ ] **Step 2:** `npx vitest run components/os/route-builder.test.tsx` fails.
- [ ] **Steps 3–4:** implement, then `npx vitest run`, `npx tsc --noEmit`, `NEXT_PUBLIC_OS_ENABLED=true npm run
  build`: PASS.
- [ ] **Step 5: Commit:** `feat(os): self-serve start and eligibility screens (Slice 4 Task 10)`. The PR names a
  Counsellor reviewer.

### Task 11: Slice gate test

**Files:** Create `tests/os/test_slice4_gate.py`.

One test per route, end to end through the API with a fake research run:
1. Start a plan alone.
2. Cards show `needs_input`.
3. Confirm a transcript and an IELTS form (Slice 3 confirm, synthetic values) → cards change, and one note
   each.
4. Swap → a revision.
5. Request a programme → research (faked) writes facts → a second student sees it, with no second research.

Fake routes run unchanged (the existing fake-route tests still pass).

- [ ] **Step 1:** write `test_slice4_gate_germany`, `test_slice4_gate_ireland`, `test_slice4_gate_pakistan_bs` →
  FAIL only where wiring is missing.
- [ ] **Steps 2–4:** fix the wiring → PASS. Full OS suite and legacy suite green.
- [ ] **Step 5: Commit:** `test(os): Slice 4 gate (Slice 4 Task 11)`.

### Final review

One fresh reviewer, on the most capable model, over the whole Slice 4 diff. Give it the spec, this plan with its
Review Focus, and the rulings from the PRs. Then one fix pass (RED→GREEN per Critical or Important finding). **No
`dev` PR.**
