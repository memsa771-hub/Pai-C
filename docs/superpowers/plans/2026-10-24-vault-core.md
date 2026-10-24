# Vault Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Vault the single, evidence-backed, English, catalog-driven store of everything about a student, fed by chat, documents, a details page and story cards, with complete conflict handling (backend only).

**Architecture:** Keep the proven pipeline (candidate → reconciler → canonical) and the typed fact/record storage. Add a catalog file, a generic catalog-item store for every other type, a normalize step shared by all inputs, a drop log, a unified Vault view with badges and freshness, and one `/v1/vault` API. Consumers (counselor context, coverage) read the Vault view.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (SQLite in tests), pytest.

**Spec:** `docs/counselor/VAULT_SPEC.md`

## Global Constraints
- Values stored in English; original words only in `evidence.quote`; `evidence.source_language` ∈ {en, ur, roman_ur, mixed}.
- Badges exactly: `Stated`, `From document`, `PAI's guess`, `Confirmed`, `In question`.
- Levels exactly: `inferred` < `stated` < `shown` < `confirmed`.
- Budget bands (PKR/year): `under_1_lakh`, `1_3_lakh`, `3_6_lakh`, `6_10_lakh`, `over_10_lakh`, `not_sure`. Never ask household income.
- Freshness days: marks/education/tests never (null), budget 180, goal 90, family_member 365, others per catalog.
- Every write goes through `MemoryCandidateService.propose` → `MemoryReconciler.reconcile`.
- DB changes only via Alembic (next revision `116`). Never edit `.env`. No live model calls in tests.
- Tests run from `backend/`: `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider`.

## Review Focus
- Urdu-script name from chat: stored as a guess (`inferred`) needing confirmation, never rejected → Task 3 test `test_urdu_script_name_is_kept_as_a_guess`.
- Student removes an entry, then a document re-states it: not re-created → Task 5 test `test_retracted_item_not_recreated_from_document`.
- Two family members of the same relation with different names: two entries, not merged → Task 4 test `test_two_brothers_with_names_stay_separate`.
- OCR-read marks: badge `PAI's guess` until confirmed, not `From document` → Task 9 test `test_ocr_values_need_confirmation`.
- Student edits a document-backed mark: student value wins, document value still visible → Task 9 test `test_student_edit_keeps_document_disagreement_visible`.

---

### Task 1: Vault catalog

**Files:**
- Create: `backend/app/memory/catalog/vault_catalog.json`, `backend/app/memory/catalog/__init__.py`
- Test: `backend/tests/test_vault_catalog.py`

**Interfaces:**
- Produces: `vault_catalog() -> VaultCatalog` (cached). `VaultCatalog.type(key) -> TypeSpec | None`; `.types(storage=None, shown_on=None) -> list[TypeSpec]`; `.choices(name) -> list[Choice]`; `.choice_code(name, text) -> str | None` (matches code, label, synonyms after `norm`); `.label(name, code) -> str`.
- `TypeSpec`: `key, storage ("fact"|"record"|"item"), shown_on ("details"|"story"), inputs (subset of chat, document, details, story), sensitivity, conflict ("latest_wins"|"evidence_wins"|"ask_student"), freshness_days (int|None), version (int), schema (JSON schema, items only), identity (list of value fields that identify one entry; [] = singleton), choice_fields (field → choice list name), label`.
- Facts: the 24 production keys plus `finance.budget`. Records: education, course, test_attempt, goal, activity, project, achievement, work_experience, exploration_experience, skill, language_proficiency, certification. Items: interest, strength, value, pressure, option, myth, certainty, family_member, domicile, quota, daily_life.
- Choice lists: `levels` (matric, o_level, fsc, ics, icom, fa, a_level, dae, bachelor, other), `intermediate_groups` (pre_medical, pre_engineering, ics, icom, fa_humanities, general_science), `boards` (Pakistani BISEs + federal, aga_khan, cambridge), `tests` (mdcat, ecat, nat, net, sat, ielts, toefl, gat, nts_other), `provinces` (punjab, sindh, kpk, balochistan, islamabad, gilgit_baltistan, ajk; with urban/rural handled by `domicile.area`), `quotas` (hafiz_e_quran, sports, disability, minority, armed_forces, other), `relations` (father, mother, brother, sister, uncle, aunt, grandparent, guardian, cousin, other), `budget_bands` (Global Constraints), `budget_covers` (fees_only, fees_and_living).

- [ ] **Step 1: Write failing tests** `test_every_type_is_valid`, `test_item_schemas_are_valid_json_schema`, `test_choice_code_matches_synonyms` (`choice_code("boards","Lahore board") == "bise_lahore"`, `choice_code("intermediate_groups","pre eng") == "pre_engineering"`, `choice_code("relations","Abbu") == "father"`), `test_budget_bands_exact`, `test_fact_keys_match_production_fields` (catalog fact keys == keys from `alembic/versions/074` + 085).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Write the JSON and loader** (loader validates every TypeSpec at load and raises `ValueError` naming the bad type).
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(vault): catalog of every Vault type and choice list`

### Task 2: Item store, drop log and migration 116

**Files:**
- Modify: `backend/app/models.py` (add `VaultItem`, `VaultDrop`)
- Create: `backend/alembic/versions/116_vault_items.py`
- Test: `backend/tests/test_vault_items_migration.py`

**Interfaces:**
- `VaultItem` (`pai_vault_items`): id, workspace_id (FK workspaces CASCADE), item_type, type_version, value (JSONB), level, source_type, source_language, confidence, evidence (JSONB; may hold `corroborations` list), status (active | superseded | retracted), conflict_state (none | in_question), observed_at, confirmed_at, valid_from, valid_until, superseded_by, candidate_id, created_at, updated_at. Index (workspace_id, item_type, status). CHECKs on level, status, conflict_state.
- `VaultDrop` (`pai_vault_drops`): id, workspace_id (FK CASCADE), source (chat | document | details | story), stage (extract | normalize | validate), reason, payload (JSONB, ≤ 2 KB), source_ref, created_at. Index (workspace_id, created_at).
- Migration 116: create both tables; add `finance.budget` field definition version with schema `{band (enum budget_bands), min, max, currency, period (per_year|per_month|total), covers (enum budget_covers), approximate (bool), possible_without_scholarship (yes|no|not_sure)}` (required: none beyond one of band/min/max), disabling the old version; drop unused `pai_counselor_slot_answers`. Downgrade restores the old budget version and drops the two tables (slot table recreated empty).

- [ ] **Step 1: Failing tests** `test_116_revision_chain`, `test_item_and_drop_tables_in_metadata`, `test_budget_definition_v2_schema` (loads 116's budget schema, validates `{"band":"1_3_lakh","covers":"fees_and_living"}` and rejects `{"band":"rich"}`).
- [ ] **Step 2–4: Implement, run.**
- [ ] **Step 5: Commit** `feat(vault): item store, drop log, budget ranges (migration 116)`

### Task 3: Normalize

**Files:**
- Create: `backend/app/memory/normalize.py`
- Test: `backend/tests/test_vault_normalize.py`

**Interfaces:**
- `detect_language(text: str) -> str` (Arabic script only → `ur`; Arabic script with Latin → `mixed`; Roman-Urdu lexicon hits ≥ 2 with English → `mixed`, ≥ 2 without → `roman_ur`; else `en`).
- `ascii_digits(text: str) -> str` (Urdu and Arabic-Indic digits).
- `iso_date(text: str) -> str | None` (day/month/year order; `"14 August 2007"`, `"14/08/2007"` → `"2007-08-14"`; month-year → `"2007-08"`).
- `normalize_candidate(candidate_type, key, value, *, student_text) -> NormalizeResult` with `value`, `source_language`, `needs_confirmation: bool`, `rejected_reason: str | None`. Applies digits, catalog choice codes (`choice_fields`), dates for date-typed fields, PKR for `currency` written as rupees/Rs, and the English rule (Arabic script outside name fields → rejected; Arabic-script names → `needs_confirmation`).
- Hooked in `MemoryCandidateService.propose` for `vault_fact`, `student_record`, `vault_item`: rejected → raise `MemoryDataError` after writing a `VaultDrop(stage="normalize")`; otherwise sets `evidence.source_language` and, when `needs_confirmation`, `evidence.inferred = True`.

- [ ] **Step 1: Failing tests** `test_detect_language` (4 cases from golden set), `test_ascii_digits("۱۰۴۵") == "1045"`, `test_iso_date_pakistani_order`, `test_choice_fields_become_codes` (education details.awarding_body "Lahore board" → "bise_lahore"), `test_urdu_script_value_is_rejected_and_logged`, `test_urdu_script_name_is_kept_as_a_guess`, `test_rupees_become_pkr`.
- [ ] **Step 2–4: Implement, run.**
- [ ] **Step 5: Commit** `feat(vault): normalize every candidate to English, codes and ISO dates`

### Task 4: Item service with the conflict engine

**Files:**
- Create: `backend/app/memory/vault_items.py`
- Test: `backend/tests/test_vault_items.py`

**Interfaces:**
- Consumes: Task 1 catalog, Task 2 `VaultItem`, `ProfileIssue`.
- Produces: `VaultItemService(db).apply(workspace_id, item_type, value, *, source_type, level, confidence, evidence, candidate_id, item_id=None, correction=False, temporal=False) -> ItemWrite(outcome: VaultOutcome, item: VaultItem | None, issue_id: str | None)`; `.retract(workspace_id, item_id, evidence) -> VaultItem`; `.confirm(workspace_id, item_id) -> VaultItem`; `.active(workspace_id, types=None) -> list[VaultItem]`; `.history(workspace_id, item_id) -> list[VaultItem]`; `.was_retracted(workspace_id, item_type, value) -> bool`.
- Identity: `TypeSpec.identity` fields after `norm`; empty identity = singleton (domicile, certainty); family_member identity = relation + name when a name is present.
- Conflict order exactly as spec §Conflicts; `ask_student` opens a `ProfileIssue(issue_type="conflict", affected_type="vault_item")` and sets the new candidate `needs_review`; the existing item gets `conflict_state="in_question"`.

- [ ] **Step 1: Failing tests (one per conflict type):** `test_same_meaning_merges_evidence`, `test_student_edit_wins_and_history_kept`, `test_correction_replaces`, `test_temporal_change_replaces_and_keeps_past`, `test_guess_never_replaces_stated`, `test_latest_wins_rule`, `test_ask_student_rule_opens_issue`, `test_two_brothers_with_names_stay_separate`, `test_father_said_twice_is_one_entry`, `test_schema_violation_raises_memory_data_error`, `test_retract_then_was_retracted`.
- [ ] **Step 2–4: Implement, run.**
- [ ] **Step 5: Commit** `feat(vault): catalog item store with the five-step conflict engine`

### Task 5: Reconciler and candidates integration

**Files:**
- Modify: `backend/app/memory/candidates.py`, `backend/app/memory/reconciler.py`, `backend/app/memory/vault_intake.py`, `backend/app/memory/vault.py`, `backend/app/memory/student_records.py`, `backend/app/memory/profile_issues.py`
- Test: `backend/tests/test_vault_reconcile.py`

**Interfaces:**
- `CANDIDATE_TYPES` gains `vault_item`; `MemoryReconciler._reconcile_item(candidate) -> ReconcileResult` (upsert/retract via Task 4; correction/temporal from `evidence.semantic_correction` / `semantic_temporal_change`).
- Guess guard for facts and records: a candidate with `evidence.inferred` never replaces an active non-inferred value (outcome RETAINED, reason `guess_against_stated`).
- `envelope_for` sets `language = evidence.source_language`; `VaultDomainRouter.route` returns the catalog key's domain for `vault_item`.
- `provenance_for`: `evidence.ocr` → verification `extracted` (never `document_supported`).
- Tombstone: a `document`-source item candidate whose value `was_retracted` → rejected `retracted_by_student`.
- Document owner: a `document`-source candidate set whose `identity.full_name`/`preferred_name` disagrees with the active Vault name (after `norm`) → nothing applied, one `ProfileIssue(issue_type="document_owner")`.
- `ISSUE_ACTIONS` gains `both_true` (accepts the proposed value with `semantic_temporal_change`, old value kept as past).

- [ ] **Step 1: Failing tests** `test_vault_item_candidate_round_trip`, `test_inferred_fact_does_not_replace_stated_fact`, `test_assertion_records_source_language`, `test_ocr_document_record_is_extracted_not_supported`, `test_retracted_item_not_recreated_from_document`, `test_someone_elses_document_is_not_applied`, `test_issue_both_true_keeps_old_as_past`.
- [ ] **Step 2–4: Implement, run; then run the whole memory suite** (`tests/memory`, `tests/test_student_records.py`, `tests/test_p1d_memory.py`) — PASS.
- [ ] **Step 5: Commit** `feat(vault): reconcile catalog items, guess guard, language, OCR and owner checks`

### Task 6: Chat extraction writes every type

**Files:**
- Modify: `backend/app/memory/extractor.py`, `backend/app/memory/handlers.py`
- Test: `backend/tests/test_vault_chat_extraction.py`

**Interfaces:**
- Prompt lists catalog item types (key, schema, choices) and record kinds; removes the bans on interests, motivations and certainty; instructs Latin-script names, English values, verbatim quote, `"inferred": true` for PAI's interpretations, `"correction"`/`"temporal_change"` flags, and never to output household income.
- `ExtractedCandidate` may be `vault_item` (key = item type). `_validate` checks catalog type and schema; every drop calls `record_drop(db?, workspace_id, "chat", "extract", reason, payload)` via a collector returned to the handler, which persists them.
- `extract_candidates(turn, allowed_keys, field_specs) -> ExtractionOutput(candidates, drops)`.

- [ ] **Step 1: Failing tests** `test_items_extracted_from_roman_urdu_turn` (fake model output with interest + family_member + certainty for golden case `ru-myth-options-certainty`), `test_unknown_item_type_is_dropped_and_logged`, `test_inferred_flag_reaches_evidence`, `test_prompt_mentions_every_item_type`.
- [ ] **Step 2–4: Implement, run; run `tests/test_eval_vault.py` and `tests/memory` — PASS.**
- [ ] **Step 5: Commit** `feat(vault): chat extraction for every catalog type with a drop log`

### Task 7: Documents: photos, subject marks, same rules

**Files:**
- Modify: `backend/app/documents/types.py`, `backend/app/documents/parsers.py`, `backend/app/documents/handlers.py`, `backend/app/documents/ocr.py`, `backend/app/documents/extractor.py`
- Test: `backend/tests/documents/test_vault_documents.py`

**Interfaces:**
- `detect_document_type` accepts JPEG/PNG (magic bytes) → `"image"`; `parse_document(data, "image")` returns one empty page; `_apply_ocr` sends the original image bytes; OCR data URL mime from magic bytes (`image/jpeg` | `image/png`).
- Document extractor: may emit `course` records with scores and catalog items allowed for documents (catalog `inputs`); drops go to `VaultDrop(source="document")`; OCR segments set `evidence.ocr = True`.

- [ ] **Step 1: Failing tests** `test_jpeg_result_card_is_accepted_and_ocr_read` (fake OCR provider), `test_png_mime_is_png`, `test_transcript_subject_marks_become_courses`, `test_document_drop_is_logged`.
- [ ] **Step 2–4: Implement, run; run `tests/documents` — PASS.**
- [ ] **Step 5: Commit** `feat(vault): photo documents, subject marks and document drop log`

### Task 8: (folded into Task 5 — document owner check)

### Task 9: Vault view: badges, documents, freshness, conflicts

**Files:**
- Create: `backend/app/memory/vault_view.py`
- Test: `backend/tests/test_vault_view.py`

**Interfaces:**
- `VaultView(db).build(workspace_id, *, include_sensitive=True, now=None) -> dict` with `details` (sections: about, education, tests, money_and_place, documents), `story` (one card per story type: `{type, label, entries, rich, next_step}`), `conflicts` (`{id, summary, question, current, proposed, answers: ["keep_current","accept_proposed","both_true","provide_new"]}`), `stale` (entries past freshness).
- Entry: `{kind (fact|record|item), type, id, value, label, level, badge, source, source_language, document: {file_id, page, filename} | null, observed_at, confirmed_at, fresh_until, stale, in_question, disagreements: [ {value, source, document} ]}` — never the quote.
- `level_of(source_type, verification_status, evidence) -> str`; `badge_for(level, in_question) -> str` (exact copy from Global Constraints).
- `entries_for_document(workspace_id, file_id) -> list[entry]`.

- [ ] **Step 1: Failing tests** `test_badges_for_each_level`, `test_document_entry_has_file_link`, `test_quote_never_in_view`, `test_ocr_values_need_confirmation`, `test_student_edit_keeps_document_disagreement_visible`, `test_freshness_marks_budget_stale_after_180_days`, `test_conflict_card_has_four_answers`, `test_entries_for_document`.
- [ ] **Step 2–4: Implement, run.**
- [ ] **Step 5: Commit** `feat(vault): one Vault view with badges, document links, freshness and conflict cards`

### Task 10: `/v1/vault` API

**Files:**
- Create: `backend/app/routers/vault.py`; Modify: `backend/app/main.py`
- Test: `backend/tests/test_vault_api.py`

**Interfaces (all owner-only, `network` query + bearer like `student_profile.py`):**
- `GET /v1/vault` → Task 9 view. `GET /v1/vault/catalog` → types with shown_on, inputs, schema, choices (no internal fields).
- `POST /v1/vault/entries` `{type, value}` → user_explicit candidate (fact, record or item by catalog storage).
- `PATCH /v1/vault/entries/{kind}/{id}` `{value}`; `POST .../{kind}/{id}/confirm`; `DELETE .../{kind}/{id}` (retract); `GET .../{kind}/{id}/history`.
- `POST /v1/vault/conflicts/{issue_id}/resolve` `{answer, value?}` → `ProfileIssueService.resolve`.
- `GET /v1/vault/documents/{file_id}/entries`; `GET /v1/vault/drops?since=` (owner sees own drop log).
- Every write: one candidate, `input_channel="profile"`, evidence `{capture: "vault_api", quote: <typed text or JSON of value>, source_language}`.

- [ ] **Step 1: Failing tests** `test_add_story_item_then_view_shows_stated`, `test_edit_confirm_remove_cycle`, `test_cross_workspace_access_denied`, `test_resolve_conflict_both_true`, `test_catalog_has_no_internal_fields`, `test_budget_band_through_api`.
- [ ] **Step 2–4: Implement, run.**
- [ ] **Step 5: Commit** `feat(vault): /v1/vault API for details, story cards, conflicts and documents`

### Task 11: Consumers read the Vault view

**Files:**
- Modify: `backend/app/pai_c/deep/context.py`, `backend/app/pai_c/understanding/areas.json`, `backend/app/pai_c/understanding/data.py` (or wherever coverage sources resolve), `backend/app/pai_c/memory.py`
- Test: `backend/tests/test_vault_consumers.py`

**Interfaces:**
- `select_context_entries(view, student_text, *, budget_tokens) -> list[entry]`: core details always; then in-question and stale entries; then entries sharing words with `student_text`; then newest; stop at budget (replaces `list(snapshot.facts.items())[:30]`). Context gains `needs_recheck` (stale) and `in_question` lists.
- Coverage sources accept `{"vault_items": [types]}`; interests, values, family_social, pressures, goals, options, sure map to item types.

- [ ] **Step 1: Failing tests** `test_context_includes_relevant_entry_beyond_thirty`, `test_context_never_contains_restricted_or_quote`, `test_item_counts_toward_coverage`.
- [ ] **Step 2–4: Implement, run; run the counselor suites** (`tests/test_counselor_deep_*.py`, `tests/test_spine_areas.py`, `tests/test_truth_map_v3.py`) — PASS.
- [ ] **Step 5: Commit** `feat(vault): counselor context and coverage read the Vault view`

### Task 12: Remove the superseded code and re-measure

**Files:**
- Delete: `backend/app/memory/entry_fields.json` (onboarding reads catalog `inputs` ∋ details with `onboarding: true`), the empty catalogs in `backend/app/pai_c/policy/fact_cards.json` (fact cards read catalog choices), `SEED_FIELD_DEFINITIONS` in `backend/app/memory/field_definitions.py` (eval support seeds production specs from Task 1's catalog), the extractor ban lines.
- Modify: `backend/scripts/counselor_eval_support.py`, `backend/scripts/eval/vault_golden.py` (adapter reads items: interest, strength, value, pressure, option, myth, certainty, family_member, domicile, quota), `backend/scripts/eval_vault.py`, `docs/counselor/VAULT_SPEC.md` (status), `CLAUDE.md` (pointer).
- Test: existing suites + `tests/test_eval_vault.py`.

- [ ] **Step 1: Delete and repoint; run the full backend suite** — PASS.
- [ ] **Step 2: Import-graph and vulture check for newly dead code** (`scripts/import_graph.py`); remove what nothing reaches.
- [ ] **Step 3: Commit** `refactor(vault): remove superseded field lists and seeds; eval reads catalog items`
