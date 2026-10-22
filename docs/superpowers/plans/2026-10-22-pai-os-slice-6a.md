# PAI OS Slice 6a (the application pack) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each programme, give the student one working page: a data sheet, every required file in the portal's
format, the approved SOP and CV as PDFs, a checklist and route instructions. The student approves one manifest
version, which completes `review_pack`. No AI.

**Architecture:**
- The pack config is per-route YAML, validated at startup.
- Pure functions build the checklist, the data sheet and the instructions.
- A ReportLab renderer in invariant mode, plus Pillow and `pypdf` conversion, writes the files. Files are stored
  once per SHA-256 in `os_pack_files`.
- An `os.pack` DBOS workflow in the worker builds a manifest artifact (kind `pack`) on the Slice 5 artifact tables.
- Approval binds the manifest's SHA-256 and completes the playbook task through the kernel.

**Tech Stack:** as Slices 1–5, plus **ReportLab** (new, pinned). Pillow, `pypdf` and `pypdfium2` are already
installed.

**Spec:** `docs/superpowers/specs/2026-10-22-pai-os-slice-6a-design.md` (S6a-D1…D12)

## Global Constraints

- Everything from the Slice 1–5 global constraints holds:
  - code in `app/os`; Tach;
  - no country, portal or currency terms in `app/os/**/*.py` (the red-flag test);
  - `tenant_id` on every table; timezone-aware datetimes;
  - DBOS step retries only; idempotent side effects;
  - before every push: `tach check`, `python scripts/check_alembic_heads.py`, `python -m pytest tests/os -v -rs`
    (0 skipped), plus the legacy suite when a shared file, `app/os/runner` or `main.py` is touched.
- **No AI in this slice:** no agent, no model call, no new budget.
- **The pack config is per-route YAML in `app/os/packs/<route_key>.yaml`.** The fake routes' configs are in
  `tests/os/fixtures/packs/`. Item kinds: `document`, `statement`, `entered`, `manual`.
- **Renderer:** ReportLab `invariant=1`; the same inputs give byte-identical bytes; PDF only.
  - Conversion shrinks to the item's `max_mb`, with a long-side floor of **1,600 px**.
  - Page cap **40**; pixel cap **40,000,000 px per page**.
  - The original upload is never changed.
- **No file bytes in DBOS step outputs.** Steps return SHA-256s.
- **Approval binds the manifest's SHA-256.** A stale or incomplete approval is `409`. A new version drops the
  approval.
- **`review_pack`:** task type `student.approve`, inbox kind `approve`, `fan_out: programme`, depending on
  `application_documents`. The route's apply tasks depend on it.
- **Shared files need a Counsellor reviewer:** `backend/requirements.txt` (Task 1) and `frontend/lib/api.ts`
  (Task 9).
- Branches: `os/s6a-tN-<name>`, each stacked on the previous one (Slice 5 handoff §2). Every branch's full suite
  must be green on its own.

## Review Focus

1. **A data-sheet value is changed after approval** (for example, the student fixes a phone number): the next
   `GET /packs` must show a new version, the approval dropped, and Approve enabled again. →
   `test_entered_change_drops_approval` (Task 7).
2. **The same photo is uploaded twice as two different document types:** two checklist items, both `ready`, one
   stored file (same SHA-256). → `test_same_file_two_items_one_blob` (Task 7).
3. **A programme whose `application_route` is unconfirmed:** the instructions show the template for no route, with
   "not confirmed yet" and the research link, never a guessed route. → `test_unconfirmed_route_no_guess` (Task 5).
4. **A student downloads with another student's SHA-256** (the same file uploaded by both): `404`, even though the
   blob exists. → `test_file_download_is_per_student` (Task 8).
5. **A huge multi-page scanned PDF** (60 pages): `needs_action` "too many pages", with no crash and no memory
   blow-up. → `test_page_cap` (Task 6).

---

### Task 1: ReportLab pin (shared file)

**Files:**
- Modify: `backend/requirements.txt` (add `reportlab==4.4.4`)
- Test: `tests/os/test_pack_render_lib.py`

- [ ] **Step 1: Failing test:** `test_reportlab_invariant_is_byte_identical`. Build a one-page canvas twice with
  `invariant=1` and assert the bytes are equal. It fails on import.
- [ ] **Step 2: Run** `pytest tests/os/test_pack_render_lib.py -v`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Add the pin**, then `pip install -r requirements.txt`.
- [ ] **Step 4: Run** the same test, then the full OS suite and the legacy suite. Expected: PASS.
- [ ] **Step 5: Commit** `chore(os): pin reportlab for the pack renderer (Slice 6a Task 1)`. The PR names a Counsellor
  reviewer.

### Task 2: Pack config, loader and validation

**Files:**
- Create: `app/os/packs/__init__.py`, `app/os/packs/config.py`, `app/os/packs/germany_master.yaml`
- Create: `tests/os/fixtures/packs/ireland_master.yaml`, `tests/os/fixtures/packs/pakistan_bs.yaml`
- Modify: `app/os/api/mount.py` and `app/os/runner/worker.py` (load and `check_pack_config` at startup, after the
  statement configs)
- Test: `tests/os/test_pack_config.py`

**Interfaces (produces):**
- `PackConfig(route_key, version, data_sheet: list[Section], checklist: list[Item], formats: Formats,
  instructions: dict[str, list[Step]], fees: list[FeeRef])`
- `Section(title, fields: list[SheetField])`; `SheetField(key, label, source: str, required: bool = False,
  hint: str = "")`. `source` is a profile key, or the literal `"entered"`.
- `Item(key, label, kind: Literal["document", "statement", "entered", "manual"], ref: str | None,
  format: str | None = None, note: str | None = None)`
- `Formats(default: Format, named: dict[str, Format])`; `Format(types: list[Literal["pdf"]] = ["pdf"],
  max_mb: float, colour: bool = False, notes: list[str] = [])`
- `Step(text: str, source: str)`. `source` is `"fact:<name>"` or `"citation:<id>"`.
- `FeeRef(label, source: str)`. `source` is `"fact:<name>"` or `"constant:<name>"`.
- `PackConfigError(ValueError)`; `load_pack_configs(directory: Path = PACK_DIR) -> dict[str, PackConfig]`.
- `check_pack_config(cfg, profile_keys: set[str], doc_types: set[str], book, research_fields: set[str] | None)`
  raises `PackConfigError("<file>: <key>: …")` for:
  - an unknown profile key or document type;
  - a `statement` ref other than `sop` or `cv`;
  - an `entered` ref that is not an `entered` data-sheet field;
  - an instruction key that is not an `application_route` value of the route's research profile (skipped when
    there is no research profile);
  - an unknown fact, constant or playbook citation;
  - an item `format` that is not in `formats.named`.
- The Germany config's instruction keys: `uni_assist`, `uni_assist_vpd`, `direct`. Its data sheet covers:
  - personal: name parts, date of birth, sex, nationality, passport number and expiry;
  - contact (`entered`): email, phone, address lines, city, postcode, country of residence;
  - education: degree title, institution, CGPA and scale, completion date, HSSC and SSC year and marks;
  - English: test, overall, test date.

  Its default checklist: passport, degree, transcript, HSSC, SSC, IELTS TRF, minimum passing grade letter, SOP, CV,
  `manual`: "paid the application fee". Format default: PDF, 5 MB. `attested` format notes: `["attested copy"]`
  for degree and transcript.

- [ ] **Step 1: Failing tests:**
  - `test_all_pack_configs_load` (Germany from `PACK_DIR`; the fake two from the fixtures directory);
  - `test_unknown_profile_key_stops_startup`;
  - `test_unknown_route_value_stops_startup`;
  - `test_unknown_fact_or_citation_stops_startup`;
  - `test_entered_item_must_name_entered_field`;
  - `test_mount_validates_pack_configs` (a bad config in a temp directory makes `mount_os` raise);
  - `test_no_country_terms_in_packs_python` (the red-flag test over `app/os/packs/*.py`).
- [ ] **Step 2: Run** `pytest tests/os/test_pack_config.py -v`. Expected: FAIL (import).
- [ ] **Step 3: Implement**, following `app/os/statements/config.py` (frozen Pydantic, `extra="forbid"`, error
  messages naming the file and the key).
- [ ] **Step 4: Run** it. Expected: PASS. Then run the full suite.
- [ ] **Step 5: Commit** `feat(os): pack config per route (Slice 6a Task 2)`.

### Task 3: Tables `os_0009`, the profile source, the pack store

**Files:**
- Create: `alembic/versions_os/os_0009_slice6a_packs.py`, `app/os/packs/store.py`
- Modify: `app/os/models.py`, `app/os/documents/store.py` (`ProfileStore.set`, `all`)
- Test: `tests/os/test_pack_store.py`

**Interfaces (produces):**
- Tables as spec §3:
  - `os_pack_files`, unique on `(tenant_id, student_ref, sha256)` (per student, so downloads stay per student);
  - `os_pack_items`, unique on `(tenant_id, student_ref, programme_ref, item_key, kind)`;
  - `os_profile_values.source` (`Text`, not null, default `'document'`, check `IN ('document','entered')`).
- `ProfileStore.set(student_ref, key, value, source_document_id, *, source: str = "document")`. `all()` returns
  `source` too.
- `PackFileStore(engine, tenant)`:
  - `put(student_ref, programme_ref, item_key, filename, content_type, data: bytes, pages: int) -> str` (SHA-256;
    insert-on-conflict-do-nothing);
  - `get(student_ref, sha256) -> PackFile | None`;
  - `meta(student_ref, sha256) -> PackFileMeta | None` (without data);
  - `delete_for_item(student_ref, item_key)`;
  - `delete_for_student(student_ref)`.
- `PackItemStore(engine, tenant)`:
  - `tick(student, programme, key)`, `untick(...)`;
  - `add(student, programme, label) -> str` (key `added:<n>`);
  - `ticked(student, programme) -> set[str]`;
  - `added(student, programme) -> list[tuple[str, str]]`.

- [ ] **Step 1: Failing tests:**
  - `test_migration_up_down_up`;
  - `test_put_same_bytes_once`;
  - `test_file_is_per_student`;
  - `test_profile_source_entered`;
  - `test_items_tick_and_add`;
  - `test_tenant_isolation`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** with the patterns in `app/os/artifacts/store.py`. The migration is self-contained (no
  `app.os` imports).
- [ ] **Step 4: Run.** Expected: PASS. `check_alembic_heads.py` shows one head, `os_0009`.
- [ ] **Step 5: Commit** `feat(os): pack tables os_0009 and stores (Slice 6a Task 3)`.

### Task 4: The `required_documents` research field and the `review_pack` task

**Files:**
- Modify: `app/os/knowledge/profiles/germany_master.research.v1.yaml` (`required_documents`: a list of item keys
  plus `extras: [str]`, with a hint and a quote)
- Modify: `tests/os/quality/scoring.py` (skip it, as `statement_requirement`)
- Modify: `app/os/playbooks/germany_master.v1.yaml`, `tests/os/playbooks/ireland_master.v1.yaml`,
  `tests/os/playbooks/pakistan_bs.v1.yaml` (add `review_pack`; apply tasks depend on it; Germany also gets the
  constant `uni_assist_fee_eur` with its citation)
- Modify: `app/os/runner/modules.py` (the `student.approve` owner, if not already registered)
- Test: `tests/os/test_pack_plan.py`

- [ ] **Step 1: Failing tests:**
  - `test_review_pack_in_each_route` (compile the golden student on all three routes: `review_pack@<prog>` exists
    per programme, after `application_documents`, before the apply tasks);
  - `test_required_documents_field_in_profile`;
  - `test_spike1_scorer_skips_required_documents`;
  - `test_golden_plan_dates_unchanged_except_review_pack` (the Slice 1 golden file is regenerated, and only the new
    task differs).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the YAML changes. Regenerate the golden file with its existing script.
- [ ] **Step 4: Run** the full OS suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): required_documents fact and review_pack task (Slice 6a Task 4)`.

### Task 5: Checklist validator, data sheet, instructions (pure)

**Files:**
- Create: `app/os/packs/checklist.py`, `app/os/packs/datasheet.py`, `app/os/packs/instructions.py`
- Test: `tests/os/test_pack_rules.py`

**Interfaces (produces):**
- `PackInputs` (a frozen dataclass):
  - `cfg: PackConfig`;
  - `documents: dict[str, DocState]` (by doc type: `{status, document_id, sha256}`);
  - `statements: dict[str, str | None]` (`sop`, `cv`, or `sop:<programme>`, mapped to the approved SHA-256 or None);
  - `profile: dict[str, ProfileValue]`;
  - `facts: dict[str, Fact]`;
  - `constants: dict[str, Constant]`;
  - `ticked: set[str]`;
  - `added: list[tuple[str, str]]`;
  - `required_override: list[str] | None`.
- `ItemResult(key, label, kind, state: Literal["ready", "missing", "needs_action", "manual"], ticked: bool,
  reasons: list[str], source: Literal["research", "default", "student"], document_id: int | None)`
- `checklist(inp: PackInputs, programme_ref: str) -> list[ItemResult]`:
  - the effective items are the override (research) if present, else the default, plus the student's additions;
  - a document whose format notes apply is `needs_action` with the note, unless a later task supplies a fixed file
    (Task 7 passes the converter's results in).
- `SheetRow(section, key, label, value: str | None, source: Literal["document", "entered"] | None,
  document_id: int | None, gap: bool)`
- `data_sheet(inp: PackInputs) -> list[SheetRow]`. `gap` is true when the value is missing and the field is
  required.
- `InstructionStep(n: int, text: str, source_url: str | None, unconfirmed: list[str])`
- `instructions(inp: PackInputs, programme_ref: str) -> tuple[str | None, list[InstructionStep]]`. It returns the
  route value used (None when `application_route` is missing or unconfirmed), and placeholders are filled as
  `{fact}` → value, or "not confirmed yet".
- `fees(inp: PackInputs) -> list[FeeRow(label, value, status, source_url)]`.

- [ ] **Step 1: Failing tests:**
  - `test_document_ready_missing_needs_action`;
  - `test_statement_needs_approval` (an unapproved SOP is `missing`);
  - `test_programme_sop_when_needed`;
  - `test_research_overrides_default` (`source="research"`);
  - `test_student_added_item_is_manual`;
  - `test_manual_needs_tick`;
  - `test_sheet_values_and_gaps`;
  - `test_entered_value_named_entered`;
  - `test_instructions_filled_with_sources`;
  - **`test_unconfirmed_route_no_guess`**;
  - `test_fees_show_status_and_source`;
  - `test_fake_routes_build_sheet_and_checklist` (Ireland and Pakistan BS configs, no code change).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as pure functions with no I/O.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): pack checklist, data sheet and instructions (Slice 6a Task 5)`.

### Task 6: Renderer and document conversion

**Files:**
- Create: `app/os/packs/render.py`
- Test: `tests/os/test_pack_render.py` (synthetic images and PDFs made in the test)

**Interfaces (produces):**
- `Unfixable(reason: str)` (a frozen dataclass).
- `render_sheet(rows: list[SheetRow], title: str) -> bytes`
- `render_statement(text: str, title: str) -> bytes`. Both use ReportLab `invariant=1`, the built-in Helvetica,
  A4, and wrapped text.
- `convert_document(data: bytes, kind: str, fmt: Format) -> tuple[bytes, int] | Unfixable` (the PDF bytes and their
  page count):
  - images are EXIF-transposed and placed one per page;
  - PDFs are rasterised only when over `max_mb`;
  - each image is downscaled in steps of 0.85 down to the 1,600 px long side, as JPEG quality 85, until it is
    within `max_mb`;
  - otherwise it returns `Unfixable("cannot make it smaller than <n> MB without losing legibility")`;
  - over 40 pages gives `Unfixable("too many pages (<n>); the limit is 40")`;
  - over 40 MP per page gives `Unfixable("page too large")`;
  - a damaged file gives `Unfixable("upload a clearer copy")`.
- `filename(item_key: str, label: str) -> str` (ASCII slug plus `.pdf`).

- [ ] **Step 1: Failing tests:**
  - `test_sheet_render_deterministic`;
  - `test_statement_render_deterministic`;
  - `test_changed_input_new_bytes`;
  - `test_large_rotated_photo_under_limit` (8000×6000, EXIF 6, `max_mb=2`: upright, ≤ 2 MB, one page);
  - `test_unshrinkable_scan` (`max_mb=0.05`: `Unfixable`);
  - `test_original_untouched`;
  - **`test_page_cap`** (60 pages: `Unfixable`, under a 20 s timeout);
  - `test_damaged_file`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): pack renderer and document conversion (Slice 6a Task 6)`.

### Task 7: Manifest, the `os.pack` workflow, approval and details

**Files:**
- Create: `app/os/packs/manifest.py`, `app/os/packs/run.py`, `app/os/packs/approval.py`,
  `app/os/packs/details.py`, `app/os/packs/inputs.py`
- Modify: `app/os/runner/worker.py` (`register_packs`, with no key needed), `app/os/documents/confirm.py`
  (`delete_document` also calls `PackFileStore.delete_for_item` for that document's items)
- Test: `tests/os/test_pack_run.py` (in-process DBOS, as `test_document_run.py`)

**Interfaces (produces):**
- `load_inputs(engine, tenant, plans, knowledge, cfg, student, programme) -> PackInputs` (`inputs.py`; reads the
  documents, approved statements, profile, facts, constants and items).
- `inputs_sha(inp: PackInputs) -> str` (64 hex characters over canonical JSON of every input, including the
  document SHA-256s).
- `FileRef(sha256: str, filename: str, size: int, pages: int)` (a frozen dataclass, in `manifest.py`).
- `build_manifest(inp, programme, files: dict[str, FileRef]) -> tuple[str, str]` (canonical JSON text with sorted
  keys and no timestamps, and its SHA-256). It holds the checklist, data sheet, instructions, fees, `files`
  `{item_key: {sha256, filename, size, pages}}` and `config_version`.
- `pack_workflow_id(tenant, student, programme, inputs_sha) -> str` = `pack:{tenant}:{student}:{programme}:{sha[:16]}`.
- `enqueue_pack(client, tenant, student, programme, inputs_sha) -> str`.
- `register_packs(engine, settings, plans, knowledge, configs)` registers `os.pack(student, programme)` with the
  steps:
  - `load` (returns the inputs SHA-256 and the item list, no bytes);
  - `render:<item>` (reads the bytes, converts or renders, calls `PackFileStore.put`, and returns a `FileRef` or the
    `Unfixable` reason);
  - `manifest`;
  - `store` (`ArtifactStore.get_or_create(student, "pack", programme)`, then `add_version(text, "system")` only if
    the SHA-256 differs from the current version; the artifact status becomes `ready` or `incomplete`);
  - `finish`.
  The artifact status is `building` while it runs, and `failed` after the step retries are used up.
- `approve_pack(engine, kernel, tenant, student, programme, sha256) -> Approval`. It raises `PackNotCurrent` or
  `PackIncomplete`. On success it approves and calls `complete_review_tasks(...)` →
  `kernel.complete_student_task(task_id, student, {"artifacts": {"pack": sha256}})`.
- `complete_review_tasks(engine, kernel, tenant, student, plan_id) -> list[int]` (it also runs on `GET /packs` and
  `GET /inbox`, as Slice 5's `complete_documents_tasks` does).
- `save_details(engine, tenant, cfg, student, fields: dict[str, str]) -> None`. Unknown or non-`entered` keys raise
  `ValueError`. It writes through `ProfileStore.set(..., None, source="entered")`.

- [ ] **Step 1: Failing tests:**
  - `test_build_once_per_inputs`;
  - `test_replay_no_duplicate_files_or_versions`;
  - `test_no_file_bytes_in_step_outputs`;
  - `test_incomplete_until_ready`;
  - `test_approve_binds_manifest_sha`;
  - `test_stale_or_incomplete_approve_refused`;
  - **`test_entered_change_drops_approval`**;
  - **`test_same_file_two_items_one_blob`**;
  - `test_review_pack_task_completes_via_kernel`;
  - `test_task_ready_later_completes_on_get`;
  - `test_delete_document_drops_its_pack_files`;
  - `test_details_refuses_unknown_keys`;
  - `test_render_failure_marks_failed`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement**, following `app/os/statements/run.py` and `approval.py`.
- [ ] **Step 4: Run.** Expected: PASS, plus the legacy suite (the runner was touched).
- [ ] **Step 5: Commit** `feat(os): os.pack workflow, manifest and approval (Slice 6a Task 7)`.

### Task 8: API

**Files:**
- Create: `app/os/api/packs.py` (a router included by `build_router`, as the statements routes are)
- Modify: `app/os/api/schemas.py`, `app/os/api/services.py` (`pack_configs`), `app/os/api/mount.py`,
  `app/os/api/router.py` (`GET /inbox` also calls `complete_review_tasks`)
- Test: `tests/os/test_api_packs.py`

**Interfaces (produces):** the endpoints of spec §4. `GET /packs` returns `PacksOut{programmes: [PackOut]}`. Each
`PackOut` is `{programme_ref, name, status, version, approved: bool, manifest_sha256, route_value, instructions,
fees, checklist, data_sheet, files}`. `GET /` enqueues a build when the inputs SHA-256 differs from the current
version's.

- [ ] **Step 1: Failing tests:**
  - `test_get_packs_enqueues_and_lists`;
  - `test_build_202_idempotent`;
  - `test_details_put_and_422`;
  - `test_items_tick_untick_add`;
  - `test_download_own_file`;
  - **`test_file_download_is_per_student`**;
  - `test_approve_409_stale_and_incomplete`;
  - `test_approve_200_completes_task`;
  - `test_other_students_pack_404`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS, plus the legacy suite.
- [ ] **Step 5: Commit** `feat(os): packs API (Slice 6a Task 8)`.

### Task 9: Screens

**Files:**
- Create: `frontend/app/[workspaceId]/os-pack/page.tsx`, `frontend/components/os/pack.tsx`,
  `frontend/components/os/pack-details.tsx`, `frontend/lib/os-packs.ts`, `frontend/components/os/pack.test.tsx`
- Modify: `frontend/lib/api.ts` (**shared**): `getOsPacks`, `buildOsPack`, `saveOsPackDetails`,
  `updateOsPackItems`, `osPackFileUrl` (a header-auth download through `fetch`, then a blob, so there is no token
  in the URL), `approveOsPack`

- [ ] **Step 1: Failing Vitest tests:**
  - the status labels;
  - the checklist marks with reasons;
  - the download button only on `ready` document items;
  - copy buttons on data-sheet values;
  - gaps highlighted with the details link;
  - a source link on each instruction step;
  - fee status;
  - Approve disabled until complete;
  - the "You submit and pay yourself" line;
  - 360 px (no overflow classes);
  - the empty state.
- [ ] **Step 2: Run** `npx vitest run components/os/pack.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement**, following `components/os/documents.tsx`. The page polls every 4 s while `building`.
- [ ] **Step 4: Run** `npx vitest run`, `npx tsc --noEmit` and `NEXT_PUBLIC_OS_ENABLED=true npm run build`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(os): pack screens (Slice 6a Task 9)`. The PR names a Counsellor reviewer.

### Task 10: Gate test, crash test, final review

**Files:**
- Create: `tests/os/test_slice6a_gate.py`
- Modify: `tests/os/test_crash.py` (`test_crash_during_pack_build`, with `os.pack` workers killed while rendering)
- Modify: `docs/os/handoff/` (a Slice 6a handoff with rulings, deferred minors and next steps: 6b)

- [ ] **Step 1: Failing tests:**
  - `test_pack_end_to_end[germany_master|ireland_master|pakistan_bs]`. For each: a test student, confirmed
    documents (synthetic), approved SOP and CV (stored versions), entered details, ticks, then build → approve →
    `review_pack` is `done`, with no code change between routes.
  - `test_crash_during_pack_build`: one version per inputs, one file per SHA-256, nothing lost (Linux CI).
- [ ] **Step 2: Run.** Expected: FAIL until the fake-route fixtures are complete.
- [ ] **Step 3: Complete the fixtures** (the fake routes' facts and seed values).
- [ ] **Step 4: Run** the full OS suite, the legacy suite and the frontend checks. Expected: PASS.
- [ ] **Step 5:** One fresh final reviewer on the most capable model over
  `git diff <pai-os before Task 1>..<Task 10 tip>`, with the spec, this plan and the Review Focus list. Then one fix
  pass, each Critical or Important finding with a RED→GREEN test. Minors go to the handoff's deferred list.
- [ ] **Step 6: Commit** `test(os): Slice 6a gate and crash test (Task 10)`, and the handoff
  `docs(os): Slice 6a handoff`.
