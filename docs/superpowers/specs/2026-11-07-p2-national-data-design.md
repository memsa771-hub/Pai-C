# P2: national data system (phase spec)

Status: **approved by the owner** (chat, 2026-11-07) · Owner: MSAQLAIN
Master spec: `docs/superpowers/specs/2026-11-03-pai-connect-design.md` (§2, §3 R-23–R-35, R-42, R-48, R-60–R-69,
R-71, R-72, R-74–R-76, R-56–R-59; §6 rows 6.10, 6.20, 6.23–6.25; §7, §8, §9, §12 row P2, §13).
P1 spec: `docs/superpowers/specs/2026-11-04-p1-connection-core-design.md`. P1 handoff: `docs/connect/handoff/p1-handoff.md` (P1 signed off 2026-11-07). Visual overview: https://www.figma.com/board/X25QOs43qaDABBYEmzUPxk

**In one paragraph.** Today OS Knowledge can hold one fact per programme, field and intake year. Two automated
readings that agree make it `confirmed`, and research reads only HTML and digital PDFs, from domains listed per
programme. That was enough for 30 German programmes. P2 turns it into a national data system:
- a registry of every in-scope institution, built from named official lists, with programmes, admission bodies,
  systems, tests, seat categories and calendars;
- allow-lists per region, plus integrity checks on every page;
- reading of JavaScript pages, scans and Urdu notices;
- a third trust level, `verified`, given by two named people;
- a review queue and a spreadsheet loop (export, import, undo) that are two views of the same review records;
- facts keyed per intake, with a yearly rollover;
- daily monitoring in season, and reports of wrong facts from students;
- a coverage dashboard that reads the launch gate;
- `MeritCheck` and `ProgrammeFacts` for the Counsellor.

**The critical path is people, not code** (master §12). The P2 code is about 12 task groups. The P2 *gate*,
however, needs walkthroughs for every region, a registry loaded from official lists, a verified sample per region
and one hand-collected source. Those come from Claude's research and the data checkers. That lane (§7) starts on
day 1, before any P2 code exists, because the spreadsheet format is already fixed (R-67).

**What the student sees in P2.** Almost nothing new on Pakistani routes: their playbooks arrive in P3/P4. What
changes for every student:
- facts on screen show `verified` / "not confirmed" / "estimated" with the year;
- a "report this as wrong" link;
- notices when a fact in their plan is being re-checked;
- with the merit flag on, merit answers in the Counsellor come from `MeritCheck`.

Everything new sits behind flags that are off by default.

## 1. Requirements this phase covers

R-23–R-35, R-42, R-48, R-60–R-69, R-71, R-72, R-74–R-76. R-56–R-59 apply as in every phase. Master §6 rows tested
here: **6.10, 6.20 (with official calendars), 6.23, 6.24, 6.25**. Consistency rules (master §9.3) added here:
**9–12**. Rule 13 needs R-70 and comes in P4. R-35 is *built* here (the dashboard and gate reading); it is
*passed* in P5. Where each requirement is built: §6. Its proof: §9.

## 2. Decisions

### 2.1 Owner decisions

None yet. The questions are in §11. Until the owner answers, each one uses its recommended default.

### 2.2 Technical decisions (proposed here; approved with this spec)

| # | Decision |
|---|---|
| P2-D1 | **One phase spec; one implementation plan per task group**, written just before that group is built (as P1-D1). |
| P2-D2 | **The OS registry is the only registry.** The Counsellor's `pai_institutions`, `pai_institution_domains`, `pai_opportunities` and `pai_requirement_sets` (`app/models.py:1404`, `:749`, `:701`, `:722`) stay for the Counsellor's own research and student-added places. They are never copied into the OS, and the OS is never copied into them (master §4, D-03). Stage H reading the OS registry is R-49 (P3/P4). |
| P2-D3 | **Extend, don't replace.** `os_programmes` (`app/os/models.py:225`) becomes the programme level of the registry by additive columns. `os_knowledge_facts` (`:199`) stays the one fact table, with new columns. `PageGateway` (`knowledge/research/pages.py:59`) stays the one way to read the web. `trust.quote_on_page` (`trust.py:115`) stays the quote rule. `after_fact_change` (`knowledge/changes.py:20`) stays the one path from a fact change to plan revisions. |
| P2-D4 | **Standing facts live on registry rows; Knowledge facts are always per intake.** An institution's existence, name, official site, region and type, with their official-list source, are registry columns (R-60, "stored once"). Everything in `os_knowledge_facts` is cycle-bound and keyed by intake. This avoids sentinel years. |
| P2-D5 | **Intake key = term + year.** `os_knowledge_facts` gains `intake_term`. The unique key becomes `(tenant, scope, ref, field, intake_term, intake_year, owner_ref)`. Existing rows are backfilled with the term of the route's playbook (Germany: its `target_intake.term`). Term codes come from a data file, never from code (R-62). |
| P2-D6 | **Trust statuses.** Knowledge status becomes `unconfirmed / confirmed / verified / stale` (today `confirmed / unconfirmed / stale`, `knowledge/port.py:9`). `verified` needs `confirmed` first, then two review records by two different reviewers (§4.5). Research and spreadsheet row statuses (`found / unconfirmed / conflict / not_readable / not_found / lead_only / superseded`, R-67) are *row* statuses, not Knowledge statuses. The import maps them (§4.6). |
| P2-D7 | **High-stakes is data.** `knowledge/fact_classes.yaml` lists each field's class and whether it is high-stakes (deadlines, schedule dates, merit formulas, eligibility thresholds, seat categories and quotas, fees, test dates, test pattern and syllabus). The display rule "high-stakes shows as fact only when `verified`" (R-25) is one function in `knowledge/display.py`. Every surface (`ProgrammeFacts`, `plan_view`, `MeritCheck`, the compiler's provisional flag) calls it. |
| P2-D8 | **A threshold has an owner (R-75).** Facts gain `owner_ref` (the registry id of the body that sets the value; empty for facts with no owner, e.g. a deadline of the institution itself). A regulator's figure and an admitting body's figure are two rows. When the admitting body cites the regulator and the regulator's document does not state it, the import (or research) opens a `conflict` review item. The admitting body's row is still the rule for that body. |
| P2-D9 | **Append-only history.** New table `os_fact_revisions`: every insert, change, status change and undo of a fact, with who or what caused it (research run, import id, reviewer, monitoring, report). An import undo replays the revisions backwards (R-68). Nothing is deleted. A row replaced by a newer intake stays (R-60). |
| P2-D10 | **The allow-list is data, its status is state.** Reviewed allow-lists are YAML files per region and family in `knowledge/sources/` (domain, body registry id, tier `regulator / board / admission_body / institution`, the official list or page that names the domain, reviewed by). They load into a new table `os_source_domains`, which also holds runtime state (`active / suspect`, reason, since). The preferred-suffix rule for two domains claiming one body (R-71) reads its suffixes from the same data, so no country suffix appears in code (R-58). The Germany profile's `official_sources` and `os_programmes.official_domains` keep working: they load as allow-list entries for that route. |
| P2-D11 | **Page snapshots.** New table `os_page_snapshots` (url, sha256 of the normalised text, text, content type, read method `fetch / render / ocr / human`, language, fetched_at), plus `os_source_files` for the original bytes of PDFs and images, with a size cap. The review queue shows the snapshot. Monitoring compares snapshots. `os_pages` stays the cache. |
| P2-D12 | **Headless reading (R-74) is a fallback inside `PageGateway`.** When a fetch returns a JavaScript shell (a little visible text plus script markers, thresholds in settings), the gateway renders the page with Playwright, which is already a backend dependency (`backend/requirements.txt:15`), through the egress proxy pattern of `app/browser/egress.py`. The adapter lives in `app/os/knowledge/research/render.py`. It uses no Counsellor code: Tach allows only `app.os`. Only if rendering also fails is the source `not_readable` (R-72). |
| P2-D13 | **OCR (R-29, D-15) behind a port `ScanText`.** The default adapter is Docling, as master §8.1 names, local with no model cost. Its first step is a bake-off on committed fixtures: English and Urdu scans of notices and merit lists, with Docling, Tesseract and the existing vision OCR pattern (`app/documents/ocr.py:59`). The winner must pass the quote-match on the fixtures. A paid vision adapter is used only within the owner's cost cap (§11 Q5). Machine-read text from an image keeps `read_method: ocr`, and its facts stay `unconfirmed` until a checker compares them with the original (R-72). |
| P2-D14 | **Urdu text normalisation is data.** `knowledge/research/normalise.yaml` holds the character folding: Arabic and Urdu forms of yeh, kaf and heh, diacritics, digits. `text.normalise` (`text.py:63`) applies it. Quotes stay in the original language (D-15). |
| P2-D15 | **Reviewers have their own identity.** New table `os_reviewers` (id, display name, role `checker / approver / admin`, hashed personal token, active). The review API needs a reviewer token, not the shared admin token (`api/deps.py:23`). The two-person rule compares reviewer ids. A script `backend/scripts/os_reviewers.py` adds and disables reviewers (no SQL by hand). This works in standalone mode, and checkers need no student-app account. |
| P2-D16 | **Spreadsheets and the queue share one record.** Every check is an `os_fact_reviews` row (fact or row id, reviewer, step `check / approve`, outcome `correct / wrong / unclear / approve / reject`, corrected value and quote, evidence file, at). The spreadsheet carries reviewer ids in the checker columns. Because typed ids can be faked, **each reviewer also attests the batch once in the queue** ("I checked rows of batch X": one click) before the import accepts their column. The queue's export writes the R-67 layout (R-69). |
| P2-D16a | **Batches 1–5 (v4) are an owner-accepted import, not a reviewer import.** Both checker columns name Claude (check 1 and check 2), so they cannot pass the reviewer-id and attestation rule of P2-D16. By the owner's decisions of 2026-11-06 and 2026-11-07, recorded in `docs/research/batches/README.md`, rows accepted by both checks load as `verified`. Their provenance is `checked_by: claude_check_1 / claude_check_2` and `accepted_by: owner`, with no reviewer id. The import has a separate mode for this, `--owner-accepted <decision ref>`, so the two kinds never mix. Rows check 2 rejected, and every row marked `wrong`, go to the queue. Rows marked `unclear` or `not_readable` load as `unconfirmed`. A non-official source is never loaded as fact (R-72). Later batches use P2-D16. |
| P2-D17 | **Spreadsheet file format: `.xlsx`** with the three sheets of R-67 and a fourth, read-only `Lists` sheet (the allowed status, region and outcome values). The import also accepts the same sheets as CSV files. New dependency: `openpyxl`, which is pure Python. |
| P2-D18 | **Two ways in, one set of trust rules.** The OS research pipeline (`knowledge/research/run.py`) and the spreadsheet import both end in the same `knowledge.record()` call. It applies: the allow-list and suspect check, the quote on a stored snapshot, the intake, `owner_ref` and revisions. A spreadsheet row whose `read_method` is model-extracted (WebFetch) or OCR is re-fetched through `PageGateway`, and its quote is matched word for word before it can be `confirmed` (R-68). |
| P2-D19 | **Research profiles per family, as data.** For the Spike 1 rerun on every region, research gets profiles for the two families' fields (`knowledge/profiles/<family>.research.v1.yaml`), keyed by family, not by playbook. Playbooks stay P3/P4 (R-81). |
| P2-D20 | **Monitoring pauses through the kernel.** A changed source sets its facts back to `unconfirmed` and calls `after_fact_change`. Steps that use a now-unconfirmed high-stakes fact become `blocked` with the new reason `fact_rechecking`, through the P1 blocked mechanism (P1 §3.5). Students get the P1 "plan revised" `os_event` and a notification. The texts are in a data file. Nothing goes to chat (R-45). |
| P2-D21 | **The season calendar is Knowledge.** Facts of class `notice_window` (when a region's notices usually appear, per family and intake) decide when daily monitoring runs for that region. With no such fact, monitoring falls back to the existing TTL sweeper (`workers/freshness.py:44`). It never invents a season. The Counsellor's `app/research/season_policy.json` is a different owner's file and is not used. |
| P2-D22 | **Reports from students (R-28)** set the fact back to `unconfirmed` at once, as the master spec requires, and open a review item. Each student may report a few facts a day (`rate_limit`). The same fact reported again joins its open item. Guardians report through the student's screen; there is no guardian login in P2. |
| P2-D23 | **Intakes are rows.** New table `os_intakes` (region, family, term, year, state `planned / open / current / closed`, gate passed at). The rollover job (§4.8) opens a row from the previous one. An intake becomes `current` only through the coverage gate (R-66). |
| P2-D24 | **Other years are labelled, never silent (R-26, R-63).** The Knowledge port's read gains `fallback_previous=True` for plans of an intake whose facts are not yet published. It returns the newest earlier intake's fact, marked `other_intake`. The compiler treats such a fact as provisional, and every surface prints its year. A plan keeps `fact_refs` without a year, so the new intake's fact revises the plan on its own (row 6.10). |
| P2-D25 | **Playbook versions name their intakes (R-65).** An optional `applies_to:` (term, from-year) on playbook versions. The compiler picks the newest version that applies to a new plan's intake. Pinned plans are unchanged (`os_playbook_pins`, `models.py:134`). |
| P2-D26 | **MeritCheck reuses the eligibility methods.** A merit formula is a structured fact value: named parts, the marks part each uses (for example Part-I only), weights, totals and the owner body. `MeritCheck` computes it with `eligibility/methods.py` `weighted_aggregate` from `StudentFacts` (P1). It answers "not confirmed" unless the formula is `verified`. It never predicts a chance (R-31). Closing merits carry `list_complete: true/false`. With `false`, the fact is stored as "lowest on list N", never as the closing merit. |
| P2-D27 | **New and versioned contracts.** `programme_facts.v1`, `merit_check.v1` (master §9.1) and `programme_list.v2` (v1 plus `coverage_level`, `region` and an "not run yet" flag; v1 stays frozen, `contracts/programme_list.py`). Each comes with a schema, samples and frozen-hash tests, as in P1. |
| P2-D28 | **Counsellor changes go through the two freeze exceptions the owner already approved (master §10).** Exception 2: merit answers from `MeritCheck`, behind flag `CONNECT_MERIT_ANSWERS`. Exception 3: `policy/academic_calendar.json` and `policy/admission_rules.json` move into Knowledge, with an adapter that returns the same shape, behind flag `CONNECT_CALENDAR_FROM_KNOWLEDGE`. Each PR carries the `freeze-exception` label, the R-ID, a replay and the Counsellor lead's approval. Their current entries carry `confidence: official / secondary / uncertain`. They enter Knowledge only through the import, as research rows: `official` rows enter as `unconfirmed` until verified, the others as `lead_only`. |
| P2-D29 | **P2 gate scope versus the launch gate.** The P2 gate needs walkthroughs for every region, the registry at 100% of each named official list (`listed`), and a *sample* per region verified for the Spike 1 rerun. The full verified floor (R-35b) is P5. This keeps the people work on P2's critical path small. |
| P2-D30 | **Spike 1 rerun design.** Per region, a sample of 5 institutions (plus the national bodies) with all their high-stakes fields for the latest published cycle. The answer key is made by a checker who did not verify those rows (checkers swap regions). It is scored with the existing `tests/os/quality/scoring.py` matching. The bars are master §12: 100% correct on `verified`, ≥ 95% on `confirmed`. Billed runs need the owner's cost cap (§11 Q5). |

## 3. What exists today (reuse, read on 2026-11-06 on `pc/p1-t6-proposals`)

| Area | Exists | Where | P2 use |
|---|---|---|---|
| Knowledge facts | One table keyed by scope (`route / programme`), ref, field, intake year. Value, quote, URL, checked_at, status, conflict note, source (`seed / manual / research`), research run, evidence | `app/os/models.py:199-221`; `knowledge/store.py:24` (`SqlKnowledge`: `programme_facts`, `route_facts`, `upsert`, `insert_if_absent`, `mark_stale`, `annotate`, `confirm`) | Extended (P2-D3–D9): `intake_term`, `owner_ref`, `fact_class`, `read_method`, `language`, status `verified`, scopes for registry entities |
| Fact rules | `Fact` dataclass: a confirmed fact needs a quote and URL; timezone-aware dates | `knowledge/port.py:13-35` | `verified` added, with the same rules |
| Fact change → plans | Completes waiting confirm tasks and revises plans of the fact's intake year; re-checks eligibility notes | `knowledge/changes.py:20` | Reused by import, review, monitoring and reports |
| Admin fact API | Confirm, supply, list open confirm tasks (shared admin token) | `api/router.py:236-258`; `workers/manual.py:16-50` | Kept for admins; reviewers use the new review API |
| Research pipeline | Per-programme workflow, two readings (plus a third), trust judge, store without downgrading a confirmed fact | `knowledge/research/run.py:97` (`store_research`), `:164`; `trust.py:365` (`judge`), `:115` (`quote_on_page`), `:312` (`cycle_year`) | Kept; ends in `knowledge.record()` (P2-D18); family profiles (P2-D19) |
| Page gateway | Official-domain check, robots.txt, per-host interval, size cap, HTML and digital PDF (pypdf), redirect off-list refused, cache and audit in `os_pages` | `knowledge/research/pages.py:59-196`; `text.py:51` (`html_to_text`), `:59` (`pdf_to_text`), `:63` (`normalise`); `models.py:242` | Allow-list lookup, integrity checks, snapshots, render fallback, OCR (T3, T4) |
| Research profiles | Per-route field types, aliases, official sources, month names, as YAML | `knowledge/profile.py:72`; `knowledge/profiles/germany_master.research.v1.yaml` | New family profiles (data only) |
| Programmes | `os_programmes`: ref, route, university, name, aliases, start URLs, official domains, status | `models.py:225`; `knowledge/programmes.py:88` | Becomes the registry's programme level |
| Freshness sweeper | Daily: a confirmed fact goes `stale` after the TTL and at the 30- and 7-day deadline marks; writes `fact_changed` | `workers/freshness.py:44`; `workers/jobs.py:37` | Kept as the off-season fallback; season monitoring added (T7) |
| Programme list port | `programme_list` with `facts_confirmed` | `ports/plan_query.py:30`; `contracts/programme_list.py` | `programme_list.v2` with coverage (T10) |
| Eligibility methods | `linear_scale`, `threshold`, `weighted_aggregate` from playbook data | `eligibility/methods.py:33`; `eligibility/rules.py:13` | `MeritCheck` computes with them (P2-D26) |
| Estimates | Playbook constants carry `estimate: true`; the compiler marks the step `estimated` | `playbooks/models.py:132`; `compiler/compile.py:269`, `:351` | R-30 label proved on screen (T10) |
| Playbook pins | One pinned version per plan | `models.py:134` | `applies_to` intakes (P2-D25) |
| Document reading | Tool-less model reading of student documents by type; images or text | `documents/reader.py:45`, `:105` | Not used for official sources (different owner of the data) |
| OCR (Counsellor side) | Vision-model OCR for scanned uploads, behind a provider protocol, max 20 pages | `app/documents/ocr.py:51`, `:59`, `:102`; `app/config.py:235-241` | Pattern only (Tach forbids the import); bake-off candidate (P2-D13) |
| Headless browser (Counsellor side) | Playwright or Browser Fabric manager; egress proxy that pins every browser request | `app/browser/manager.py:99`; `app/browser/egress.py`; `requirements.txt:15` | Pattern for the OS render adapter (P2-D12) |
| Counsellor season and rule files | `season_policy.json` (empty, "no guessed entries"); `academic_calendar.json` and `admission_rules.json` with `official / secondary / uncertain` confidence | `app/research/seasons.py:8`, `season_policy.json`; `app/pai_c/policy/academic_calendar.json` (frozen), `admission_rules.json` (frozen); loaders `app/pai_c/roadmap/calendar.py:75`, `rules.py:59` | Calendar and rules enter Knowledge through the import (freeze exception 3); the season file is not used (P2-D21) |
| Counsellor institution identity | ROR lookup for officialness; `pai_institutions` | `app/plugins/_shared/institution_registry.py:17`; `app/models.py:1404` | Not used by the OS (P2-D2). ROR may be a lead, never a source |
| Review / admin screens | Admin support inbox with a typed token | `frontend/app/[workspaceId]/os-admin/support/page.tsx` | Pattern for `os-admin/review` and `os-admin/coverage` |
| Quality harness | Spike 1 scoring, answer key, page snapshot fixtures | `backend/tests/os/quality/run_research_quality.py`, `scoring.py`, `spike1_answer_key.yaml`; `tests/os/fixtures/research/` | Spike 1 rerun per region (P2-D30) |

**Not found in the repo:**
- **Research batches 1–4.** Searched `docs/`, every branch's history, and `/home/user`: no batch spreadsheet or
  notes. Only master §3 H3/H4 summarise them, and the import's legacy-layout mapping (R-68) needs the files (§11 Q1).
- **A registry**, allow-lists, integrity checks, OCR or rendering for official sources, a `verified` status,
  reviewer identities, a review queue, a spreadsheet import or export, intake terms, a rollover, or a coverage
  dashboard.
- **P1 dependencies P2 relies on** that are not built yet: P1 T8 (blocked reasons, `os_student_requests`), T9
  (facts on screen with their level, R-54) and T10 (the consistency job).

## 4. Design

### 4.1 The registry (R-32, R-33, R-34, R-60, R-76)

- **Entities**: `os_registry` rows, each with: id (stable, e.g. `inst:<slug>`), kind, parent id, region (R-76 code),
  institution type, name, aliases, official domains, status (`active / closed / merged / renamed`, with the
  successor id), the official list it came from, source URL, quote, checked_at.
  - Kinds: `regulator`, `board`, `admission_body`, `admission_system`, `entry_test`, `institution`, `campus`,
    `seat_category`, `calendar`, `official_list`.
  - Kinds are generic concepts and live in code. Their *instances* are data.
- **Programmes / streams**: `os_programmes` gains `institution_id`, `campus_id`, `level`, `field`, `family` and
  `region`.
- **Admission systems** link bodies to programmes: which body runs which system for which programmes, with the
  test and seat categories it uses. They are registry rows plus cycle-bound facts.
- **Official lists** (R-35a) are registry rows: the list's name, URL, date, the region and institution type it
  defines, and the row count as published. A checker confirms the count. Each institution names the list or lists
  it came from.
- **Coverage level** (R-34) is computed, not stored:
  - `listed`: the row exists;
  - `researched`: at least one cycle-bound fact for the coming intake;
  - `verified`: every high-stakes fact of the coming intake is `verified`.
  - A `not_readable` institution with no official online information stays `listed`, with the "PAI can't run this
    place yet" label (R-35d).
- **Vocabulary** (R-76): `knowledge/regions.yaml` lists the region codes, display names and the spellings the
  import accepts. The import normalises every other spelling or rejects it.
- The registry is filled **only** by the import (§4.6) and, for corrections, by the review queue. No seed is written
  by hand from memory.

### 4.2 Sources: allow-lists and integrity (R-24, R-71)

- **Lookup.** `PageGateway.fetch` asks `os_source_domains` whether the domain is `active` for the region and family
  (or for the route, for Germany). Any other domain is refused with `not_official`; a `suspect` one with
  `suspect_domain`.
- **Integrity checks** run on every page fetched (thresholds and patterns in `knowledge/sources/integrity.yaml`):
  - spam patterns: gambling and link-farm words, in every language the data lists;
  - a link flood: the share of links to off-list domains against the domain's own last snapshot;
  - a wholesale change: the text's similarity to the last snapshot is below a bar, and no notice explains it;
  - valid TLS: httpx verifies by default; a failure is recorded, not ignored;
  - a redirect off the list: already refused, `pages.py:162`.
- **A failed check** marks the domain `suspect`:
  - its facts drop to `unconfirmed` (through `after_fact_change`);
  - nothing new is taken from it;
  - a `suspect_domain` review item opens.
  - Only an approver can set the domain back to `active` (two-person rule).
- **Two domains claiming one body:** the one with a preferred suffix (from data) stays, and the other is `suspect`
  until a person confirms it.
- **Proof:** the committed fixture of a page with injected gambling links (as described in master R-71) is refused,
  and its domain becomes `suspect`.

### 4.3 Reading what is hard to read (R-29, R-72, R-74, D-15)

- **Render fallback** (P2-D12) for JavaScript shells. `read_method: render`.
- **Scans and image-only notices:** OCR through `ScanText` (P2-D13), `read_method: ocr`, and the original file is
  kept in `os_source_files`.
- **Urdu:** normalisation from data (P2-D14). The quote is kept in Urdu, with `language: ur`.
- **Not readable** (blocked, login-only, failed OCR, render failed): the source and its facts get `not_readable`,
  and a `collect` review item opens. In it, a checker uploads the official document or a screenshot as evidence,
  types the value and the quote they read, and a second person approves. Those facts carry `read_method: human`.
  They can become `verified` but never `confirmed` by machine, because there is no machine reading to agree with.
- **Copies on secondary sites** may be recorded only as `lead_only` with their URL. They never become a source.

### 4.4 Trust levels and the display rule (R-23, R-25, R-26, R-30)

- `unconfirmed` → `confirmed` (the existing two-reading agreement; or, for an import row, the re-fetch and quote
  match) → `verified` (P2-D6, two review records).
- **Display** (one function, P2-D7). High-stakes facts show as fact only when `verified`; below that, "not
  confirmed" with the link. Other facts show from `confirmed`. A fact of another intake always carries its year.
  An `estimate` always says "estimated".
- Every surface that shows a fact (`ProgrammeFacts`, `plan_view` from P1, `MeritCheck`) gets it with URL, quote,
  checked date, intake and level (R-23, R-54).

### 4.5 The review queue (R-42, R-72, R-75)

- **Items** (`os_review_items`): `verify` (a confirmed high-stakes fact), `report` (R-28), `change` (monitoring),
  `suspect_domain`, `collect` (not readable), `conflict` (R-75, a document disagreement, or two readings that
  disagree), `import_dispute` (rows checkers marked `wrong / unclear`).
- **The screen** `frontend/app/[workspaceId]/os-admin/review`, reached with a reviewer token (P2-D15):
  - the snapshot with the quote highlighted, and the original file for PDFs and images;
  - the value, the intake and the owner body;
  - approve / reject / correct (with a new quote) / upload evidence.
- **Two-person rule:** the approver must differ from the checker. High-stakes facts need both. For other facts,
  one check suffices for `verified`. Their `confirmed` level is already shown as fact anyway.
- **Audit:** every action is an `os_fact_reviews` row plus an `os_fact_revisions` row. Nothing is edited in place.
- **Export** (R-69): any filter of the queue exports as an R-67 spreadsheet, and the same file imports back.

### 4.6 Spreadsheets: format, import, undo (R-67, R-68, R-69, R-76, D-13)

- **Format** (`knowledge/sheets/format.yaml`, P2-D17):
  - **Institutions:** `inst_id, kind, parent_id, name, aliases, region, inst_type, official_domains,
    official_list_id, source_url, quote_verbatim, read_method, retrieved, claude_status, claude_note`;
  - **Programmes:** exactly the R-67 layout;
  - **Facts:** master §8.6: entity, field, value, unit, intake term and year, owner body, source URL and type, quote,
    language, read at, read method, status, reason;
  - **checker columns on every sheet:** `checker1_id, checker1_result, checker1_value, checker1_quote,
    checker1_evidence, checker1_at, checker2_id, checker2_result, checker2_at`.
  - A template generator writes an empty batch file with the `Lists` sheet.
- **Import** (`backend/scripts/os_import_batch.py`, and an admin API for the screen):
  1. Validate the whole file first: format, region spelling, URLs on the allow-list, quotes present, both checkers
     on high-stakes rows, reviewer ids known and attested (P2-D16).
  2. Re-fetch rows read by a model or OCR and match their quotes (R-68).
  3. Load the rows that passed through `knowledge.record()` in one import transaction per sheet.
  4. List every failed row in an import report (CSV beside the file), never loaded silently.
  5. Log the import (`os_imports`: file sha256, who, when, counts).
  6. `--undo <import_id>` reverts it through the revisions.
- **Status mapping:**
  - `found` + checker 1 `correct` + (high-stakes: checker 2 `approve`) → `verified`;
  - `found` alone → `confirmed` only after the re-fetch match, else `unconfirmed`;
  - `unconfirmed` / `conflict` → `unconfirmed`, plus a review item;
  - `not_readable` → a `collect` item;
  - `not_found` → no fact; the entity's field is recorded as searched;
  - `lead_only` → stored as a lead, never shown;
  - `superseded` → kept as history.
- **Legacy layouts:** a mapping file per old batch layout (`knowledge/sheets/legacy/<batch>.yaml`). The import
  converts them to the canonical layout, and no row is edited by hand.
- **Batch files** live in `docs/research/batches/<batch-id>/` (sent, returned, import report). They contain no
  student data.

### 4.7 Season monitoring and reports (R-27, R-28, rows 6.23, 6.24)

- **Daily job `os.monitor`:**
  1. For each region and family inside its notice window (P2-D21), re-fetch every source URL behind a fact of the
     current intake.
  2. Compare the new snapshot with the last one: the quote still on the page, and the page's text hash.
  3. A changed or missing quote sets the fact `unconfirmed` (from `confirmed` or `verified`).
  4. Pause the steps that use it (P2-D20), notify the affected students, and open a `change` item.
- **Off season:** the TTL sweeper as today.
- **Reports** (P2-D22): `POST /v1/os/facts/{id}/report` with a reason code and optional text. The text goes only to
  the review item, never to another student. A "Report as wrong" link sits on every fact display (P1 T9 component).
- **Proof:** a scripted page change (the fixture server changes a deadline) resets the fact, pauses the step,
  notifies the student and queues the item. The same proof runs for a student report.

### 4.8 Intakes and the yearly rollover (R-60–R-66)

- **`os_intakes`** (P2-D23). Students may plan for any `open` or `current` intake (R-63). Before an intake is
  `current`, its plans use labelled values from the previous year (P2-D24).
- **Rollover job** `backend/scripts/os_rollover.py --region --family --term --year` (and a scheduled job later):
  1. Open the intake.
  2. Copy the *structure*: the list of (entity, field, owner) keys from the previous intake, as `expected` slots in
     `os_fact_slots`, with no values.
  3. The new intake's facts start absent, so plans read the labelled previous ones.
  4. Queue research batches: export a pre-filled spreadsheet of the slots for Claude and the checkers.
  5. Leave the previous intake's facts untouched and visible with their year.
- **Two intakes in one year** (spring / fall) are two rows with different terms (R-62).
- **A new plan for the next intake** (R-64) is a new decision version with the next intake (P1 row 6.2 / 6.3). The
  proof here is that the Vault and documents are reused, and nothing is asked again that is already known.
- **Playbook versions** with `applies_to` (P2-D25).
- **Proof:** a scripted rollover from a fake 2026 intake to 2027 on the fake PK routes. Values stay labelled 2026
  until the 2027 ones are verified. Then the plans revise on their own (row 6.10).

### 4.9 Coverage dashboard and launch-gate reading (R-34, R-35, R-66)

- **`frontend/app/[workspaceId]/os-admin/coverage`** and `GET /v1/os/admin/coverage?intake=`, per region ×
  institution type × family × intake:
  - the denominator (official list and its count), listed / researched / verified counts;
  - high-stakes facts verified / not confirmed / missing;
  - not-readable sources, suspect domains, open review items;
  - the review workload left (rows × checks needed).
- **Gate reading:** R-35 (a)–(d) computed per family and region, green or red with the failing items listed. An
  intake becomes `current` only when its gate is green (R-66). Setting it is an admin action that the API refuses
  while red.
- **Workload estimate** (master §12): registry size × high-stakes facts per institution × 2 checks, against the
  checkers' measured rows per hour. It feeds the owner's checker decision (§11 Q2).

### 4.10 `ProgrammeFacts`, `MeritCheck` and merit answers (R-23, R-31, R-48, rows 6.10, 6.25)

- **Ports** `PlanQuery.programme_facts(programme_ref, intake)` and `PlanQuery.merit_check(student_ref,
  programme_ref, intake, category)`, with the contracts of P2-D27.
- **`MeritCheck`** (P2-D26) returns:
  - the formula with its source;
  - the student's aggregate and the marks used, with their Vault evidence level;
  - each part's status (`known / missing / not_confirmed`);
  - past closing merits by year with sources, labelled "lowest on list N" when the list is not complete.
  - It answers "not confirmed" when the formula is not `verified`, and "missing" (with a provide step from P1) when
    a mark is missing. It never predicts a chance.
- **Counsellor side** (freeze exception 2, P2-D28): with `CONNECT_MERIT_ANSWERS` on, the path analyzer's merit
  data comes from `MeritCheck`, in the existing reply style. Proof: replay where only merit answers change; row
  6.25 on fictional students.

### 4.11 Official calendars (R-20 with official data, row 6.20; freeze exception 3)

- Exam, result and admission calendars are registry `calendar` rows with cycle-bound date facts, from the import.
- P1's `result_expected` step reads them by registry id instead of the P1 test calendar.
- The Counsellor's calendar and admission-rules JSON move into Knowledge through the import (P2-D28). The
  Counsellor reads them through an adapter that gives today's shape. Proof: the roadmap time estimate is identical
  with the flag off and on, apart from the values that the import verified.

## 5. Rules for every P2 task

- Branch `pc/p2-t<N>-<name>` from `pai-connect`, squash-merged by PR. Nothing goes into `pai-merge` until the whole
  plan is done (P0-D14).
- Name the R-IDs in the PR; set `built: true` in `docs/requirements/connection.yaml` in the PR that adds the tests;
  tag tests `@pytest.mark.req("R-xx")` or `// req: R-xx`.
- DB changes only through Alembic, OS tree `backend/alembic/versions_os/`, one head. Tasks that run in parallel
  each add their migration in merge order and rebase their `down_revision` before merging. The integration owner
  checks for one head.
- **No data from memory.** Tests use fictional institutions on fake domains, served by a local fixture server.
  Real institution, body, test or date names appear only in data files that came through the import, never in code
  or in test expectations written by hand. No country, region, institution, exam or suffix names in `app/os`
  `*.py` (R-58).
- With every new flag off, the app behaves byte-for-byte as today; each task has a test for that.
- No live model or API call without the owner's approval and a cost cap. The fixture server and recorded snapshots
  are the default.
- `tach check` and `pytest tests/os` before pushing OS code.

## 6. Task groups

### 6.1 Code (the developers)

| # | Branch | Builds | R-IDs | Needs (hard) | Merge after (soft) |
|---|---|---|---|---|---|
| T1 | `pc/p2-t1-foundations` | Migration: fact columns (`intake_term`, `owner_ref`, `fact_class`, `read_method`, `language`), status `verified`, `os_fact_revisions`; `Fact` and port changes; `regions.yaml`, `fact_classes.yaml`, the display function; contracts `programme_facts.v1`, `merit_check.v1`, `programme_list.v2` with samples and hash tests; local fixture server for official-looking fake sites | R-23, R-25 (model), R-26 (model), R-60, R-76 | P1 T1 (merged) | — |
| T2 | `pc/p2-t2-registry` | `os_registry`, `os_programmes` columns, official lists, coverage-level computation, registry read API, `knowledge.record()` for registry rows | R-32, R-33, R-34 | T1 | — |
| T3 | `pc/p2-t3-sources` | Allow-list YAML, `os_source_domains`, gateway lookup, integrity checks, suspect flow, `os_page_snapshots`, `os_source_files`, spam fixture proof | R-24, R-71, R-29 (snapshot part) | T1 | — |
| T4 | `pc/p2-t4-reading` | Render fallback; `ScanText` port with the bake-off and the Docling adapter; Urdu normalisation data; `not_readable` marking | R-74, R-29 (OCR, Urdu), R-72 (marking) | T1 | T3 (gateway hook) |
| T5 | `pc/p2-t5-review-queue` | `os_reviewers` and the script, `os_review_items`, `os_fact_reviews`, two-person rule, `verified` transitions, `collect` with evidence upload, `conflict` items, batch attestation, review screen | R-25, R-42, R-72 (collection), R-75 | T1 | T3 (snapshot view) |
| T6 | `pc/p2-t6-sheets` | Format file, template generator, validator, re-fetch and quote match, status mapping, legacy mappings for batches 1–4, import log and undo, CLI and admin API, queue export and re-import | R-67, R-68, R-69, R-76 (normalise) | T1, T2 | T3 (allow-list and re-fetch), T4 (OCR rows), T5 (R-69 export and attestation) |
| T7 | `pc/p2-t7-monitoring` | Notice-window facts, `os.monitor` job, change detection, reset and pause (`fact_rechecking`), student notices (texts as data), reports API and link, rate limit | R-27, R-28; rows 6.23, 6.24 | T3, T5; **P1 T8, T9** | — |
| T8 | `pc/p2-t8-intakes` | `os_intakes`, `os_fact_slots`, rollover script, labelled previous-year fallback in the port and compiler, playbook `applies_to`, next-intake plan proof | R-26, R-61, R-62, R-63, R-64, R-65 | T1, T2 | — |
| T9 | `pc/p2-t9-coverage` | Coverage API and screen, R-35 (a)–(d) reading, intake `current` gate, workload estimate | R-34 (display), R-35, R-66 | T2, T5, T8 | — |
| T10 | `pc/p2-t10-merit` | `ProgrammeFacts` and `MeritCheck` ports, formula and closing-merit fact shapes, `programme_list.v2`, R-30 label proof; **then** the freeze-exception PR for Counsellor merit answers (`CONNECT_MERIT_ANSWERS`) | R-23, R-30, R-31, R-48; rows 6.10, 6.25 | T1 | T5 (`verified` to answer), T8 (labelled years) |
| T11 | `pc/p2-t11-calendars` | Calendar registry rows and facts; P1 `result_expected` on official calendars; freeze-exception PR moving the calendar and admission-rules JSON into Knowledge with the same-shape adapter | R-20 (official), R-26; row 6.20 | T2, T6; **P1 T8** | — |
| T12 | `pc/p2-t12-gate` | Consistency rules 9–12 in the nightly job; scripted proofs (spam, not-readable collection, monitoring change, rollover, spreadsheet round trip with deliberate errors); Spike 1 rerun harness per region; `check_traceability.py --gate P2`; handoff | R-35 (reading), R-59, all P2 R-IDs (gate) | all; people lane H4, H6 (§6.2) | — |

**Parallel lanes** (with three implementer lanes; a fourth lane can take T10 if there are people for it):

```
Week   1        2        3        4        5        6
Lane A T1 ─┬─► T2 registry ──► T6 sheets ──────────► T11 calendars ─┐
Lane B     ├─► T3 sources ──► T4 reading ──► T7 monitoring* ────────┼─► T12 gate
Lane C     ├─► T5 review queue ──► T9 coverage ─────────────────────┤
Lane D     └─► T8 intakes ──► T10 merit (+ freeze exception PR) ────┘
People H1 ─ H2 walkthroughs ─ H3 official lists ─ H4 registry batches ─ H5 sample verified ─ H6 answer key ─►
            (§6.2; starts day 1, needs no P2 code until H4's import)
* T7 also waits for P1 T8 and T9.
```

- **Run at once after T1:** T2, T3, T5 and T8. T4 and T10 can start too (T4 merges after T3).
- **Second wave:** T6 (after T2; it merges its allow-list and attestation parts once T3 and T5 are in), T7, T9
  and T11.
- **Code critical path:** T1 → T2 → T6 → T11 → T12, about 5–6 weeks. T6 matters most, because it is how the people
  lane's work enters the system. Build its core (format, validator, load, undo) first, so batches 1–4 can be
  imported as soon as possible.

### 6.2 Data and verification (people: Claude research, the checkers, the owner)

| # | Work | Who | Needs | Output |
|---|---|---|---|---|
| H1 | Checkers recruited and briefed; reviewer ids issued (script from T5; until then a named list) | Owner (§11 Q2) | — | 2+ named checkers, the R-67 format guide |
| H2 | **Walkthroughs** per region × family, plus one national walkthrough: how admission works, bodies, official lists, seat categories, documents, calendar, each line with an official citation (master §8.4). `docs/research/walkthroughs/<region>-<family>.md` | Claude drafts; checker 1 checks every citation; checker 2 approves | H1; region order (§11 Q3) | 15 checked walkthroughs (7 regions × 2 families + national) |
| H3 | **Official lists and allow-lists** per region and institution type, named with date (R-35a); the domains of each body | Claude finds; checkers confirm the list and its row count | H2 for that region; §11 Q4 for A-level schools | `official_list` rows and allow-list YAML (reviewed as PRs) |
| H4 | **Registry batches** (master §8.6 batches 1–2: national backbone, then per region bodies, systems, categories, calendars) in the canonical spreadsheet; batches 1–4 converted | Claude researches; checkers verify; developers import (T6) | H3; T6 for import (verification can run in the spreadsheet before T6 lands) | Registry at 100% of each named list (`listed`) |
| H5 | **Sample verified per region**: 5 institutions per region with all high-stakes fields of the latest cycle (P2-D30) | Claude; checker 1 + checker 2 | H4 for those institutions; T6 | Verified rows for the Spike 1 rerun |
| H6 | **Answer key** for the Spike 1 rerun, by a checker who did not verify those rows | Checker (swapped region) | H5 | `tests/os/quality/<region>_answer_key.yaml` |
| H7 | **One not-readable source collected** with evidence through the queue (gate item) | Checker | T5 | A `collect` item closed with evidence |
| H8 | **Batch 3–4 onward** (per university, per college) continues after the gate toward the P5 launch gate | Claude; checkers | H4 | Ongoing (P5) |

- **People critical path:** H1 → H2 → H3 → H4 → H5 → H6 → the T12 Spike 1 rerun. H2 and H3 are per region, so
  regions run in parallel with more checkers. The region order (§11 Q3) decides which regions finish first.
- **The owner decides:** the number of checkers and who they are (Q2), the region order (Q3), the official list for
  A-level schools (Q4) and the cost cap (Q5). Everything else in the loop follows master §8.6 and this spec.

## 7. How much is code and how much is people

| Part | Effort (rough) | Calendar |
|---|---|---|
| Code T1–T12 | 12 groups, about 5–6 weeks on 3–4 lanes (master: 6–10 weeks) | Finishes before the people lane if checkers start in week 1 |
| People to the P2 gate (H1–H7) | 15 walkthroughs checked twice; every region's official lists; the registry `listed` for all regions; 5 institutions × all high-stakes fields × 7 regions verified twice; answer keys | **Sets the P2 date.** The exact hours are unknown until H3 gives the list sizes; the coverage dashboard (T9) then computes them |
| People to the launch gate (H8, P5) | Every high-stakes fact of every first-live institution, verified twice, per intake, every year | Ongoing; much larger than P2's share |

**Estimate for P2 alone:** about **30–40% code and 60–70% people work** by effort. On the calendar, the people lane
is the critical path once T6 is merged (about week 3). These are planning assumptions, not measurements. After H3,
the dashboard's workload figure replaces them.

## 8. Risks

| Risk | Answer |
|---|---|
| Parallel migrations in one OS tree (T1–T8 each add tables) | T1 owns the shared fact columns; others add only their own tables; rebase `down_revision` at merge; the integration owner checks one head |
| P1 is not finished (T8–T10 open), and T7 and T11 need P1 T8 and T9 | T7 and T11 are last in their lanes; everything else touches only Knowledge, which P1 does not change |
| Docling is heavy (model files, image size) and may read Urdu poorly | Bake-off first (P2-D13); OCR facts stay `unconfirmed` until a checker compares them (R-72), so poor OCR costs checker time, never a wrong fact |
| Checker ids in a spreadsheet can be typed by anyone | Batch attestation in the queue (P2-D16); the import is an admin action with an audit log |
| A student report knocks a verified fact to "not confirmed" for everyone (R-28 says at once) | Rate limit; repeated reports join one item; the queue sorts reports first; the restore is one approval |
| Official sites block automated reading or show merit only after login | `not_readable` → human collection (R-72); R-70 is P4 |
| A hacked official site | Integrity checks on every page; `suspect` drops its facts (R-71) |
| Checker capacity is unknown | The dashboard workload (T9) after H3; the owner sets checkers against the P5 date (master §12) |
| Batches 1–4 are not in the repo | §11 Q1; T6's legacy mappings wait for them; the canonical layout does not |
| Copying real data into tests by mistake | Fixture server with fictional sites; the reviewer checks "no data from memory" (master §13.3) |

## 9. Gate (master §12, P2)

| # | Gate item | Proved by |
|---|---|---|
| 1 | Every task merged into `pai-connect` with all CI jobs green | CI |
| 2 | `python scripts/check_traceability.py --gate P2` passes | CI |
| 3 | Walkthroughs for every region and family (plus national) checked: every citation checked by checker 1 and approved by checker 2 | H2 sign-off rows |
| 4 | Integrity check proven on a page with injected spam: refused, domain `suspect`, its facts unconfirmed, review item open | T12 scripted test |
| 5 | A `not_readable` source collected by a checker with evidence, approved by a second person | H7 + queue audit |
| 6 | Registry built from official lists: 100% of each named list, per region and institution type | Coverage dashboard (R-35a) |
| 7 | Spike 1 rerun on a sample from every region: **100% correct on verified facts, ≥ 95% on confirmed** | T12 harness with H6 answer keys (billed run within the owner's cap) |
| 8 | Monitoring proven on a scripted page change; a student report proven the same way (rows 6.23, 6.24) | T12 scripted tests |
| 9 | A scripted rollover from one intake to the next (rows 6.10, R-61–R-63) | T12 scripted test |
| 10 | A spreadsheet round trip with deliberate errors (bad URL, missing quote, one checker on a high-stakes row, a typed region spelling, a model-extracted quote not on the page), each caught; undo restores the state | T12 scripted test |
| 11 | Rows 6.20 and 6.25 pass on fictional students; consistency rules 9–12 find zero | T12 |
| 12 | Freeze-exception replays (merit answers, calendar move): only the intended answers changed; Counsellor lead approved | T10, T11 PRs |
| 13 | `docs/connect/handoff/p2-handoff.md` written; the owner signs off | Owner |

## 10. Open items for later phases

- Stage H places from the registry with coverage levels (R-49) and route families (R-36–R-38, R-81) are P3/P4. The
  registry and `programme_list.v2` built here are their inputs.
- R-70 (merit visible only in the student's login) and consistency rule 13 are P4.
- The full verified floor (R-35b) and the launch reading are P5.
- Abroad registries (R-77) reuse all of P2 per country in P6.

## 11. Owner decisions needed

1. **Batches 1–4: where are the files?** They are not in the repo or its history. *Default:* send them (the
   spreadsheets and Claude's notes) and they go into `docs/research/batches/b1…b4/`. T6 maps their layouts into the
   canonical one. Until then, the new batches use the canonical layout only.
2. **How many checkers, who, and from when?** *Default:* **2 checkers from week 1** (one checks, the other
   approves, swapping by region), the bottom of the 2–4 range in master §15 Q1. Revisit after H3, when the dashboard
   gives the workload against the P5 date: go to 4 if the per-region verified floor does not fit.
3. **Region order.** *Default:* national backbone first (HEC list, boards and IBCC, regulators, national tests),
   then **Punjab → Sindh → Khyber Pakhtunkhwa → Islamabad Capital Territory → Balochistan → Azad Jammu and Kashmir →
   Gilgit-Baltistan**. This is a guess at where most students are; it is not data. With 2 checkers, two regions run
   at once.
4. **Denominator for A-level schools.** Master R-35a says "the board's affiliation list", but A-level schools are
   registered with the exam boards that run A-levels, not the provincial boards. *Default:* the official list of the
   bodies that register A-level schools, per region, as found and checked in H3. If none is published, A-level
   schools are counted from IBCC's or the province's official list, and the gap is recorded in the walkthrough.
5. **Cost cap for P2's live calls** (the Spike 1 reruns per region, and any paid OCR). *Default:* **US$25 in total
   for P2**, with the per-run cost reported before each billed run. OCR runs locally (Docling); a paid vision-OCR
   fallback is used only inside this cap. (The Slice 2 gate ran about $1 per 30-programme run.)
6. **May P2 start before the P1 gate is signed off?** *Default:* **yes** for T1–T6, T8, T9 and T10, which touch only
   Knowledge and new tables. T7 and T11 wait for P1 T8 and T9. The people lane (H1–H4) starts now. P2's gate still
   comes after P1's sign-off.

### 11.1 Answered by the owner already
- **Q1, the batch files:** batches 1–5 v4 were returned on 2026-11-07, both checker columns filled in by AI checks and the developers' review. They are on `pc/p2-research-batches`, under the owner-accepted import mode (P2-D16a, `docs/research/batches/README.md`).
- **Q3, the region order:** yes, as proposed.
- **Q5, the cost cap:** **US$20** for P2's live calls (not the $25 default).
- **Q6, starting early:** yes. P1 is now signed off, so nothing waits on it any more.

### 11.2 Owner rulings at approval (chat, 2026-11-07)
- **The spec is approved and building starts.**
- **Checkers (Q2): "AI checks are enough."**
  - For the P2 gate items that ask for two people (items 3, 5 and 7), an independent AI check 1 and AI check 2 count as the two checks, and the owner accepts them. This also covers the `not_readable` collection and the answer keys.
  - This deviates from master R-25 and R-42, which say "a person checks and a second person approves". It is recorded in the P2 handoff as an owner decision.
  - The rule that the two checks must be independent stays: check 2 never sees check 1's verdict before it gives its own.
  - The review queue keeps reviewer identities (P2-D15), so people can take over later without changing the code.
- **Q4 (the A-level denominator)** takes the default.
