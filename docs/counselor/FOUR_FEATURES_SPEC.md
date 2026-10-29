# Four features spec (28 Oct 2026)

Founder decision: Placement AI is four features and everything else helps them. The Vault is the student's
digital twin. Everything reconciles into it, and the Mirror, the Path engine and the Roadmap engine are all
derived from it (plus memory embeddings). The published map is the design:
https://claude.ai/artifact/SfE5GjUKytSWR2ix4KBKtJ. This spec turns it into exact requirements. Scope is the
founder's option A: each feature's target state plus the pieces the target cannot work without.

Binding product rules stay: education first, hobbies as supporting evidence only; no fact about the student
without evidence, no world fact without a source; at most one question per reply; straightforward voice; no
university names before stage H.

## 0. What changes, in one paragraph
The old Mirror (4 lines the student confirms, with lanes that create paths and gates on everything after it)
goes. The new Mirror is a **state card** computed from the Vault on every read, plus a short text written in
the background when the Vault changes. Nothing waits for the Mirror. The Path engine runs when the Vault
changes and reads the Vault (facts, records, items) plus semantic recall from the embeddings index. The
Roadmap engine gives every step of a route a colour (done / half / not) with the Vault fact behind it, and a
time estimate from a dated academic calendar. The Vault exposes a completeness meter that both the Mirror's
"still unknown" list and the counselor's next question read.

## 1. Vault: the digital twin

### 1.1 Completeness meter
`VaultCompleteness(db).build(workspace_id)` returns
```
{known: int, total: int, areas: [{key, label, covered: bool, evidence: inferred|stated|shown|confirmed|null,
  stale: bool, item_count, min_items, question_key}], unknowns: [{area, label, question_key, priority}]}
```
- Areas, `min_items`, sources and `requires` come from `pai_c/understanding/areas.json` (the existing
  `coverage_areas`). An area counts as known only when covered and not stale (freshness from the catalog).
- `priority` and `question_key` come from `pai_c/policy/areas_policy.json` (`priority` order; a new
  `questions` map of area → copy key; copy lives in the counselor prompts' data, not in code).
- Exposed in `GET /v1/vault` as `completeness` and in `GET /v1/counselor/workspace` (replacing the binary
  `coverage` map, which stays for one release as `coverage` for the Overview chips).
- The counselor's next question (guided table `question_due`) picks the first unknown in priority order
  that passes the existing sensitivity and cooldown rules. One list, one source of truth.

### 1.2 Vault items as evidence everywhere
Vault items (interest, strength, value, pressure, option, certainty, family_member, domicile, daily_life) are
added to `profile_cards` with ids `item:<id>` and their evidence level, so the Path engine and the Mirror can
cite them like facts and records.

### 1.3 Embeddings on
- `index_sources.py` adds Vault items (type, value, evidence level) to what is embedded; `memory.embed` is
  enqueued for items on reconciler acceptance like facts and records.
- `PAI_SEMANTIC_RECALL_ENABLED` defaults to true in docker-compose. The founder sets
  `MEMORY_EMBEDDING_API_KEY` in `.env` (never by Claude). Without a key, recall returns `[]` and every
  feature still works from structured data.
- Monthly cap: `PAI_EMBEDDING_MONTHLY_CAP_USD` (default 5) in config. `inference/gateway.embed` records
  estimated cost per call (tokens × a per-model rate in `policy/embedding_costs.json`) in a monthly counter
  (BackgroundJob-free: a small `pai_usage_months` row per workspace-less scope); at the cap it logs once and
  returns no vectors, and recall falls back to lexical. Tests never call the live API.

## 2. Mirror: "you are this"

### 2.1 State card (deterministic, computed on read)
`MirrorEngine(db).build(workspace_id)` returns
```
{version: int, header: {name, education_line}, areas: [{key, label, level: 0|1|2|3, entries: [{id, text,
  evidence, source_label, observed_at}], tension: [{a_id, b_id, note_key}]}], unknowns: [...from §1.1],
  text: {sentences: [str], version, written_at} | null, ready: bool}
```
- `areas` are the ten coverage areas. `level` is 0 unknown, 1 stated only, 2 shown or confirmed, 3 shown or
  confirmed with two or more entries. Each area's `entries` are its Vault entries (facts, records, items)
  with evidence badge, source label and date, in the view language (English values; never the student's
  verbatim words).
- For `history` and `status` the entries include the education line and marks (percent, from the same record
  as the level, as the roadmap engine reads them). Subject marks appear as bars when the education record
  carries per-subject marks; otherwise the bar is the area level.
- `tension` pairs are data-driven: `policy/mirror.json` lists pairs of area keys and a rule (for example
  family_social wish field vs goals leaning field differ) and the note copy key. The Mirror marks the tension
  with both sources; it never resolves it.
- `ready` is true when the areas named in `deep/coverage_requirements.json` "light" are known. Below that,
  the page shows the areas it has and says what would complete the picture.
- `version` is a digest of the Vault entries the card was built from, so the text job and the page can tell
  whether the card changed.

### 2.2 Mirror text (model, background)
- Job `counselor.mirror_text`, enqueued by the reconciler after an accepted write that changed any
  Mirror-relevant type (catalog types whose area is in areas.json), debounced: one pending job per workspace,
  skipped when the state-card `version` is unchanged.
- Input: the state card only (no raw chat). Output: 3–4 sentences, second person, present tense, no
  question, no praise, no university names, no numbers not in the card. Prompt
  `deep/prompts/mirror_text.md`; `COUNSELOR_V3_PROMPTS.md` synced. Stored on the journey as
  `counselor_summary_draft = {type: "mirror_state", version, text, written_at, card_version}`.
- A failed job leaves the last text; the card still renders.

### 2.3 No confirm gate
- Removed: `POST /summary/confirm`, `POST /summary/edit`, `POST /summary/feedback`, the Mirror lanes, the
  old `counselor.mirror` LLM job and schema (`mirror_schema.py` lanes/dimensions/blockers/question), the
  `counselor.mirror_research` job, `PossibilityService.from_mirror`, `mirror_is_current`, and the
  `pai_counselor_mirror_feedback` table (migration 120; founder may object before merge).
- `GET /summary` returns the state card; `GET /v1/counselor/workspace.picture` becomes the card's header,
  unknowns and text (the Overview reads the same shape).
- Corrections: every entry on the Mirror has "This is wrong", which opens the Vault entry (Details) or, for
  an item, a conflict card proposing removal; the write goes through propose → reconcile. No Mirror-specific
  write path.
- Explore, try-it, program search and Operator results key on the **Vault version** (the snapshot digest the
  Path engine's idempotency key already uses) instead of `mirror_version`. A stored explanation is current
  when its `vault_version` matches; a path can be explored as soon as it exists.
- Ratings: the "understood 1–5" rating is dropped. Certainty stays as the existing Vault item `certainty`,
  asked by the counselor through the unknowns list.

### 2.4 Journey
- Stages keep their names. New transitions: DIRECTION → MIRROR when `MirrorEngine.ready` first becomes true
  (set by the reconciler after the write that made it ready); MIRROR → PROPOSED when the first path exists
  (set by the Path engine job after it saves paths). RESEARCHING, ASSESSING and NEEDS_INFO are no longer
  entered by any code; migration 120 moves any journey still in them to PROPOSED (with events).
- Frontend signal `mirror_confirmed` becomes `mirror_ready` (card `ready`). Stage E title "Your Mirror".
- `guided_state` `options_ready` becomes "any path exists"; `mirror_ready` is the card's `ready`.

### 2.5 Chat
- The guided table's `mirror` rule no longer produces a spoken 4-line Mirror with a question. When the card
  becomes ready, the counselor posts one short line and a `counselor_mirror` card linking to the Mirror page
  (card payload = header + unknowns + text). The `mirror_changes` rule is removed; corrections go through
  the Vault.
- Voice and chat context get `<mirror>` = the state card's text and unknowns (not the areas' raw entries).

### 2.6 Mirror page (frontend)
- View `mirror` in the Overview section's pill nav (sections: Overview · Mirror), reusing the workspace kit.
- Layout: header (name, education line, "Updated <date>"); the state card as a grid of area tiles, each with
  a level bar, its entries with evidence badges and "This is wrong"; the "Still unknown" list with the
  question each would answer and a "Tell PAI" button that opens chat with that topic; the text under the
  card; tension markers inline on both areas. Empty state: "PAI needs a little more to draw your picture"
  with the first unknown.
- The old chat Mirror card and the profile MirrorPanel/FeltUnderstood are removed; the chat
  `counselor_mirror` card becomes a small link card.

## 3. Path engine: "where you could go"
- Trigger: the reconciler enqueues path analysis with reason `vault` after an accepted write of a path-relevant
  type (education, test_attempt, goal, interest, strength, pressure, option, certainty, family_member);
  idempotency key = Vault version digest of those types + own paths. Reason `mirror` and `from_mirror` go.
  Reasons `asked`, `planner`, `student_added`, `education` stay (education is a subset of `vault`).
- Inputs add Vault items (§1.2) and `<semantic_recall>`: `MemoryService.recall(workspace_id, query, top_k)`
  with the query built from the candidate field titles and the student's goals; results carry ids that map
  to Vault entries, so the model can cite them. Empty recall is fine.
- A path's `why` must cite at least one Vault entry id (fact, record or item); the analyzer drops paths
  whose why cites nothing (today: fit items need evidence; this extends it to the why).
- Stored `evidence` gains `evidence_level` and `source_label` per cited entry so the Paths page can show the
  badge next to the reason (small frontend change in `path-card.tsx`).
- `MIRROR → PROPOSED` is set here when the first paths are saved (§2.4).

## 4. Roadmap engine: "how far along, how long"

### 4.1 Steps with colour
`route_steps(card, standing, vault)` returns the full route, in order, every step as
```
{key, label_key, values, status: done|half|not, evidence: {id, level, source_label} | null,
 rule: {source, confidence} | null, manual_done: bool}
```
Step kinds and their rules (data in `policy/roadmap.json`; all tests pure):
- `group`: has the right intermediate group → done (evidence = education record); Matric/O-level → not, with
  the choose-group label.
- `complete_intermediate`: education record completed → done; current → half (shows "exam <month>" from the
  calendar); none → not.
- `marks`: percent ≥ floor → done; percent known and below floor → not; unknown → half ("add your marks").
- `bridge` / `check` (from `needs`) → not unless a Vault record proves it (course record matching the
  bridge) → done.
- `test`: a `test_attempt` record for that test with a score ≥ pass → done; a planned/registered attempt or
  a score below pass → half; none → not.
- `apply`: manual only (not until the student ticks it; then done with evidence "you marked it").
- `degree`: not (years shown).
Colour: done = green, half = yellow, not = red. The evidence badge shows the level separately, so a step
done on a stated fact reads "done · stated".
`steps_done` stays as the manual tick list; a manual tick sets `manual_done` and counts as done.

### 4.2 Time estimate
- New data file `pai_c/policy/academic_calendar.json` (from the research draft): dated events (exam months,
  result months, test registration/test/result months, intake apply/start months) per level, test and field
  family, each with sources, confidence and `as_of`; `degree_years` by field.
- `estimate(route, today)` returns `{to_entry_months, to_finish_years, next_intake: {label, start_month,
  year}, basis: [{event_key, month, year, source, confidence}], confidence}`. Rule: walk the not/half steps
  in order, each needs its next event after the previous one; the entry month is the first intake start
  after the last required event; `to_finish_years = to_entry + degree years`. Unknown event → that step's
  time is "date not confirmed" and the total carries `confidence: uncertain`.
- Shown on the card ("about 10 months to entry"), on the route sheet per step, and on Your route.
- Today's date comes from the request clock; tests freeze it.

### 4.3 API and page
- `GET /v1/roadmap` cards gain `steps` (§4.1) and `time` (§4.2); `chosen` gains the same (live) plus the
  snapshot.
- Route sheet timeline shows each step's colour, evidence and rule link; Your route shows the coloured list
  with the manual tick only on `apply` (and on any `not` step the student wants to claim; it stays "stated").
- Compare adds rows "Steps done" (n of m) and "Time to entry".

## 5. Removed and kept
Removed: old Mirror job/schema/prompt/lanes, confirm/edit/feedback routes, mirror feedback table, from_mirror,
mirror_research job, mirror_is_current and mirror_version keys, chat Mirror card and profile MirrorPanel,
`understood` rating. Kept: `counselor_summary_draft` column (new shape), certainty item, all of the roadmap
engine, student requests, PAI OS contract.

## 6. Acceptance
- A student with onboarding only: Vault completeness 2 of 10; Mirror page shows two areas and "PAI needs a
  little more"; no path yet; chat asks the first unknown (education basics first).
- After three chat turns giving marks, interests and a goal: completeness rises; the Mirror is `ready` and
  redraws with no action; the Path engine ran from the Vault change; the stage is PROPOSED; Explore works
  with no 409.
- Uploading a Part-2 result card turns the `complete_intermediate` and `marks` steps green with the document
  as evidence and shortens the time to entry; nothing was pressed.
- A `test_attempt` "ECAT registered" turns the test step yellow; a passing score turns it green.
- Tension: family wish MBBS + goal engineering is marked on both areas with both sources.
- With recall disabled, every page and job gives the same shapes (recall only adds citations).
- Nothing in chat or voice writes to the Mirror, paths or roadmaps directly; only the Vault changes them.
- Page works at 375px.
