# PAI OS Slice 6b (the visa file) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the student one working, approvable visa file for the programme they choose: the visa checklist with
its files, a funds calculation with its source, a data sheet and the steps. Approving it completes
`review_visa_file`. There is no AI.

**Architecture:**
- 6a's pack machinery gains a file kind, `pack` | `visa`, threaded through the config loader, inputs, workflow,
  approval and API. Nothing is copied.
- A pure funds calculator reads a route fact named in the visa YAML.
- Three new document types are YAML only.
- The visa choice (programme, reduction) is a small new table.

**Tech Stack:** as Slice 6a. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-22-pai-os-slice-6b-design.md` (S6b-D1…D11)

## Global Constraints

- Everything from the Slice 6a global constraints holds:
  - code in `app/os`; Tach; no country, portal or currency terms in `app/os/**/*.py`;
  - `tenant_id` on every table; DBOS step retries only; no file bytes in step outputs;
  - approval binds the manifest SHA-256; a stale or incomplete approval is `409`; `building` while stale; a failed
    build shows `failed` and Rebuild starts a new attempt.
- **No AI.** The Compliance agent is dropped (S6b-D1).
- **Kinds:** `pack` and `visa`. The visa config is `app/os/packs/<route>.visa.yaml`; there is one visa artifact per
  student (`programme_ref` = the chosen programme).
- **Funds:** required = `fact` × `months` ÷ 12 − reduction, never below 0. Germany: the route fact
  `blocked_account_yearly_eur`, 12 months, currency label "EUR" in YAML only.
- **Motivation letter:** the approved base SOP, as the checklist item `motivation_letter` (`kind: statement`,
  `ref: sop`), with the note from S6b-D5.
- **Fake routes:** their playbooks stay unchanged, and they have no visa config.
- **Every PR targets `pai-os` directly.** Merge in order; after each merge, rebase the next branch on `pai-os` and
  force-push.
- Before every push, on **that branch**: `tach check`, the heads check, the full `pytest tests/os` (0 skipped), and
  the legacy suite when a shared file, `app/os/runner` or `main.py` is touched.

## Review Focus

1. **The student changes the chosen programme after approving:** the file rebuilds for the new programme, the old
   approval drops, and `review_visa_file` is not completed for the wrong programme. →
   `test_choice_change_drops_approval` (Task 3).
2. **A reduction larger than the requirement** (a full scholarship): required is 0, not negative, and the proof item
   needs no blocked account. → `test_full_reduction_floors_at_zero` (Task 2).
3. **The proof document's `amount` was read as text** ("11,904.00"): it is compared numerically, never rejected as
   lower. → `test_proof_amount_with_separators` (Task 2).
4. **A pack and a visa file for the same programme:** two artifacts and two manifests, and approving one never
   approves the other. → `test_pack_and_visa_are_separate` (Task 3).
5. **The route funds fact is missing:** the funds show "not confirmed yet", and the proof item is `needs_action`,
   not `ready`. → `test_missing_funds_fact` (Task 2).

---

### Task 1: The three document types

**Files:**
- Create: `app/os/documents/types/admission_letter.v1.yaml`, `blocked_account_confirmation.v1.yaml`,
  `insurance_certificate.v1.yaml`
- Test: `tests/os/test_visa_doc_types.py`

**Fields** (generic types only):
- `admission_letter`: `student_name` (name, `cross_check: full_name`), `institution` (text), `programme` (text),
  `start_date` (date), `issue_date` (date).
- `blocked_account_confirmation`: `holder_name` (name, `cross_check: full_name`), `provider` (text), `amount`
  (number), `monthly_payout` (number), `issue_date` (date).
- `insurance_certificate`: `holder_name` (name, `cross_check: full_name`), `insurer` (text), `cover_start` (date),
  `cover_end` (date).

- [ ] **Step 1: Failing tests:**
  - `test_visa_types_load` (all three in `load_document_types()`; each builds a `reading_model`);
  - `test_holder_names_cross_checked` (`cross_check` on the name fields; a different holder name gives a `mismatch`
    finding through `cross_check`);
  - `test_no_code_change_needed` (`git diff` of `app/os/documents/*.py` is empty for this task: the test asserts
    the three keys are loaded from YAML by the existing loader).
- [ ] **Step 2: Run** `pytest tests/os/test_visa_doc_types.py -v`. Expected: FAIL (KeyError).
- [ ] **Step 3: Write the three YAMLs.**
- [ ] **Step 4: Run** them, plus `test_document_types.py`, `test_profile.py` and `test_eligibility_rules.py`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): visa document types by config (Slice 6b Task 1)`.

### Task 2: Visa config and the funds calculator

**Files:**
- Modify: `app/os/packs/config.py`, `app/os/packs/checklist.py`
- Create: `app/os/packs/funds.py`, `app/os/packs/germany_master.visa.yaml`
- Test: `tests/os/test_visa_funds.py`

**Interfaces (produces):**
- `Funds(fact: str, months: int, currency_label: str, alternatives: list[Alt], proof_item: str, proof_field: str)`;
  `Alt(key, label)`. `PackConfig.funds: Funds | None = None`.
- `load_pack_configs(directory=PACK_DIR, kind: Literal["pack", "visa"] = "pack")`:
  - `pack` reads `*.yaml` except `*.visa.yaml`; `visa` reads `*.visa.yaml`;
  - `load_checked_pack_configs(directory, types, books, profiles, kind="pack")` likewise.
- `check_pack_config` also checks `funds`: `proof_item` is a `document` item, and `proof_field` is a field of its
  document type. The route fact is not checked against the research profile (route facts are seeded).
- `FundsResult(required: float | None, base: float | None, months: int, reduction: float, currency_label: str,
  status: str, quote: str | None, url: str | None)`, where `status` is the fact's status or `missing`.
- `required_funds(funds: Funds, fact, reduction: float) -> FundsResult`: `max(0, base × months / 12 − reduction)`,
  rounded to 2 decimals.
- `as_number(value) -> float | None`: accepts `11904`, `"11,904.00"`, `"11.904,00"`, and `None` for unparsable.
- `checklist(inp, programme_ref, unfixable=None, funds: FundsResult | None = None)`:
  - the proof item is `needs_action` with "the amount is below what you need: <required> <label>" when the proof
    amount is below `required`;
  - with "check the amount against the embassy's page" when `required` is None;
  - unchanged when `required == 0`.
- The Germany visa YAML:
  - data sheet: personal and passport fields; programme, institution and start date from `admission_letter.*`;
    entered contact fields;
  - checklist: passport, admission letter, blocked-account confirmation, insurance certificate, degree and transcript
    (format `attested`), CV, `motivation_letter` (statement `sop`, with the D5 note), and manual items "Applied on
    the Consular Services Portal" and "Paid the visa fee";
  - instructions keyed by the route values (`uni_assist`, `uni_assist_vpd`, `direct`; the same steps for all), each
    citing S9, S11, S13 or S15;
  - `funds`: fact `blocked_account_yearly_eur`, months 12, label EUR, alternatives scholarship and sponsor, proof
    item `blocked_account`, proof field `amount`.

- [ ] **Step 1: Failing tests:**
  - `test_visa_config_loads_separately` (`load_pack_configs(kind="visa")` has `germany_master` with `funds`;
    `kind="pack"` does not include the visa file);
  - `test_bad_proof_field_stops_startup`;
  - `test_required_funds` (11904, 12 months, reduction 2000 → 9904.0; status and URL carried);
  - **`test_full_reduction_floors_at_zero`**;
  - **`test_missing_funds_fact`**;
  - **`test_proof_amount_with_separators`**;
  - `test_proof_below_requirement_needs_action`;
  - `test_motivation_letter_is_the_sop`;
  - `test_no_currency_in_python` (the red-flag test now also forbids `eur` and `€` in `app/os/packs/*.py`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run**, then the full OS suite on this branch. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): visa config and funds calculator (Slice 6b Task 2)`.

### Task 3: The second kind: table, inputs, workflow, approval

**Files:**
- Create: `alembic/versions_os/os_0011_slice6b_visa.py`, `app/os/packs/visa.py`
- Modify: `app/os/models.py`, `app/os/packs/inputs.py`, `app/os/packs/run.py`, `app/os/packs/approval.py`,
  `app/os/packs/manifest.py`, `app/os/runner/worker.py`
- Test: `tests/os/test_visa_run.py`

**Interfaces (produces):**
- `os_0011`: `os_artifacts.kind` adds `visa`; a new table `os_visa_choices(tenant_id, student_ref, programme_ref,
  reduction numeric ≥ 0, updated_at)`, unique on (tenant_id, student_ref).
- `VisaChoiceStore(engine, tenant)`: `get(student) -> VisaChoice | None` (`programme_ref`, `reduction`),
  `set_programme(student, ref)`, `set_reduction(student, amount)`.
- `preselect(engine, tenant, plan_id) -> str | None`: the programme of a `done` `admission_result` task whose
  result payload contains the value `"admitted"` anywhere; None otherwise.
- `load_inputs(..., kind="pack")`. For `visa`, `PackInputs` gains `funds: FundsResult | None`, from
  `knowledge.route_facts(route_key, [funds.fact], year)` and the stored reduction. The choice and the reduction are
  part of `inputs_sha`.
- `pack_workflow_id(tenant, student, programme, inputs_sha, version=0, attempt=0, kind="pack")`: a visa ID starts
  `visa:`.
- `enqueue_pack(..., kind="pack")`, and the workflow `os.pack(student, programme, route_key, year, kind)`: the
  artifact is `get_or_create(student, kind, programme)`. For a visa, the artifact's `programme_ref` is the chosen
  programme, and only one visa artifact per student stays live: changing the programme moves the same artifact.
- `register_packs(engine, settings, knowledge, books, configs, statement_configs, visa_configs=None)`.
- `REVIEW_TASKS = {"pack": "review_pack", "visa": "review_visa_file"}`.
  `approve_pack(..., kind="pack")` and `complete_review_tasks(..., kind="pack")`: the visa task is not fanned out,
  so it is matched by plan.
- The manifest includes `funds` (the asdict of `FundsResult`) for a visa.

- [ ] **Step 1: Failing tests** (in-process DBOS, as `test_pack_run.py`):
  - `test_migration_up_down_up`;
  - `test_visa_build_and_funds_in_manifest`;
  - **`test_pack_and_visa_are_separate`**;
  - **`test_choice_change_drops_approval`**;
  - `test_reduction_change_rebuilds`;
  - `test_preselect_admitted`;
  - `test_visa_replay_idempotent`;
  - `test_approve_visa_completes_review_visa_file` (the Germany plan, with the task set to `waiting_student`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** The worker registers the visa configs (`load_checked_pack_configs(..., kind="visa")`).
- [ ] **Step 4: Run**, then the full OS suite and the legacy suite (the runner is touched). Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): visa file kind, choice and approval (Slice 6b Task 3)`.

### Task 4: The `review_visa_file` playbook task

**Files:**
- Modify: `app/os/playbooks/germany_master.v1.yaml`, `tests/os/golden/test_student_plan.json` (regenerated),
  `tests/os/test_golden.py` (21 tasks)
- Test: `tests/os/test_visa_plan.py`

The task: `review_visa_file` (`student.approve`, inbox `approve`, not fanned out), depending on `blocked_account` and
`travel_insurance`, citing S11. `visa_apply` depends on it. The fake routes are unchanged.

- [ ] **Step 1: Failing tests:**
  - `test_review_visa_file_before_visa_apply`;
  - `test_fake_routes_unchanged` (the fake playbooks have no `review_visa_file`, and their task sets equal
    `pai-os`'s).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Edit the YAML** and regenerate the golden file (`UPDATE_GOLDEN=1`). Check that only
  `review_visa_file` is added and that only `blocked_account` and `travel_insurance` move earlier.
- [ ] **Step 4: Run** the full OS suite on this branch. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): review_visa_file task (Slice 6b Task 4)`.

### Task 5: API

**Files:**
- Modify: `app/os/api/packs.py` (`add_visa_routes`, sharing the pack helpers), `app/os/api/services.py`
  (`visa_configs`), `app/os/api/mount.py`, `app/os/api/router.py` (`/inbox` also completes `review_visa_file`)
- Test: `tests/os/test_api_visa.py`

The endpoints of spec §4. `VisaOut` = `PackOut` + `funds` + `choice` (`programme_ref`, `reduction`, `preselected`).

- [ ] **Step 1: Failing tests:**
  - `test_get_visa_preselects_and_builds`;
  - `test_choice_422` (a programme not in the plan; a negative reduction);
  - `test_visa_items`;
  - `test_visa_download_per_student`;
  - `test_visa_approve_409_without_choice`;
  - `test_visa_approve_200_completes_task`;
  - `test_route_without_visa_config_404`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run**, then the full OS suite and the legacy suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): visa API (Slice 6b Task 5)`.

### Task 6: Screens

**Files:**
- Create: `frontend/app/[workspaceId]/os-visa/page.tsx`, `frontend/components/os/visa-funds.tsx`,
  `frontend/lib/os-visa.ts`, `frontend/components/os/visa.test.tsx`
- Modify: `frontend/lib/api.ts` (**shared**): `getOsVisa`, `saveOsVisaChoice`, `updateOsVisaItems`,
  `downloadOsVisaFile`, `approveOsVisa`
- Reuse: `PackView` for the checklist, data sheet and steps; it already takes an `OsPack`.

- [ ] **Step 1: Failing Vitest tests:**
  - the funds box (the amount and label, the status, the source link, the reduction input);
  - "not confirmed yet" when the amount is missing;
  - the programme choice;
  - the "check against the embassy portal's own list" line;
  - the "You apply and pay yourself" line;
  - Approve only when ready;
  - 360 px.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run`, `npx tsc --noEmit` and the OS-enabled build. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): visa screens (Slice 6b Task 6)`. The PR names a Counsellor reviewer.

### Task 7: Gate, crash test, final review, handoff

**Files:**
- Create: `tests/os/test_slice6b_gate.py`, `docs/os/handoff/slice-6b-handoff.md`
- Modify: `tests/os/test_crash.py` (`test_crash_during_visa_build`)

- [ ] **Step 1: Failing tests:**
  - `test_slice6b_gate`, on Germany. A student with confirmed documents (including the three new types, with a
    blocked-account amount ≥ the requirement), an approved SOP and CV, entered details, a chosen programme and
    ticks, goes through build → approve → `review_visa_file` done.
  - `test_fake_routes_have_no_visa_page` (`/v1/os/visa` is `404`; their Slice 6a gates still pass).
  - `test_crash_during_visa_build` (Linux CI).
- [ ] **Step 2: Run.** Expected: FAIL until the fixtures are complete.
- [ ] **Step 3: Complete the fixtures.**
- [ ] **Step 4: Run** the full OS suite, the legacy suite and the frontend checks. Expected: PASS.
- [ ] **Step 5:** One fresh final reviewer on the most capable model, over all the 6b commits, with the spec, this
  plan and Review Focus. Then one fix pass, each Critical or Important finding with a RED→GREEN test **on the branch
  that introduced it**. Minors are deferred.
- [ ] **Step 6: Commit** the gate, the fixes and the handoff. Open the PRs (each targeting `pai-os`).
