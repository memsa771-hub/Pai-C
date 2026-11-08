# P2-T6 spreadsheets report

Branch `pc/p2-t6-sheets` (cut from pc/p2-t2-registry 788e87b). Migration `os_0027_imports` (down_revision `os_0026`; renumber at merge). New dependency `openpyxl==3.1.5`.

## Built (R-67, R-68; R-69 and R-76 partly)
- `app/os/knowledge/sheets/`: `format.yaml` (columns, statuses, read-method map, intake patterns, type->kind map, non-official hosts, programme value columns, owner-accepted checker names), `legacy/*.yaml` (4 old Programmes layouts: batch 1, 2, 3, 5; batch 4 is canonical), `reader.py` (xlsx or CSV folder -> canonical rows with file row numbers, legacy conversion), `plan.py` (pure validation + status mapping = the dry run), `importer.py`, `refetch.py`, `undo.py`, `importlog.py`, `template.py` (template generator, `queue_export`), `ports.py`.
- Modes: `owner_accepted` (needs `--owner-accepted <decision ref>`; checks must be the two AI checks; provenance `claude_check_1/2`, `accepted_by: owner`, decision ref, note in `evidence`; verified is set with `set_status(cause="review", actor="owner-accepted:<ref>")`) and `reviewers` (a checker counts only if `attested(ref, batch_ref)`; two different ids).
- Row outcomes: accepted (verified/confirmed), unconfirmed, queued (`import_dispute` / `collect` / `conflict` item via `open_item`), rejected (reason in the report), skipped (lead, history, searched, out of scope). Report CSV beside the file lists every row. Load goes through `RegistryStore.record`, `ProgrammeStore.upsert` + `link_programme`, `SqlKnowledge.upsert` + `set_status`; all with `cause="import"`, `cause_ref=import-<id>`, `actor`.
- Re-fetch and quote match (`Refetcher`, `PageGateway.fetch(url, (), (), Scope)` and `trust.quote_on_page`): model- and OCR-read rows never exceed `unconfirmed` unless the quote matches on the re-fetched page; an unconfirmed row with a quote is promoted to `confirmed` (never `verified`) on a match; conflicts are not promoted. One fetch per URL.
- Import log `os_imports` (sha256, mode, decision ref, actor, counts, status). A unique index refuses importing the same file twice while it is done/running. Undo (`undo.py`) replays revisions backwards: inserted facts become `stale` with an empty value and a note, inserted registry rows are `closed`, changed rows get their `before` back, created programmes are `excluded`; every step is an `undo` revision; it refuses (all or nothing) if something changed after the import, and ignores imports already undone (so LIFO works).
- CLI `backend/scripts/os_import_batch.py` (`template`, `validate` dry run with `--lists DIR` and `--no-list-needed`, `import --owner-accepted REF | --reviewers`, `undo`, `list`; `--refetch`), admin API `/admin/imports` (template, validate, import, list, get, undo). T3/T5 objects are wired by `wire_other_tasks` when their modules exist; here they are used through protocols with fakes.

## Deviations and open points
- Canonical Institutions and Facts layouts are the v4 batch layouts, and the checker columns are the v4 ones (`checker1_result ... checker_note`), not the `checker1_id` names of spec §4.6, which no batch uses. The name columns carry the reviewer ref.
- One import = several store transactions, not one transaction per sheet (the stores open their own). A failure is logged `failed` and is undoable.
- A programme row yields one fact per value column (field `seats_<category>`, `closing_merit_<category>`, ...), class stored on the fact. Programmes get `route_key` `registry` (option), `family` is not set.
- Intake text -> (term, year) is a proposed mapping in `format.yaml`, for the owner to confirm: `Session 2026-27` -> session 2026, `Fall 2027` -> fall 2027. Text no rule matches (`standing`, `previous cycle ...`, `current`) is queued as `intake_unresolved`, never guessed.
- `conflict` rows stay `unconfirmed` plus a conflict item even if both checks accepted them (spec mapping over README line). A model/OCR-read row accepted by both checks is NOT verified without a re-fetch match (R-68/R-72 over the README line); this affects 34 facts in the dry run below. If the owner wants those verified without re-fetch, it is a one-line change in `plan._cap`.
- The registry (T2) takes `https` sources only; any `http` institution source would be rejected as `invalid_entry` (none of the five files had one that got that far).
- R-69: `queue_export(items, path)` writes the queue in this format from plain dicts; wiring it to `ReviewQueue` listing is left for the merge with T5 (R-69 left `built: false`). R-76: region normalisation is in the plan (via T1 `normalise_region`); `built` left to T1.
- PENDING on the T2 fix: `link_programme` currently has no `cause/cause_ref/actor`; `_load_programme` already passes them. The 3 tests in `tests/os/sheets/test_import_programmes.py` fail with `TypeError ... unexpected keyword argument 'cause'` until pc/p2-t2-registry carries the fix and is merged. After the merge: (a) run those 3 tests, (b) add the one-line filter in `coverage.py` so withdrawn (stale, empty-value) facts do not count as `researched`.
- New student sentences: none.

## Dry run of the five v4 files (read-only, no DB, `scripts.os_import_batch validate`; official lists from docs/research/lists/*.yaml; owner-accepted rules)
Source rows: Institutions 570, Programmes canonical rows 359 (297 source rows; batch 2 explodes into up to 3), Facts 336.

Official lists as present (25 list URLs):
- Institutions: accepted 428 (all verified), unconfirmed 1, queued 4 (checker2 rejected 1, not_readable collect 3), rejected 128 (no_official_list 94, unknown_region 20, no_quote 13, non_official_source 1), skipped 9 (lead 3, out of scope 6).
- Programmes: accepted 3, queued 40 (checker2 rejected 15, intake_unresolved 25), rejected 320 (institution_not_loaded 319, bad_status 1 = the "(batch 3)" placeholder row).
- Facts: accepted 150 (verified; 34 of them model/OCR-read and need the re-fetch match), unconfirmed 12 (conflict 6, check unclear 6), queued 36 (checker1 wrong 7, intake_unresolved 19, not_readable 6, checker2 rejected 4), rejected 134 (entity_unknown 129, entity_not_single 5), skipped 4 (lead 3, searched 1).

If every official list were loaded (`--no-list-needed`):
- Institutions: accepted 522, unconfirmed 1, queued 4, rejected 34 (unknown_region 20, no_quote 13, non_official 1), skipped 9.
- Programmes: accepted 181, unconfirmed 116 (no_quote: the total-seats and closing-value parts of the batch 2/3 layouts carry no quote of their own), queued 40, rejected 26 (institution_not_loaded 25, placeholder 1).
- Facts: accepted 172 (39 need re-fetch), unconfirmed 13, queued 41, rejected 106 (entity_unknown 99, entity_not_single 5, non_official 2), skipped 4.

What the reasons mean:
- no_official_list (94): medical-college rows cite prospectus PDFs (UHS 75, SMBBMU 9, BMC 4, SZABMU 3 ...) that are not an H3 official list URL. R-32 needs each institution to name its list; H4 must load a list for them (PMDC list) and map them, or the owner relaxes the rule.
- unknown_region (20): `United Kingdom` 8, `ICT (multi-campus)` 4, `National (private)` 2, `Islamabad / federal` 1, `Punjab (federal)` 1, one each of other countries. Aliases for the ICT, national and federal spellings would be T1 data (`regions.yaml`); foreign ones are R-77 (abroad).
- entity_unknown (129): facts about institutions that were rejected above, and facts that cite an institution from another batch file (resolved when batch 1 is imported first; the dry run reads one file at a time).
- entity_not_single (5): `PK-UNI-*`, `PK-BRD-*`, `FQ-*` rows about a group; they need one row per entity.
- intake_unresolved (19 facts, 25 programmes): `standing`, `previous cycle (as shown on ...)`, `current ...`. P2-D4 says Knowledge facts are always per intake; the owner decides the mapping.
- no_quote (13 institutions): rows with no source quote.

## Checks
- tests/os/sheets + tests/os/test_api_imports.py: 69 passed, 3 failed (the programme tests above, blocked by the T2 fix).
- Full tests/os (excluding the 3 blocked tests): 2470 passed, 1 skipped, 1 xfailed, 1 failed (`test_crash_during_research`, Postgres restart at ~13:50 UTC); `tests/os/test_crash.py` rerun: 7 passed.
- Legacy suite: 2560 passed, 13 skipped. tach OK. Freeze OK. Alembic heads OK (one OS head). Traceability OK. ruff clean on the new code.

## Update after the owner rulings (spec §11.3)
- Owner-accepted mode only: a model- or image-read row accepted by both AI checks is `verified` with no re-fetch; each fact's `evidence` carries `refetch_waived: "P2 spec §11.3"` (plus the decision ref and checker provenance). A single-check model-read row still needs the re-fetch. Reviewers mode keeps the re-fetch (tests for both).
- `standing` / `current` / `previous cycle` intakes stay queued as `intake_unresolved`.
- Foreign-country institutions (format.yaml `out_of_scope_regions`: Australia, Switzerland, United Kingdom, United States of America) are skipped (`out_of_scope_region`), and so are their facts and programmes (`entity_out_of_scope`).
- Region alias proposals for T1's `regions.yaml` (not edited here): `ICT (multi-campus)` (5 universities, campuses in the capital territory but possibly elsewhere too) -> islamabad_capital_territory; `Islamabad / federal` (1 board) -> federal_institution (or islamabad_capital_territory); `National (private)` (2 boards) -> national; `Punjab (federal)` (1 public medical college) -> owner to decide (federal_institution or punjab); `Various` (1 row, technical board, type says out of scope) -> leave rejected.
- The 94 institutions with no official list: national.yaml carries only the PMDC list's metadata (row count 190), no member names, so nothing can be matched against it. I also read the PMDC PDF itself (the URL in that file, text layer, read-only): 6 of the 94 appear by exact full name (with the city suffix the batches write): PB-MED-019, PB-MED-025, PB-MED-059, PB-MED-072, SD-MED-03, IC-MED-03. 68 more appear when the ", city" suffix is dropped; those are NOT counted (not exact). If H4 names that list for them, only the 6 would load now; the rest need an exact-name decision.

Dry run after the rulings (same method as above):
- Lists as present: Institutions accepted 428 (verified), unconfirmed 1, queued 4, rejected 117 (no_official_list 94, no_quote 13, unknown_region 9, non_official 1), skipped 20 (lead 3, in_scope=no 6, foreign 11). Programmes accepted 3, queued 40, rejected 320 (319 institution_not_loaded + placeholder). Facts accepted 150 (verified, 0 waiting for re-fetch), unconfirmed 12, queued 36, rejected 112 (entity_unknown 107, entity_not_single 5), skipped 26 (foreign 22, lead 3, searched 1).
- Every list loaded: Institutions accepted 522, unconfirmed 1, queued 4, rejected 23 (no_quote 13, unknown_region 9, non_official 1), skipped 20. Programmes accepted 181, unconfirmed 116 (no_quote), queued 40, rejected 26. Facts accepted 172, unconfirmed 13, queued 41, rejected 84 (entity_unknown 77, entity_not_single 5, non_official 2), skipped 26.

## Final (after merging the T2 fix 051a0f4)
- `_load_programme` passes only the columns it has (level, field, region) to `link_programme(..., cause="import", cause_ref, actor)`.
- `coverage_map` ignores withdrawn facts (stale with an empty value), with a test.
- The 4 programme tests pass. tests/os: 2493 passed, 1 skipped, 1 xfailed. Legacy: 2560 passed, 13 skipped. tach, freeze, alembic heads (one OS head), traceability OK.

## T6 review fixes (fix(os): T6 review fixes (R-67, R-68))
Critical
1. Real imports with missing ports: rows that need a review item with no review queue connected are refused (`ImportRefused`; nothing logged or loaded; CLI exit 2, API 409). With no allow-list connected no row goes above `unconfirmed` (`allow_list_not_connected`). `except ImportError: pass` in `wire_other_tasks` now only leaves the port None, and None has these consequences. Tests for both.
2. Undo handles every revision kind: `entity` chains restore or close registry rows, `programme` revisions restore the six programme columns from `before` (and the created programmes are excluded), `link` revisions take the added links away; conflict detection is per kind and subject. Scenario A (institution exists, import only places programmes) and scenario B (import re-links an existing programme) are tested, plus a link-revision test.
Important
3. A failed import stays live (unique index covers `failed`); undo handles failed imports; `programmes_created` is saved on failure. Test: failed import, same file refused, undo, re-import.
4. CSV formula guard (`safe_cell`: `= + - @`, tab, CR get a leading apostrophe) in the report, the template/workbook cells and the queue export.
5. Facts attach only to programmes that were loaded or already exist; otherwise `programme_not_loaded` (a queued or rejected programme row is not "loaded").
6. A missing `read_method` (legacy Programmes layouts) is never assumed to be fetch: the row needs a re-fetch.
7. The §11.3 waiver is scoped: owner-accepted mode, a decision reference, and the sha256 of one of the five v4 files (listed in `format.yaml`); any other file keeps the re-fetch. Batch 2/3/5 programme rows (no `read_method` column) are covered by the waiver in those files.
8. A legacy batch 2 row with no value column becomes one placeholder row and is rejected `no_value`; a programme row with no value column is rejected `no_value` in general.
9. API actor is the identity behind the admin token (`admin`); the typed name is stored as `note_actor` (also on the import log). The undo ignores the typed name.
Minor
10/11. Spec clarifications written in the plan (one check -> `confirmed`, never `verified`; `conflict` stays `unconfirmed`; check 1 `not_readable` -> `unconfirmed`; and the rest), see "Spec clarifications" in docs/superpowers/plans/2026-11-07-p2-t6-sheets.md.
12. The report is kept in the import log (`os_imports.report_csv`, `GET /admin/imports/{id}/report`); the template is built in memory (no temp file).
13. Undo marks the import undone in the same transaction as the data.
14. Row, column, file-size and unpacked-size caps (`limits` in `format.yaml`), zip check before parsing, defusedxml required (added to requirements).
15. `seen_keys` are registered only after a row passed every check. The intake patterns, approved by the owner (spec §11.3) and no longer marked PROPOSED:
   - `Fall|Spring|Summer|Autumn|Winter YYYY` -> that term and year (`Fall 2027` -> fall 2027)
   - `Session YYYY-YY` and `YYYY-YY` -> term `session`, year = first year (`Session 2026-27` -> 2026)
   - `Batch YYYY`, `Annual YYYY` -> term `batch` / `annual`, year YYYY
   - `YYYY` -> no term, year YYYY
   - anything else (`standing`, `current`, `previous cycle ...`) -> queued `intake_unresolved`.

Migration `os_0027` edited in place (new columns `note_actor`, `report_csv`; unique index also covers `failed`).
Dry-run change: 110 Sindh programme rows (seat allocations whose number is only in the quote/note, with no cut-off) are now rejected `no_value`; the rest as before. With every list loaded: Programmes accepted 71, unconfirmed 116, queued 40, rejected 136 (no_value 110, institution_not_loaded 25, placeholder 1). Institutions and Facts unchanged.
Checks: tests/os 2524 passed, 1 skipped, 1 xfailed; legacy 2560 passed, 13 skipped; tach, freeze, alembic heads (one OS head), traceability OK.

## T6 final touches
- Undo restores a system's links from `chain[0].before["links"]` (the first `link` revision of the import); if a link that should stay has gone (an import that removed links), undo refuses instead of putting it back. Tests for both.
- `safe_cell` looks through leading whitespace (`" =1+1"`, `" \t-1"` are neutralised).
- Known gap, documented here and in the plan: an edit made outside the revisions (a direct change to a programme's columns or a registry row, which writes no revision) is not seen by the undo's conflict check and is overwritten by the restore. All store write paths write revisions, so it only concerns hand edits.
- Intake patterns: approved by the owner (spec §11.3, 2f741a2); PROPOSED marks removed from `format.yaml`, the plan and this report.
- Checks after these touches: tests/os 2529 passed, 1 skipped, 1 xfailed; tach, freeze, heads, traceability OK.
