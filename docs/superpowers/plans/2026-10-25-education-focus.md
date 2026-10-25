# Education Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Onboarding captures exact current education, paths become real fields of study (0–5, never forced) filtered by the student's group, and PAI stays on education.

**Architecture:** Data first (catalog lists and a study-fields file), then onboarding (backend + frontend), then the path analyzer, then the counselor prompt and policy. Every write still goes through propose → reconcile.

**Tech Stack:** FastAPI, SQLAlchemy 2, pytest; Next.js, vitest.

**Spec:** `docs/counselor/EDUCATION_FOCUS_SPEC.md`

## Global Constraints
- Branch `education-focus` (from `pai-c`). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Lists live in data (Vault catalog choices, `pai_c/policy/study_fields.json`); no field, group or country names hardcoded in code.
- Keep existing education codes readable: `fsc` + `pre_engineering`/`pre_medical`, `ics`, `icom`, `fa`, `matric`, `o_level`, `a_level`.
- Prompts in `.md`; sync `docs/counselor/COUNSELOR_V3_PROMPTS.md` when a counselor prompt changes.
- No migrations expected; DB changes only via Alembic if truly needed. No live model calls in tests. Never edit `.env`.
- Tests from `backend/` with the shim (see `.superpowers/sdd/2026-10-25-education-focus/env-notes.md`); frontend `npm test`, `npm run build`.

## Review Focus
- A student who picks "Other" level must still finish onboarding and get no paths until education is known → Task 3 `test_no_paths_without_education`.
- An old account whose education is `fsc` without a group must still load the form prefilled → Task 2 `test_legacy_fsc_prefill`.
- ICS student and engineering: shown only as "needs checking", never as plainly open → Task 3 `test_check_field_is_flagged`.
- Analyzer output naming a field outside the allowed list is dropped, not shown → Task 3 `test_unknown_field_dropped`.
- Pre-Medical student never gets Mechanical Engineering as a plain fit → Task 3 `test_group_filters_fields`.

---

### Task 1: Education lists and the study-fields file
**Files:** Modify `backend/app/memory/catalog/vault_catalog.json` (choices: `levels` gains `intermediate`, `dae`, `bachelors`, `masters` where missing; new `matric_groups`, `o_level_subjects`, `a_level_subjects`, `dae_technologies`); Create `backend/app/pai_c/policy/study_fields.json`, `backend/app/pai_c/paths/fields.py`; Test `backend/tests/test_study_fields.py`.
**Interfaces:** `study_fields() -> dict[str, StudyField]` (`key`, `title`, `family`, `levels`, `isced`, `open_to: list[str]`, `check: list[str]`); `fields_for_group(group_code: str) -> tuple[list[StudyField], list[StudyField]]` (open, check); `student_group(education_record: dict) -> str | None` (maps `fsc`+`pre_engineering` → `pre_engineering`, `ics` → `ics`, A-level/O-level subjects to a group by rule in data, etc.).
- [ ] Failing tests: every field has a valid ISCED code from `fields_of_study.json`; every `open_to`/`check` value is a known group; at least 40 fields covering engineering, computing, medical/health, business, sciences, arts/humanities, law, architecture/design; `fields_for_group("pre_medical")` includes MBBS and excludes Mechanical Engineering from `open`; `fields_for_group("ics")` has Computer Science in `open` and at least one engineering field in `check`; `student_group` covers every intermediate group and legacy `fsc` without a group returns None.
- [ ] Implement; run tests and the full backend suite; commit `feat(education): education lists and study fields by group`.

### Task 2: Onboarding asks level, group and status
**Files:** Modify `backend/app/memory/onboarding.py` and the catalog `onboarding` entries (dependent fields: `group` shown for a level that has one, `subjects` multi for O/A-level, `technology` for DAE, `field` for bachelor/master from study fields, `status` + `year`); Modify `frontend/components/onboarding/onboarding-view.tsx`, `frontend/lib/onboarding.ts`, copy; Test `backend/tests/test_student_onboarding.py`, `frontend` onboarding tests.
**Interfaces:** `GET /v1/vault/onboarding` fields gain `depends_on: {field, values}` and `multi: bool`; `POST` writes ONE education record (`qualification_name`, `field_of_study`, `academic_status`, `details.subjects`, `graduation_year` or `details.current_year`).
- [ ] Failing tests: backend `test_intermediate_pre_med_writes_fsc_record`, `test_a_level_subjects_saved`, `test_group_required_when_level_has_groups`, `test_legacy_fsc_prefill`, `test_other_level_needs_no_group`; frontend: picking Intermediate reveals the group chips, picking O-level reveals subject chips, status and year, submit payload shape.
- [ ] Implement in the existing step-2 design (same chips, spacing, copy style); run backend suite, `npm test`, `npm run build`; commit `feat(onboarding): exact current education with group and status`.

### Task 3: Paths are fields of study, 0–5, filtered by group
**Files:** Modify `backend/app/pai_c/paths/analyzer.py`, its prompt, `backend/app/pai_c/policy/path_analyzer.json` (`max_paths: 5`, new `min_fit` rule), `backend/app/pai_c/possibilities.py` if titles are set there; Test `backend/tests/test_path_fields.py`.
**Interfaces:** analyzer input lists only `fields_for_group(...)` (open + check, each marked); output entries name a `field_key`; title = study field title; `check` fields carry `needs_check: true` shown as "needs checking for your group".
- [ ] Failing tests: `test_group_filters_fields`, `test_check_field_is_flagged`, `test_unknown_field_dropped`, `test_no_paths_without_education`, `test_zero_paths_allowed` (model returns none → none saved and the student sees the "PAI needs to know more" state), `test_old_generic_paths_replaced`.
- [ ] Implement; run paths/possibility suites and the full suite; commit `feat(paths): fields of study by group, never forced`.

### Task 4: PAI stays on education
**Files:** Modify `backend/app/pai_c/voice/prompts/voice_guided.md` (education-first rules, no praise, no echo, one question when an education basic is missing), `backend/app/pai_c/policy/areas_policy.json` (priority: education/history, goals and field interest, options, pressures (budget, mobility), interests as academic subjects; values, strengths and daily life last and only if mentioned), `backend/app/memory/prompts/extractor.md` (hobbies as supporting evidence; third person; planned vs done), sync `docs/counselor/COUNSELOR_V3_PROMPTS.md`; Test `backend/tests/test_education_focus.py`.
- [ ] Failing tests: prompt contains the education-first rules and none of the praise words; `askable_areas` order starts with education and goals; with education and field interest missing, `decide` allows a question; extractor prompt says third person and done vs planned.
- [ ] Implement; run counselor suites and the full suite; commit `feat(counselor): stay on education; hobbies are supporting evidence`.
