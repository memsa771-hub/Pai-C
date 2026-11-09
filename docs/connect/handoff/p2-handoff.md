# P2 handoff: national data system

Status: **DRAFT, awaiting the owner's sign-off** (P0-D13). The owner, MSAQLAIN, signs off alone, in chat. Nothing in this file marks P2 as signed off or `done`; the owner's words and the date are added only after he gives them, in a separate small PR, and `docs/requirements/connection.yaml` keeps the P2 phase status as it is until then.

Phase spec: `docs/superpowers/specs/2026-11-07-p2-national-data-design.md` (with the owner rulings of §11.1 to §11.3). Master spec: `docs/superpowers/specs/2026-11-03-pai-connect-design.md` (§12 row P2). Gate plan: `docs/superpowers/plans/2026-11-08-p2-t12-gate.md`. The next phase is P3.

**Read this first.** The code of P2 is built and tested on fictional data. Three things in the gate are not code and are not done by this branch: the people lane (walkthrough sign-offs, the registry loaded to 100% of each named list, the answer keys), the live Spike 1 rerun inside the US$20 cap, and the two freeze-exception PRs. They are listed in §2 and §4 with who owns each.

## 1. What was built

| Task | Result | R-IDs | Where |
|---|---|---|---|
| T1 | Fact columns (intake term, owner, class, read method, language), the `verified` level (only through review), append-only fact revisions, regions and fact classes as data, the one display rule, contracts `programme_facts.v1`, `merit_check.v1`, `programme_list.v2`, the fixture server for fictional `.test` sites | R-23, R-25, R-26, R-60, R-76 | PR #203, merged (`399ab80`); `os_0025` |
| T2 | The OS registry (institutions, bodies, systems, tests, categories, calendars, official lists), programme columns, coverage level computed never stored, registry read API | R-32, R-33, R-34 | PR #204 (`051a0f4`); `os_0026` |
| T3 | Allow-list YAML and `os_source_domains`, integrity checks, the suspect flow, page snapshots and original files | R-24, R-71, R-29 (snapshots) | PR #205 (`3a8f13e`); `os_0027` |
| T4 | Headless rendering for JavaScript pages (resource-capped, sandboxed), OCR behind a port, Urdu text normalisation as data, `not_readable` marking | R-74, R-29, R-72, R-76 | branch `pc/p2-t4-reading` (`0b9881a`); `os_0030` |
| T5 | Reviewers with tokens and identities, the review queue, the two-person rule, `verified` transitions, collection with evidence, conflict items, batch attestation, the review screen | R-25, R-42, R-72, R-75 | PR #206 (`b80d53e`); `os_0028` |
| T6 | The one spreadsheet format, template, validator, re-fetch and quote match, status mapping, legacy mappings for batches 1 to 4, import log and undo, CLI and admin API | R-67, R-68, R-76 | branch `pc/p2-t11-calendars` carries it (`046f529`); `os_0031` |
| T7 | Notice windows, the `os.monitor` job (two-run rule, sanity guard, advisory day lock, retry tick), `fact_rechecking`, student reports and their owner-ruled scope, recovery by "fact stands" | R-27, R-28; rows 6.23, 6.24 | branch `pc/p2-t7-monitoring` (`7413d3a`); `os_0032` |
| T8 | `os_intakes`, expected slots, the yearly rollover, the labelled previous-year read, playbook `applies_to`, the next-intake plan proof | R-26, R-61, R-62, R-63, R-64, R-65 | PR #207 (`3a46d2b`); `os_0029` |
| T9 | Coverage API and screen, the launch-gate reading (a) to (d), the intake `current` gate (`set_state` refuses `current`), workload estimate | R-34, R-35, R-66 | branch `pc/p2-t9-coverage` (`0bb5bc3`); no migration |
| T10 | `ProgrammeFacts` and `MeritCheck` ports, merit formula and closing-merit shapes, `programme_list.v2` | R-23, R-30, R-31, R-48; rows 6.10, 6.25 | branch `pc/p2-t10-merit` (`a748803`); no migration |
| T11 | Calendars as registry rows and facts, `result_expected` from an official calendar by registry id, imports and undo revise plans for every fact | R-20, R-26, R-33; row 6.20 | branch `pc/p2-t11-calendars` (`6b94c6c`); no migration |
| T12 | This gate: consistency rules 9 to 12 in the nightly job, the scripted gate proofs, the R-69 queue export, not-readable sources into the queue, the Spike 1 harness, this handoff | R-05 (rules 9 to 12), R-35 (the reading), R-69; it does not build R-59 (CI) | branch `pc/p2-t12-gate`; `os_0033` |

Integration: `pc/p2-integration` merges T1 to T11 on one migration chain `os_0025` to `os_0032` (`os_0033` is T12's). Each task branch keeps its own migration number; the chain was renumbered on the integration branch and again when the tasks reach `pai-connect`.

T12 in detail:

| Part | Result | Where |
|---|---|---|
| Rules 9 to 12 | What a student is shown is read through the ProgrammeFacts port for each programme of each open plan: 9 a value with no source, or from a domain off the allow-list that applies to the programme (its region and family, else its route; its own and its institution's official domains also count); 10 a high-stakes value below `verified` (recomputed from `fact_classes.yaml`); 11 another intake shown without its year; 12 a value from a `suspect` domain. Codes name the rule and field, never a value. **A rule that cannot run is reported as "not run" with its reason, never as zero**: rule 9 needs a loaded allow-list, rule 12 needs the source guard. The worker loads the allow-lists whether or not the guard is on. `os_0033` widens the case rule check to 1 to 12; the admin list names rules 9 to 12 | `backend/app/os/consistency/facts.py`, `ports/consistency.py`, `app/pai_os_bridge.py` (`consistency_run`), `frontend/lib/os-consistency.ts` |
| R-69 | `GET /v1/os/admin/review/export` writes the open queue (or any filter) as the one R-67 spreadsheet; the file imports back through the normal import | `backend/app/os/knowledge/review/export.py` |
| Collection | T4's open `os_not_readable` rows for a field with an intake year become `collect` items (`sync_not_readable`, also in the admin sync); collecting closes them | `ReviewQueue.sync_not_readable`, `collect` |
| Gate proofs | Spam page, not-readable collection, spreadsheet round trip with the five deliberate errors and undo, rules 9 to 12 on a clean and a violating student, the R-69 round trip; a manifest names the existing proof for the other items and checks that it exists | `backend/tests/os/gate/test_p2_gate.py` |
| Spike 1 harness | Scores the facts held against `tests/os/quality/<region>_answer_key.yaml`, per region; **every key entry is scored and must be held at `confirmed` or above** (a missing or unconfirmed entry fails the region), 100% right among verified, 95% among confirmed, and at least 5 distinct institutions (a programme counts for its institution); plans a billed run against the cap; never researches or calls a model | `backend/app/os/gate/spike1.py`, `backend/scripts/os_spike1_rerun.py` |
| Traceability | `python scripts/check_traceability.py --gate P2` passes: every P2 R-ID is `built: true` with a tagged test | `docs/requirements/connection.yaml` |

## 2. Gate report (phase spec §9)

| # | Gate item | Status |
|---|---|---|
| 1 | Every task merged into `pai-connect` with all CI jobs green | **Partly.** T1 is merged (#203). T2, T3, T5, T8 are open PRs #204 to #207, approved, waiting for merge in that order. T4, T6, T7, T9, T10, T11 and T12 are branches, all green locally and together on `pc/p2-integration`; their PRs and CI links are to be added when they open |
| 2 | `check_traceability.py --gate P2` passes | **Exit 0, but read it honestly.** The gate asks only for a tagged test per P2 R-ID, and every one has one. **R-48 is `built: false`**: the OS side (`ProgrammeFacts`, `MeritCheck`) is built and tested, but the Counsellor answers from it only after freeze exception 1, so the requirement is not met end to end. R-15 (a P1 requirement) is also still unbuilt (§4) |
| 3 | Walkthroughs for every region and family checked by checker 1 and approved by checker 2 | **Not proved by code.** The H2 walkthroughs and H3 lists are drafted on `pc/p2-research-batches`; the sign-off rows are the owner's to confirm. By ruling §11.2 two independent AI checks count as the two checks |
| 4 | Spam page: refused, domain `suspect`, facts unconfirmed, review item open | **Yes.** `tests/os/gate/test_p2_gate.py::test_gate_4_spam_page_is_refused_the_domain_suspect_facts_unconfirmed_item_open` (with the real queue); also T3's `test_spam_fixture_is_refused_and_its_domain_becomes_suspect` |
| 5 | A `not_readable` source collected with evidence, approved by a second person | **Mechanism proved** (`test_gate_5_...`: not-readable row, collect item, evidence file, collected value, comparing check, approval, verified; audit). **The real one (H7) is a people step still to do** |
| 6 | Registry built from official lists: 100% of each named list | **Reading built, figure not measured here.** The coverage dashboard (T9) and the launch-gate reading (a) to (d) are tested; the real percentage needs the registry batches imported (H4) |
| 7 | Spike 1 rerun on a sample from every region: 100% on verified, at least 95% on confirmed | **Harness built and tested; live run not done.** The harness is strict: every key entry must be held at `confirmed` or above (one correct entry and 99 missing fails), the sample is 5 distinct institutions (five programmes of one institution fail), NaN and infinity match nothing. No answer key exists yet (H6), so `os_spike1_rerun regions` lists every region as missing a key. The billed run is the controller's, inside the US$20 cap (ruling Q5) |
| 8 | Monitoring and a student report proven on a scripted page change (rows 6.23, 6.24) | **Yes.** T7's `test_a_page_change_in_season_resets_the_fact_pauses_the_step_and_queues_the_item` and `test_a_report_shows_not_confirmed_to_everyone_but_only_the_reporters_steps_wait`, with the owner-ruled scope (§3) |
| 9 | A scripted rollover (rows 6.10, R-61 to R-63) | **Yes.** T8's `test_rollover_proof_2026_to_2027`; the next-intake plan proof |
| 10 | Spreadsheet round trip with deliberate errors; undo restores | **Yes.** `test_gate_10_...` asserts each error by its reason: `unknown_region` (typed region spelling), `source_not_on_allow_list` (bad URL), `no_quote` (missing quote), `second_check_missing` (one checker on a high-stakes row, the fact stays `confirmed`), `quote_not_found` (model-extracted quote not on the re-fetched page). **Undo withdraws what the import loaded**: every fact goes `stale` and the entity is `closed`; nothing is deleted. It does not put back a state that never existed |
| 11 | Rows 6.20 and 6.25 pass; consistency rules 9 to 12 find zero | **Yes, with limits (§4).** `test_calendar_plan.py::test_6_20_...`, `test_p2_merit_ports.py`; rules 9 to 12 find zero on a clean fictional student **only once the allow-list is loaded and the guard is on**; before that the run reports rules 9 and 12 as "not run" (asserted in `test_gate_11_...`), and each violation is found. The nightly run's result carries `not_run` |
| 12 | Freeze-exception replays (merit answers, calendar move): only the intended answers changed; Counsellor lead approved | **Not done: open.** No frozen file changed in P2 so far (`check_freeze.py --base origin/pai-connect`: unchanged). The two freeze-exception PRs (flags `CONNECT_MERIT_ANSWERS`, `CONNECT_CALENDAR_FROM_KNOWLEDGE`) each need the label, the R-ID, a replay and `@memsa771-hub`'s approval; the OS side they call is built (T10, T11) |
| 13 | This handoff written; the owner signs off | Written (draft). **Awaiting the owner's sign-off** |

Test counts on the T12 branch: `tests/os` 2946 (2 skipped, 1 xfailed) passed; the legacy suite 2560 passed, 13 skipped; vitest 602 passed; `next build --webpack` ok; `tach check`, `check_freeze.py`, `check_traceability.py --gate P2` ok; one OS Alembic head (`os_0033`).

## 3. Owner decisions and rulings

Phase decisions P2-D1 to P2-D30 are in the phase spec §2.2 (approved with the spec). The owner's own rulings:

| When | Ruling |
|---|---|
| 2026-11-07 (§11.1) | Q1: batches 1 to 5 (v4) were returned on 2026-11-07, both checker columns filled by AI checks and the developers' review (branch `pc/p2-research-batches`, `docs/research/batches/README.md`); loaded under the owner-accepted mode (P2-D16a). Q3: the region order as proposed (national backbone first, then Punjab, Sindh, Khyber Pakhtunkhwa, Islamabad Capital Territory, Balochistan, Azad Jammu and Kashmir, Gilgit-Baltistan). **Q5: the cost cap for P2's live calls is US$20** (not the US$25 default). Q6: P2 may start before the P1 gate (P1 was signed off) |
| 2026-11-07 (§11.2) | The spec is approved and building starts. **"AI checks are enough" (Q2):** for the gate items that ask for two people (3, 5, 7) an independent AI check 1 and AI check 2 count as the two checks, including the not-readable collection and the answer keys. **This deviates from master R-25 and R-42** ("a person checks and a second person approves"). The independence rules stay and are enforced: two distinct reviewer identities (a person, or the model and prompt behind an AI reviewer), check 2 never sees check 1 before it gives its own (an admin too, except through a separate audit view of closed items), the author of a correction or collection cannot check it. The review policy (`knowledge/review/review_policy.yaml`) can require people again by data alone. Q4 (the A-level denominator) takes the default: the official list of the bodies that register A-level schools, per region |
| 2026-11-08 (§11.3) | **Model- or image-read rows of batches 1 to 5 v4** (34 facts in the dry run, about 39 with all lists): both AI checks accepted them, so they are `verified` **without** the R-68 re-fetch quote match. This is an owner-accepted deviation from R-68, only for the `--owner-accepted` import of those files (by file hash), recorded in each fact's provenance. Later batches still need the re-fetch |
| 2026-11-08 (§11.3) | Rows whose intake is "standing", "current" or "previous cycle" go to the queue as `intake_unresolved`; a check assigns the year from the source. Nothing is guessed |
| 2026-11-08 (§11.3) | Intake text rules approved as in T6 `format.yaml` (`Fall\|Spring\|Summer\|Autumn\|Winter YYYY`; `Session YYYY-YY` and `YYYY-YY` become term `session` and the first year; `Batch YYYY` and `Annual YYYY`; a bare year has no term; anything else is queued) |
| 2026-11-08 (§11.3) | Sindh seat rows: 110 rows carry the seat number only inside their quote; research re-enters each value from its quote and both AI checks re-check those rows. Nothing is parsed automatically |
| 2026-11-08 (§11.3, refines P2-D22 and R-28) | **A student's report shows the fact as "not confirmed" to everyone at once, but only the reporting students' steps wait.** Other students' steps keep running (on a provisional date) until a reviewer agrees, or until 3 different students report the same fact in the same open round; then every plan waits. A report the reviewer dismisses puts the fact back to the status it had (from the revision log) |
| Standing | Student sentences are added directly in data files with `approved: true`, under the owner's standing approval ("you dont need to open PRs for such silly student sentences just update it directly"). P2 added twelve, listed in §6 |
| Research (progress ledger) | Sindh seats: 74 rows accepted by both checks. PMDC: 59 matches accepted; the 045 rule and the 048 city accepted, the 043 disagreement held back |

## 4. Open gaps and deviations

People and process (not code):

- **The live Spike 1 rerun is not done.** The harness scores and plans; the billed research run and the answer keys (H6, one per region, by a checker who did not verify those rows) are still to come. Until then gate item 7 is open. The cost cap is US$20 for all of P2.
- **No real not-readable source has been collected through the queue (H7)**; the mechanism is proved on fictional data.
- **The registry percentage (gate item 6) is not measured**: it needs the H4 batches imported.
- **The freeze-exception PRs (gate item 12) are not opened** (merit answers behind `CONNECT_MERIT_ANSWERS`, calendar and admission-rule move behind `CONNECT_CALENDAR_FROM_KNOWLEDGE`). They need the replay and the Counsellor lead.
- **PRs #204 to #207 wait for merge in order**, then the migrations are renumbered after each (the chain is `os_0026` to `os_0033` on the integration branch).
- **R-48 is `built: false`.** The OS ports are built and tested; the Counsellor's merit answers from `MeritCheck` wait for freeze exception 1 (`CONNECT_MERIT_ANSWERS`), which needs the Counsellor lead. The traceability gate passes on the tagged tests but the requirement is not met end to end.
- **R-15's OS side** (an excluded field disappears from the OS programme list) was moved from P1 to P2 by the P1 handoff (Q4) but is not in the P2 spec's scope; it is still not built (`built: false`, phase P1). The owner decides where it goes.
- R-46 stays `built: false` as recorded in the P1 handoff.

Code limits and known gaps:

- **Imported dates that are not written in ISO format stay as text and do not move plans** until someone converts them (the compiler reads ISO dates only).
- **Reading (T4):** the Tesseract bake-off passed 6 of 10 quotes after the fixes (5 of 10 before), below the bar; **Docling could not be installed and was not compared**, so the OCR engine choice is open. Urdu numbers are misread by the engine. OCR text therefore stays `unconfirmed` until a checker compares it with the original (R-72). The render memory cap works only where a cgroup exists (tested for v1, untested for v2; otherwise the browser heap limit is the only cap); the render deadline uses the host clock per process.
- **Coverage (T9):** a source on an unlisted domain fails check (c) of the launch-gate reading; a follow-up is noted in the T9 review.
- **Monitoring (T7):** programme-scope facts only; the day's run is one per day; a sanity failure delays a change but never hides it (two failures in a row take the facts back); notices to students are the existing "plan updated" notice and bell, no new event kind.
- **Registry (T2):** which kind a parent may have is chosen per kind table by the agent; the final review is to check it.
- **Intakes (T8):** the Counsellor adapter maps an intake error to `route_not_supported` (an approximation); the upgrade route has no handler for the new value error (no current path reaches it).
- **Consistency job:** rules 9 to 12 read PAI OS alone, per student with an open plan, and run inside the connection's job (they are off when the connection is off); rule 13 is P4 (R-70).
  - **They cover only the programmes in open plans.** A fact a student could see elsewhere (a browse screen, a programme list of a route they have not planned) is not read.
  - **Rule 9 is checked against the allow-list for the programme's region and family** (else its route), plus its own and its institution's official domains. It cannot run until an allow-list is loaded (the worker loads `knowledge/sources/lists/*.yaml` at start whether or not the guard is on; the job reads the table the worker wrote). Rule 12 exists only with `OS_SOURCE_GUARD=1`. Each says "not run" otherwise.
  - **R-24 (only listed domains count as sources) is enforced at read time only with `OS_SOURCE_GUARD=1`.** With the guard off the lists are data, loaded and checked by rule 9, but the gateway does not refuse an unlisted page.
  - The `no_source` part of rule 9 (a value shown with no source) always runs.
- The queue export (R-69) writes only items whose fact belongs to a registry entity or to a programme placed under one; the other items are listed in the second result and in the `X-Items-Without-Row` header, not dropped silently.

## 5. Flags and settings added in P2

| Name | Meaning | Default |
|---|---|---|
| `OS_SOURCE_GUARD` | Allow-lists, integrity checks and snapshots in the page gateway (T3) | off |
| `OS_MONITOR` | The daily `os.monitor` job and its retry tick (T7) | off |
| `OS_REPORTS` | The student report routes, and the `fact_rechecking` marker on the suspect path (T7) | off |
| render / scan settings (`OS_RENDER_*`, scan limits) | Headless rendering and OCR limits (T4) | see `settings.py` |
| `CONNECT_MERIT_ANSWERS`, `CONNECT_CALENDAR_FROM_KNOWLEDGE` | The Counsellor's merit answers and calendar read, after their freeze exceptions | not built into the Counsellor yet |

With every flag off the application behaves as before P2 (tested per task).

## 6. Student sentences added in P2 (`approved: true`, for the owner to read)

All twelve are in `backend/app/os/monitor/texts.yaml`:

1. "PAI is checking this date again with the official site. This step waits until it is confirmed."
2. "Report as wrong"
3. "What looks wrong?"
4. "The date is wrong"
5. "The amount is wrong"
6. "The official page now says something else"
7. "Something else"
8. "Tell us more (optional). Only the person who checks it will read this."
9. "Send report"
10. "Thank you. PAI will check this again. Until then it shows as not confirmed."
11. "You have sent several reports today. Please try again tomorrow."
12. "The report could not be sent. Please try again."

## 7. How to run the P2 tools

- Reviewers: `python -m scripts.os_reviewers add|list|disable|enable|rotate` (AI reviewers need `--identity`).
- Import: the spreadsheet CLI of T6 (`--owner-accepted <decision ref>` for batches 1 to 5 v4); undo by import id.
- Spike 1: `python -m scripts.os_spike1_rerun regions|plan|score` (no model call). A key is `tests/os/quality/<region>_answer_key.yaml`; the shape is in `app/os/gate/spike1.py`.
- Gate: `python scripts/check_traceability.py --gate P2`; the proofs: `pytest tests/os/gate`.
- Consistency: the nightly job runs rules 1 to 12; `scripts/connect_consistency.py run|status` as in P1.

## 8. Open items for later phases

- P3 and P4: playbooks per route and family (R-81); stage H from the OS registry with coverage levels (R-49); merit shown only in the student login (R-70, rule 13).
- P5: the launch gate (R-35 (a) to (d) as the launch decision) and the verified floor per region; the rest of batches 3 and 4 onward (H8).
- Making the Docling comparison, and a second OCR engine if Tesseract stays below the bar.
- The Counsellor-side freeze exceptions above, after the Counsellor lead's replay review.
