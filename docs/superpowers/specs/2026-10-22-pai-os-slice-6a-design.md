# PAI OS Slice 6a: the application pack (design)

Date: 2026-10-22. Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (§3.2 application pack, renderer,
checklist validator, agents table; invariants 3, 4, 5, 8, 12; §6 Slice 6). Builds on Slices 0–5 on `pai-os`. The
owners split parent Slice 6 into **6a (this pack)** and **6b (the visa file)**, each with its own spec, plan and
build (2026-10-22).

**Goal.** For each programme, the student gets one working page with everything needed to apply in the portal
themselves:
- a data sheet of the commonly asked fields, with a copy button on each;
- every required file, ready in the portal's format and size;
- the approved SOP and CV as PDFs;
- a checklist;
- step-by-step instructions for that programme's application route, with its fees and deadline and a source on
  each step.

The student approves one exact pack version, which completes a plan task. **There is no AI in this slice.** The
student submits and pays; the OS never does (invariant 6).

**Done when:**
- the Germany test student builds and approves a complete pack;
- the fake Ireland and Pakistan BS routes do the same with no code change (invariant 12).

## 1. Decisions

| # | Topic | Decision |
|---|---|---|
| S6a-D1 | What the pack is | **A working page per programme**, not a bundle (owners, 2026-10-22). Portals take form fields and separate uploads, so the page gives copyable fields and one download per required file. |
| S6a-D2 | Required documents | **Three layers, as Slice 5's statement rules** (owners). (1) The **route default** list in the pack config, labelled as a default. (2) A new research field, **`required_documents`**, that overrides it per programme when confirmed with a quote. (3) **Student additions**: an item the student sees in the portal that is missing. The new field closes the playbook's `citation_from_fact: required_documents`. |
| S6a-D3 | Format and size | **Convert where safe, flag the rest** (owners). The renderer turns photos into PDF, merges pages, shrinks to the item's `max_mb` while keeping it legible, and names the file. What it cannot fix (an attested or certified copy, a translation, a file still too large) becomes `needs_action` with a plain instruction. **The original upload is never changed.** |
| S6a-D4 | Data sheet | **A per-route field list in the pack config** (owners). Each field has a label and a source: a confirmed profile key, or `entered`. `entered` fields are collected by one short form and stored as confirmed profile values with the source "entered by you" and no document (invariant 4: the student writes them). A missing value is shown as a gap, never guessed. |
| S6a-D5 | No AI | **The Pack generator agent is dropped from 6a**, as a deliberate change from the parent spec (owners, 2026-10-22; for all the owners to confirm, §11 Q1). Every part of the pack is rule-based. **What would justify adding it back:** needing to read unstructured, programme-specific instructions (for example a programme page's own upload rules). It would then be a tool-less actor whose output goes through the Slice 5 facts check and student approval. **The same question will be asked about the Compliance agent in 6b.** |
| S6a-D6 | Instructions | **Route YAML templates, one per `application_route` value** (owners). Each step is text with `{fact}` placeholders, filled from the programme's facts, plus a source: the fact's URL, or a citation from the playbook. A fact that is not confirmed is shown as "not confirmed yet" with its research link. No AI. |
| S6a-D7 | Approval (invariant 5) | **The student approves a pack version** (owners). A pack is an `os_artifacts` row of kind **`pack`**, one per programme. Its version text is a canonical JSON **manifest**: checklist results, data-sheet values, each file's SHA-256 (including the approved SOP and CV versions' SHA-256), the filled instructions, the fees, and the pack-config version. Approval stores the manifest's SHA-256. A rebuild with different inputs makes a new version, which drops the approval (Slice 5's rule). |
| S6a-D8 | Plan | **A new playbook task, `review_pack`** (student, `approve`, fan-out per programme), after `application_documents` and before the route's apply tasks. Approval completes it through the kernel, as Slice 5's approval completes `application_documents`. It is a playbook YAML change; the fake routes gain the same task. A task that becomes ready after the approval completes on the next `GET /packs` or `GET /inbox`, as in Slice 5. |
| S6a-D9 | Renderer | **PDF only, with ReportLab in `invariant` mode** (owners). It is pure Python, with no system libraries in the worker image, and the same inputs give byte-identical files. ReportLab renders the data sheet, the SOP and the CV. Pillow and `pypdf` (both already installed) convert the documents. `requirements.txt` is a shared file: the ReportLab pin goes in its own small PR with a Counsellor reviewer. |
| S6a-D10 | Where it runs | **A DBOS workflow, `os.pack`, in the worker**, enqueued by the API. Rendering is CPU-heavy and reads file bytes, so it stays out of the API process. The workflow ID is `pack:{tenant}:{student}:{programme}:{inputs_sha16}`, so the same inputs are built once. Rendered files are stored once per SHA-256. No file bytes go into DBOS step outputs (the Slice 3 rule). |
| S6a-D11 | Fees | Tuition and the semester contribution come from the existing research facts (`tuition_fee_non_eu_eur`, `semester_contribution_eur`). Application fees (for example uni-assist's) come from a **playbook constant with a citation**, as `uni_assist_lead_days` does (§11 Q2). Each fee shows its status (confirmed or unconfirmed) and source. |
| S6a-D12 | Route-neutral (invariant 12) | Data-sheet fields, checklist items, format rules and instruction templates are **per-route YAML** (`app/os/packs/<route>.yaml`), validated at startup. Python knows only generic item kinds (`document`, `statement`, `entered`, `manual`). No country, portal or currency name appears in Python. The fake Ireland and Pakistan BS routes must each build a complete pack with no code change. |

## 2. Components (`app/os/packs/`)

- **`config.py`:** the pack config model and loader.
  - **`data_sheet`:** sections, each with fields `{key, label, source: <profile key> | entered, required, hint}`.
  - **`checklist`:** the default items `{key, label, kind, ref, format?, note?}`, where `kind` is one of `document`
    (`ref`: a document type), `statement` (`ref`: `sop` | `cv`), `entered` (`ref`: a data-sheet field) or
    `manual`.
  - **`formats`:** a route default plus per-item overrides `{types: [pdf], max_mb, colour, notes: [...]}`. The notes
    become `needs_action` reasons, such as "attested copy".
  - **`instructions`:** `{<application_route value>: [{text, source}]}`. A `source` is `fact:<name>` (that fact's
    URL) or `citation:<playbook source id>`.
  - **`fees`:** the facts and playbook constants to show.
  - **Validated at startup** (`mount.py` and `worker.py`). It fails, naming the file and the key, on an unknown
    profile key, document type, statement kind, data-sheet field, `application_route` value, fact name or
    citation.
- **`checklist.py` (the checklist validator, a pure function):**
  - **Inputs:** the effective items (research `required_documents` if confirmed, else the route default, plus the
    student's additions), the student's documents and their state, the approved statement versions, the entered
    values, and the manual ticks.
  - **Output:** per item, `ready` | `missing` | `needs_action` (with reasons) | `manual` (ticked or not).
- **`datasheet.py`:** builds the sheet from confirmed profile values. It reports gaps (required fields with no
  value) and never guesses.
- **`instructions.py`:** fills the template for the programme's `application_route` from its facts. A missing or
  unconfirmed fact is marked "not confirmed yet", with the research link.
- **`render.py`:**
  - `render_sheet(...)`, `render_statement(text, ...)` (ReportLab, `invariant=1`, fixed fonts and metadata);
  - `convert_document(data, kind, fmt)`, which turns images into PDF, merges pages, and shrinks by lowering the
    image resolution down to a legibility floor (long side ≥ 1,600 px);
  - each returns `bytes | Unfixable(reason)`. There is a page cap and a pixel cap.
- **`manifest.py`:** builds the canonical JSON manifest (sorted keys, no timestamps) and its SHA-256.
- **`run.py`:** the `os.pack(student, programme)` workflow, with the steps `load` → `render` (one step per file,
  which stores the bytes in `os_pack_files` and returns only the SHA-256) → `manifest` → `store` (a new version
  only if the manifest SHA-256 changed) → `finish`. It is enqueued from the API with the deterministic ID in
  S6a-D10.
- **`approval.py`:**
  - checks that every non-manual item is `ready`, every manual item is ticked, and the given manifest SHA-256 is
    the current version's;
  - writes the approval;
  - completes `review_pack` through the kernel with `{artifacts: {pack: <manifest sha256>}}`.
- **`details.py`:** saves `entered` fields as profile values with the source `entered`.

## 3. Tables (Alembic `os` branch, `os_0009`; every table has `tenant_id`)

- **`os_pack_files`:** `sha256` (unique per tenant), `student_ref`, `programme_ref`, `item_key`, `filename`,
  `content_type`, `size`, `pages`, `data` (bytea), `created_at`.
- **`os_pack_items`:** the student's per-programme state: `student_ref`, `programme_ref`, `item_key`, `kind`
  (`added` | `ticked`), `label` (for added items), `at`. Unique on (student, programme, item_key, kind).
- **`os_profile_values`:** gains `source` (`document` | `entered`, default `document`), so an entered value names
  its source without a document (invariant 3, extended to "entered by you").
- **Reused:** `os_artifacts` (kind `pack`, with `programme_ref`), `os_artifact_versions` (the manifest as text) and
  `os_approvals`.

## 4. API (under `/v1/os/packs`; the student's own data only; writes need write access)

| Method and path | Purpose |
|---|---|
| `GET /` | Per programme in the student's plan: pack status (`building` \| `ready` \| `incomplete` \| `approved` \| `failed`), checklist, data sheet with gaps, instructions, fees, files (name, size, SHA-256), current version and approval |
| `POST /{programme}/build` | Enqueue a (re)build. `202`; the same inputs give the same workflow |
| `PUT /details` | Save `entered` fields: `{fields: {key: value}}`. Unknown keys are `422` |
| `PUT /{programme}/items` | `{tick: [keys], untick: [keys], add: [{label}]}` |
| `GET /{programme}/files/{sha256}` | Download one rendered file (`Content-Disposition` with its file name). Another student's file is `404` |
| `POST /{programme}/approve` | `{sha256}`. `409` if it is not the current version or the pack is incomplete |

## 5. Student screens (mobile-first, 360 px; behind `NEXT_PUBLIC_OS_ENABLED`)

`/<workspace>/os-pack`:

```
┌ Your application packs ───────────┐
│ TU Example · MSc Data · ready ✓   │
│ Uni Sample · MSc AI · 2 to do ⚠   │
└───────────────────────────────────┘
┌ Uni Sample · MSc AI ──────────────┐
│ How to apply (via uni-assist)     │
│ 1. Create an account … [source]   │
│ Fees: 75 € (confirmed) [source]   │
│ Deadline: 15 Jul 2027             │
│ Checklist                         │
│ ✓ Passport      [Download PDF]    │
│ ⚠ Degree: needs an attested copy  │
│ ☐ Paid the fee (tick when done)   │
│ Data sheet          [A few more…] │
│ Passport no.  AB1234567   [Copy]  │
│ Phone         — missing           │
│ [Approve pack]                    │
└───────────────────────────────────┘
```

- The page says plainly: "You submit and pay yourself. We never send anything for you."
- `frontend/lib/api.ts` is a shared file, so its PR needs a Counsellor reviewer.

## 6. Error handling

| Failure | Handling | Ends in |
|---|---|---|
| A file cannot be shrunk to `max_mb` at the legibility floor | not converted; the original is kept | item `needs_action`: "upload a smaller scan" |
| An unreadable or damaged upload | as in Slice 3 | item `needs_action`: "upload a clearer copy" |
| A required document not uploaded, or a statement not approved | — | item `missing`, with a link to the documents or statements page |
| A fact is missing or unconfirmed | shown, never guessed | "not confirmed yet" with the research link; it does not block approval |
| Rendering raises | DBOS step retry (max 3) | pack `failed`, with a Rebuild button |
| A source changes after approval (a new document, statement version or fact) | the next build makes a new version | the approval is dropped; the pack is `ready` again and needs approval |
| A document is deleted | its pack files are deleted; the pack is rebuilt | as above |
| Approve with a stale SHA-256 (an old tab) | refused | `409` (this avoids Slice 5 deferred minor 3) |

## 7. Invariants touched

- **3:** every fact and fee shown carries its source and status. An entered value names its source, "entered by
  you".
- **4:** profile values are set only by the student: confirmed from documents (Slice 3) or typed on the details
  form.
- **5:** approval is bound to the manifest's SHA-256, which binds every file's SHA-256 and the approved statements'
  SHA-256.
- **6:** no submit, payment or portal tool exists; the student acts.
- **7, 8:** DBOS step retries only; the build is idempotent per inputs; files are stored once per SHA-256.
- **11:** no Counsellor imports (Tach).
- **12:** the pack config is per-route YAML; the fake routes run unchanged.

## 8. Testing (TDD; the pre-push checks as before)

1. **Config:** the Germany, Ireland and Pakistan BS configs load. An unknown profile key, document type, route
   value, fact or citation stops startup, naming the file and the key.
2. **Checklist validator:** each item kind gives each outcome. Research `required_documents` overrides the
   default, and student additions appear.
3. **Data sheet:** values come from the profile; gaps are reported; an `entered` value is used and named as
   entered.
4. **Instructions:** a template is filled per route value; a missing fact gives "not confirmed yet" with its link.
5. **Renderer:**
   - the same inputs give byte-identical PDFs, and changed inputs give a new SHA-256;
   - an 8000×6000 EXIF-rotated photo becomes an upright PDF under `max_mb`;
   - a scan that cannot be shrunk becomes `Unfixable`;
   - the original upload's bytes are unchanged;
   - the page cap holds.
6. **Workflow:** one build per inputs; replay does not duplicate files or versions; no file bytes in step outputs;
   a crash test (Linux CI).
7. **Approval:** binds the manifest SHA-256; incomplete or stale is `409`; a new version drops the approval;
   `review_pack` completes through the kernel.
8. **API:** a student sees and downloads only their own packs and files; the details form refuses unknown keys.
9. **Gate test (`test_slice6a_gate.py`):** on Germany, the fake Ireland route and the fake Pakistan BS route, a test
   student goes from documents, approved statements and entered details to a complete approved pack, and
   `review_pack` is `done`, with no code change between routes.
10. **Screens (Vitest):**
    - the status labels;
    - checklist marks with reasons;
    - copy buttons;
    - gaps highlighted;
    - a source on each instruction step;
    - Approve enabled only when the pack is complete;
    - 360 px;
    - the empty state.

No billed run: there is no AI in this slice.

## 9. Done when (the slice gate)

- §8 is green in CI (`os` and `legacy`).
- The gate test passes on all three routes.
- One fresh final review has been done, with its fix pass.

## 10. Build order (one branch and PR per task, off `pai-os`; stack as the Slice 5 handoff §2 advises)

1. ReportLab pin (shared `requirements.txt`; Counsellor reviewer).
2. Pack config, loader and validation, plus the Germany and fake-route configs.
3. Tables `os_0009`, `ProfileStore` source, the pack store.
4. The `required_documents` research field and the `review_pack` playbook task (Germany and the fake routes).
5. Checklist validator, data sheet, instructions.
6. Renderer and document conversion.
7. Manifest, the `os.pack` workflow and approval.
8. API.
9. Screens (`api.ts` is shared).
10. Gate test, crash test, final review and fix pass.

## 11. Open questions for the owners

| # | Question | Proposal |
|---|---|---|
| Q1 | Confirm dropping the Pack generator agent from 6a (S6a-D5) | Drop it; add it back only to read unstructured, programme-specific instructions |
| Q2 | Application fees (for example uni-assist's): a playbook constant or a research fact? | A playbook constant with a citation, re-checked like the other constants |
| Q3 | How long are rendered pack files kept? | As long as their source documents (Slice 3 §11 Q1); deleted with them |
