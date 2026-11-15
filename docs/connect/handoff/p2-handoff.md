# P2 handoff: national data system

Status: **DRAFT, awaiting the owner's sign-off** (P0-D13). The owner, MSAQLAIN, signs off alone, in chat. Nothing in this file marks P2 as signed off or `done`; the owner's words and the date are added only after he gives them, in a separate small PR, and `docs/requirements/connection.yaml` keeps the P2 phase status as it is until then.

Phase spec: `docs/superpowers/specs/2026-11-07-p2-national-data-design.md` (with the owner rulings of §11.1 to §11.3). Master spec: `docs/superpowers/specs/2026-11-03-pai-connect-design.md` (§12 row P2). Gate plan: `docs/superpowers/plans/2026-11-08-p2-t12-gate.md`. The next phase is P3.

**Read this first.** The code of P2 is built, tested on fictional data and merged into `pai-connect` (last: #221), with both freeze exceptions. What is not done is not code: the research batches need fixing before they import (§4), then the people lane (walkthrough sign-offs, the registry loaded to 100% of each named list, the answer keys) and the live Spike 1 rerun inside the US$20 cap. They are listed in §2 and §4 with who owns each.

## 1. What was built

| Task | Result | R-IDs | Where |
|---|---|---|---|
| T1 | Fact columns (intake term, owner, class, read method, language), the `verified` level (only through review), append-only fact revisions, regions and fact classes as data, the one display rule, contracts `programme_facts.v1`, `merit_check.v1`, `programme_list.v2`, the fixture server for fictional `.test` sites | R-23, R-25, R-26, R-60, R-76 | PR #203 (`399ab807`); `os_0025` |
| T2 | The OS registry (institutions, bodies, systems, tests, categories, calendars, official lists), programme columns, coverage level computed never stored, registry read API | R-32, R-33, R-34 | PR #204 (`b3937120`); `os_0027` |
| T3 | Allow-list YAML and `os_source_domains`, integrity checks, the suspect flow, page snapshots and original files | R-24, R-71, R-29 (snapshots) | PR #205 (`6d4d39b0`); `os_0028` |
| T4 | Headless rendering for JavaScript pages (resource-capped, sandboxed), OCR behind a port, Urdu text normalisation as data, `not_readable` marking | R-74, R-29, R-72, R-76 | PR #210 (`f1b39022`); `os_0030` |
| T5 | Reviewers with tokens and identities, the review queue, the two-person rule, `verified` transitions, collection with evidence, conflict items, batch attestation, the review screen | R-25, R-42, R-72, R-75 | PR #206 (`10f6e726`); `os_0026` |
| T6 | The one spreadsheet format, template, validator, re-fetch and quote match, status mapping, legacy mappings for batches 1 to 4, import log and undo, CLI and admin API | R-67, R-68, R-76 | PR #211 (`84409959`); `os_0031` |
| T7 | Notice windows, the `os.monitor` job (two-run rule, sanity guard, advisory day lock, retry tick), `fact_rechecking`, student reports and their owner-ruled scope, recovery by "fact stands" | R-27, R-28; rows 6.23, 6.24 | PR #213, landed by #221 (`e30797a0`); `os_0032` |
| T8 | `os_intakes`, expected slots, the yearly rollover, the labelled previous-year read, playbook `applies_to`, the next-intake plan proof | R-26, R-61, R-62, R-63, R-64, R-65 | PR #207 (`65f8cded`); `os_0029` |
| T9 | Coverage API and screen, the launch-gate reading (a) to (d), the intake `current` gate (`set_state` refuses `current`), workload estimate | R-34, R-35, R-66 | PR #215, landed by #221 (`e30797a0`); no migration |
| T10 | `ProgrammeFacts` and `MeritCheck` ports, merit formula and closing-merit shapes, `programme_list.v2` | R-23, R-30, R-31, R-48; rows 6.10, 6.25 | PR #212, landed by #221 (`e30797a0`); no migration |
| T11 | Calendars as registry rows and facts, `result_expected` from an official calendar by registry id, imports and undo revise plans for every fact | R-20, R-26, R-33; row 6.20 | PR #216, landed by #221 (`e30797a0`); no migration |
| T12 | This gate: consistency rules 9 to 12 in the nightly job, the scripted gate proofs, the R-69 queue export, not-readable sources into the queue, the Spike 1 harness, this handoff | R-35 (the reading), R-69, and rules 9 to 12 of the consistency job (R-05 stays a P1 requirement in the yaml: the master spec §12 lists it under P1 only); it does not build R-59 (CI) | PR #217, landed by #221 (`e30797a0`); `os_0033` |

Integration: `pc/p2-integration` merges T1 to T11 on one migration chain `os_0025` to `os_0032` (`os_0033` is T12's). Each task branch keeps its own migration number; the chain was renumbered on the integration branch and again when the tasks reach `pai-connect`.

**Local completion run, 2026-11-13 and 2026-11-14 (LOCAL, not on GitHub).** T13 to T22 were built on the owner's PC. Each code task (T13, T14, T16, T18 to T22) and the data task T17 were built by an implementer and checked by an independent reviewer. T15 was checked by a controller script (its entries against both checks), and its squash was then covered by the independent merge review of T13 to T15 (`briefs/MERGE-T13-15-review.md`). **T13 to T22 are squash-merged into the local branch `pai-connect`** (from `1614f24`, the GitHub head after #222; T21 at `37e061d0`, T22 at `bde1c4c5`). Its hashes below are branch commits and will change when it is squashed; the controller puts in the final hash at merge time. Nothing is pushed; these are local commits, not PRs. Source: `.local-ci/LEDGER.md` and the briefs, reports and reviews in `.local-ci/work/briefs/` (local, not in the repo). The R-IDs are those the task briefs name (R-58, the no-country-names rule, is named by every code brief and is left out below).

| Task | Result | R-IDs | Where (local commit) |
|---|---|---|---|
| T13 | **Import aliases**: an alias file (YAML, bound to the returned file's sha256) maps an id used inside one returned file to an Institutions-sheet entity that is planned in the same file or already in the registry, so a returned file stays byte-identical. An alias applies only when check 1 is `correct`, check 2 is `yes` and both checkers have attested the alias file's ref `aliases-<sha256 of the alias file>` in the review queue, whatever the batch's row mode; any edit needs new attestations. A Facts alias never resolves to a programme. Report reasons: `alias_applied` and `alias_not_accepted` (the `Aliases` sheet), `aliased` (the aliased Institutions row is skipped), `alias_target_not_loaded` (`docs/research/batches/README.md`, "Alias files") | R-67, R-68, R-76 | `8a764588`; `os_0034` |
| T14 | **A T6-format sheet from re-entered values**: a generic command builds a new workbook from a base sheet, a values CSV and check CSVs, with a YAML mapping (no file names in code). Built the Sindh v5 seats workbook: 74 rows (10 check-2 `unclear` rows held, 37 rows without a value not written; `briefs/T14-rereview.md`; the first implementer commit had 121) | R-67, R-68, R-76 | `771bd295`; no migration |
| T15 | Data: five official-list entries (UHS x2 Punjab, SMBBMU Sindh, BMC Balochistan, SZABMU ICT), the FDE HSSC list (ICT), alias files for batch 5 (19) and batch 4 (2), the v6 Sindh seat re-entry, check records in `docs/research/lists/checks/` | data task (no brief file) | `19e0f559` |
| T16 | **List union**: an institution on several official lists keeps every list on import; undo restores the entity that was there before. A row whose own regional list does not match its region is a plan rejection (`region_conflicts_with_list`), and a registry refusal is a rejected row (`registry_refused`), not a failed import. A URL shared by several list entries (HEC `recognised.aspx`) puts the row on the national list(s) and the regional list matching its region. `validate --lists` reads list regions | R-32, R-35 (a), R-60, R-68, R-69 (undo), R-76 | `668d1bf8`; no migration |
| T17 | Data: the Sindh v6 seats workbook (34 rows, both checks agree). **Reviewer refs**: checker names in alias files and seats workbooks are reviewer refs (`claude-local-check-1/2`, `claude-research-seats-check-1/2`, `claude-research-v6-seats-check-1/2`), since reviewers mode matches names against refs (`[a-z0-9_.-]{2,64}`) | data task (no brief file) | `b4ac61ec` |
| T18 | **The parent kind**: a programme under a non-institution is a rejected row (`parent_not_institution`) in the plan, and the importer turns a programme `RegistryError` into a rejected row (`registry_refused`). Batch 4 now imports; P4-034..036 are rejected | none besides R-58 | `84972b73`; no migration |
| T19 | **Per-row family**: a row's allow-list family is the `family` of every official list its entity is on (files for a dry run, the registry for an import; aliases resolved; programme facts take the institution's region), else `--family`; the scope that accepted it is kept in `provenance.allow_list_scope`. **`validate --allow-list DIR`**: the dry run judges sources against the allow-list files as the import does. **Re-fetch scope**: `--refetch` uses the row's accepting scope, else its list families, else `--family`, and fetches only for families the host is listed for (none: `refetch_blocked:not_official` without a gateway call) | none besides R-58 | `68010d0b`; no migration |
| T20 | **The allow-lists**: 16 files in `backend/app/os/knowledge/sources/lists/`, 56 entries, from W13 check 1 drafts and check 2 `yes` only (`hed.ajk.gov.pk` out), `reviewed_by` both check refs. **Sync race fix**: `SourceDomains.sync` skips a row another worker's sync has just inserted (it raised `UniqueViolation` when several workers start). Downgrade tests take the `clean` fixture | R-71 | `321cc3fd`; no migration |
| T21 | **The body family**: a body of a kind in `SERVES_A_REGION` (`regulator`, `board`, `admission_body`, `admission_system`, `entry_test`; `backend/app/os/registry/model.py`) on no list with a family is judged against every family of the loaded official lists, `--family` first (`family_choice`, basis `body_any`; `provenance.family_basis`). Data: `admission.hed.gkp.pk` (KP intermediate) and `etea.edu.pk` (KP bachelor), from checks 1b and 2b. **Allow-list total: 58 entries** (W13 checks 1, 2, 1b and 2b; the bare `hed.gkp.pk` entries were removed in the fix round) | R-71 | `37e061d0`; no migration |
| T22 | **Page cache scope (FU-9)**: with the source guard on, the allow-list is checked for the asked scope before any cache lookup, a `not_official` refusal is no longer stored in `os_pages`, and a cached redirect to an unlisted target is refused. No-guard path unchanged. Spec notes in the Slice 2 spec §6 and the P2 spec §4.2 | R-71 | branch commits `2d92c4fa`, `8d732d6d` (squash-merged as `bde1c4c5`); no migration |

**Migration added after T12: `os_0034_import_aliases`** (T13; `backend/alembic/versions_os/os_0034_import_aliases.py`, down `os_0033`). It adds `os.os_imports.aliases` (JSONB, default `[]`): the alias files an import used, with their sha256. Its downgrade is refused while any import has logged an alias file (no silent loss). There is no `os_0035`; the OS head is `os_0034`. This closes the remainder of T13 review item 6 (ledger ruling: "T13 #6 remainder ... is done in W11").

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
| 1 | Every task merged into `pai-connect` with all CI jobs green | **Yes.** All twelve tasks are in `pai-connect` with every CI job green: #203 to #207, #210, #211, and #221, which landed the approved stacked PRs #212, #213, #215, #216, #217, #219 and #220 (they had been squash-merged into the task branch beneath them). Spec rulings #214, research batches #218. Migrations `os_0025` to `os_0033`, one head. (On GitHub. T13 to T22 are local only; see "Local evidence" below) |
| 2 | `check_traceability.py --gate P2` passes | **Exit 0.** Every P2 R-ID has a tagged test. **R-48 is `built: true`** since freeze exception 1 (#219, `CONNECT_MERIT_ANSWERS`) landed in #221; the Counsellor lead was asked to confirm in #219 whether admission answers from ProgrammeFacts also count, else it goes back to `false`. R-15 (a P1 requirement) is still unbuilt (§4) |
| 3 | Walkthroughs for every region and family checked by checker 1 and approved by checker 2 | **Not proved by code.** The H2 walkthroughs and H3 lists are drafted on `pc/p2-research-batches`; the sign-off rows are the owner's to confirm. By ruling §11.2 two independent AI checks count as the two checks |
| 4 | Spam page: refused, domain `suspect`, facts unconfirmed, review item open | **Yes.** `tests/os/gate/test_p2_gate.py::test_gate_4_spam_page_is_refused_the_domain_suspect_facts_unconfirmed_item_open` (with the real queue); also T3's `test_spam_fixture_is_refused_and_its_domain_becomes_suspect` |
| 5 | A `not_readable` source collected with evidence, approved by a second person | **Mechanism proved** (`test_gate_5_...`: not-readable row, collect item, evidence file, collected value, comparing check, approval, verified; audit). **The real one (H7) is a people step still to do** |
| 6 | Registry built from official lists: 100% of each named list | **Reading built, figure not measured here.** The coverage dashboard (T9) and the launch-gate reading (a) to (d) are tested; the real percentage needs the registry batches imported (H4). **Measured locally on 2026-11-14: 686 / 2435 = 28.2%, NOT met** (see "Local evidence" below) |
| 7 | Spike 1 rerun on a sample from every region: 100% on verified, at least 95% on confirmed | **Harness built and tested; live run not done.** The harness is strict: every key entry must be held at `confirmed` or above, the sample is 5 distinct institutions, NaN and infinity match nothing. **No answer key exists yet (H6)**: the dry run of batches 1 to 5 (#218, `docs/research/batches/VALIDATION-2026-11-12.md`) accepts only admission-body and system facts (1 to 4 per region), no institution facts, so no region can reach 5 institutions. `os_spike1_rerun regions` lists 0 of 9 regions with a key and `plan` refuses, so there is no cost estimate yet. The billed run is the controller's, inside the US$20 cap (ruling Q5) |
| 8 | Monitoring and a student report proven on a scripted page change (rows 6.23, 6.24) | **Yes.** T7's `test_a_page_change_in_season_resets_the_fact_pauses_the_step_and_queues_the_item` and `test_a_report_shows_not_confirmed_to_everyone_but_only_the_reporters_steps_wait`, with the owner-ruled scope (§3) |
| 9 | A scripted rollover (rows 6.10, R-61 to R-63) | **Yes.** T8's `test_rollover_proof_2026_to_2027`; the next-intake plan proof |
| 10 | Spreadsheet round trip with deliberate errors; undo restores | **Yes.** `test_gate_10_...` asserts each error by its reason: `unknown_region` (typed region spelling), `source_not_on_allow_list` (bad URL), `no_quote` (missing quote), `second_check_missing` (one checker on a high-stakes row, the fact stays `confirmed`), `quote_not_found` (model-extracted quote not on the re-fetched page). **Undo withdraws what the import loaded**: every fact goes `stale` and the entity is `closed`; nothing is deleted. It does not put back a state that never existed |
| 11 | Rows 6.20 and 6.25 pass; consistency rules 9 to 12 find zero | **Yes, with limits (§4).** `test_calendar_plan.py::test_6_20_...`, `test_p2_merit_ports.py`; rules 9 to 12 find zero on a clean fictional student **only once the allow-list is loaded and the guard is on**; before that the run reports rules 9 and 12 as "not run" (asserted in `test_gate_11_...`), and each violation is found. The nightly run's result carries `not_run` |
| 12 | Freeze-exception replays (merit answers, calendar move): only the intended answers changed; Counsellor lead approved | **PRs done, both approved and merged (in #221), flags off by default.** Freeze exception 1, `CONNECT_MERIT_ANSWERS` (R-48), #219: offline replay with a recorded model reply, flag off vs on differ only by the added merit items; `COUNSELOR_V3_PROMPTS.md` gains one sentence, no prompt text changed. Freeze exception 2, `CONNECT_CALENDAR_FROM_KNOWLEDGE`, #220: offline replay of 1032 estimates, 0 differ with the shipped (empty) links, 516 differ with one fictional confirmed date and all 516 are exactly the estimates that use it. **Turning flag 2 on changes nothing until** the policy JSON's official rows are imported into Knowledge and linked in `policy_links.yaml` |
| 13 | This handoff written; the owner signs off | Written (draft). **Awaiting the owner's sign-off** |

Test counts on the T12 branch: `tests/os` 2955 (2 skipped, 1 xfailed) passed; the legacy suite 2560 passed, 13 skipped; vitest 602 passed; `next build --webpack` ok; `tach check`, `check_freeze.py`, `check_traceability.py --gate P2` ok; one OS Alembic head (`os_0033`).

### Local evidence, 2026-11-14 (LOCAL, not GitHub CI)

Everything in this subsection was run on the owner's PC. The W4 import ran on the local branch `pai-connect` at `37e061d0` (T13 to T21) with a fresh local database; the test counts come from the commits named with each count. It is **not** GitHub CI and does not change the table above. It changes no gate to "met".

**W4 local import** (all 7 imports exit 0; Batch 4 now imports). Sources: the ledger entry "W4 re-run 2026-11-14 on 37e061d0" and the report CSVs `.local-ci/work/W4/out/i-*.csv` (counts below recounted from the CSVs).

| Batch | `verified` (both checks) | Still `unconfirmed`, by reason |
|---|---|---|
| B1 (national) | 361 | conflict 1 |
| B2 (Punjab) | 186 | `no_quote` 116, conflict 3, `check_unclear_or_missing` 3 |
| B3 (Sindh) | 111 | `check_unclear_or_missing` 2, conflict 1 |
| B4 (KP, Bal, ICT, AJK, GB) | 94 | `source_not_on_allow_list` 10 (`www.imcgf72.edu.pk`), conflict 2, `check_unclear_or_missing` 2 |
| B5 (universities BS) | 55 | `check_unclear_or_missing` 1, `no_quote` 1 |
| Seats v5 (Sindh) | 0 | `refetch_not_run` 74 |
| Seats v6 (Sindh) | 0 | `refetch_not_run` 34 |
| **Total** | **807** | |

Before this run nothing was above `unconfirmed` (no allow-list file existed). The ledger line lists the unconfirmed rows without B1's conflict 1 and B4's conflict 2 and unclear 2; the CSVs of the same run hold them, so the CSV counts are used here. Rows that are queued, rejected or skipped are in the same CSVs (for example B3's 110 `no_value` programmes). **Seats v5 and v6 stay `refetch_not_run`**: their workbooks import in reviewers mode, which needs `--refetch`, a live page fetch through the app; it was not run because an outbound call needs the owner's approval (CLAUDE.md).

**Gate 6 (registry from official lists): NOT met.** List memberships loaded / published, over the lists that have a published count: **686 / 2435 = 28.2%** (ledger; recounted from `.local-ci/work/W4/out/progress.csv`). By region: AJK 8/186, Balochistan 16/16, Gilgit-Baltistan 29/29, ICT 30/112, KP 47/47, national 284/541, Punjab 180/1057, Sindh 92/447. No published count yet: `kp-hed-participating-colleges` (0 loaded), `hec-recognised-campuses` (0 loaded), `seccap-participating-colleges` (60 loaded). The research batches name only the institutions they researched; the gate needs every line of each official list. That needs **registry batches built from the official lists** (W12: one T6 workbook per region, rows = list lines, source = the list URL, two independent extractions as check 1 and 2). The allow-list work does not move this number. These figures replace the earlier gate-6 list numbers, which the shared-URL defect fixed in T16 had distorted (FU-7).

**Test counts (local).** Full `tests/os` at the T21 review, on `ccc90417` (T21 before its fix round `e20aaef9`; the fix round was checked with a targeted set): 3023 passed, 24 skipped, 1 xfailed, 0 failed (`briefs/T21-review.md`). Earlier local full runs: merge trial `668d1bf8` (T13 to T16) os 3001 passed, 24 skipped, 1 xfailed; standalone 51 passed; legacy 3953 passed, 1662 skipped; frontend 602/602 (ledger). T22 was checked on its branch commit `2d92c4fa` with a targeted set (623 passed, 22 skipped; `briefs/T22-review.md`), not a full run. No full local run on `37e061d0` is recorded yet.

LOCAL full CI on <commit>: <to fill>

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
| 2026-11-14 (W13, local ledger) | **For the allow-list files, an AI check 1 plus an independent AI check 2 is enough review** ("ai ke review kafi hai"). `reviewed_by` names the two AI check refs. Applied in T20 and T21 |
| 2026-11-14 (local ledger) | **Delegation:** with the owner away, he delegated the open decisions to the controller: "build the best of it ... do it by yourself". The controller decisions below were made under it. **Each is for the owner to confirm at sign-off.** |

Controller decisions under the delegation of 2026-11-14 (source: the local ledger; **all for the owner to confirm at sign-off**):

| Decision | What and why |
|---|---|
| Body family rule | A body row (a regulator, board, admission body, admission system or entry test) on no official list with a family is judged against every family of the loaded official lists, `--family` first; institutions are unchanged; the region is never widened. Built in T21 (`SERVES_A_REGION`, a positive tuple after the T21 review) |
| `hed.ajk.gov.pk` kept out | Its only proof page (`ajk.gov.pk`) carries live spam (replica watches), seen in checks 1, 2 and 1b; check 2 gave `unclear`. It stays off the allow-list |
| `hed.gkp.pk` proven, not listed on its own | Checks 1b and 2b proved it (via `kpese.gov.pk`), and it proves `admission.hed.gkp.pk` and `etea.edu.pk`, which are listed. The bare `hed.gkp.pk` entries were removed in the T21 fix round: they rested on one check's family, and listed `admission.hed.gkp.pk` under bachelor through the subdomain |
| No-region rows and P4-034..036 held | The 40 rows without a usable region (34 foreign-board IBCC rows, 6 with an empty region; the ledger calls them wildcard) and P4-034..036 stay rejected or held. No region, institution id or other data was guessed |
| Seats re-fetch not run | Seats v5 and v6 stay `refetch_not_run`: the re-fetch is a live outbound page fetch, which needs the owner's approval (CLAUDE.md) |

## 4. Open gaps and deviations

People and process (not code):

- **The live Spike 1 rerun is not done.** The harness scores and plans; the billed research run and the answer keys (H6, one per region, by a checker who did not verify those rows) are still to come. Until then gate item 7 is open. The cost cap is US$20 for all of P2.
- **No real not-readable source has been collected through the queue (H7)**; the mechanism is proved on fictional data.
- **The registry percentage (gate item 6) is not measured**: it needs the H4 batches imported.
- **The calendar freeze exception is wired but has no links yet** (#220): the Counsellor policy JSON's `official` rows still go into Knowledge through the T6 import (`unconfirmed`; `secondary` and `uncertain` as `lead_only`), then get their registry calendar ids in `backend/app/pai_c/connect/policy_links.yaml`.
- **The research batches do not import cleanly yet** (#218, dry run in `docs/research/batches/VALIDATION-2026-11-12.md`): most institutions fail `no_official_list` (their official lists are not loaded); 110 Sindh MBBS/BDS seat rows have no cut-off and the re-entered seat file `PAI-Research-Batch3-Sindh-v5-seats.csv` is not in the T6 format (a mapping is needed); every Batch 5 row fails (13 without a quote, 5 with a region outside the vocabulary). The research lane fixes these; the import has not been run.
- **R-48 is `built: true`** with freeze exception 1 (#219). Open question for the Counsellor lead (in #219): the R-48 title also names admission answers from ProgrammeFacts, which no Counsellor reply reads yet; and the merit items are added in code after the model runs, not given to the model as input.
- **R-15's OS side** (an excluded field disappears from the OS programme list) was moved from P1 to P2 by the P1 handoff (Q4) but is not in the P2 spec's scope; it is still not built (`built: false`, phase P1). The owner decides where it goes.
- R-46 stays `built: false` as recorded in the P1 handoff.

Data gaps found in the local run of 2026-11-14 (source: the local ledger and `.local-ci/work/W4/out/*.csv`):

- **10 `www.imcgf72.edu.pk` rows** (IC-ADM-002 and B4-F-043..051) stay `unconfirmed`, `source_not_on_allow_list`: the host is not proven (check 1b: the `fde.gov.pk` prospectus link was unreachable).
- **4 hosts researched again in check 1b and not proven**, so not on the allow-list: `jac.ajk.gov.pk`, `gcwg.punjab.gov.pk`, `www.imcgf72.edu.pk`, `hed.ajk.gov.pk` (its proof page is compromised). This is not the full list of hosts left out (W13 check 1 lists the others).
- **`ajkbise.net` is kept out on purpose**: `docs/research/lists/ajk.yaml` marks it suspect (gambling spam, 2026-11-07); W13 check 2 found it compromised again (ledger).
- **PK-TST-005 is `checker2_rejected`**: a data finding, not an allow-list one; the row never reaches the allow-list check.
- **40 no-region rows** (34 foreign-board IBCC, 6 with an empty region; W13 check 1 summary) are held; no region is guessed.
- **P4-034..036** (Balochistan divisional-merit MBBS seats in other provinces) are filed under BL-ADM-001, an admission system; they are rejected `parent_not_institution` until research gives a real institution id or another model.
- **Batch 3's 110 `no_value` programmes** (v4 MBBS/BDS seat rows with the number only in the quote) are rejected; their re-entered values are the v5 (74) and v6 (34) seats workbooks, which wait for the re-fetch.

Follow-ups from the local reviews (FU-1 to FU-10, as the ledger records them):

- **FU-1**: list progress must not count withdrawn rows (gate (a) could go green from undone imports). **Withdrawn rows: addressed by T27**: `list_progresses` and `list_progress` count a row only for the lists `kept_lists` gives it, so a row closed by an import undo (status `closed` plus `withdrawn_by_import`) counts for no list, and an undone alias membership (T28 `add_lists`) does not count either. **Still open for the owner (W10):** whether a row closed or merged for any other reason counts. Today it still counts (unchanged, pinned by `tests/os/sheets/test_list_progress_withdrawn.py`).
- **FU-2**: per-list evidence (`source_url` and quote per list) for R-76; the first list's URL and quote are replaced on the row and kept only in revisions. Own task.
- **FU-3**: an aliased row on another list could add that list to its target; later decision.
- **FU-4**: merge review F1/F2: a `validate --institutions-from` dry run plans OTHER files without their own alias files; alias files load after the OTHER loop.
- **FU-5**: a `--institutions-from` dry run checks only the last row's list when OTHER has one entity on two lists (dry run only).
- **FU-6**: hand-built plan contexts without list regions treat shared-URL lists as national (affects `test_real_batches_dry_run` only).
- **FU-7**: a database that already holds a pre-T16 HEC import may have universities on a wrong regional list, so a re-import gives `region_conflicts_with_list`; the local W4 run used a fresh database. Whether a production import ever happened is to check.
- **FU-8**: a theoretical orphan after a late link refusal (T18 review minor).
- **FU-9**: a cached page served to a scope it is not listed for. **Done in T22.**
- **FU-10**: cached render sub-request hosts, and `not_readable:render` per URL (both need a schema change; low risk); the T22 review also notes that an integrity check is judged with the first caller's domains.

Code limits and known gaps:

- **Imported dates that are not written in ISO format stay as text and do not move plans** until someone converts them (the compiler reads ISO dates only).
- **Reading (T4):** the Tesseract bake-off passed 6 of 10 quotes after the fixes (5 of 10 before), below the bar; **Docling could not be installed and was not compared**, so the OCR engine choice is open. Urdu numbers are misread by the engine. OCR text therefore stays `unconfirmed` until a checker compares it with the original (R-72). The render memory cap works only where a cgroup exists (tested for v1, untested for v2; otherwise the browser heap limit is the only cap); the render deadline uses the host clock per process.
- **Coverage (T9):** a source on an unlisted domain fails check (c) of the launch-gate reading; a follow-up is noted in the T9 review.
- **Monitoring (T7):** programme-scope facts only; the day's run is one per day; a sanity failure delays a change but never hides it (two failures in a row take the facts back); notices to students are the existing "plan updated" notice and bell, no new event kind.
- **Official lists and aliases (T28):** FU-2 (the evidence part: a list line no longer overwrites the entity, and its evidence is kept in `attrs.list_evidence`) and FU-3 (an aliased list line adds its list to the target) are addressed by T28. See the alias section of `docs/research/batches/README.md`.
- **Registry (T2):** which kind a parent may have is chosen per kind table by the agent; the final review is to check it.
  **Decided 2026-11-14** (controller decision under the owner's delegation, for the owner to confirm at sign-off): the
  table is approved as built, with one change: `board` may be the parent of a `calendar` (exam and result date
  sheets come from boards; walkthrough rows PI-09 and GI-02). No other loosening; a campus still needs an
  institution (`backend/app/os/registry/model.py` `ALLOWED_PARENTS`, task T26).
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

Import and dry-run options changed or added in the local run (T16, T19; `backend/scripts/os_import_batch.py`):

| Option | Meaning | Default |
|---|---|---|
| `validate --lists DIR` | The dry run reads the official-list files: their regions are used since T16, their families since T19 | none |
| `validate --allow-list DIR` | The dry run judges every source against the allow-list YAML files in DIR as the import does; it carries no database state, so a domain marked `suspect` in a database is not seen (T19) | not checked; the report says "allow-list: NOT checked" |
| `--family` | The allow-list family used only for a row that gets no family from its lists (see below) | `''` |

**How the allow-list family of a row is chosen** (`family_choice` in `backend/app/os/knowledge/sheets/plan.py`): (1) the `family` of every official list the row's entity is on (the `--lists` files in a dry run, the registry in an import), basis `lists`; else (2) for a body of a kind in `SERVES_A_REGION`, every family of the loaded official lists, `--family` first, basis `body_any` (T21); else (3) `--family`, basis `run`. The region is never widened. The scope that accepted the source is stored in `provenance.allow_list_scope`, the basis in `provenance.family_basis`.

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
  - Alias files: `--aliases FILE.aliases.yaml` (T13); the alias applies only after two reviewers attest `aliases-<sha256>`.
  - Dry run with the allow-list: `python -m scripts.os_import_batch validate FILE --country PK --lists DIR --allow-list DIR [--report OUT.csv]`. The allow-list files are in `backend/app/os/knowledge/sources/lists/`. The family of each row is chosen as in §5; give `--family` only for rows that get none.
  - Re-fetch (`--refetch`): model- and OCR-read rows are fetched again through the page gateway, only for the families the host is listed for (T19). It is an outbound call: run it only with the owner's approval.
- Spike 1: `python -m scripts.os_spike1_rerun regions|plan|score` (no model call). A key is `tests/os/quality/<region>_answer_key.yaml`; the shape is in `app/os/gate/spike1.py`.
- Gate: `python scripts/check_traceability.py --gate P2`; the proofs: `pytest tests/os/gate`.
- Consistency: the nightly job runs rules 1 to 12; `scripts/connect_consistency.py run|status` as in P1.

## 8. Open items for later phases

- P3 and P4: playbooks per route and family (R-81); stage H from the OS registry with coverage levels (R-49); merit shown only in the student login (R-70, rule 13).
- P5: the launch gate (R-35 (a) to (d) as the launch decision) and the verified floor per region; the rest of batches 3 and 4 onward (H8).
- Making the Docling comparison, and a second OCR engine if Tesseract stays below the bar.
- The Counsellor-side freeze exceptions above, after the Counsellor lead's replay review.
