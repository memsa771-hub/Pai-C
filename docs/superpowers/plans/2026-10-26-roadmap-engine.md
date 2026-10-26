# Roadmap Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A deterministic roadmap engine that tells the student which fields they can get into from their Vault, one simple Roadmap page (cards, route sheet, compare, chosen route), and removal of the old chat-linked roadmap system.

**Architecture:** Data file of admission rules → pure engine (`pai_c/roadmap/`) computed on read → small API + route decision table → one frontend view replacing Compare/Plan → removal of old code.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest; Next.js, vitest.

**Spec:** `docs/counselor/ROADMAP_ENGINE_SPEC.md`

## Global Constraints
- Branch `roadmap-engine` (from `pai-c`). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No field, group, exam, number or country hardcoded in code: rules in `pai_c/policy/admission_rules.json`, copy in `copy.json` / data.
- No model calls in the engine. No live calls in tests. Never edit `.env`.
- DB changes only via Alembic (head is 117). Do NOT drop old roadmap tables; code just stops using them.
- Reuse `paths/fields.py` education readers and `PossibilityService`; follow the workspace UI kit (`components/pai`, `CARD`, `StatChip`, `toneClass`, `Heading`, `useResource`).
- Tests from `backend/` with the shim (see `.superpowers/sdd/2026-10-25-education-focus/env-notes.md`); frontend `npm test`, `npm run build`.
- Existing-feature map: `.superpowers/sdd/roadmap-engine/roadmap-map.md`.

## Review Focus
- Student path with no study field (own path "Mobile repair") → card status `unknown`, never a crash → Task 2 `test_own_path_without_field_is_unknown`.
- Marks given as marks_obtained/marks_total (e.g. 858/1100) → percentage 78 used → Task 2 `test_marks_from_obtained_total`.
- A-level student with grades → IBCC percentage used; missing grades → marks unknown → Task 2 `test_a_level_grades_equivalence`.
- Choosing a field whose verdict later changes (marks edited) keeps the decision snapshot, and the page shows the live verdict beside it → Task 3 `test_decision_keeps_snapshot`.
- Old account with an old chosen `pai_roadmaps` row → new page loads with no chosen route, no 500 → Task 3 `test_legacy_roadmap_rows_ignored`.

---

### Task 1: Admission rules data
**Files:** Create `backend/app/pai_c/policy/admission_rules.json` (from `.superpowers/sdd/roadmap-engine/admission_rules_draft.json` + `admission_rules_summary.md`), loader `backend/app/pai_c/roadmap/rules.py`; Test `backend/tests/test_admission_rules.py`.
**Interfaces:** `rule_for(field_key: str) -> Rule | None` (field-specific rule wins over family rule); `Rule` fields: `groups_open`, `groups_with_step` (group, step, source, scope_fields), `min_percent`, `required_subjects`, `entry_tests` (name, body, pass_percent, source), `years`, `fee_band_pkr_per_year`, `sources`, `confidence`; `ibcc_percent(grades: list[str]) -> float | None`.
- [ ] Failing tests: every `fields` key exists in `study_fields.json`; every family exists; every group code is a known group; every rule has ≥1 https source and a valid confidence; every study field resolves to a rule (field or family); `rule_for("mbbs").groups_open == ["pre_medical"]`; a pre_medical step on engineering is scoped to civil/electrical/mechanical; `ibcc_percent(["A","A","B"])` matches the IBCC table in the file.
- [ ] Fill `years` per rule where the draft has it (engineering 4, MBBS 5, BDS 4, Pharm-D 5, LLB 5, nursing 4, BS 4); keep nulls as null. Commit `feat(roadmap): admission rules data`.

### Task 2: The engine
**Files:** Create `backend/app/pai_c/roadmap/engine.py`, `backend/app/pai_c/policy/roadmap.json` (status order, copy keys, limits); Test `backend/tests/test_roadmap_engine.py`.
**Interfaces:** `student_standing(education_records: list[dict]) -> Standing` (level, groups, percent|None, readable); `verdict(field_key: str | None, standing: Standing) -> Verdict` (`status: "open"|"step"|"not_open"|"unknown"`, `reasons: list[str]` copy-keyed with values, `needs: list[Need]`, `tests`, `years`, `min_percent`, `student_percent`, `confidence`, `sources`); `RoadmapEngine(db).build(workspace_id) -> dict` returning `{education_line, standing, counts, fields: [card], chosen}` where card = `{possibility_id, field_key, title, family, why, status, verdict}` for live (not dismissed) paths.
- [ ] Failing tests = spec §5 scenarios: `test_pre_eng_78_open`, `test_pre_eng_55_step`, `test_pre_med_engineering_step_and_mbbs_open`, `test_ics_cs_open_ce_step_mech_not_open`, `test_matric_choose_group_step`, `test_no_marks_open_with_note`, `test_no_education_not_readable`, `test_bachelor_undergrad_only_note`, plus Review Focus `test_own_path_without_field_is_unknown`, `test_marks_from_obtained_total`, `test_a_level_grades_equivalence`; and `test_engine_makes_no_model_call` (patch the model gateway to raise).
- [ ] Implement; full suite; commit `feat(roadmap): deterministic eligibility engine`.

### Task 3: Route decision + API
**Files:** Create `backend/alembic/versions/118_route_decisions.py`, model `RouteDecision` in `backend/app/models.py`, `backend/app/routers/roadmap.py`, neutral auth module `backend/app/routers/_workspace_auth.py` (move `_authorized` from `routers/roadmaps.py`; update all importers); modify `routers/decision_records.py` to read `RouteDecision`; Test `backend/tests/test_roadmap_api.py`.
**Interfaces:** table `pai_route_decisions` (id, workspace_id FK CASCADE, field_key, possibility_id nullable FK SET NULL, title, verdict JSONB, route JSONB, steps JSONB list[str], steps_done JSONB list[bool], chosen_at, withdrawn_at; partial unique one active per workspace). Routes per spec §3. `GET /v1/decision-records/current` → active decision or null.
- [ ] Failing tests: GET shape; choose open/step ok, not_open/unknown 409; choosing another withdraws the first; steps toggle persists and validates index; withdraw; auth 401; `test_decision_keeps_snapshot`; `test_legacy_roadmap_rows_ignored`; migration up/down.
- [ ] Implement; full suite; commit `feat(roadmap): route decision and API`.

### Task 4: Roadmap page
**Files:** Create `frontend/components/counselor/workspace/roadmap.tsx` (+ small parts file if >300 lines), `frontend/lib/roadmap.ts` (types), api methods in `frontend/lib/api.ts`; modify `shell.tsx`, `shell-parts.tsx` (section views `paths`, `roadmap`), `layout-context.tsx` / `use-desktop-workspace-state.ts` view lists (`roadmap`; old `compare`/`plan`/`roadmaps` alias to `roadmap`), `use-journey.ts` signals (`route_checked` when cards exist, `route_chosen` when chosen), `copy.json`, offline preview (`tests/preview/fake-api.ts`, `screens.cjs`, `flow.cjs`); Test `frontend/components/counselor/workspace/roadmap.test.tsx`.
- [ ] Failing tests: groups render with counts; card shows test, years, "needs 60% · you 78%"; uncertain rule shows "Check with the university"; route sheet timeline order and sources; compare needs 2–3 picks and renders the same rows per field; choose → "Your route" card with progress; tick step calls API; withdraw; empty states (no education → Vault link, no paths, bachelor note); 375px: compare table has sticky labels (class check).
- [ ] Design: same tokens and card style as Paths/Overview; status tones open=success, step=warning/amber, not_open=neutral, unknown=info. Implement; `npm test`, `npm run build`; capture preview screens at 375 and 1280; commit `feat(roadmap): one simple Roadmap page`.

### Task 5: Remove the old roadmap system
**Files:** per spec §4 and `roadmap-map.md` (backend generation, routers, plugin, jobs, enqueues, chat coupling, check-ins repoint to `RouteDecision`, data export, operator handoff, frontend components, chat roadmap comparison, old types/api, preview fakes, i18n keys, and their tests). Keep old models/tables; keep student requests; keep Mirror lanes; keep model role "roadmap" only if `paths/explain.py` still needs it (rename to `path_explain` if simple).
- [ ] Failing guard test `backend/tests/test_roadmap_removed.py`: `/v1/roadmaps` 404; `/v1/counselor/paths/{id}/roadmap` 404; no module imports `app.pai_c.roadmaps`, `plugins.roadmap_builder`, `pai_c.deep.roadmaps`; reconciler accepts a fact without enqueuing `roadmaps.mark_stale`; a chat turn context has no roadmap block. Frontend: no import of `components/roadmaps`.
- [ ] Remove; sync `COUNSELOR_V3_PROMPTS.md` if prompts change; update `DECISIONS.md` and `BUILD_REPORT_V1.md`; full backend suite, `npm test`, `npm run build`; commit `refactor(roadmap): remove the chat-linked roadmap system`.
