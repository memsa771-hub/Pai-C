# P1-T4: student facts from the Vault — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PAI OS reads a student's education, marks, test scores and constraints only through a `StudentFacts` port backed by the Vault, each fact with its evidence level and Vault version. A Vault change raises a version and reaches the OS as a `student_fact_changed` event. An exclusion has one source, the Vault.

**Architecture:**
- Each accepted Vault write bumps a per-student counter (`pai_vault_versions`, via the reconciler accept hook) and, when the part is on, writes a `vault_event` outbox row.
- The bridge delivers it to a new OS port.
- The OS evaluator reads a profile built from `StudentFacts` through a data mapping in the document-type YAMLs.
- The OS replanner turns a relevant fact change into a re-check, and into a proposal (never a silent removal).

**Tech Stack:** Python 3.13, SQLAlchemy, Alembic (app `126`; OS none expected), DBOS replan worker, Next.js onboarding form, pytest/vitest.

**Spec:** `docs/superpowers/specs/2026-11-04-p1-connection-core-design.md` §3.3, with P1-D4, P1-D13, P1-D14 and P1-D15. Master: R-01, R-13, R-14, R-15, R-16, R-78, R-80, and §6 rows 6.8 and 6.9. Code map: the T4 notes in the session scratchpad, carried into the SDD workspace.

## Global Constraints

- **Flags off.** With `CONNECT_STUDENT_FACTS` off (the default), the OS evaluates exactly as today from `os_profile_values`. No `pai_vault_versions` row is written, no outbox row is written, and no OS port is called. The counter checks the raw config flag, not `part_on`, so a Vault write never queries the OS engine.
- **Code boundaries.**
  - `app/os` never imports Counsellor code (Tach).
  - All glue lives in `backend/app/pai_os_bridge.py`.
  - Counsellor connection code lives in `backend/app/pai_c/connect/`, as Python or YAML only.
  - No country, qualification or exam names in `app/os` Python (R-58). Mapping data in the OS document-type YAMLs is allowed.
- **Frozen files.** Never edit them: `pai_c/deep/**`, `pai_c/policy/*.json` (including `path_analyzer.json`), `pai_c/**/*.md`, and `docs/counselor/COUNSELOR_V3_PROMPTS.md`. Do not edit `app/memory/prompts/extractor.md` either.
- **Frozen contracts.** `student_facts.v1` and `vault_event.v1` are frozen. Use them as they are.
- **Evidence.** A Vault `inferred` value is sent as evidence `unknown` with value `None`. Nothing about the student is used without evidence.
- **Privacy.** StudentFacts carries only these keys:
  - education levels and marks;
  - test scores;
  - excluded fields and field order;
  - the budget band;
  - the domicile province;
  - place preference;
  - `eligible_levels`.

  Never the date of birth, the name, the guardian email or document values.
- **Database and checks.** DB changes go through Alembic only. Run `tach check` and `pytest tests/os` before pushing OS code. Never run the OS suite and the legacy suite at once.
- **Tests and commits.** Never weaken a test. Tag tests with R-IDs. End every commit message with the session attribution lines.

## Decisions taken in this plan (rulings, flagged to the owner in the PR)

- **D-l, the interim second source.** With the part on, the OS profile comes from StudentFacts. For a key the Vault does not hold, the OS still uses its own document-confirmed `os_profile_values`. This overlay is marked `interim: removed by T7` in code and in tests. Cutting it now would make students with confirmed documents look ineligible. R-01 is complete only after T7, when OS documents propose into the Vault.
- **D-m, the mapping.**
  - Each OS document-type field may declare `fact: <student facts key>` (data, for example `hssc_certificate.marks_obtained` → `education.intermediate.marks_obtained`).
  - A pure OS function `profile_from_facts(facts, types)` builds the `<doc_type>.<field>` profile the playbooks already use, so no playbook changes version.
  - The Counsellor adapter emits keys by qualification family from the Vault catalog (`education.<family>.<field>`, `test.<type>.score`, `constraint.*`, `preference.*`).
- **D-n, R-15 on the OS side.** OS programmes have no study-field tag, and `programme_list.v1` is frozen. In P1 the Counsellor filters excluded fields on the choice screen (T3 `places_for`) and in every Counsellor reader. The OS programme field tag and `programme_list.v2` are deferred and recorded as an open item.
- **D-o, what a fact change does in the OS.**
  - A `student_fact_changed` event on a plan that uses a changed key re-runs eligibility.
  - A programme that now reads `likely_below` becomes a `CancelProgramme` proposal. That is "big", so the student accepts it; it is never silent.
  - Plan-level breaks (an excluded field, a destination against the place preference) are T6's `choice_request`; in T4 they only add an inbox note.
- **D-q, the extractor sees new types.**
  - Adding the `field_order` and `place_preference` item types, and the Part-I and Part-II marks, changes the rendered extractor prompt automatically (`_render_catalog`).
  - Neither the template nor any frozen file changes, so no freeze exception is needed.
  - It is a behaviour change in what the Vault captures from chat, named in the PR for the Counsellor lead.

## Review Focus

1. **A Vault write while the OS is down.** The version still goes up, the outbox row is pending, and the sweep delivers it later. → Task 1 test.
2. **Two Vault writes in one request.** Two versions, two events, in order. The OS dedupes by version. → Task 1 test.
3. **A student restores a path they excluded with the button.** The Vault option becomes `considering`, the path shows everywhere again, and the next analysis does not dismiss it again. → Task 3 test.
4. **An FSc student (intermediate level) and a master's route.** `eligible_levels` holds no `master`, and the choice screen offers no master's destination. → Task 4 test.
5. **An `inferred` mark in the Vault.** It is sent as `unknown`, and the evaluator shows "needs input", never "not eligible". → Task 5 test.

---

### Task 1: Vault version and vault events

**Files:**
- Create: `backend/alembic/versions/126_vault_versions.py`, `backend/app/pai_c/connect/vault_version.py`.
- Modify: `backend/app/models.py` (`VaultVersion`), `backend/app/capabilities/system.py` (register the hook), `backend/app/pai_c/connect/outbox.py` (`record_vault_event`), `backend/app/pai_os_bridge.py` (deliver `vault_event`, backfill), `backend/app/os/ports/` (new `student_facts.py` with `record_event`, the OS side of delivery only).
- Tests: `backend/tests/test_migration_126.py`, `backend/tests/test_vault_version.py`, `backend/tests/os/test_vault_event_port.py`; extend `tests/test_connect_flags_off.py` and `tests/test_handoff_delivery.py`.

**Interfaces:**
- Table `pai_vault_versions`: `workspace_id` (PK, FK CASCADE), `version` (int), `key_versions` (JSONB: StudentFacts key → version), `updated_at`.
- `vault_version.keys_for(candidate) -> list[str]`: the StudentFacts keys a reconciler candidate touches (the one shared map, also used by Task 4).
- `vault_version.after_accept(db, candidate) -> None`:
  - when `config.CONNECT_STUDENT_FACTS` is on and the candidate touches at least one StudentFacts key: bump the version under the workspace lock, set `key_versions[k]`, and call `outbox.record_vault_event(db, ws, version, keys)`, which is a no-op unless `part_on`;
  - never swallow an error from the bump itself, so a lost version cannot happen silently;
  - wrap only the outbox call like the other hooks.
- OS port `student_facts.record_event(event: dict) -> "stored" | "duplicate" | "module_off"`: validates `VaultEventV1` and stores it in a new OS table `os_vault_events` (unique per tenant, student and version; OS migration `os_0020`).
- Bridge: `deliver_pending` also delivers `kind == "vault_event"` rows; the sweep backfills the newest version per student whose OS copy is lower.

- [ ] **Step 1: Write the failing tests (R-13):**
  - flag off: no version row, no outbox row;
  - flag on: one write gives version 1 and one outbox row with a `VaultEventV1`-valid payload; two writes give versions 1 and 2 in order;
  - a write that touches no StudentFacts key (e.g. a hobby) changes nothing;
  - OS down: the row stays pending and the sweep delivers it;
  - a repeat delivery gives `duplicate`;
  - migration 126 chains after 125;
  - os_0020 gives one head.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new files, `tests/test_vault_reconcile.py`, `tests/test_handoff_delivery.py`, `tests/test_connect_flags_off.py`, `tests/os/test_vault_event_port.py`, then `tach check`.
- [ ] **Step 5: Commit** `feat(connect): Vault version and vault events to PAI OS (R-13, P1-D15)`.

### Task 2: New Vault types and per-part marks

**Files:**
- Modify: `backend/app/memory/catalog/vault_catalog.json`, `backend/app/memory/student_schema.py` (education result parts), `backend/app/memory/vault_view.json` (display), `frontend/lib/i18n/messages/en-US.ts` (part labels).
- Tests: extend `tests/test_vault_catalog.py`, `tests/test_vault_chat_extraction.py`, `tests/test_vault_view.py`, `tests/test_student_onboarding.py`, `frontend/lib/onboarding.test.ts`, `frontend/components/onboarding/onboarding-view.test.tsx`.

**Interfaces:**
- Item `field_order`: identity `[]`, schema `{fields: array<=30 of study_fields codes}`, inputs `chat`, `details`.
- Item `place_preference`: identity `[]`, schema `{scope: local|abroad|either, fallback: none|local_first|abroad_first, regions: array of province codes from the existing provinces list}`, inputs `chat`, `details`.
- `education.result` gains optional `part1` and `part2`, each `{marks_obtained, marks_total}`, with the obtained ≤ total check per part. `course.score` is not widened.
- Onboarding asks for Part-I marks when the level is intermediate-family and (completed, or current in `year_2`). It asks for Part-II marks when completed. Both are optional, and totals stay as today.

- [ ] **Step 1: Write the failing tests (R-16, R-80):**
  - the catalog has both types and their schemas validate;
  - `test_prompt_mentions_every_item_type` still passes, listing the new types;
  - a part above its total is refused;
  - an existing total-only record stays valid;
  - onboarding shows part fields only in the right cases and saves them as `stated`;
  - the frontend renders the part fields and labels.

  Update the exact-set assertions in `test_vault_catalog.py` (item set, fact count) by extending them; do not loosen them.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Run** the named tests, then `npm test` and `npm run build`. **Step 5: Commit** `feat(vault): field order, place preference and Part-I/II marks (R-16, R-80, P1-D4)`.

### Task 3: Exclusions from one source

**Files:**
- Modify: `backend/app/routers/counselor_possibilities.py` (dismiss and restore write the Vault option), `backend/app/pai_c/paths/exclusions.py` (helper `record_button_exclusion` / `record_restore`), `backend/app/pai_c/possibilities.py` (`current()` also drops fields in `hidden_field_keys`).
- Check, and adapt only if needed: `roadmap/engine.py`, `journey_sync.py`, `checkins.py`, `research/gateway.py`, `routers/counselor_paths.py`, `paths/programs.py`. The frozen `deep/` readers stay untouched.
- Tests: extend `tests/test_path_exclusions.py`, `tests/test_possibilities.py`, `tests/test_roadmap_engine.py`.

**Interfaces:**
- Dismiss through the button with a known `study_field.key`: propose and reconcile a Vault `option` with `{text: <catalog label>, status: "ruled_out"}`, `source_type="user_explicit"`, evidence `{capture: "paths_button", possibility_id}`, before the commit.
- Restore: the option becomes `considering`.
- A path with no study-field key: status only, as today, documented.

- [ ] **Step 1: Write the failing tests (R-78, R-15):**
  - a button dismiss creates a `ruled_out` option at `stated`;
  - the field disappears from the chat card, the roadmap, journey sync and stage H;
  - a restore makes it `considering` and the field shows again;
  - the next analysis does not re-dismiss it;
  - a chat exclusion works as before.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Run** the named tests plus `tests/test_path_analyzer.py`, `tests/test_counselor_journey.py`, `tests/test_journey_sync.py`. **Step 5: Commit** `feat(connect): exclusions have one source, the Vault (R-78, R-15)`.

### Task 4: The StudentFacts builder and eligible levels

**Files:**
- Create: `backend/app/pai_c/connect/eligible_levels.yaml`, `backend/app/pai_c/connect/student_facts.py`.
- Modify: `backend/app/pai_c/connect/places.py` (destinations intersect with `eligible_levels`).
- Tests: `backend/tests/test_student_facts_builder.py`; extend `tests/test_connect_places.py`.

**Interfaces:**
- `eligible_levels.yaml` maps qualification code → open levels:
  - matric, o_level → intermediate;
  - intermediate-family codes, a_level, dae → bachelor;
  - bachelor → master;
  - masters → master, phd.

  A current student counts at the level they are finishing.
- `student_facts.build(db, workspace_id) -> dict`: a `StudentFactsV1`-valid dict built from the snapshot and items.
  - Each fact carries its `evidence` (inferred → unknown with value None), `vault_version` (from `key_versions`, else 0), `document_ref` (when shown from a file) and `as_of`.
  - Only the keys allowed by the privacy constraint.
  - `eligible_levels` is None when there is no education.

- [ ] **Step 1: Write the failing tests (R-13, R-14):**
  - an FSc student → `eligible_levels == ["bachelor"]`;
  - matric → intermediate;
  - no education → None;
  - an inferred mark → unknown and None;
  - a shown mark carries `document_ref`;
  - no DOB, name or guardian key appears;
  - the output validates as `StudentFactsV1`;
  - places for an FSc student offer no master's destination.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Run.** **Step 5: Commit** `feat(connect): StudentFacts from the Vault, eligible levels (R-13, R-14, P1-D13)`.

### Task 5: The OS port, adapters and the evaluator cut-over

**Files:**
- Modify: `backend/app/os/ports/student_facts.py` (`get`), `backend/app/os/eligibility/notes.py` (`profile_of` → port, D-l overlay), the OS document-type YAMLs under `backend/app/os/documents/types/` (`fact:` per field, data), `backend/app/os/mount.py` and the worker env hook (`OS_STUDENT_FACTS=app.pai_os_bridge:student_facts`).
- Create: `backend/app/os/adapters/standalone/student_facts.py` (from `os_profile_values`) and `backend/app/os/eligibility/facts.py` (`profile_from_facts`).
- Modify: `backend/app/pai_os_bridge.py` (`student_facts(student_ref)` → Task 4 `build`, in its own session).
- Tests: `backend/tests/os/test_student_facts_port.py`; extend `tests/os/test_eligibility_evaluate.py` and `tests/os/test_eligibility_notes.py`.

**Interfaces:**
- `ports.student_facts.get(student_ref) -> StudentFactsV1`: the Counsellor adapter when the module and the part are on, else the standalone adapter.
- `profile_from_facts(facts, types) -> dict` is pure.
- A startup check that every `fact:` key matches the contract key pattern.

- [ ] **Step 1: Write the failing tests (R-01, R-13):**
  - the Germany route and the fake PK BS, PK intermediate and Ireland routes each evaluate the same with a Vault-sourced profile as with the equivalent document profile;
  - an inferred or unknown fact gives `needs_input` (Review Focus 5);
  - flags off gives exactly today's profile;
  - the D-l overlay fills only keys the Vault lacks;
  - the red-flag search is clean;
  - `tach` passes.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Run** `tests/os -k "eligib or student_facts or documents"`, then `tach check`. **Step 5: Commit** `feat(os): eligibility reads StudentFacts through a port (R-01, R-13)`.

### Task 6: The OS replan consumer and the end-to-end proof

**Files:**
- Modify: `backend/app/os/replan/events.py` (`student_fact_changed`), `backend/app/os/replan/rules.py` (the rule), and the Task 1 port (`record_event` also records the replan event on each open plan using a changed key).
- Create: `backend/tests/os/test_student_fact_replan.py` and `backend/tests/os/test_connect_t4_flow.py`.
- Modify: `docs/requirements/connection.yaml`.

**Interfaces:**
- `EVENT_TYPES` gains `student_fact_changed`.
- The rule re-evaluates eligibility with StudentFacts. A programme now `likely_below` gives a `CancelProgramme` proposal (big, so the student accepts it). The eligibility note is refreshed. Plan-level breaks give a note only (D-o).

- [ ] **Step 1: Write the failing tests (R-15, R-16):**
  - a fact change on a used key records one event per open plan, deduped by version;
  - an unused key records none;
  - marks dropping below a fake route's merit threshold → a pending big proposal, never an applied cancel;
  - end to end, a Vault write moves through the hook, the outbox, delivery, the OS event and the replan, and ends in a proposal (Postgres OS plus an app session, using the `test_handoff_crash.py` pattern).
- [ ] **Step 2: Fail.** **Step 3: Implement.**
- [ ] **Step 4: Run** the full suites one after the other: legacy (`--ignore=tests/os`), then `tests/os`, `npm test`, `npm run build`, `tach check`, `check_freeze.py --base origin/pai-connect`, `check_alembic_heads.py`, `check_traceability.py`. Set `built: true` for R-13, R-14, R-78 and R-80, which are complete here. Do not flip R-01, R-15 or R-16: R-01 needs T7, R-15 needs the OS programme tag, and R-16 needs the T7 document compare. Record each reason in the PR.
- [ ] **Step 5: Commit** `feat(os): fact changes replan with proposals; T4 flow test (R-13, R-14, R-78, R-80)`.
