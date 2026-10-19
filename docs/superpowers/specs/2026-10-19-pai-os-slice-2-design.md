# PAI OS Slice 2: Knowledge — Design Spec

Status: draft for review · 2026-10-19 · Parent spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md`
(the parent wins on any conflict). Inputs: the Spike 1 design and report (`docs/os/spikes/spike1-design.md`,
`docs/os/spikes/spike1-report.md`, PR #54), the Slice 1 spec and handoff, and the Spike 5 walkthrough.

## 1. Outcome

Programme facts are researched by the research agent from official pages and checked by rule.
Every fact a student sees carries its official source and a `confirmed` / `unconfirmed` / `stale`
label (parent success criterion 2). Plans re-date themselves when a fact changes. Facts are
re-checked before deadlines.

**Parent "Done when":** Spike 1 holds. §9 turns that into checks.

## 2. Decisions

| # | Decision | Choice |
|---|---|---|
| S2-D1 | Scope | Programme facts only (the 11 Spike 1 fields). Route facts (blocked account, visa) stay seeded or admin-supplied: Spike 1 did not measure them. |
| S2-D2 | Who owns `knowledge.confirm_fact` | A new module, `knowledge.research`, replaces `knowledge.manual` as the owner (invariant 2). The admin API to confirm or supply a fact stays: it is the fallback for anything research leaves unconfirmed. |
| S2-D3 | Unit of research | One research run per (programme, intake), shared by every `confirm_fact` task for that programme. It is a separate DBOS workflow (`os.research`) with workflow ID `research:{tenant}:{programme}:{intake}:{day}`, so a programme is researched at most once a day, however many plans wait for it. It is started by the worker's enqueue loop through `DBOSClient` (the Spike 3 pattern), never from inside a step. |
| S2-D4 | Country-specific data | Field definitions, enum values and aliases, official shared domains, link keywords, month names and "not required" phrases live in a per-route **research profile** YAML (invariant 12). Python has only generic field types (§4.2). |
| S2-D5 | The agent has no tools | Fetching and link choice are rule-based (Spike 1 SP1-D5). The agent only reads fenced page text and returns a typed answer. This meets invariants 6 and 9 by construction. |
| S2-D6 | Trust | Spike 1's rules (official domain, quote on the page, every valid reading agrees with at least two valid, cycle year), **plus** the evidence validators from the Spike 1 lessons (§4.4). Statuses stay three; a disagreement is `unconfirmed` with a `conflict_note` (S1-D6; Spike 1 lesson 10). |
| S2-D7 | Readings | A and B always; C only when a field has a single valid reading (Spike 1 SP1-D6 ruling). `cheap` tier (`gpt-5.4-mini`, D8). |
| S2-D8 | Text extraction | Standard-library HTML parser and `pypdf`, as in Spike 1. **No Docling in Slice 2:** Spike 1 did not need it, and adding it changes `requirements.txt`, a shared file that cannot reach `dev` now. Slice 3 (documents) decides. |
| S2-D9 | Cycle rule in production | A date or amount is `confirmed` only for the plan's intake year. Until WS 2027/28 is published, research stores what the page shows as `unconfirmed` for 2027, with a `conflict_note` naming the cycle the page gives ("page shows WS 2026/27"). The quality gate uses `min_cycle 2026` until then (§9). |
| S2-D10 | Spend | Every reading writes an `os_agent_runs` row (tokens, cached tokens, cost). Research has its own monthly cap, `OS_RESEARCH_MONTHLY_USD` (default 20). Over the cap, no research starts, the task waits for an admin, and a `budget_exceeded` event is written. |

**Out of this slice:** route-fact research, web search (Tavily/Brave), document reading (Slice 3),
Phoenix tracing, the Supervisor acting on escalations (Slice 7), and the Counsellor reading OS Knowledge
(Slice 8).

## 3. Layout

```
app/os/
  knowledge/
    profiles/germany_master.research.v1.yaml   research profile (S2-D4)
    profile.py        profile models, loader, dynamic field model (create_model)
    programmes.py     programme registry (os_programmes) + seed loader
    seed/programmes_germany.yaml               the 30 shortlist programmes (from the Spike 1 key's sources)
    research/
      pages.py        page gateway: robots, allowlist, rate limit, size limit, cache + audit (os_pages)
      text.py         HTML/PDF to text, links
      links.py        rule-based link ranking (keywords from the profile)
      readings.py     agent spec, readings A/B/C (Pydantic AI + DBOSDurability)
      trust.py        Spike 1 rules + evidence validators (§4.4)
      run.py          the research workflow and storing facts
    store.py          (+ evidence, source, research_run_id; fact_changed events)
  agents/research.v1.yaml                      agent spec (parent §3.2)
  workers/freshness.py                         daily sweeper
alembic/versions_os/os_0003_slice2_knowledge.py
tests/os/fixtures/research/                    recorded pages + readings for the regression set
tests/os/quality/run_research_quality.py       the billed quality run (manual)
frontend/app/[workspaceId]/os-programmes/page.tsx
```

The Spike 1 code (`backend/spikes/spike1/`) is not imported (Tach). The useful parts are re-written into
`app/os/knowledge/research/` with the profile replacing hard-coded terms. The spike folder is deleted in
its own PR after this slice's quality gate passes.

## 4. Components

### 4.1 Programme registry

- **Table `os_programmes`:** `tenant_id`, `ref` (unique per tenant), `route_key`, `university`, `name`,
  `aliases` (names the pages use), `start_urls`, `official_domains` (the university's own),
  `status` (`active` | `excluded`), `notes`.
- **Seed:** `seed/programmes_germany.yaml` has the 30 programmes. Start URLs and domains come from the
  Spike 1 answer key's sources and its `EXTRA_START_URLS` / `EXTRA_DOMAINS`. Hof is `excluded` (tuition).
  Loading is insert-or-update and never touches facts (handoff M6).
- RouteContract programme refs are checked against the registry when a plan starts. An unknown
  programme is accepted and its facts stay `fact_missing` (Slice 1 behaviour), with a warning event.

### 4.2 Research profile (per route)

- `key`, `version`, `route_key`.
- `official_sources`: shared domains (for Germany: uni-assist, DAAD, myGUIDE).
- `link_keywords`.
- `month_names`: English and German names per month.
- `none_phrases`: per field, the phrases that state "not required".
- `exclusive_phrases`: phrases that make a one-item list complete, such as "only" or "no summer intake".
- `fields`: the 11 fields. Each has:
  - a **generic type**: `enum`, `month_day`, `amount`, `level`, `level_scores`, `grade`, `name_set`, `season_set`;
  - its values and aliases (for example `uni_assist: ["uni-assist"]`);
  - `cycle_bound` (dates and amounts);
  - the prompt hint text.
- The loader validates the profile at startup and builds the reading model with `pydantic.create_model`.
  An invalid profile stops startup, naming the file and field (as playbooks do).
- The red-flag test (invariant 12) keeps passing: no enum value or domain is in Python.

### 4.3 Page gateway (the tool gateway for this slice, parent §3.2)

`fetch(url, programme) -> Page` is the only way research reads the web. It checks, in order:

- the URL's domain is official (the programme's domains or the profile's `official_sources`);
- robots.txt (a 401/403 robots file means disallow all);
- a per-host minimum interval (`OS_FETCH_HOST_INTERVAL_S`, default 2), held with a Postgres advisory lock;
- size ≤ 5 MB, and the content type is HTML or PDF.

Pages are cached in `os_pages` (url, final_url, status, text, links, fetched_at, blocked reason) for
`OS_PAGE_TTL_H` (default 24 h). The cache is also the audit log of what was read. Network retries happen
only as DBOS step retries, max 3 (invariant 7). The agent never sees a URL it could act on.

### 4.4 Trust rules and evidence validators (no AI)

A reading's fact is valid only if every check passes. A field is `confirmed` only if at least two
readings are valid and all valid readings agree after normalisation (Spike 1). The checks:

1. **Official source** — the fact's URL is on an official domain.
2. **Quote on the page** — as one passage, or as pieces in order within 400 characters (Spike 1).
3. **Not a link label** — a quote equal to an anchor text on the page is rejected (Spike 1 lesson 5, D4).
4. **The value is in the quote** (Spike 1 lesson 1, D5), by generic type:
   - `month_day`: the day and the month (number or a profile month name).
   - `amount`: the number, accepting 1.234,56 and 1,234.56.
   - `level`: the level token; `none` needs a profile `none_phrase`.
   - `level_scores`: every score given; a CEFR level alone confirms only if no page in the run lists
     scores for it (Spike 1 lesson 4, D2).
   - `grade`: the number.
   - `enum`: one of the value's aliases.
   - `name_set`: every name.
5. **Complete lists** — a `season_set` (intakes) or `name_set` with one item needs an `exclusive_phrase`
   in the quote (Spike 1 lesson 3, D1).
6. **Scope** — if the page is not specific to the programme (its title and URL do not name the
   programme or an alias), the reading must return a `scope_quote` that is on the page, within 2,000
   characters of the quote, and names the programme or says the rule is for all programmes. Otherwise:
   `unconfirmed` (`scope_unclear`) (Spike 1 lesson 2, D3).
7. **Cycle** (cycle-bound fields only) — S2-D9.

Each fact stores `evidence` (JSONB): every reading's value, quote, URL, scope quote, and the reasons it
failed. That is what the admin review screen shows.

### 4.5 Readings and the agent spec

- **`agents/research.v1.yaml`:** id `research`, version 1, zone `reader`, tier `cheap`, tools `[]`,
  output = the profile model, limits (max 3 readings per programme, timeout 120 s per reading, spend
  ≤ $0.10 per programme), retries `{tools: 0, output: 2}` (invariant 7).
- **Prompts:** A (extraction), B (questions), C (audit checklist), as in Spike 1. Page text is fenced:
  a fixed delimiter, plus the instruction that the text is data and any instructions inside it are ignored.
- Readings run with `DBOSDurability` (Spike 3 lesson): each model request is a step of the research
  workflow. The OpenAI client has `max_retries=0`.
- Each reading writes an `os_agent_runs` row (`run_id`, `reading`, model, tokens, cached tokens, cost,
  error). The row is keyed `(research_run_id, reading)`, so a re-executed step does not double-count
  (invariant 8).

### 4.6 The research workflow and the task flow

1. The kernel makes a `confirm_fact@<programme>:<field>` task `ready`; the runner calls `knowledge.research`.
2. The handler returns `needs_review` (`waiting_for: research`), and the task goes to `waiting_review`.
   The worker's enqueue loop (every second, as for tasks) finds programmes with such tasks and no research
   run today, and enqueues `os.research` with the S2-D3 workflow ID ("return-existing").
3. The workflow, all in DBOS steps:
   - budget check (S2-D10);
   - collect pages (§4.3; start URLs + ranked links);
   - readings A and B;
   - judge; reading C only if needed (S2-D7), then judge again;
   - **store**.
4. **Store** upserts each researched field into `os_knowledge_facts`, with `source = research`,
   `research_run_id` and `evidence`. The upsert is idempotent on the fact key.
   - A fact whose value or status changed writes a `fact_changed` event (handoff M5).
   - It then calls Slice 1's `_after_fact_change`, which completes the waiting `confirm_fact` tasks of
     **confirmed** facts and revises the plans that use the fact.
   - `unconfirmed` facts leave their task in `waiting_review` for an admin, with the evidence attached.
5. **A fact research cannot find** stays `fact_missing` and waits for an admin (`POST /v1/os/facts`, Slice 1).
6. **Facts never downgrade silently.** A `confirmed` fact is replaced only by a newer `confirmed` reading,
   or marked `stale` by the sweeper. Research that disagrees with a confirmed fact writes a `conflict_note`
   and a `fact_conflict` event for an admin; the value is not changed.

### 4.7 Freshness sweeper (from Slice 1, S1-D1)

A daily DBOS scheduled job, `os.freshness`:

- A confirmed fact older than `OS_FACT_TTL_DAYS` (default 30) becomes `stale` (`fact_changed`). The
  compiler already treats non-confirmed facts as provisional, with a `confirm_fact` task, so research
  runs again.
- Deadline facts are re-checked 30 and 7 days before the deadline (parent §3.2) by marking them `stale` on
  those days. That reuses the same loop (`stale` → `confirm_fact` task → research → re-dated plan); a
  second trigger is not needed.
- It also fixes M17: confirming or matching facts uses the intake year.

### 4.8 API (under `/v1/os`; admin calls use `X-OS-Admin-Token`)

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /research/{programme_ref}` | admin | Start research now (same workflow ID rule, enqueued through `DBOSClient`) |
| `GET /research/runs?programme=` | admin | Runs with pages, readings, cost and outcome |
| `GET /facts/open` | admin | (Slice 1) now with `evidence` and the last research run |
| `GET /programmes` | student | Facts of the programmes in the student's plan: value, status, source URL, quote, checked_at, conflict note |

### 4.9 Student screens (mobile-first, 360 px)

**Programme facts** — `frontend/app/[workspaceId]/os-programmes/page.tsx`, behind `NEXT_PUBLIC_OS_ENABLED`:

```
┌ Your programmes ──────────────────┐
│ TU Chemnitz · Embedded Systems    │
│ Deadline   15 Jul · ⚠ unconfirmed │
│            page shows WS 2026/27  │
│            source: tu-chemnitz ↗  │
│ Apply via  uni-assist · ✓ checked │
│            12 Oct 2026 · source ↗ │
│ English    IELTS 5.5 · ✓ checked  │
│ [Ask the university]  ▾           │
└───────────────────────────────────┘
```

- Every value shows its status label and source link. Tapping it shows the quote.
- `unconfirmed` and `stale` facts show why (the conflict note) and an **"Ask the university"** draft: a
  template from the research profile, filled with the programme and the question, which the student
  copies and sends themselves. Nothing is sent by the OS (parent trust flow; invariant 5 does not apply).
- **Inbox:** items whose date comes from a fact show the fact's label next to `provisional`/`estimated`,
  and link to the programme facts page.
- `frontend/lib/api.ts` gains `getOsProgrammes`. **This is a shared file: it needs a Counsellor reviewer.**

## 5. Tables (Alembic `os` branch, migration `os_0003`; every table carries `tenant_id`)

- `os_programmes` (§4.1).
- `os_pages` (§4.3): unique (tenant_id, url).
- `os_research_runs`: `id`, `programme_ref`, `intake_year`, `workflow_id` (unique), `status`
  (`running` | `done` | `failed` | `skipped_budget`), `started_at`, `ended_at`, `pages`, `confirmed`,
  `unconfirmed`, `cost_usd`.
- `os_agent_runs` (parent §4.1): `research_run_id`, `reading`, `agent`, `agent_version`, `model`,
  `input_tokens`, `cached_tokens`, `output_tokens`, `cost_usd`, `error`, `at`. Unique (research_run_id, reading).
- `os_knowledge_facts` gains `source` (`seed` | `manual` | `research`), `research_run_id`, `evidence` (JSONB).

## 6. Error handling (Slice 2 subset of parent §4.4)

| Failure | Handling | Ends in |
|---|---|---|
| Page fetch transient | DBOS step retry, max 3 | page `blocked: error:*` if still failing |
| robots / not official / too big | not fetched, logged in `os_pages` | facts from other pages only |
| Reading invalid output | Pydantic AI repair, max 2 | reading `error`, other readings still judged |
| Model service down | DBOS step retry, max 3 | run `failed`; tasks wait for an admin |
| Budget exceeded | no run; `budget_exceeded` event | tasks wait for an admin |
| Worker crash | DBOS resumes the research workflow | no duplicate facts or agent-run rows |
| Research contradicts a confirmed fact | value kept; `conflict_note` + `fact_conflict` event | admin decides |

## 7. Invariants touched

- 1: research writes facts, never plan state. Plans change only through `kernel.revise` from `_after_fact_change`.
- 2: `knowledge.research` owns `confirm_fact`.
- 3: every researched fact carries a quote, URL, check date and status.
- 6, 9: the reader has no tools and sees only fenced text.
- 7, 8: DBOS step retries only; idempotent upserts and agent-run rows.
- 11: Tach.
- 12: the research profile.
- 13: dates with their timezone.

Invariants 4 and 5 do not apply: no profile changes, and nothing is sent for the student.

## 8. Testing

Tests are written first (TDD). From `backend/`: `tach check`, the heads check, and `pytest tests/os`
(CI job `os`).

1. **Profile:** loads; an invalid profile stops startup; the built model accepts the Germany values; the
   red-flag test still passes.
2. **Gateway:** allowlist, robots, rate interval, size limit, cache TTL, audit row.
3. **Trust and validators:** a table-driven test per rule and generic type, plus the **Spike 1
   regression set**. These are recorded pages and readings in `tests/os/fixtures/research/` for D1–D5
   (Anhalt intakes, the BTU English handout, the TU Chemnitz German and route rules, the Koblenz menu
   label, the value-contradicts-quote case). None may be `confirmed` wrong.
4. **Replay:** the recorded readings of Spike 1 reruns 9–11 (`docs/os/spikes/spike1-results/`) go through
   the new judge. Correct rate against key v3 must not fall, and every newly unconfirmed fact names its rule.
5. **Workflow:** with a fake model, research stores facts with evidence, completes the waiting tasks of
   confirmed facts, re-dates the golden student's plan, and is not run twice the same day.
6. **Crash:** SIGKILL workers during research (fake model). No lost task, no duplicate `os_agent_runs`
   row, no duplicate fact. CI runs on Linux (the crash tests need SIGKILL).
7. **Sweeper:** TTL to `stale`, the 30- and 7-day re-checks, `fact_changed` events, intake-year matching.
8. **API and screen:** student sees only their programmes; admin-only endpoints. A Vitest test covers
   labels, source links, the quote on tap and the draft email.
9. **Fake routes:** still run unchanged (D5).

## 9. Done when (the slice gate)

- §8 is green in CI (`os` and `legacy`).
- **Quality gate ("Spike 1 holds"):** `tests/os/quality/run_research_quality.py` runs the production
  research on the 30 programmes against answer key v3, three times, with `min_cycle 2026`. **Each of the
  three runs** must reach correct rate ≥ 0.95 and confirmed rate ≥ 0.70. This is billed (about $1 a run)
  and run by a developer, and the results are recorded in a report.
- **If the gate fails** (the new validators can lower the confirmed rate): stop and report. The parent's
  fallback (show more facts unconfirmed, use fewer programmes) is the owners' call (Q1).
- Once WS 2027/28 is published, the same run with `min_cycle 2027` gates real pilot data.

## 10. Build order (for the plan; one branch and PR per task, off `pai-os`, not stacked)

1. Research profile: models, loader, dynamic model, Germany profile.
2. Tables `os_0003`; programme registry and seed.
3. Page gateway and text/link extraction.
4. Trust rules and evidence validators; the regression fixtures.
5. Agent spec, readings A/B/C, `os_agent_runs`, budget.
6. The research workflow, the `knowledge.research` module, store and `fact_changed`.
7. Freshness sweeper.
8. API.
9. Programme facts page and inbox labels (`api.ts` is a shared file).
10. Replay test, crash test with research, quality runner; then the billed gate run and its report.

## 11. Open questions for the owners

| # | Question | Proposal |
|---|---|---|
| Q1 | Gate strictness | Every one of three runs passes both bars (the parent's bar applied per run). The Spike 1 confirmed rate was 5 of 6, so if the gate fails, decide between the parent's fallbacks. |
| Q2 | Research budget | $20 a month cap (`OS_RESEARCH_MONTHLY_USD`), event at 75%. Separate from D7, which is per student and still "proposed". |
| Q3 | Show unconfirmed values to students? | Yes, labelled, with the cycle the page shows and the "Ask the university" draft (parent §3.2 trust flow). |
| Q4 | The remaining Spike 1 key questions (TOEFL new scale, HSRW GATE/GRE thresholds, Web Engineering A2, Koblenz, Anhalt) | A developer resolves them before the gate run; key changes need a source, a quote and the intake (Spike 1 lesson 9). |
