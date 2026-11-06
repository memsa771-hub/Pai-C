# P1-T7: one upload entry point, the `DocumentFiles` port, fact proposals to the Vault — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every upload button posts to one endpoint, `POST /v1/files`. The file is stored once, in the Counsellor file store (`files` table, `app/files/storage.py`). When `CONNECT_ONE_UPLOAD` is on and the student picked a document type, the same upload also registers an OS document linked to that file. The OS keeps all its document features: types, checks, reader, cross-checks, confirmation, packs, visa file, consent gate and tenant isolation. It reads the bytes through a new port, `DocumentFiles` (P1-D2). After the student confirms a document on the OS confirm screen, its fact fields go to the Vault reconciler as proposals with evidence `shown`, linked to the file (R-16, row 6.7). With the Counsellor module off, the OS stores bytes in `os_document_files` exactly as today.

**Architecture:**
- **OS side.**
  - A new column, `os_documents.file_ref`, holds the Counsellor file ID. It is the document ID both products share.
  - A new port, `ports/document_files.py`, has these parts:
    - the host reads bytes with `read(student_ref, file_ref)`;
    - the host registers documents with `register(...)` and forgets them with `forget(...)`;
    - `enabled()` tells the OS whether the host part is on;
    - `on_deleted(student_ref, file_ref)` is the hook the OS calls when it deletes a document.
  - `DocumentStore.file_bytes` (`documents/store.py:87`) is the single place that changes.
  - A second new port, `ports/fact_proposals.py`, writes `fact_proposal.v1` rows to the OS outbox (channel `counsellor`) when the student confirms a document. Rows are delivered after commit, with the sweep as backup.
  - A live endpoint, `GET /v1/os/documents/{id}/vault-check`, compares each read field with StudentFacts.
- **Host side, in `backend/app/pai_os_bridge.py`.**
  - The read adapter, `document_file_bytes`. It runs in the API through `mount_os` and in the worker through `OS_DOCUMENT_FILES`.
  - `register_os_document`, `forget_os_document`, and the hooks for deletion and delivery.
  - `deliver_fact_proposals` and its place in `sweep_once`.
- **Counsellor side.**
  - `app/pai_c/connect/uploads.py` is the one upload function, called by `POST /v1/files` and `POST /v1/files/upload`.
  - `app/pai_c/connect/document_facts.py` with `document_facts.yaml` maps a confirmed fact to a Vault candidate. Proposals go through `MemoryCandidateService.propose` and then the existing reconcile job.
  - A small idempotence table, `pai_document_proposals`.
  - `GET /v1/uploads/options` and `POST /v1/uploads/{file_id}/os-document`.
- **Frontend.**
  - The type picker on the Counsellor Documents page.
  - The OS Documents page uploads through `POST /v1/files`.
  - The vault-check line on the confirm screen.
  - All of this applies only while `GET /v1/uploads/options` says `one_upload: true`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy (app ORM, OS Core), Alembic (two trees), DBOS worker, Next.js, pytest/vitest.

**Spec:** `docs/superpowers/specs/2026-11-04-p1-connection-core-design.md` §3.4, P1-D2, P1-D9, P1-D3 pattern; §5 T7; §7. Master: R-01, R-16, row 6.7, §4 (document files: "one store, one upload entry point"; facts read from documents: "OS documents propose; the Vault reconciler writes after the student confirms"), §9.2 (`FactProposalSink`), §9.3 rule 6.
- **Code map:** the session scratchpad `p1-t7-explore.md` (copied into the SDD workspace). All file:line references below come from it and were checked on `pc/p1-t7-one-upload` at 034dde2 (T1–T5).

**Test database for implementers.** This worktree runs alongside another task, so it uses its own Postgres database: `postgresql://os_test:os_test@localhost:5432/os_test_b`. Export it in your shell only, as `OS_TEST_DATABASE_URL`, before `pytest tests/os`. Never print it, never write it to a file, and never commit it.

## Global Constraints

- **Flags off means today, byte for byte.**
  - Every new backend path needs `part_on("CONNECT_ONE_UPLOAD")`, which is the flag plus the OS `counsellor` module (P1-D9). No new flag is added.
  - The OS cannot read host flags. It learns the host part through the `enabled()` callable the host configures on `ports/document_files`.
    - An unconfigured port means off. That covers the worker, the standalone tests and an OS without a host.
  - **One exception, on purpose (D-y6).** A document that already has a `file_ref` is read through the host adapter whenever an adapter is configured, flags or not. Its bytes live only there.
  - The per-field profile rule (D-y12) needs both `CONNECT_STUDENT_FACTS` (the StudentFacts host adapter answers) and the documents port `enabled()`. Any other combination keeps T4's per-type overlay unchanged.
  - Each task names the tests that prove the flags-off behaviour. Those tests already exist and must pass **unchanged**. Where a task extends `tests/test_connect_flags_off.py`, it compares against fixtures captured from the current code **before any change**.
  - New response fields are never added to existing response models. FastAPI would print them as `null` with the flags off. New data comes only from new endpoints (D-y5, D-y11).
- **Frozen.**
  - The v1 and v2 contracts are used as they are (hash tests in `tests/os/contracts/test_frozen.py` and `test_frozen_v2.py`). The new `fact_proposal.v1` (D-y8) gets its own hash-pinned schema in this PR.
  - Also frozen, and never touched:
    - `app/pai_c/**/*.md`, `app/pai_c/deep/**`, the planner/policy/voice prompts, `app/pai_c/playbooks/**`, `app/pai_c/policy/*.json` and `actions/`;
    - `docs/counselor/COUNSELOR_V3_PROMPTS.md`;
    - the model settings in `app/config.py`.
    - `python scripts/check_freeze.py --base origin/pai-connect` must pass.
  - `app/documents/**` and `app/routers/files.py` are Counsellor files but not frozen. The Counsellor lead (`@memsa771-hub`) reviews them.
  - The chat never says anything new. No change to the extractor prompt or to `app/memory/catalog/vault_catalog.json` (P1-D16).
- **Imports, names and checks.**
  - `app/os` never imports Counsellor code (Tach, `backend/tach.toml`). All glue lives in `backend/app/pai_os_bridge.py`.
  - The bridge imports `app.files.storage`, `app.routers.files` helpers and `app.pai_c.connect.*` lazily, inside functions, as T4–T6 do.
  - No country, institution, exam or qualification names in `app/os` Python (R-58, `tests/os/test_invariants.py`).
    - OS document-type YAMLs keep their keys.
    - The doc-type → authority map and the education families live in Counsellor data (`app/pai_c/connect/document_facts.yaml`).
  - Only the kernel changes plans and tasks. This task changes none.
  - DB changes go only through Alembic.
    - **OS tree:** `os_0022_document_file_ref.py`, `down_revision` T6's `os_0021` (T7 is built on top of T6, branch `pc/p1-t6-proposals`).
    - **Counsellor tree:** `128_document_proposals.py` on top of T6's `127_route_decision_request_key.py`.
    - One head each: `backend/scripts/check_alembic_heads.py`.
    - Re-check both heads after every rebase.
- **Clock.**
  - OS code takes the time from `app.os.clock.now()` (the rehearsal clock), never `datetime.now()`.
  - Counsellor code uses `datetime.now(timezone.utc)` as its neighbours do.
  - Proposal keys use the stored `confirmed_at`, never "now", so a retry yields the same key.
- **Privacy.**
  - A fact proposal carries only fields whose type field declares `fact:` (marks, GPA and scale, test scores). Never a name, date of birth, passport number or other document value.
  - Logs carry IDs and class names, never values or bytes. File bytes never enter a DBOS step output (`documents/run.py` docstring).
- **Every new student-facing sentence is marked "approved by the owner".**
  - It lives in a data file with `approved: true`, never in code.
  - The owner approved T-series student sentences in chat: "you dont need to open PRs for such silly student sentences just update it directly".
  - Loaders fail at import when a listed key is missing.
- **Process.**
  - Run `tach check` and `pytest tests/os` before pushing OS code. Never run them alongside the legacy suite: run the legacy suite and `tests/os` one after the other.
  - Never weaken a test. A test whose expectation changes on purpose (the "interim: removed by T7" tests) is named in the commit message with the reason.
  - Tag tests with `@pytest.mark.req("R-xx")` or `// req: R-xx`. Commit messages end with the session attribution lines.
  - Fictional students only. No live model calls: the OS reader runs offline with canned answers (`OS_MODEL_MODE=offline`), and the Counsellor extractor is stubbed in the tests.

## Decisions taken in this plan (within the spec; flagged to the owner in the PR)

- **D-y1, the shared document ID.**
  - The Counsellor file ID (`files.id`, a UUID string) is "the document ID" of §3.4. The OS keeps its own BIGINT primary key.
  - The OS migration adds `os_documents.file_ref TEXT NULL` and a partial unique index `uq_os_documents_file_ref (tenant_id, file_ref) WHERE file_ref IS NOT NULL AND status <> 'deleted'`.
  - A row with `file_ref` has **no** `os_document_files` row.
  - The Counsellor side stores no OS IDs. The link lives only on the OS document, so there is no second copy (R-01).
- **D-y2, the one endpoint.**
  - `POST /v1/files` (and `POST /v1/files/upload`) take an optional form field `doc_type`. The agent routes `/files/base64` and `/files/from_url` take none: an agent never picks a type.
  - Both routes call one function, `app/pai_c/connect/uploads.py` `register_typed(db, workspace_id, file_id, data, filename, doc_type)`, after the `FileRecord` flush.
  - **Off, or no `doc_type`:** a `doc_type` field is ignored, and the response is today's bytes.
  - **On, with `doc_type`:** the response gains `os_document: {id, status} | {refused: code, note}`. This is a new key, present only on this path.
  - With the part on, the OS route `POST /v1/os/documents` answers 409 `{"detail": <use_documents_page sentence>}`. The OS learns this from `document_files.enabled()`. It stops being a second store for a connected student. With the part off it is exactly today's route (standalone, P1-D2).
- **D-y3, uploads without a type.**
  - Chat attachments, request-card uploads and agent uploads have no type picker. They stay Counsellor files with today's Counsellor document pipeline.
  - The student can make any of their files an OS document later, by picking a type: `POST /v1/uploads/{file_id}/os-document {doc_type}`. It runs the same `register_typed` on the stored bytes.
  - This is how the chat, the Vault fact card and the request card reach the OS ("any screen", row 6.7) without a type picker in chat. Chat turns stay untouched (§10).
- **D-y4, one reader per typed file.**
  - When a typed upload registers an OS document, the Counsellor pipeline still parses and indexes the file, so the chat can still read it (`files.read`). It does **not** run its own extraction.
  - The mechanism: `DocumentArtifactService.register_and_enqueue(..., extract=False)` puts `extract: false` in the parse job payload. `parse_document_job` then skips the `JOB_DOCUMENT_EXTRACT` enqueue (`handlers.py:~189`).
  - So facts from a typed document enter the Vault only after the student confirms it on the OS screen (row 6.7), with no double model cost.
  - Untyped files keep today's extraction.
- **D-y5, how the frontend knows.**
  - A new endpoint, `GET /v1/uploads/options?network=`. It answers `{"one_upload": false}` while the part is off. While it is on, it answers `{"one_upload": true, "doc_types": [{key, label}], "text": {...}}`, with the types read from the OS through `bridge.document_types()` and the text from `upload_texts.yaml`.
  - This new endpoint is the only channel. Existing endpoints do not change shape.
- **D-y6, reading bytes.**
  - `DocumentStore.file_bytes(doc_id)` reads the row (tenant filtered). With a `file_ref`, it calls `document_files.read(student_ref, file_ref)`; with no adapter configured, that is `KeyError`, as for a missing file today. Otherwise it reads `os_document_files` as today.
  - The host adapter checks four things:
    - the `FileRecord` exists;
    - its `workspace_id == student_ref`;
    - its `status == "active"`;
    - then it calls `get_file_store().read(storage_key)`.
    - Any failure is `KeyError` (the caller's existing "deleted since the check" path, `run.py:241`).
  - The worker loads the adapter from `OS_DOCUMENT_FILES=app.pai_os_bridge:document_file_bytes`. An unloadable value stops the worker, like `OS_STUDENT_FACTS`. Compose sets it. The shared `files` volume already exists (`docker-compose.yml:66-68`).
- **D-y7, deletion in both places.**
  - **OS delete** (`DELETE /v1/os/documents/{id}`) of a document with `file_ref`:
    1. Today's `delete_document`: fields, profile values, workflows and pack files.
    2. Then `document_files.on_deleted(student_ref, file_ref)`, which the host turns into a **purge** of the file: its bytes, the record and the derived document state, the same as `purge_trash` (`files.py:1384-1478`). The OS delete promises that the content is gone (S3-D10).
  - **Counsellor delete** (`DELETE /v1/files/{id}`, or `POST /v1/files/trash` for files and folders):
    1. The bridge calls `document_files.forget(student_ref, file_ref)` for each file, which runs the OS `delete_document` on the linked document.
    2. The file stays restorable in the trash as today, but restoring it does not bring the OS document back. The student registers it again.
  - A purge after a trash finds no live OS document and does nothing more.
  - Vault facts learned from the document are **not** retracted. That is today's Counsellor rule (`files.py:1433-1437`), applied the same way (see "Ruling problems" 6).
- **D-y8, the proposal contract.**
  - Master §9.2 names `FactProposalSink.propose`, but §9.1 has no contract for it. This plan adds `app/os/contracts/fact_proposal.py` plus `fact_proposal.v1.schema.json`, hash-pinned in `tests/os/contracts/test_frozen_v2.py`. Both teams review it in this PR.
  - Fields: `schema` (`pai.fact_proposal.v1`), `key`, `student_ref`, `document_ref` (the `file_ref`, or `os:<id>` for an OS-only document), `doc_type`, `confirmed_at`, and `facts: [{key, value}]`.
    - `key` matches `^[a-z0-9_:.-]+$`. `confirmed_at` is aware.
    - Each fact key matches `FACT_KEY`, and the list has 1–20 unique items.
  - The model uses `extra="forbid"` and `frozen=True`.
- **D-y9, delivery and idempotence.**
  - `confirm_document` (`confirm.py:30`) then emits in one OS transaction. The emit happens only when `document_files.enabled()` holds and the type has at least one `fact:` field with a non-empty confirmed value.
    - The row: channel `counsellor`, template `fact_proposal`, recipient `student_ref`, key `fact_proposal:{doc_id}:{confirmed_at in epoch microseconds}` (not `isoformat()`: its capital T and plus sign break the key pattern `^[a-z0-9_:.-]+$`; the stored `confirmed_at` is still what makes the key), `on_conflict_do_nothing(uq_os_outbox_key)`.
  - After the route returns, `notify(key)` calls the host hook. Errors are swallowed and the class name is logged.
  - The sweep is the backup. It delivers the pending rows. It also runs `backfill()`, which emits for every `confirmed` document of a Counsellor-mode student that has fact fields and no row yet; this covers a crash between the confirm and the emit, and documents confirmed before the part was on.
  - The Counsellor side records each delivered key in a new table `pai_document_proposals`: `key` unique, `workspace_id`, `file_id NULL`, `candidate_ids JSON`, `created_at`. A repeat delivery answers `duplicate` and proposes nothing.
  - The OS marks the row `sent` on `written` or `duplicate`, and `skipped` on `refused`, with the code kept in `payload.outcome`.
- **D-y10, the mapping to Vault candidates (Counsellor data).** `app/pai_c/connect/document_facts.yaml` holds:
  - `authority` per OS doc type: `institution_issued` for the school and university certificates and the transcript, `test_provider_issued` for the test report;
  - the education families, reusing `student_facts_keys.yaml`;
  - `new_record_code` per family (the catalog `levels` code used when the Vault has no record of that family).

  For `education.<family>.<field>`:
  - one `student_record` / `education` candidate per family;
  - the record is chosen exactly as `_record_facts` chooses it (`student_facts.py`), and its id goes in `entities.record_id`;
  - `proposed_value.result` holds the fields, with `part1.x` → `result.part1.x`.

  For `test.<type>.score`, the candidate is one `student_record` / `test_attempt` with `test_type` (the catalog name for the code) and `overall_score`.
  - The candidate's `source_type` and `input_channel` are both `document`.
  - Its evidence is `{file_id, filename, authority, os_document_id, os_doc_type, os_confirmed: true}`. With a Counsellor file, that gives evidence `shown` (`evidence.py evidence_level`).
  - Then `enqueue(JOB_RECONCILE, idempotency_key=f"reconcile:os_document:{key}")`, as documents do (`handlers.py:533-541`).
  - The reconciler's own conflict rule decides; for these types it is `evidence_wins`. Its accept hook raises the Vault version and writes the `vault_event` (T4), so the OS replans through row 6.8.
- **D-y11, "every field compared with the Vault" (R-16).** `GET /v1/os/documents/{id}/vault-check` (student-owned, new) compares live and stores nothing. The OS never stores a Vault value (R-01).
  - It answers `{"fields": [{"field", "outcome": "same"|"differs"|"new"|"not_compared"}], "note": <vault_differs sentence or null>}`.
  - For every field of the type with `fact:`, it compares the confirmed value (else the read value) with `student_facts.get(student_ref)`:
    - numbers are compared as floats, to 1e-9;
    - text is compared case-folded and with the whitespace collapsed;
    - a Vault `unknown` or missing value → `new`.
  - Fields without `fact:` → `not_compared`.
  - While the port is off, or the StudentFacts host adapter does not answer, it returns 404.
  - Resolving a difference is T8's "which is right" step. T7 only shows it.
- **D-y12, the interim overlay becomes a per-field rule.**
  - With both parts on, `profile_of` (`eligibility/notes.py:25-41`) builds the profile in two halves:
    - fields whose type field declares `fact:` come **only** from StudentFacts;
    - fields with no `fact:` key keep coming from `os_profile_values`. Example: `min_passing_grade_letter.min_pass` and `scale_best`, for which the Vault has no type (P1-D16 forbids new catalog types here).
  - With only `CONNECT_STUDENT_FACTS` on, T4's per-type overlay stays as it is.
  - The "interim" comments are removed. The four `interim: removed by T7` tests become two sets:
    - with ONE_UPLOAD off, they stay unchanged;
    - with both on, new expectations, named in the commit.
  - Packs (`packs/inputs.py:87`) and statements (`statements/run.py:58`) keep reading the document's own confirmed reading in `os_profile_values` (document data for the attached file). See "Ruling problems" 4.
- **D-y13, OS-only documents of a connected student.**
  - A document uploaded before the part was on keeps its bytes in `os_document_files` (P1-D2). No byte move is made in T7.
  - Its proposal carries `document_ref: "os:<id>"` and evidence without a `file_id`, so the Vault records it as `stated`, not `shown`. That is honest: the Counsellor store does not hold the file.
- **D-y14, `plan_view.documents_needed` (T5).**
  - While `document_files.enabled()` holds, `plan_view.build` fills `documents_needed` from the plan route's pack config checklist, items of kind `document` (`svc.pack_configs[route_key]`), with a status for each:
    - none → `missing`;
    - `uploaded`, `reading`, `read` or `needs_student` → `uploaded`;
    - `confirmed` → `confirmed`.
  - Otherwise it stays `[]`, exactly T5's output.
  - T9 renders it on "My plan". This also prepares §9.3 rule 6 for T10.
- **D-y15, student sentences, approved by the owner (stored `approved: true`).**
  - `backend/app/pai_c/connect/upload_texts.yaml`, version 1:
    - `type_label`: "What is this document?"
    - `type_none`: "Something else"
    - `registered`: "Saved. PAI will read it and ask you to check what it found."
    - `consent_needed`: "Saved. To let PAI read it, first agree to the pilot terms on your study documents page."
    - `duplicate`: "Saved. This file is already in your study documents."
    - `unknown_type`: "Saved. PAI cannot read this kind of document yet."
    - `not_readable`: "Saved. PAI can read PDF, JPEG, PNG or WebP files only."
  - `backend/app/os/documents/connect_texts.yaml`, version 1:
    - `use_documents_page`: "Upload your documents from the Documents page."
    - `vault_differs`: "PAI has a different value saved for this. Check which one is right."

## Ruling problems found (reported to the controller)

1. **"Registers an OS document with the same document ID" cannot be done literally.** OS document IDs are BIGINT (`models.py:303`), and Counsellor file IDs are UUID text (`models.py:435`). This plan uses one shared ID, the Counsellor file ID, carried on the OS row as `file_ref` (D-y1). Nothing in the OS API changes its integer `id`.
2. **"Every upload button … with the document type the student picked" does not fit the chat.** The chat and the agents have no type picker, and adding one to chat turns would touch the frozen conversation. The chat still posts to the one endpoint, and the type is picked later on the Documents page (D-y3). Please confirm.
3. **`FactProposalSink` has no contract in master §9.1.** A new `fact_proposal.v1` is added (D-y8). It needs both teams' sign-off in the PR.
4. **The interim overlay cannot be "removed" in full.** The Germany playbook needs `min_passing_grade_letter.min_pass` and `scale_best` (`germany_master.v1.yaml:39-42`), and the Vault has no type for them. P1-D16 rules out new catalog types without a freeze exception. This plan:
   - narrows the overlay to fields with no Vault key (D-y12);
   - leaves packs and statements on the attached document's confirmed reading.

   If the owner wants these values Vault-owned too, that is a new catalog type and a freeze decision, not T7.
5. **R-01 is "built" only when every §4 row has one owner.** The choice row with the Counsellor on needs T6's builder through the decision service (R-09). T7 sets `R-01: built: true` only if T6 is merged on `pai-connect` when Task 6 runs, and the owner accepts item 4. Otherwise it leaves R-01 false and says why in the PR. R-16 is set either way.
6. **"Deletion deletes in both places" versus the Vault.** The file and the OS document go, but Vault facts already learned from the document stay. That is the existing Counsellor rule ("a purge is not a retraction", `files.py:1433-1437`, `service.py:248-254`). The plan keeps it. Please confirm that this is what the owner means.
7. **Evidence level.** The spec says `shown`, although the student confirmed the value. `confirmed` in the Vault means the student confirmed it on the Vault's own profile screen (`evidence.py`, `profile_confirmation`). The plan follows the spec: `shown`, plus `os_confirmed: true` in the evidence.
8. **Two document paths into the Vault remain.** These are the Counsellor extractor for untyped uploads and the OS confirmation for typed ones. Both write only through the reconciler, so R-16 ("one owner") holds. The overlap is ended per file by D-y4.

## Review Focus

1. **Isolation.**
   - Student A's `file_ref` named on student B's OS document is never read.
   - Another tenant's `doc_id` raises `KeyError`.
   - A trashed or purged file is never read.
   - → Task 1 and Task 2 tests.
2. **A crash between the OS confirm and the emit, or a repeated delivery.**
   - There is exactly one set of candidates and one reconcile job.
   - → Task 3 tests.
3. **Flags off.**
   - `/v1/files` responses and `/v1/os/documents` behave byte for byte as today.
   - The Counsellor extraction still runs.
   - No OS port is called.
   - → the flags-off tests named in every task.
4. **The per-field profile rule.**
   - With STUDENT_FACTS on and ONE_UPLOAD off, it is identical to T4.
   - With both on, a fact-mapped field never comes from `os_profile_values`.
   - → Task 4.
5. **Deletion order.**
   - The OS delete commits before the host purge. A purge that fails leaves the file record in place (retried by the student) and never a live OS document pointing at nothing.
   - → Task 2.

---

### Task 1: OS — `file_ref`, the `DocumentFiles` port, the byte change point, register and forget

**R-IDs:** R-01 (one store for bytes), row 6.7 (OS half).

**Files:**
- Create: `backend/alembic/versions_os/os_0022_document_file_ref.py` (number per Global Constraints). It adds the column `file_ref` and the index `uq_os_documents_file_ref`. The downgrade drops both, and refuses if a row with `file_ref` has no bytes. It is self-contained like `os_0020_vault_events.py`.
- Create: `backend/app/os/ports/document_files.py`. It mirrors `ports/student_facts.py`:
  - `configure(read=None, enabled=None, on_deleted=None)`;
  - `current()`;
  - `load(spec)` / `from_settings(settings)`, raising `DocumentFilesSourceError` that names `OS_DOCUMENT_FILES` and never a value;
  - `enabled() -> bool` (False when unconfigured or on any exception);
  - `read(student_ref, file_ref) -> bytes` (`KeyError` when unconfigured);
  - `register(student_ref, doc_type, file_ref, filename, data) -> dict`;
  - `forget(student_ref, file_ref) -> bool`.
  - `register` and `forget` use the mounted services (`ports.services()`).
  - `register` runs these checks in order and raises `Refused(code)`:
    1. `enabled()` → `not_on`;
    2. the type is known → `unknown_type`;
    3. the pilot consent → `consent_needed` / `terms_not_set`, through the new `consent/gate.py` shared with `consented_student`;
    4. `check_upload` → `not_readable`;
    5. `DocumentStore.create_ref` → `duplicate`.
  - Then `enqueue_document`. It returns `{"id", "status"}`.
- Create: `backend/app/os/consent/gate.py`: `upload_refusal(svc, student) -> str | None`. This is the body of `router.py:134-143`, moved; the router dependency calls it, with the same 409 bodies.
- Create: `backend/app/os/documents/connect_texts.yaml` and the loader `connect_texts.py` (`text(key)`; fails at import on a missing key). D-y15 — **approved by the owner, stored approved: true.**
- Modify:
  - `backend/app/os/models.py` `documents` (:303-327): `file_ref` and the index.
  - `backend/app/os/documents/store.py`:
    - `Document` gains `file_ref`;
    - new `create_ref(student_ref, doc_type, type_version, filename, content_type, data, file_ref)` writes the row with the SHA and size of `data`, and no `B` row;
    - `file_bytes` (:87) reads `student_ref, file_ref` with `self._mine(doc_id)` first, then the port when `file_ref` is set, else `B` as today;
    - `delete` (:135) is unchanged.
  - `backend/app/os/documents/confirm.py` `delete_document` (:72): after today's steps, when `doc.file_ref` is set, it calls `document_files.on_deleted(doc.student_ref, doc.file_ref)` and swallows any error, logging the class name only. The host purge is idempotent and the trash still holds nothing live.
  - `backend/app/os/api/router.py`:
    - `upload_document` (:369): while `document_files.enabled()`, it answers 409 `{"detail": connect_texts.text("use_documents_page")}` **before** reading the body;
    - `consented_student` uses `gate.upload_refusal`.
  - `backend/app/os/api/mount.py` `mount_os` (:32-77) and `backend/app/os/ports/__init__.py` `configure` (:24): new keyword args `document_files=`, `documents_enabled=` and `on_document_deleted=`. All default to None, which means today's behaviour.
  - `backend/app/os/settings.py` (:22, :104): `document_files` from `OS_DOCUMENT_FILES`.
  - `backend/app/os/runner/worker.py` (:272-276): also `document_files.from_settings(settings)`, and it calls `configure(read=…)`.
  - `docker-compose.yml` os-worker (:186): `OS_DOCUMENT_FILES: app.pai_os_bridge:document_file_bytes`.
- Tests: new `backend/tests/os/test_document_files_port.py`, `backend/tests/os/test_os_0022_file_ref.py`; extend `tests/os/test_document_store.py` (new cases only).

- [ ] **Step 1: Write the failing tests (`@pytest.mark.req("R-01")`).**
  - `test_file_ref_upgrade_downgrade`:
    - after the upgrade, two live rows with one `file_ref` raise `IntegrityError`;
    - a deleted one plus a live one insert;
    - the downgrade works on an empty table;
    - `check_alembic_heads.py` reports one OS head.
  - `test_create_ref_stores_no_bytes`: the row has `file_ref` and the right SHA, and `os_document_files` has no row.
  - `test_file_bytes_reads_through_the_port_with_the_documents_student`: a fake `read` records `(student_ref, file_ref)` and returns bytes.
  - `test_file_bytes_without_an_adapter_is_keyerror`, and `test_file_bytes_other_tenant_is_keyerror`.
  - `test_file_bytes_standalone_row_reads_os_document_files`: no `file_ref`, the port configured, and the port is not called.
  - `test_register_refusals_in_order`: `not_on`, `unknown_type`, `consent_needed`, `not_readable` (a `.pdf` named text), `duplicate` (the same bytes twice).
  - `test_register_enqueues_the_document_workflow`: a fake DBOS client records one enqueue, with the workflow id `document:pai:{id}:{sha16}`.
  - `test_worker_reads_a_registered_document`: run `os.document` through the existing `test_document_run.py` harness with a ref-backed document and a configured `read`. The fields are stored, and `check_file` and the reading each call `read` exactly once.
  - `test_forget_deletes_the_linked_document_only`: `forget(A, ref)` deletes A's document; `forget(B, ref)` returns False and deletes nothing.
  - `test_os_delete_calls_on_deleted_after_the_delete`: the hook sees `status == "deleted"`, and a hook that raises still leaves the delete done.
  - `test_upload_route_refuses_while_enabled`: 409, with the YAML sentence.
  - `test_load_names_the_setting_and_never_a_value`.
  - `test_worker_refuses_to_start_with_a_bad_os_document_files`.
  - **Flags-off proof:**
    - `tests/os/test_api_documents.py`, `test_document_store.py`, `test_document_run.py`, `test_api_packs.py`, `test_api_visa.py`, `test_pack_run.py` and `test_api_consent.py`, `test_consent_pause.py` pass **unchanged**;
    - new `test_unconfigured_port_upload_is_todays_route`: a byte-equal response body and the `os_document_files` row present.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new files, then `tests/os -k "document or pack or visa or consent"`, then `tach check`, then `tests/os/test_invariants.py`.
- [ ] **Step 5: Commit** `feat(os): documents read their bytes through the DocumentFiles port (R-01, P1-D2)`.

### Task 2: Counsellor — the one upload endpoint, registration, the read adapter, deletion both ways

**R-IDs:** R-01, row 6.7.

**Files:**
- Create: `backend/app/pai_c/connect/uploads.py`:
  - `register_typed(db, workspace_id, file_id, data, filename, doc_type) -> dict`. It calls `bridge.register_os_document`, maps `Refused(code)` to `{"refused": code, "note": text(code)}` and success to `{"id", "status", "note": text("registered")}`.
  - `options() -> dict` (D-y5).
- Create: `backend/app/pai_c/connect/upload_texts.yaml` and its loader inside `uploads.py`. D-y15 — **approved by the owner, stored approved: true.**
- Create: `backend/app/routers/uploads.py`:
  - `GET /v1/uploads/options` (workspace auth like `files.py`);
  - `POST /v1/uploads/{file_id}/os-document`. It requires the signed-in student (`resolve_human`) and an active `FileRecord` of the workspace; 404 otherwise. Without the part it answers 409. It reads the bytes through `get_file_store()` and calls `register_typed`.
  - Registered in `backend/app/main.py` with the other routers (:425).
- Modify:
  - `backend/app/routers/files.py`:
    - `upload_file` (:447) and `upload_files_to_folder` (:870) take `doc_type: Optional[str] = Form(None)`.
    - After the `FileRecord` flush, when `doc_type` is set and `part_on("CONNECT_ONE_UPLOAD")`, they call `register_typed`, then `_register_student_document(..., extract=not registered)`.
    - The response adds `os_document` only on that path.
    - `delete_file` (:1912) and `move_to_trash` (:1146): when the part is on, they call `bridge.forget_os_document(workspace_id, file_id)` for each trashed record, **after** `db.commit()`. Errors are logged as class names, and the trash still succeeds.
    - `_register_student_document` (:70) gains `extract: bool = True`.
  - `backend/app/documents/service.py` `register_and_enqueue` (:226) and `enqueue_parse`: `extract=True` → the parse payload gains `"extract": False` only when false.
  - `backend/app/documents/handlers.py` `parse_document_job` (:~189): the extract enqueue is skipped when `payload.get("extract") is False`.
  - `backend/app/pai_os_bridge.py`. Each new function catches `ports.OsUnavailable`, as `route_supported` does:
    - `document_file_bytes(student_ref, file_ref) -> bytes`. It opens its own `new_session`, then checks the `FileRecord` id, `workspace_id == student_ref` and `status == "active"`, then calls `get_file_store().read(storage_key)`. Any miss is `KeyError`.
    - `register_os_document(...)`.
    - `forget_os_document(workspace_id, file_id)`.
    - `document_types() -> list[dict]`.
    - `documents_enabled() -> bool` = `part_on("CONNECT_ONE_UPLOAD")`.
    - `on_os_document_deleted(student_ref, file_ref)`: it purges the file like `purge_trash` (bytes, `purge_for_files`, the unindex job, the record delete) in its own session, and is idempotent when the record is gone.
  - `backend/app/main.py` (:477-478): `mount_os(..., document_files=document_file_bytes, documents_enabled=documents_enabled, on_document_deleted=on_os_document_deleted)`.
- Tests: new `backend/tests/test_one_upload_api.py` (SQLite; the bridge port functions monkeypatched), `backend/tests/os/test_one_upload_bridge.py` (Postgres OS plus the app session, built on the `world` pattern of `tests/os/test_connect_t5_flow.py:34-53`); extend `tests/test_connect_flags_off.py`, `tests/documents/test_parse_job.py` (new cases only).

- [ ] **Step 1: Write the failing tests (`@pytest.mark.req("R-01")`).**
  - `test_typed_upload_stores_once_and_registers` (on):
    - one `FileRecord`;
    - bytes in the file store;
    - the response has `os_document.id`;
    - the OS row's `file_ref` is the file id;
    - `os_document_files` is empty.
  - `test_typed_upload_skips_counsellor_extraction`: the parse job payload has `extract: False`; after the parse job, no `document.extract` job exists, and `document.index` still runs when recall is on.
  - `test_untyped_upload_runs_todays_pipeline_even_when_on`.
  - `test_refused_registration_keeps_the_file`: `consent_needed`, `duplicate` and `not_readable` each give 200, the file stored, and `os_document.refused` with the YAML note.
  - `test_register_later_from_a_chat_attachment`: `POST /v1/uploads/{id}/os-document` registers. Another workspace's file gives 404. With the part off it gives 409.
  - `test_options_off_and_on`: off → exactly `{"one_upload": false}`; on → the types from the OS and the text from the YAML.
  - `test_adapter_refuses_other_students_and_trashed_files` (Review Focus 1).
  - `test_counsellor_trash_forgets_the_os_document`: the OS row is `deleted`, its fields are gone, the file is in the trash, and a restore does not bring the OS document back.
  - `test_os_delete_purges_the_counsellor_file` (Review Focus 5):
    - the record and the bytes are gone, and the `DocumentArtifact` is purged;
    - a second call is a no-op;
    - a purge that raises leaves the OS document `deleted` and the file record present.
  - `test_os_upload_route_answers_409_while_on`.
  - **Flags-off proof:**
    - In `tests/test_connect_flags_off.py`, `test_t7_upload_responses_unchanged`: `POST /v1/files` (with and without `doc_type`), `/v1/files/upload`, `/v1/files/base64`, `DELETE /v1/files/{id}` and `/v1/files/trash` give bodies equal to fixtures captured **before** the change (ids and times masked). Every `pai_os_bridge` document function is patched to raise, so none is called. A parse job is followed by an extract job, as today.
    - `tests/documents/*`, `tests/test_upload_limits.py`, `tests/test_os_route_detachment.py` and `tests/test_p0_entry_audit.py` pass unchanged.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run:**
  1. the legacy files (`--ignore=tests/os`);
  2. then, separately, `tests/os/test_one_upload_bridge.py` plus `tests/os -k document`;
  3. then `tach check`, `check_freeze.py --base origin/pai-connect` and the R-58 test.
- [ ] **Step 5: Commit** `feat(connect): one upload entry point; the OS reads files from the Counsellor store (R-01, row 6.7)`.

### Task 3: Fact proposals — contract, OS outbox at confirm, Counsellor sink, delivery and backfill

**R-IDs:** R-16, R-01 (facts read from documents), row 6.7 ("facts enter the Vault after confirmation").

**Files:**
- Create: `backend/app/os/contracts/fact_proposal.py` and `fact_proposal.v1.schema.json` (D-y8). Extend `tests/os/contracts/test_frozen_v2.py` with its hash, and `test_contracts_v2.py` with the samples.
- Create: `backend/app/os/ports/fact_proposals.py`. It mirrors the T6 `choice_requests` port shape:
  - `configure(on_proposal=None)`;
  - `facts_of(doc, types, values) -> list[dict]` (the `fact:` fields with non-empty values);
  - `emit(conn, tenant_id, doc, facts) -> str | None`;
  - `pending(limit=100) -> list[FactProposalV1]`;
  - `mark(key, outcome)`;
  - `notify(key)`, which swallows errors;
  - `backfill(limit=100) -> int`, which emits for `confirmed` documents of students with an applied Counsellor intake (`counsellor_intake`) and no row.
- Create: `backend/alembic/versions/128_document_proposals.py` (number per Global Constraints): the table `pai_document_proposals` (D-y9). Add the model `DocumentProposal` in `backend/app/models.py`.
- Create: `backend/app/pai_c/connect/document_facts.py` and `document_facts.yaml` (D-y10). `apply(db, proposal: dict) -> tuple[str, list[str]]`:
  - `written` (with the candidate ids), or `duplicate`;
  - `refused`, with the codes `no_workspace`, `no_mapping` and `file_not_yours`.
    - `file_not_yours` means the `file_id`'s workspace differs from `student_ref`. A `document_ref` of the form `os:<id>` has no file and is fine.
  - It does not import `app.os`.
- Modify:
  - `backend/app/os/documents/confirm.py` `confirm_document` (:30-52). After today's writes, when `document_files.enabled()`, it opens `engine.begin()` → `fact_proposals.emit(...)` and returns the key, or None. The router calls `fact_proposals.notify(key)` after the response is built (`router.py:397-411`).
  - `backend/app/os/api/mount.py`, `ports/__init__.py`: the keyword arg `on_fact_proposal=`.
  - `backend/app/pai_os_bridge.py`:
    - `deliver_fact_proposals(db) -> dict`. For each `pending()` row: `document_facts.apply`, then `db.commit()`, then `mark`. An exception rolls back and leaves the row pending (class name logged).
    - `deliver_fact_proposal_now(key)`, which opens its own session.
    - `sweep_once` (:167-188): when `part_on("CONNECT_ONE_UPLOAD")`, it runs `fact_proposals.backfill()` and `deliver_fact_proposals(db)` **before** `deliver_pending`, so the resulting `vault_event` rows go out in the same sweep.
  - `backend/app/main.py`: `on_fact_proposal=deliver_fact_proposal_now`.
- Tests: new `backend/tests/test_document_facts.py` (SQLite, the Vault side alone, on `MemoryCandidateService` and `MemoryReconciler`, as `tests/os/test_connect_t4_flow.py:81-96` writes), `backend/tests/os/test_fact_proposals.py` (Postgres OS plus the app session); extend `tests/os/test_crash_counsellor_intake.py` only if its kill-point helper is reusable; otherwise put the kill points in `test_fact_proposals.py`.

- [ ] **Step 1: Write the failing tests (`@pytest.mark.req("R-16")`).**
  - `test_contract_rejects_names_and_extra_fields`: an `identity.full_name`-style value is not refused by the schema itself, so `facts_of` is tested to never emit a field without `fact:`. `extra` raises.
  - `test_confirm_emits_one_proposal_with_only_fact_fields`:
    - an `hssc_certificate` confirm → one outbox row with template `fact_proposal`;
    - its facts are `education.intermediate.marks_obtained` and `marks_total` only;
    - no name and no date of birth.
  - `test_reconfirm_emits_a_new_key_and_retry_does_not`.
  - `test_apply_writes_education_result_to_the_chosen_record`: with an existing `fsc` record (stated), the candidate has `entities.record_id` and `result.marks_obtained`. After reconcile, the record's evidence level is `shown` and `evidence.file_id` is the file.
  - `test_apply_new_record_uses_the_family_code`.
  - `test_apply_test_score_to_test_attempt`.
  - `test_repeat_delivery_is_duplicate_no_new_candidates` (Review Focus 2).
  - `test_file_of_another_workspace_is_refused`.
  - `test_os_only_document_is_stated` (D-y13).
  - `test_accept_raises_vault_version_and_queues_vault_event` (T4 hook, with `CONNECT_STUDENT_FACTS` on).
  - `test_backfill_covers_a_crash_between_confirm_and_emit`: kill `emit` → `backfill()` writes the row → one delivery → one candidate set.
  - `test_notify_errors_are_swallowed`.
  - **Flags-off proof:**
    - `test_confirm_with_port_off_writes_no_outbox_row`: the module is on and `enabled` is unconfigured.
    - `test_sweep_skips_fact_proposals_when_one_upload_off`: the rows stay pending, and no candidate is written.
    - `tests/os/test_api_documents.py`, `tests/test_pai_os_bridge.py`, `tests/os/test_connect_t4_flow.py` and `tests/os/test_connect_t5_flow.py` pass unchanged.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run:**
  1. the legacy files;
  2. then, separately, `tests/os -k "fact_proposal or document or contracts"`;
  3. then `tach check` and `check_alembic_heads.py`.
- [ ] **Step 5: Commit** `feat(connect): confirmed document facts become Vault proposals (R-16, row 6.7)`.

### Task 4: Compare with the Vault, the per-field profile rule, documents needed in the plan view

**R-IDs:** R-16 ("every field compared with the Vault"), R-01 (one source per fact), row 6.7.

**Files:**
- Modify:
  - `backend/app/os/api/router.py`: new `GET /documents/{doc_id}/vault-check` (D-y11). It uses `own_document`, `student_facts.host_facts` (no fallback to the standalone adapter: no host answer → 404) and `connect_texts.text("vault_differs")` when any outcome is `differs`.
  - `backend/app/os/api/schemas.py`: new `VaultCheckOut` (new model only).
  - `backend/app/os/documents/vault_check.py` (new, pure): `compare(type, values, facts) -> list[dict]`.
  - `backend/app/os/eligibility/notes.py` `profile_of` (:25-41): the D-y12 rule.
    - With `document_files.enabled()` and host facts: `{k: v for k, v in own.items() if k not in fact_fields(types)} | profile_from_facts(...)`.
    - Otherwise: today's T4 code, unchanged.
    - New helper `fact_fields(types)` in `eligibility/facts.py`.
  - `backend/app/os/plan_view.py` `build` (:~140): `documents_needed` per D-y14. It gets a new private helper `_documents_needed(svc, conn, student_ref, route_key)` and reads `svc.pack_configs`; a route with no pack config gives `[]`.
- Tests:
  - new: `backend/tests/os/test_vault_check.py`;
  - extend: `tests/os/test_student_facts_port.py` (:252-290), `tests/os/test_eligibility_notes.py` (:190-215) and `tests/os/test_plan_view.py` (new cases; the T5 cases stay as they are).

- [ ] **Step 1: Write the failing tests.**
  - `test_vault_check_outcomes` (R-16): same, differs (`700` vs `"700.0"` is the same; `700` vs `705` differs), new (Vault unknown), not_compared (`full_name`); the note is set only when something differs.
  - `test_vault_check_404_without_host_or_other_student`.
  - `test_vault_check_stores_nothing`: the row counts of every `os_*` table are unchanged.
  - `test_per_field_rule_with_both_parts_on` (R-01): `transcript.cgpa` is absent when the Vault lacks it, even with an `os_profile_values` row; `min_passing_grade_letter.min_pass` still comes from `os_profile_values`.
  - The four `interim: removed by T7` tests are kept unchanged under "ONE_UPLOAD off". Their "both on" twins carry the new expectations. Name all four in the commit message: "interim overlay replaced by the per-field rule (D-y12)".
  - `test_germany_eligibility_same_after_confirm_and_reconcile`: a confirmed transcript gives Vault `education.bachelor.gpa`, and the evaluator gives the same verdict as the T4 document profile.
  - `test_documents_needed_from_pack_checklist`: missing / uploaded / confirmed. With the port off it is `[]`.
  - **Flags-off proof:**
    - `test_flags_off_profile_is_exactly_todays_os_profile_values` (`test_student_facts_port.py:225`) passes unchanged;
    - `tests/os/test_plan_view.py`, `test_connect_t5_flow.py` and `test_eligibility_*.py` pass unchanged;
    - `tests/test_connect_flags_off.py` `test_roadmap_and_steps_are_byte_identical_to_the_pre_adapter_answers` passes unchanged.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/os -k "vault_check or student_facts or eligib or plan_view"`, then `tach check` and the R-58 test.
- [ ] **Step 5: Commit** `feat(os): document fields compared with the Vault; one source per fact (R-16, R-01)`.

### Task 5: Frontend — one endpoint from every button, the type picker, the vault-check line

**R-IDs:** R-01, R-16; row 6.7.

**Files:**
- Modify:
  - `frontend/lib/api.ts`:
    - `uploadFile` (:1055) gains `options.docType`, appended as `doc_type`;
    - the `WorkspaceFile` mapping keeps `os_document` (optional);
    - new `getUploadOptions()`, `registerOsDocument(fileId, docType)` and `getOsVaultCheck(docId)`.
  - `frontend/lib/os-documents.ts`: the types `UploadOptions` and `VaultCheck`.
  - `frontend/hooks/use-upload-queue.ts`: `enqueueUploads(files, folder, docType?)` passes it through, and shows `os_document.note` as the toast text when it is present.
  - `frontend/lib/workspace-context.tsx` (:164, :893): the signature.
  - `frontend/components/counselor/workspace/documents.tsx`: with `one_upload`, a `<select>` with `text.type_label`, the types and `text.type_none`, next to Upload. With `type_none`, no `docType`. Without `one_upload`, nothing changes.
  - `frontend/app/[workspaceId]/(os)/os-documents/page.tsx`: with `one_upload`, `onUpload` calls `uploadFile(file, undefined, {docType})`. It shows `os_document.note` on a refusal; on `consent_needed` it shows the existing `ConsentCard`. Without it, it calls `uploadOsDocument` as today.
  - `frontend/components/os/document-confirm.tsx`: with `one_upload`, it calls `getOsVaultCheck` and shows `note` once above the fields, and a small "different" marker on the `differs` fields. A 404 shows nothing.
  - Fixtures: `frontend/tests/preview/fake-api.ts`, `frontend/tests/fixtures/counselor.ts`.
- Tests:
  - extend: `components/os/documents.test.tsx`;
  - new: `components/counselor/workspace/documents.test.tsx`, `components/os/document-confirm.test.tsx`, `hooks/use-upload-queue.test.ts`.

- [ ] **Step 1: Write the failing tests (`// req: R-01`, `// req: R-16`).**
  - `documents view shows type picker only when one_upload`.
  - `upload with picked type sends doc_type to /v1/files`.
  - `something else sends no doc_type`.
  - `os documents page uploads through /v1/files when one_upload`.
  - `refused registration shows the backend note`.
  - `consent_needed shows the consent card`.
  - `confirm screen shows vault note and differs marker`.
  - `vault-check 404 shows nothing`.
  - **Flags-off proof:**
    - every existing test passes unchanged;
    - with `{one_upload: false}`, `os-documents` calls `uploadOsDocument` and the Counsellor Documents page renders as before (a snapshot of the header row);
    - the `copy.json` / `roadmap.json` equality test passes.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test`, then `npm run build` (in `frontend/`).
- [ ] **Step 5: Commit** `feat(connect): every upload button uses the one endpoint; the type picker and the Vault check (R-01, R-16)`.

### Task 6: Scripted flow and traceability

**R-IDs:** R-16, and R-01 if "Ruling problems" 5 allows it; row 6.7.

**Files:**
- Create: `backend/tests/os/test_connect_t7_flow.py`. It follows `test_connect_t5_flow.py`:
  - the `world` fixture (:34-53), with `CONNECT_ONE_UPLOAD`, `CONNECT_STUDENT_FACTS`, `CONNECT_HANDOFF` and `CONNECT_ROADMAP_FROM_PLANVIEW` on;
  - `run_os` (:55) and `no_chat()`;
  - `test_connect_t4_flow.py` `run_rules` (:96) for the replan;
  - the offline OS reader with the sample documents (`tests/os/fixtures/documents/samples`);
  - the reconcile job run inline.
- Modify: `docs/requirements/connection.yaml` (:29, :44).

- [ ] **Step 1: Flow test (fictional students; the Germany master's route and the fake PK intermediate route).** In order:
  1. **6.7, Germany.**
     1. Choose with places → planned.
     2. The Documents page uploads a transcript with type `transcript` through `POST /v1/files` → one `FileRecord`, an OS document with `file_ref`, and no `os_document_files` row.
     3. The worker reads it through the adapter → `read`.
     4. The vault-check shows `new` for the CGPA.
     5. Confirm → a `fact_proposal` row; the hook delivers it → candidates; reconcile → the Vault education record's `result.gpa` has evidence `shown` and `evidence.file_id` = the file.
     6. The Vault version is raised, and the `vault_event` is delivered → the OS records `student_fact_changed` → `run_rules` re-evaluates.
     7. `profile_of` reads the GPA from StudentFacts only.
     8. `plan_view.documents_needed` shows `transcript: confirmed`.
  2. **R-16, compare.** The student said 3.4 in chat (stated). The transcript shows 3.2. The vault-check says `differs` before the confirm. After the confirm and reconcile, the Vault holds 3.2 `shown`, and the disagreement is kept in the evidence (`merge_disagreements`).
  3. **Fake PK intermediate, per part.** An `hssc_certificate` confirm proposes `education.intermediate.marks_*`. The Vault record keeps its `part1` from onboarding (R-80), and nothing is asked in chat.
  4. **A chat attachment.**
     1. An untyped PDF → today's Counsellor extraction runs (stubbed) and no OS document is made.
     2. `POST /v1/uploads/{id}/os-document` → an OS document.
     3. From then on there is no second extraction of that file.
  5. **Deletion.**
     1. An OS delete → the Counsellor file is purged.
     2. A Counsellor trash of another typed file → its OS document is deleted.
     3. The Vault facts stay (Ruling problems 6).
  6. **Isolation.** Student B cannot read, confirm, vault-check or register student A's file. Every read checks the tenant and the student.
  7. **Module off (standalone).**
     1. `POST /v1/os/documents` stores bytes in `os_document_files` as today.
     2. The reader reads them.
     3. No outbox row is made.
     4. Ref-backed documents still read through the adapter (D-y6).
  8. Throughout, no chat message is created (`no_chat()`).
- [ ] **Step 2: Traceability.**
  - Set `R-16: built: true`.
  - Set `R-01: built: true` only if T6 is merged on `origin/pai-connect` (`git log origin/pai-connect --oneline | grep P1-T6`) and the owner accepted Ruling problems 4. Otherwise leave it false and write the reason in the PR.
  - Run `python scripts/check_traceability.py`.
- [ ] **Step 3: Full checks, one after the other.**
  - The legacy suite (`env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider --ignore=tests/os`), then `tests/os` (with `OS_TEST_DATABASE_URL` exported in the shell only).
  - `npm test`, then `npm run build`.
  - `tach check`, `python scripts/check_freeze.py --base origin/pai-connect`, `backend/scripts/check_alembic_heads.py`.
  - Report the counts.
- [ ] **Step 4: Commit** `test(connect): T7 flow test; R-16 built`. Add `(R-01)` to the message if it was set.
