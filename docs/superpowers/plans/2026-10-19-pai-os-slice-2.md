# PAI OS Slice 2 (Knowledge) Implementation Plan

> **For agentic workers:** use superpowers:executing-plans (or subagent-driven-development) task by
> task, with TDD. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Research the programme facts from official pages, check them by rule, show each fact to the
student with its source and status, and re-check facts before deadlines (spec
`docs/superpowers/specs/2026-10-19-pai-os-slice-2-design.md`).

**Architecture:**
- A per-route **research profile** (YAML) defines the fields; Python has only generic types.
- A rule-based **page gateway** fetches official pages.
- A tool-less reader runs readings A/B(/C) on fenced text.
- **Trust rules and evidence validators** decide `confirmed`.
- An `os.research` DBOS workflow per (programme, intake, day) stores facts and hands changes to Slice 1's
  `_after_fact_change`, which completes the waiting tasks and re-dates the plans.

**Tech stack:** as Slice 1, plus Pydantic AI 2.55 (`DBOSDurability`), httpx and pypdf (already
dependencies). No new requirements (spec S2-D8).

## Global constraints

- Everything in Slice 1's global constraints still holds:
  - product code in `app/os`;
  - Tach (`app.os` depends on nothing);
  - no country terms in `app/os/**/*.py` (the red-flag test);
  - timezone-aware datetimes;
  - `tenant_id` on every table;
  - kernel-only plan writes;
  - one owner per task type;
  - DBOS step retries only;
  - idempotent side effects.
- The research agent has **no tools** (spec S2-D5). Its prompts fence page text.
- Spike 1 code is not imported. Re-write what is needed into `app/os/knowledge/research/`.
- **Branches:** `os/s2-tN-<name>`, each **cut from `pai-os`** and merged before the next task starts.
  Do not stack (the #53 lesson). If a task needs the previous one, wait for its merge.
- **Before every push**, from `backend/`: `tach check`, `python scripts/check_alembic_heads.py`,
  `python -m pytest tests/os -v -rs`. On Windows, the two crash tests run in the Linux container
  (see the Spike 1 report §8 setup).
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Shared files** need a Counsellor reviewer: `frontend/lib/api.ts` (Task 9). No requirements change.

## Rulings made while planning

- **R2-P1:** research is started by the worker's enqueue loop through `DBOSClient`, not from the handler
  (a DBOS step must not start workflows; this is the Spike 3 pattern).
- **R2-P2:** deadline re-checks mark facts `stale` (spec §4.7); there is no second research trigger.
- **R2-P3:** the 11 field names stay as in the Spike 1 answer key, so key v3 scores production output
  unchanged.
- **R2-P4:** `_after_fact_change` becomes the public `knowledge.after_fact_change(...)` (moved from
  `workers/manual.py`), used by the manual API and by research.
- **R2-P5:** the Spike 1 page cache is kept as a fixture,
  `tests/os/fixtures/research/spike1-pages-2026-10-19.json.gz` (178 pages; committed with this plan).
  The regression and replay tests read it.

## Review focus

1. Two plans waiting on the same programme start **one** research run a day
   → `test_one_run_per_programme_per_day`.
2. A fact research cannot confirm leaves its task in `waiting_review` with evidence, and the admin path
   still completes it → `test_unconfirmed_waits_for_admin`.
3. Research never overwrites a confirmed fact with a different value
   → `test_conflict_keeps_confirmed_value`.
4. The D1–D5 regression set is never confirmed wrong → `test_spike1_regressions`.
5. A crash during research leaves no duplicate `os_agent_runs` or facts → `test_crash_during_research`.

---

### Task 1: Research profile

**Files:** create `app/os/knowledge/profile.py`, `app/os/knowledge/profiles/germany_master.research.v1.yaml`,
`tests/os/test_profile.py`.

**Interfaces (`app.os.knowledge.profile`):**
- `FieldSpec`:
  - `name`, `type`: `enum | month_day | amount | level | level_scores | grade | name_set | season_set`;
  - `values: dict[str, list[str]] = {}` (value → aliases, for `enum` / `name_set` / `season_set` / `level`);
  - `scores: list[str] = []` (test names for `level_scores`);
  - `cycle_bound: bool = False`, `hint: str`.
- `ResearchProfile`: `key`, `version`, `route_key`, `official_sources: list[str]`, `link_keywords`,
  `month_names: dict[int, list[str]]`, `none_phrases: dict[str, list[str]]`, `exclusive_phrases`,
  `draft_email: str`, `fields: list[FieldSpec]`. `extra="forbid"` throughout.
- `load_profile(path)`, `load_profile_dir(dir) -> dict[str, ResearchProfile]` (by route_key; highest
  version), `class ProfileError(ValueError)`.
- `reading_model(profile) -> type[BaseModel]`, built with `create_model`:
  - one optional `Found` per field;
  - `Found` = `value`, `quote`, `url`, `cycle`, `scope_quote`;
  - enum values are `Literal`s built from the profile.
- The Germany profile carries the 11 Spike 1 fields, the values and aliases from Spike 1
  `fields.py`/`agent.py`, and the shared domains `uni-assist.de`, `daad.de`, `myguide.de`.

- [ ] **Step 1: Failing tests.**
  - `test_germany_profile_loads`;
  - `test_invalid_profile_rejected` (unknown type, duplicate field, an enum with no values, an unknown
    `none_phrases` field);
  - `test_reading_model_accepts_profile_values_and_rejects_others`;
  - `test_no_country_terms_in_python` (the existing red-flag test still passes).
- [ ] **Step 2:** Implement. **Step 3:** Pass, and run the pre-push checks.
- [ ] **Step 4:** Commit `feat(os): research profile and dynamic reading model`.

### Task 2: Tables `os_0003`, programme registry, seed

**Files:** modify `app/os/models.py`; create `alembic/versions_os/os_0003_slice2_knowledge.py`,
`app/os/knowledge/programmes.py`, `app/os/knowledge/seed/programmes_germany.yaml`,
`tests/os/test_programmes.py`; extend `tests/os/test_models.py`.

**Interfaces:**
- **Tables** `os_programmes`, `os_pages`, `os_research_runs`, `os_agent_runs`, with columns and unique
  keys exactly as spec §5. Plus the new `os_knowledge_facts` columns `source` (default `seed`),
  `research_run_id`, `evidence`.
- `ProgrammeStore(engine, tenant_id)`: `upsert(Programme)`, `get(ref)`, `active(route_key)`.
- `load_programme_seed(path, store) -> int`: idempotent, and never touches facts.
- **Seed:** 30 programmes. Refs, start URLs and domains come from `tests/os/quality/spike1_answer_key.yaml`
  sources plus the Spike 1 `EXTRA_START_URLS` / `EXTRA_DOMAINS`. Hof is `excluded`.

- [ ] **Step 1: Failing tests.**
  - `test_migration_matches_models` (extended);
  - `test_every_table_has_tenant_id`;
  - `test_seed_idempotent`;
  - `test_seed_refs_match_answer_key`;
  - `test_seed_does_not_touch_facts`;
  - `test_downgrade_then_upgrade`.
- [ ] **Step 2–3:** Implement; pass.
- [ ] **Step 4:** Commit `feat(os): slice 2 tables and programme registry`.

### Task 3: Page gateway, text and links

**Files:** create `app/os/knowledge/research/{__init__,text,links,pages}.py`,
`tests/os/test_research_pages.py`.

**Interfaces:**
- `text.html_to_text(html, base) -> (text, links)`, `text.pdf_to_text(bytes)`, `text.normalise(s)`
  (Spike 1 behaviour, including the garbled non-breaking space).
- `links.rank_links(pages, own_domains, keywords, seen, limit=5)`: own domains only; skips portals and
  wrapped URLs.
- `pages.PageGateway(engine, tenant_id, client: httpx.Client, settings, clock)`:
  - `fetch(url, programme, shared_domains) -> Page`, with the checks of spec §4.3 in that order;
  - `collect(programme, profile) -> list[Page]`.
- **Settings:** `fetch_host_interval_s` (default 2), `page_ttl_h` (24), `page_max_bytes` (5 MB).

- [ ] **Step 1: Failing tests** (httpx `MockTransport`):
  - `test_not_official_not_fetched`, `test_robots_disallow`, `test_robots_403_disallows_all`;
  - `test_host_interval_respected` (fake clock);
  - `test_too_big_refused`, `test_pdf_text`;
  - `test_cache_ttl_and_audit_row`, `test_rank_links_own_domains_only`.
- [ ] **Step 2–3:** Implement; pass.
- [ ] **Step 4:** Commit `feat(os): research page gateway`.

### Task 4: Trust rules and evidence validators

**Files:** create `app/os/knowledge/research/trust.py`, `tests/os/test_research_trust.py`,
`tests/os/fixtures/research/regressions.yaml` (D1–D5: programme, field, page URL from the snapshot, the
recorded wrong readings).

**Interfaces:**
- `quote_on_page`, `is_link_label`, `value_in_quote(spec, value, quote, profile)`,
  `list_complete(spec, value, quote, profile)`, `scope_ok(page, programme, quote, scope_quote)`.
- `judge(spec, readings: dict[str, Found | None], pages, programme, profile, min_cycle) -> Verdict`.
  `Verdict` has `status`, `value`, `quote`, `url`, `cycle_year`, `reasons`, `conflict_note`, `evidence`.
- **Rules:** exactly spec §4.4, in that order. A reading is valid only if all its checks pass;
  `confirmed` needs at least two valid readings that all agree.

- [ ] **Step 1: Failing tests.**
  - A table per rule and generic type: dates with German and English month names, amounts in both
    number formats, `none` phrases, a one-item list with and without an exclusive phrase, scope on a
    general page, a link label.
  - `test_spike1_regressions`: load the snapshot pages and `regressions.yaml`; every case is not
    `confirmed` with its wrong value.
- [ ] **Step 2–3:** Implement; pass.
- [ ] **Step 4:** Commit `feat(os): research trust rules and evidence validators`.

### Task 5: Agent spec, readings, spend

**Files:** create `app/os/agents/research.v1.yaml`, `app/os/agents/spec.py`,
`app/os/knowledge/research/readings.py`, `tests/os/test_research_readings.py`.

**Interfaces:**
- `AgentSpec`: id, version, zone, tier, tools (must be `[]` for zone `reader`), limits, retries.
  `load_agent_spec(path)`.
- `build_readers(model, profile, spec) -> dict["A" | "B" | "C", Agent]`.
  - Prompts are A, B and C from Spike 1, with field hints from the profile and a fenced page block.
  - Retries are `{tools: 0, output: 2}`; `DBOSDurability` uses the runner's step config.
- `model_for(settings, tier)`: OpenAI client with `max_retries=0`.
- `AgentRuns(engine, tenant_id)`: `record(run_id, reading, usage, cost, error)` with `ON CONFLICT DO NOTHING`,
  and `month_spend(now)`.
- `cost(usage)`: list prices from settings, cached input at the cached price.

- [ ] **Step 1: Failing tests** (`FunctionModel`):
  - `test_reader_has_no_tools`, `test_prompt_fences_page_text`, `test_cost_uses_cached_price`;
  - `test_agent_run_recorded_once` (a repeated record is ignored);
  - `test_invalid_output_repaired_max_two`.
- [ ] **Step 2–3:** Implement; pass.
- [ ] **Step 4:** Commit `feat(os): research readings, agent spec and spend`.

### Task 6: Research workflow and the `knowledge.research` module

**Files:** create `app/os/knowledge/research/run.py`; modify `app/os/runner/modules.py` (`KNOWLEDGE_RESEARCH`
replaces `KNOWLEDGE_MANUAL` as the owner of `knowledge.confirm_fact`), `app/os/runner/worker.py` (the
research enqueue in its loop), `app/os/knowledge/store.py` (upsert with source, evidence and run;
no-downgrade; `fact_changed` / `fact_conflict` events), `app/os/workers/manual.py` (uses
`knowledge.after_fact_change`, R2-P4); create `tests/os/test_research_run.py`.

**Interfaces:**
- `register_research(engine, settings, registry, kernel, knowledge, gateway, readers)` registers
  workflow `os.research(programme_ref, intake_year, day)` with steps `budget`, `collect`, `read_A`,
  `read_B`, `judge`, `read_C` (only if needed), `judge`, `store`. It is called before `DBOS.launch()`.
- `research_workflow_id(tenant, ref, intake, day)`.
- `enqueue_research(engine, client, tenant_id, today) -> int`: programmes with `confirm_fact` tasks in
  `waiting_review` whose result says `waiting_for: research`, and no run today. Enqueue with
  "return-existing".
- `store_research(...)`: spec §4.6 step 4–6.

- [ ] **Step 1: Failing tests** (fake model, golden student, `dbos_worker` fixture):
  - `test_confirm_task_waits_for_research`;
  - `test_one_run_per_programme_per_day`;
  - `test_confirmed_fact_completes_task_and_redates_plan`;
  - `test_unconfirmed_waits_for_admin` (then the admin confirm completes it);
  - `test_conflict_keeps_confirmed_value`;
  - `test_budget_exceeded_skips_run`;
  - `test_registry_single_owner`;
  - `test_fake_routes_run_unchanged` (still).
- [ ] **Step 2–3:** Implement; pass.
- [ ] **Step 4:** Commit `feat(os): research workflow and knowledge.research module`.

### Task 7: Freshness sweeper

**Files:** create `app/os/workers/freshness.py`; modify `app/os/workers/jobs.py` (daily `os.freshness`)
and `app/os/knowledge/store.py` (`mark_stale`, intake-year matching, M17); create `tests/os/test_freshness.py`.

- [ ] **Step 1: Failing tests:**
  - `test_old_confirmed_fact_goes_stale`;
  - `test_deadline_fact_stale_at_30_and_7_days` (end of day in the fact's timezone);
  - `test_stale_triggers_confirm_task_and_research`;
  - `test_confirm_matches_intake_year`;
  - `test_freshness_schedule_registered`.
- [ ] **Step 2–3:** Implement; pass.
- [ ] **Step 4:** Commit `feat(os): freshness sweeper`.

### Task 8: API

**Files:** modify `app/os/api/{router,schemas,queries,services}.py`; create `tests/os/test_api_knowledge.py`.

- [ ] **Step 1: Failing tests:**
  - `test_research_trigger_admin_only` (and that it enqueues with the day's workflow ID);
  - `test_research_runs_list`;
  - `test_facts_open_has_evidence`;
  - `test_student_sees_only_own_programmes`;
  - `test_programme_facts_show_status_source_quote`.
- [ ] **Step 2–3:** Implement (spec §4.8); pass. The legacy suite is still green.
- [ ] **Step 4:** Commit `feat(os): knowledge API`.

### Task 9: Programme facts page and inbox labels (frontend; `api.ts` shared)

**Files:**
- create `frontend/app/[workspaceId]/os-programmes/page.tsx`, `frontend/components/os/programme-facts.tsx`,
  `frontend/lib/os-programmes.ts`, `frontend/components/os/programme-facts.test.tsx`;
- modify `frontend/components/os/inbox-list.tsx` (the fact label and a link) and `frontend/lib/api.ts`
  (`getOsProgrammes`; **shared file**).

- [ ] **Step 1: Failing Vitest tests:**
  - labels for confirmed, unconfirmed and stale;
  - the source link;
  - the quote shown on tap;
  - the draft email filled from the template;
  - the conflict note shown;
  - the 360 px layout (no overflow class).
- [ ] **Step 2–3:** Implement; `npx vitest run`, `npx tsc --noEmit`, and `npm run build` with
  `NEXT_PUBLIC_OS_ENABLED=true`.
- [ ] **Step 4:** Commit `feat(os): programme facts page and inbox fact labels`. The PR names a
  Counsellor reviewer for `api.ts`.

### Task 10: Replay, crash and quality gate

**Files:** create `tests/os/test_research_replay.py`, `tests/os/quality/run_research_quality.py`,
`docs/os/slice-2-quality-report.md` (after the billed run); extend `tests/os/test_crash.py`
(research in the loop).

- [ ] **Step 1: Failing tests:**
  - `test_replay_spike1_reruns`: the readings recorded in `docs/os/spikes/spike1-results/rerun9-11.json`,
    with the snapshot pages, go through `judge`. The correct rate against key v3 is ≥ the Spike 1 value
    per run, and every newly unconfirmed fact names its rule.
  - `test_crash_during_research`: workers are SIGKILLed during research (fake model). No lost task, and
    no duplicate `os_agent_runs` row or fact. It runs in Linux CI.
- [ ] **Step 2:** Implement the quality runner. It runs the production `collect` → readings → `judge` on
  the 30 programmes (no plans, no store), scores with the Spike 1 matching rules against key v3, and
  prints both rates and the pass line. `--runs 3 --min-cycle 2026`.
- [ ] **Step 3:** All CI tests pass. Then a developer runs the billed gate (`--runs 3`, about $3) and
  writes `docs/os/slice-2-quality-report.md`:
  - every run, the rates and the cost;
  - every wrong fact, with its cause.
- [ ] **Step 4:** If the gate fails, stop: report, then the owners decide (spec Q1). Do not change the key or
  the thresholds to pass.
- [ ] **Step 5:** Commit `test(os): research replay, crash and quality gate`. After the gate passes,
  delete `backend/spikes/` in its own PR.

---

## Done when (Slice 2 gate, spec §9)

- All the tests above pass in CI: `os` (Linux, crash tests included) and `legacy`.
- The billed quality gate passes in each of 3 runs (correct ≥ 0.95, confirmed ≥ 0.70, key v3,
  `min_cycle 2026`), recorded in `docs/os/slice-2-quality-report.md`, and the developers sign it.
- The readiness doc (`docs/os/slice-1-readiness.md` → a Slice 2 section) lists what is still mock or
  unconfirmed.
