# Beta Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the beta: Claude-driven empathetic conversation that PAI drives, chat that knows onboarding, research-backed engines on strong models under one $100 cap, Pakistan-wide calendar, language-generic replies, "how PAI works", and extraction verified on a golden set.

**Architecture:** A provider layer in the inference gateway (OpenAI + Anthropic) with one monthly USD cap; the Director gains `intro`, `bank_question`, `about_pai` moves and a drive guard; a cached field-research store feeds the analyzer; a monthly refresh job proposes rule/calendar updates; the calendar gains regions.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic (head 122), pytest; `anthropic` SDK; Next.js, vitest.

**Spec:** `docs/counselor/BETA_CONVERSATION_SPEC.md`. Inputs: `.superpowers/sdd/2026-10-29-beta-conversation/` (academic_calendar_pk.json + summary, env-notes.md).

## Global Constraints
- Branch `beta-conversation` (from `pai-c` 159ff58). Commits end with the implementer model's `Co-Authored-By` trailer.
- No model, provider, language, board, field or copy hardcoded in code: `pai_c/policy/model_roles.json`, `model_costs.json`, `question_bank.json`, `about_pai.json`, `next_steps.json`, the calendar, `copy.json`.
- No live model/API calls in tests (mock both providers). Live runs only in Task 7 under the founder's caps ($5 each). Never print secrets; `.env` edits add missing names only.
- DB changes only via Alembic (next: 123). Prompts in `.md`; sync `docs/counselor/COUNSELOR_V3_PROMPTS.md`.
- Product rules: education first; evidence for every student fact; sources for every world fact; one question per reply; no praise/lectures; no universities before stage H.
- Tests from `backend/` with the shim (env-notes.md); frontend `npm test`, `npm run build`.

## Review Focus
- Anthropic key missing or provider down: the counselor falls back cleanly (fixed reply, logged), never a 500 → Task 1 `test_anthropic_failure_falls_back`.
- Student writes in English after Roman Urdu: the next reply and the next chat-posted message follow the latest language → Task 2 `test_language_follows_latest_turn`.
- Student answers a bank question with a one-word reply: PAI asks one gentle follow-up, never repeats the bank item → Task 2 `test_short_answer_gets_one_followup`.
- Field note missing (research off or capped): analyzer still runs with the same output shapes → Task 3 `test_analyzer_without_field_notes`.
- Board unknown and city outside Pakistan: timeline uses federal/uncertain, never crashes → Task 4 `test_region_fallback_federal`.

---

### Task 1: Providers and the monthly cap
**Files:** Create `backend/app/inference/anthropic_client.py`, `backend/app/pai_c/policy/model_roles.json`, `backend/app/pai_c/policy/model_costs.json`, `backend/app/routers/admin_usage.py`, test `backend/tests/test_providers.py`, `test_monthly_cap.py`; Modify `inference/gateway.py` (`resolve_role(role) -> RoleConfig{provider, model, api_key, base_url}`; `complete` dispatches by provider), `inference/client.py`, `inference/usage.py` (scope `models`, per-role est_usd, `cap_state() -> {spent, cap, stage: ok|research_paused|paused}`), `config.py` (`PAI_<ROLE>_PROVIDER`, `ANTHROPIC_API_KEY`, `PAI_RESEARCHER_MODEL`, `PAI_MONTHLY_CAP_USD`), `requirements.txt` (`anthropic`), `.env` (append missing names only via a script that never reads values), `.env.example`, `docker-compose.yml` (pass `ANTHROPIC_API_KEY`), `pai_c/deep/turn.py` + `opening.py` (cap fallback), `paths/analyzer.py`, `mirror/text_job.py`, `research/gateway.py` (research_paused skip).
- [ ] Failing tests: role resolution from data + env; Anthropic client maps system/messages/json_object and records usage (mock SDK); `test_anthropic_failure_falls_back`; cost per call recorded per role; at 80 % research/analysis skip with one daily log; at 100 % counselor fallback; admin usage endpoint auth + shape; `.env` script adds only missing names.
- [ ] Implement; full suite; commit `feat(inference): Anthropic provider per role and one monthly cap`.

### Task 2: PAI drives the conversation
**Files:** Create `pai_c/policy/question_bank.json`, `pai_c/policy/next_steps.json`, `pai_c/policy/about_pai.json`, `pai_c/policy/actions/intro.md`, `actions/bank_question.md`, `actions/about_pai.md`, `policy/prompts/drive_retry.md`, tests `backend/tests/test_director_drive.py`, `test_about_pai.py`, `test_language_generic.py`, `test_opening_knows_student.py`, golden fixtures `backend/tests/fixtures/conversations/{fresh_roman_urdu,english_student,short_answers,asks_about_pai,distressed}.json`; Modify `policy/actions/opening.md`, `pai_c/opening.py` (Vault core in context; chat_language), `policy/classifier.py` + `turn_classifier.md` (`language {code, script}`, request kind `about_pai`), `policy/state.py` (`next_bank_item`, `chat_language`), `policy/controller.py`, `policy/guided_table.json` (`intro`, `bank_question`, `about_pai`; cadence rule change), `deep/turn.py` (drive guard), `deep/context.py` (`<about_pai>`, language), `deep/grounding.py`, `voice/prompts/voice_guided.md` + `voice.md` (empathy rule, language-neutral examples, no "do not explore hobbies"), `config.py` (blocked-script replacement = student's language), `models.py` + migration 123 (`workspaces.chat_language` JSON or a column), chat-posted messages in `paths/analyzer.py` and `mirror/text_job.py` rendered in `chat_language` (copy via the counselor model when not English, cached per language), `docs/counselor/COUNSELOR_V3_PROMPTS.md`.
- [ ] Failing tests: opening names the education line and asks one open question; bank order and no-repeat; `test_short_answer_gets_one_followup`; drive guard rewrites then appends; care never drives; about_pai answers from data and may show_place; `test_language_follows_latest_turn`; no Roman Urdu default in code (grep guard); golden conversations run with fake models and assert moves, Vault fill, one question per reply, no banned phrases.
- [ ] Implement; full suite; commit `feat(counselor): PAI drives the conversation; knows onboarding; about PAI; language-generic`.

### Task 3: Engines with research
**Files:** Create `pai_c/paths/field_research.py`, model `FieldNote` + migration 124 (`pai_field_notes`: field_key, country, note JSONB, sources JSONB, confidence, researched_at), job `counselor.field_research`, `pai_c/research/rules_refresh.py` + job `counselor.rules_refresh`, `scripts/apply_refresh.py`, tests `test_field_research.py`, `test_rules_refresh.py`; Modify `paths/analyzer.py` (`<field_notes>` block; enqueue missing/stale notes after a run; `test_analyzer_without_field_notes`), `paths/explain.py` (reuse the note), `deep/prompts/path_analyzer.md` + prompt sync, `capabilities/system.py`, `config.py` (`PAI_FIELD_NOTE_DAYS`, `PAI_RULES_REFRESH_MAX_CALLS`), scheduler entry for monthly refresh.
- [ ] Failing tests: note built from mocked search/fetch with sources and verified quotes; cached and refreshed by age; analyzer cites note facts with sources; research_paused → no run; refresh writes a proposal file with diffs and never edits policy files; apply script applies a proposal and validates against the admission-rules tests.
- [ ] Implement; full suite; commit `feat(research): cached field notes and a monthly rules refresh`.

### Task 4: Pakistan-wide calendar
**Files:** Modify `pai_c/policy/academic_calendar.json` (merge `regions` from the research draft; keep sources/confidence; `_note` on gaps), `pai_c/roadmap/calendar.py` (`region_for(education_record, city) -> str`, board→region map in data: catalog `boards` choices gain `region`), `timeline.py` (region events first, then national; basis carries region + confidence), `memory/catalog/vault_catalog.json` (board → region), tests `test_academic_calendar.py`, `test_roadmap_timeline.py`.
- [ ] Failing tests: Karachi board student uses Sindh dates; A-level student uses Cambridge sessions + IBCC lag; `test_region_fallback_federal`; every region event has a source and confidence; summary gaps are null not invented.
- [ ] Implement; full suite; commit `feat(roadmap): Pakistan-wide calendar regions`.

### Task 5: Extraction golden set
**Files:** Create `backend/tests/fixtures/extraction/*.json` (≥ 12 cases across Roman Urdu, Urdu, English: education + marks, interests with source, strengths, family wish, budget band, mobility no/yes, goal, obstacle, duplicate statements, a correction), `backend/tests/test_extraction_golden.py` (normalizer + reconciler with fixed extractor outputs), `backend/scripts/eval_extraction.py` (live, `--cap-usd 5`, prints recall/precision per type, saves recordings for replay); Modify `memory/prompts/extractor.md` only where a golden case shows a rule gap (+ prompt sync).
- [ ] Failing tests per case; implement; commit `test(memory): extraction golden set and live eval script`.

### Task 6: Frontend touches
**Files:** Modify `frontend/components/chat/*` (render `about_pai` reply with the place button; nothing else new), `copy.json` (next-step copy if shown), admin usage page `frontend/components/counselor/workspace/settings.tsx` (founder-only "This month's model spend" card reading `/v1/admin/usage`), tests.
- [ ] Failing tests; implement; `npm test`, `npm run build`; commit `feat(frontend): usage card; about PAI reply`.

### Task 7: Live verification (founder caps)
**Files:** `backend/scripts/beta_smoke.py` (drives the API end to end with real models, `--cap-usd 5`), report `docs/counselor/BETA_SMOKE_REPORT.md`; run `scripts/eval_extraction.py --cap-usd 5`.
- [ ] Run both on the local stack once Task 1–6 are merged into the branch and keys are set; record results and cost; fix anything broken (new tasks if needed); commit `docs(counselor): beta smoke and extraction eval results`.

### Task 8: Docs
**Files:** `docs/counselor/BUILD_REPORT_V1.md`, `DECISIONS.md`, `README.md`, `SPINE.md`, `COUNSELOR_V3_PROMPTS.md` sync check.
- [ ] Update; commit `docs(counselor): beta conversation shipped`.
