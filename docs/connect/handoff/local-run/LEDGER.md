# Local completion ledger — pai-connect (owner request 2026-11-13)

Owner rules for this run (chat 2026-11-13):
- No money: no paid model/API calls (OpenAI, Anthropic API, Tavily, Firecrawl credits). Web reading only through
  Claude Code's own WebFetch/WebSearch inside subagents. Spike 1 billed run NOT done (needs money).
- Nothing pushed to origin. Local branch `pai-connect` in C:\Users\MSA\Desktop\PAI-CORE\PAI-OS\pai-connect,
  push URLs disabled in that worktree. Task work on local branches `pc/p<N>-t<M>-<name>`, squash-merged locally.
- Everything committed in local git. Testing and merging with the owner afterwards.
- Docker Desktop must be started as administrator (F:\Docker\Desktop\Docker desktop.exe, -Verb RunAs).

Local CI: `.local-ci/ci.sh [checks|os|standalone|legacy|frontend|all]` (git archive HEAD, image pai-ci-py, postgres:16).

Start state: origin/pai-connect 1614f24 (#222 merged). No open PRs on origin.

## Work list
P2 finish
- [ ] W0 baseline: local CI on 1614f24
- [ ] W1 H3 official lists: UHS (Punjab medical/dental), SMBBMU (Sindh), KMU/others (batch 4) — sourced list entries
- [ ] W2 Batch 5 fix: 13 quotes, 5 regions, ids mapped to batch 1 HEC ids (new v5 file; v4 kept)
- [ ] W3 Sindh seats: v5 seats CSV -> T6 format mapping
- [ ] W4 dry run again; import into a local DB; registry % (gate 6)
- [ ] W5 H5 sample: 5 institutions per region, high-stakes fields, check 1 + check 2 (AI, independent)
- [ ] W6 H6 answer keys (checker who did not verify); Spike 1 plan (no billed run)
- [ ] W7 H7 one not_readable source collected through the queue with evidence (AI collect + AI approve)
- [ ] W8 gate 3: walkthrough citations check 1 / check 2 sign-off rows
- [ ] W9 calendar links (policy_links.yaml) once official rows imported
- [ ] W10 owner decisions: R-15, Germany CGPA, OCR engine, T2 parent-kind table — recommendations recorded
- [ ] W11 P2 handoff update; gate report
P3, P4, P5 (code part), P6 — spec, plan, tasks, gate each (after P2)

## Log
- 2026-11-13 setup: worktree pai-connect (local branch at 1614f24), push disabled per worktree. CI image pai-ci-py built.
- Dry run v4 x5 reproduced VALIDATION-2026-11-12 exactly (reports in .local-ci/work/v4-*.report).
- W1: 8 unlisted source URLs (95 institution rows): .local-ci/work/W1-unlisted.json. Research check 1 dispatched -> W1-check1.yaml.
- Ruling: Batch 5 fixed by an alias file applied at import (v4 file unchanged, waiver hash kept), not by an edited v5 copy — why: README keeps files as the source record and §11.3 waiver is by sha256 — cost if wrong: one importer feature to drop.
- T13 (import aliases) implementer dispatched on pc/p2-t13-aliases (worktree ../pai-connect-t13), base 1614f24.
- B5 alias research check 1 dispatched -> B5-aliases-check1.yaml.
- Baseline local CI running -> .local-ci/work/baseline-1614f24.log
- B5 aliases: check 1 and check 2 agree on 19/19 (B5-aliases-check1/2.yaml). Check 2 reported two files left by check 1 in the scratchpad (hec/*.html) that it did not use: independence held by its report, noted.
- Findings for the review queue (batch 1 v4, not edited): PK-UNI-242 MUET city Khairpur -> HEC profile says Jamshoro; PK-UNI-058 GIKI city Abbottabad -> HEC profile says Topi, District Swabi. TST-USAT aliases to the test body PK-TST-003 (no separate USAT row in batch 1).
- W1 check 1 done (W1-check1.yaml, docs in W1-docs/): 5 official lists (UHS x2 punjab, SMBBMU sindh, BMC balochistan, SZABMU ict), 3 not lists (KMU portal, IMCG policy page, KIU rules). 91/95 rows on their cited list. Private UHS tables and SZABMU notice were read from images (OCR/eye) -> model-read. 4 rows (KP-ADM-001, IC-ADM-001, GB-UNI-001, IC-COL-001) cite non-lists; their entities are on HEC / FDE lists.
- W1 check 2 dispatched (independent, own downloads) -> W1c2/W1-check2.yaml.
- T13 implementer DONE 4c4df209 (os_0034 migration added). Review dispatched.
- Finding for T13 fix round (controller): alias checks are judged in the batch's row mode; batch 5 rows import in owner-accepted mode, so new AI checks (not 2026-11-07 names) would be ignored. Fix: judge aliases by reviewer attestation (os_reviewers.py, ReviewQueue.attest) whatever the row mode.
- T13 review: PASS/APPROVE, 0 blocking, 2 should-fix, 5 minor + controller finding 0. Fix round 1 -> 92b871b0. Re-review: all addressed except #6 part (os_0034 in handoff migration list).
- Ruling: T13 #6 remainder (handoff migration list mentions os_0034 and os_imports.aliases) is done in W11 (P2 handoff update) — why: spec/handoff edits belong to the handoff task — cost if wrong: one line missing until W11.
- Operational: an alias applies only after two reviewers attest batch ref `aliases-<sha256 of alias file>`; any edit to the alias file needs new attestations.
- T13 pending: full local CI on pc/p2-t13-aliases, then squash-merge into local pai-connect.
- W1 check 2 done (W1c2/W1-check2.yaml): agrees with check 1 on all decisions, counts and cited rows. Dates: printed UHS notification dates used (2025-10-22, 2026-10-14) over PDF metadata (verified in text).
- T15 (data) pc/p2-t15-official-lists 34e97849: 5 list entries (punjab x2, sindh, balochistan, ict) + check records docs/research/lists/checks/. All 8 list files parse (parse_official_lists). Dry run: Punjab inst accepted 3->78, Sindh 63->72, batch 4 31->39 (3 no_official_list left: KP-ADM-001, GB-UNI-001, IC-COL-001; 1 non_official ajkbise expected). Reviewed by controller script (entries vs both checks).
- Note: IC-ADM-001 (SZABMU, publisher of its notice, not a table line) is now accepted because its source URL is the list URL. Flag for the handoff.
- Batch 4 leftovers check 1 dispatched (aliases KMU/KIU to batch 1, FDE list for IC-COL-001) -> B4/B4-check1.yaml.
- T14 implementer DONE 7400e135 (values sheet tool + PAI-Research-Batch3-Sindh-v5-seats.xlsx, 121 rows). Rulings:
  - translate check2 correct->yes kept — why: check2_result "correct" is an approval (the handoff counts 74 accepted by both) — cost if wrong: one mapping line.
  - The seats workbook imports in reviewers mode with registered AI reviewers "Claude research – seats check 1" / "... check 2 (independent)" attesting its batch ref — why: owner-accepted names belong to the 2026-11-07 checks only — cost if wrong: re-attest under other names.
  - No §11.3 waiver for it: model-read rows get the R-68 re-fetch quote match at import (free).
  - New work W3b: 37 seat rows without a re-entered value -> research re-entry from quote + two checks.
- B4 leftovers check 1 (B4/B4-check1.yaml): KP-ADM-001 -> PK-UNI-066 (KMU), GB-UNI-001 -> PK-UNI-021 (KIU, not board PK-BRD-033); FDE HSSC participating institutes list (82, eadmissions.fde.gov.pk/hssc/institutes) names IC-COL-001. Check 2 dispatched (B4c2/). T14 review dispatched.
- Note: a new list entry cannot fix IC-COL-001 itself (its row cites imcgf72, file unchanged); it needs a new batch row citing the FDE list (W12).
- Gate 6 scope measured: official lists hold 1866 institutions; batches hold 263 of them. Missing: Punjab public colleges 797, Sindh BIEK 355, PMDC 190, AJK 177, others. KP/national campus lists have row_count 0 (not counted yet).
- New W12: registry batches from official lists (new T6 workbooks per region, rows = list lines, source = list URL, two independent extractions as check 1/2, reviewers mode). First study how the registry identifies the same institution across lists (dedupe/aliases) before generating anything.
- B4 leftovers check 2 agrees (KMU PK-UNI-066, KIU PK-UNI-021; FDE HSSC list 82, stored URL /hssc/institutes, read at per=200).
- T15 61122c57: alias files Batch5 (19) and Batch4 (2) in docs/research/batches/*.aliases.yaml (T13 format; names "Claude local - check 1/2 (independent)"; attest batch ref aliases-<sha>), FDE list in ict.yaml (+ eadmissions.fde.gov.pk domain), check records in docs/research/lists/checks/.
- T14 review: PASS/APPROVE, 0/3/4. Rulings: #1 add validate --institutions-from (dry run only); #3 check-2 `unclear` rows are held (not written) for review — why: unclear is a doubt; loading on check 1 alone would hide it — cost if wrong: 10 rows load later. 37 no-value rows not written (-> W3b research). Fix round 1 sent.
- T16 brief written (list union on import + undo restores pre-existing entity); dispatch after T14 closes.
- T14 re-review: all addressed (957c250c). T13, T14, T15 ready; merge after baseline CI finishes (ci.sh archives HEAD per job). T16 dispatched.
- W3b S37 check 1 (S37/S37-check1.csv): 35 decided, 2 unclear (SD-PRG-142, SD-PRG-146: quote lacks the row's total). Two-number quotes are seat categories of one programme (Merit vs UEAP/CEAP/self-finance), not MBBS vs BDS.
- Ruling: for these rows `seats` = the open/general merit figure and seat_category is written explicitly `open_merit` (not empty) — why: matches the 74 accepted rows (merit-seat tables) and does not show a category subset as a total — cost if wrong: re-label 35 rows. UEAP/CEAP/self-finance seats are not entered (later rows if wanted). 142/146 held for re-quote.
- S37 check 2 dispatched (independent, same rule) -> S37c2/S37-check2.csv.
- S37 check 2: 34 rows agree with check 1 (value + header). Held: SD-PRG-142, -146 (quote lacks the row figure), -144 (237 vs 238 cell). T15 32809f2d: v6 seat re-entry CSV + check CSVs + README section; check records copied to docs/research/lists/checks/. Workbook from it: generate with the T14 tool after merge.
- Line endings verified: all committed blobs LF (gitattributes normalises); only working-copy README mixed, harmless.
- Baseline CI os job had failures (progress lines at 2%, 4%, 51%, 58%); classify when the run ends.
- 2026-11-13 new PC (user Maanz-AI, path C:\Users\Maanz-AI\Desktop\PAI-CORE\PAI-OS): worktrees repaired (git worktree repair), commits unchanged. Push disabled per worktree for BOTH remotes (origin, beta) incl. the main worktree `workspace`, which had no block before (dry-run only, nothing pushed). Docker Desktop and WSL not installed on this PC.
- W0 baseline classified from the full log (run had finished: os 28 failed / 2908 passed; standalone pass; legacy 22 failed = same as os; frontend 4 failed). All environment: (a) 15 schema hash pins + route contract: `git archive` emits CRLF because system gitconfig core.autocrlf=true (proved: 123 CR bytes vs 0 with autocrlf=false, blob 0); (b) scan/bakeoff/OCR tests: binary/fixture bytes altered the same way (PIL cannot identify image) — to re-confirm after fix; (c) 6 fixture_sites RemoteProtocolError — to re-check; (d) frontend 4: ci.sh archived only frontend/, tests read backend/app/*.json (ENOENT). ci.sh fixed: `git -c core.autocrlf=false archive`, frontend job archives backend/app too (backup ci.sh.bak-2026-11-13). Rerun needed once Docker runs.
- 2026-11-13 (after restart): WSL2 installed; Docker Desktop 4.99.0 installed via winget (C:\Program Files\Docker\Docker), started elevated, engine 29.9.3. Docker VM has ~4 GB RAM, host 7.9 GB: one full CI at a time. Image pai-ci-py rebuilt. git identity set in repo config (memsa771-hub, as the earlier commits).
- W0 baseline rerun with fixed ci.sh -> .local-ci/work/baseline2-1614f24.log (running).
- Merge trial: worktree ../pai-connect-merge, branch pc/p2-merge-trial = 1614f24 + squashes T13 8a764588, T14 771bd295, T15 19e0f559 (local pai-connect not moved yet: ci.sh archives HEAD per job while baseline runs). Conflicts: os_import_batch.py validate (both kept; aliases on FILE's context only — why: an alias file is bound to FILE's sha256 — cost if wrong: dry-run of OTHER ignores aliases); batches README (both sections kept). Independent merge review dispatched -> briefs/MERGE-T13-15-review.md.
- T16: WIP rebased onto 19e0f559 (now a58e78ec; original kept on pc/p2-t16-wip-orig-6f1d4e1). plan.py conflict: dedupe key (id, list url) then alias skip. Addendum briefs/T16-addendum-2026-11-13.md. Implementer dispatched (own docker net pai-t16).
- Merge review (briefs/MERGE-T13-15-review.md): PASS, 0 blocking / 0 should-fix. Minor F1: OTHER files in `--institutions-from` are planned without their own alias files (dry run only; no current workflow hits it, batch 1 has none). Minor F2: alias files load after the OTHER loop (refusal no longer first line). Gap: no test runs --aliases with --institutions-from -> run real dry runs (batch 5/4 with --aliases --assume-aliases-attested --institutions-from batch1) in the container in W4. F1/F2 -> small follow-up task after T16 (implementer + reviewer).
- T16 implementer DONE ab69c5e6 (base 19e0f559): union kept from WIP; fixed defect: a row withdrawn by undo kept its lists, so a re-import brought them back (now `WITHDRAWN` rows keep no lists). Tests: 11 union tests; registry+sheets+gate+coverage+api 294 passed/1 skipped; tach, traceability, alembic heads OK. Open questions (for review/owner): Q1 list progress counts withdrawn/closed rows (pre-existing); Q2 first list's source_url/quote replaced on the row, kept in revisions (R-76?); Q3 aliased row on another list adds nothing to that list's count; Q4 region change with a kept list fails the whole import. Independent review dispatched -> briefs/T16-review.md.
- T16 review (briefs/T16-review.md): FIX NEEDED, 0 blocking / 1 should-fix / 3 minor; reviewer reran 294 passed / 1 skipped. F1: region change vs kept regional list raises an uncaught RegistryError mid-import (rows before stay, rows after never load; dry run blind). F2 dup key (id, None) for unloaded list URLs. F3 rows with one id on two lists not checked for same kind/region. F4 withdrawn rule ignores status.
- Ruling F1: reject such a row in the plan with its own reason + per-row RegistryError backstop in _load_institution — why: §4.6 says the dry run shows every refusal and the import keeps going row by row — cost if wrong: one reason code to rename. Fix round 1 sent (F1-F4).
- Follow-ups (not T16): FU-1 list progress must not count withdrawn rows (gate (a) can go green from undone imports); whether genuinely closed rows count = owner decision (W10). FU-2 per-list evidence (source_url/quote per list) for R-76 — own task. FU-3 aliased row on another list could add that list to its target — later decision. FU-4 merge review F1/F2 (dry-run --institutions-from without OTHER's aliases; alias load order).
- T16 fix round 1 d8c93293: F1 plan reason region_conflicts_with_list + backstop registry_refused (import ends done; dependent programme/fact rows rejected); F2 key (id, list id or normalised URL); F3 duplicate_id_conflict; F4 closed+withdrawn. Union tests 17 (7 new fail on ab69c5e6); targeted set 301 passed / 1 skipped. Behaviour change: a row whose own regional list mismatches its region is now a plan rejection (was a crash). Re-review dispatched -> briefs/T16-rereview.md.
- T16 re-review (briefs/T16-rereview.md): PASS/APPROVE, F1-F4 fixed, 301 passed/1 skipped, new tests fail on ab69c5e6 (7). New: N1 should-fix — CLI validate gets no list regions (all lists national) so dry run accepts rows the import rejects; N2 minor — fact on a programme of a refused institution still written. Ruling: both in T16 scope (W4 relies on the CLI dry run; N2 writes a fact for a missing programme). Fix round 2 sent.
- T16 fix round 2 3080b3bb: N1 validate --lists reads list regions (also for --institutions-from); help says DB-stored lists are not seen. N2 fact on refused programme -> programme_not_loaded. Union tests 18; targeted 302 passed/1 skipped; new tests fail on d8c93293 (2). Re-review 2 dispatched.
- T16 re-review 2: PASS/APPROVE (302 passed/1 skipped). Minor for later FU-5: --institutions-from dry run checks only the last row's list when OTHER has one entity on two lists (dry run only). T16 squashed onto pc/p2-merge-trial: 61791e20 (tree == T16 branch). Next: full CI on merge trial after baseline, then move local pai-connect.
- W0 DONE. Baseline rerun (baseline2-1614f24.log, fixed ci.sh): checks OK; os 14 failed/2922 passed; standalone 51 passed; legacy 8 failed; frontend 602/602 passed. Remaining 14 = scan/bakeoff (8) + scan_gateway via fixture_sites (6): python:3.12-slim has no fonts, scan_fixtures.text_png returns None (fixture server then disconnects). Fix: Dockerfile.py adds fonts-dejavu-core fonts-freefont-ttf (backup .bak-2026-11-13), image rebuilt. Rerun of test_p2_scan, test_p2_bakeoff, test_p2_scan_gateway + all scan_fixtures users: 20 passed, 4 skipped (tesseract, docling, real OCR engine, Urdu font+raqm — absent in the image). Conclusion: 1614f24 green locally; every earlier failure was environment.
- Full CI on pc/p2-merge-trial 61791e20 started -> .local-ci/work/ci-merge-61791e20.log
- W4 dry runs on merge trial 61791e20 (W4/dryrun-61791e20.out, m-*.report): Batch1 Institutions accepted 133 / rejected 201 region_conflicts_with_list (v4 baseline: 334 accepted). Cause: HEC recognised.aspx URL is shared by 7 list entries (national + 6 province-filtered); ctx.list_urls maps url -> ONE list (last file wins: sindh). Pre-existing (before T16 every HEC university would count under hec-recognised-sindh; gate-6 list numbers in this ledger may be wrong); T16 N1 exposed it. Batch2 78, Batch3 72 inst OK; Batch4 aliases 2 accepted, inst 38; Batch5 aliases 19 accepted (19 inst skipped aliased), facts 23 accepted (without aliases 0); v5 seats 74 programmes unconfirmed (as expected before import).
- Ruling: a row citing a URL shared by several lists is on the national list(s) among them AND the regional list(s) matching its region; neither -> region_conflicts_with_list — why: one page; the province list is a filter of it, both hold the institution — cost if wrong: HEC list progress counts only. T16 fix round 3 sent. Merge-trial CI stopped (rerun after fix).
- T16 fix round 3 8b2afca1: url -> all lists (CLI files + registry path); rule per ruling. Real Batch1 dry run: Institutions accepted 334 / rejected 0 / queued 1 / skipped 19 (= v4 baseline). Pre-T16 confirmed wrong: CLI put HEC universities on last file's list (sindh); DB import on the first HEC list loaded (a regional one would have failed the import part-way at the store's region check). Now 284 HEC universities on national + own region (AJK 8, Bal 12, GB 2, ICT 27, KP 47, Punjab 105, Sindh 83). Targeted 304 passed/1 skipped; 2 new tests fail on 3080b3bb. Re-review 3 dispatched.
- T16 re-review 3: PASS/APPROVE. Reviewer reran real Batch1 dry run: 334 accepted / 0 rejected; DB path vs CLI path on all real list files: 0 rows differ. HEC recognised.aspx = URL of 8 list entries (not 7). Targeted 304 passed/1 skipped. Notes: FU-6 hand-built plan contexts without list regions treat shared-URL lists as national (test_real_batches_dry_run only). FU-7 a DB that already holds a pre-T16 HEC import may have universities on a wrong regional list -> re-import gives region_conflicts_with_list; fresh local DB in W4 avoids it; note for the handoff (production import never happened? check).
- T16 re-squashed on pc/p2-merge-trial: 668d1bf8 (tree == T16 branch 8b2afca1); old squash kept on pc/p2-merge-trial-old-61791e20. Full CI on 668d1bf8 started -> work/ci-merge-668d1bf8.log
- W10 recommendations written (work/W10-owner-decisions.md; all four found in the docs): R-15 build now as a small P2 task (os_programmes.field; untagged programmes stay listed; strict-xfail test must pass) or move to P3 — owner choice; Germany CGPA -> germany_master v3 adds transcript (shown) + CGPA (stated) on the apply steps, source uni-assist S2 page (check 1 via WebFetch = summary, so check 2 with raw HTML dispatched -> W10-check2-uniassist.md); OCR: Tesseract for drafts only (6/10 < bar), no winner, Docling bake-off later, no paid OCR — record deviation from P2-D13; T2 parent table: confirm + allow board -> calendar (walkthroughs PI-09, GI-02). FU-1 closed-rows question listed for the owner, no recommendation. Owner decides all four (not acted on).
- W10 check 2 (work/W10-check2-uniassist.md): uni-assist transcript requirement confirmed for master's, but check 1's quote is from the bachelor's section; master's quote recorded; page has no CGPA/average. Correction appended to W10-owner-decisions.md: transcript need supported, CGPA need unsupported (drop or find a programme-level official source with two checks).

## 2026-11-14 — merge-trial CI green, local pai-connect fast-forwarded
- Full local CI on pc/p2-merge-trial 668d1bf8 (T13+T14+T15+T16 squashes): checks exit 0; os 3001 passed, 24 skipped,
  1 xfailed; standalone 51 passed; legacy 3953 passed, 1662 skipped; frontend 602/602. Log: work/ci-merge-668d1bf8.log.
- Local `pai-connect` fast-forwarded 1614f24 -> 668d1bf8 (nothing pushed). RESUME steps 1-3 done. Next: step 4 (v6 seats workbook).
- T17 (data) pc/p2-t17-v6-seats-sheet -> squash b4ac61ec on local pai-connect. v6 seats workbook (34 rows, both checks agree).
  Review 1 PASS. Finding by controller (W4 import): reviewers mode matches checker names against reviewer refs
  ([a-z0-9_.-]{2,64}); alias files and seats workbooks carried display names, so their checks could never count in a real
  import (dry run hid it via --assume-aliases-attested). Fixed: names are refs (claude-local-check-1/2,
  claude-research-seats-check-1/2, claude-research-v6-seats-check-1/2); README section. Review 2 finding: CRLF working copies
  (core.autocrlf=true) gave wrong 'Derived from' sha256s -> worktree pai-connect set core.autocrlf=false (worktree config)
  and all LF files re-checked out; workbooks rebuilt; re-review PASS. Ruling: the 2026-11-14 ledger line 55 names
  ("Claude research – seats check 1") are replaced by the refs above — why: refs are the only thing reviewers mode can match
  — cost if wrong: rename data again.
- Operational: every worktree used to build data must have core.autocrlf=false (else tool-recorded sha256s are CRLF hashes).
- W4 first local import (fresh DB pai-w4-pg on network pai-w4; driver/logs .local-ci/work/W4/w4_driver.py, w4_run.sh,
  w4_run.log, out/): lists 38 loaded; 6 AI reviewers registered + attested (distinct identities). Results:
  b1 Inst unconfirmed 334; b2 78; b3 72 (Programmes rejected 110 no_value = v4 rows without seats, expected); b4 REFUSED
  (whole file): P4-034..036 programmes under BL-ADM-001 (kind admission_system) -> RegistryError -> T18; b5 aliases 19
  accepted (attestation works); v5 seats 74 and v6 34 programmes pass the checks.
  NOTHING is above `unconfirmed`: reason source_not_on_allow_list. app/os/knowledge/sources/lists/ holds no allow-list
  YAML at all (T3 built the mechanism; no reviewed list was ever written). -> new W13: reviewed allow-list files per region
  and family (data: domains from the H3 list files + check 1/2), owner decides who is reviewed_by. Owner question.
- Gate 6 (registry %) first measured from a real local DB: see W4/out/progress.csv (before b4 import).
  Gate 6 (list memberships loaded / published, lists with a published count, batch 4 not yet in): 686 / 2435 = 28.2%.
  By region: AJK 8/186, Bal 16/16, GB 29/29, ICT 30/112, KP 47/47, national 284/541, Punjab 180/1057, Sindh 92/447.
  No published count: kp-hed-participating-colleges (0), hec-recognised-campuses (0), seccap-participating-colleges (60).
  These replace the earlier gate-6 list numbers (shared-URL bug, FU-7).
- OWNER RULING 2026-11-14 (W13): for allow-list files, an AI check 1 plus an independent AI check 2 is enough review
  ("ai ke review kafi hai"). reviewed_by names the two AI check refs.
- W13 plan: (a) data: allow-list files per region x family (families bachelor/intermediate, per walkthroughs), check 1
  dispatched (briefs/W13-check1-brief.md -> work/W13/check1/), then independent check 2. (b) code T19 (after T18, both
  touch plan.py): the import's allow-list scope uses ONE --family per batch (default ''), and a region list needs a
  family, so nothing in mixed batches 1-5 can ever match. Proposed: per-row family from the family of the official
  list(s) the row's entity is on (H3 data), else the batch --family. Implementer + reviewer.
- T18 implementer DONE 7081128e (pc/p2-t18-programme-parent-kind): plan rejects a programme under a non-institution
  (reason parent_not_institution); importer backstop turns a programme RegistryError into a rejected row
  (registry_refused) instead of failing the file. 5 new tests fail on 668d1bf8; 331 passed/1 skipped. Real Batch 4
  dry run: P4-034..036 rejected parent_not_institution, all else unchanged. Review dispatched.
- Data note (owner/research): P4-034..036 (Balochistan divisional-merit MBBS seats in other provinces) are filed under
  BL-ADM-001 (admission system); they need a real institution id or another model to load. No id guessed.
- W13 check 1 DONE (work/W13/check1/, summary.md): 16 region x family drafts, 41 domains proven (58 hosts, 12 not
  proven), load_allowlist OK; covers 776/777 source_not_on_allow_list rows once family scope works. AJK portal fetches
  showed spam/injected text (possible compromise). Check 2 (independent) dispatched -> work/W13/check2/.
- W13 check 2 DONE (work/W13/check2/check2.yaml, 57 records): 56 yes, 0 no, 1 unclear (hed.ajk.gov.pk: only proof page
  ajk.gov.pk carries live replica-watch spam). Inventory recomputed: same 58 hosts/1376 rows; W4 count corrected to 821
  source_not_on_allow_list rows (820 covered; B5-F-035 etea.edu.pk not). No not_proven host newly proven
  (hed.gkp.pk would unlock admission.hed.gkp.pk + etea.edu.pk if accepted as KP HED's domain). Compromised today:
  ajk.gov.pk (replica watches), ajkbise.net (gambling) -> keep ajkbise.net out. Tier views: NUST better admission_body.
  Owner questions: hed.ajk.gov.pk (accept with note or wait); hed.gkp.pk (no independent official page names it).
- Next: T18 review -> merge; T19 per-row family scope; then T20 data: allow-list files in
  app/os/knowledge/sources/lists/ from the 56 approved records (reviewed_by both check refs), then re-run W4.
- T18 review PASS/APPROVE (0 blocking/0 should-fix; minors: README wording fixed; theoretical orphan after a late
  link refusal -> FU-8; small simplifications). Squash-merged into local pai-connect.
- T19 dispatched (briefs/T19-brief.md, worktree pai-connect-t19 @84972b73): per-row family set from the row entity's
  official lists (attrs.family), fallback --family; plus `validate --allow-list DIR` so the dry run judges the
  allow-list like the import (today validate never checks it).
- T19 implementer DONE 7e045a1d (pc/p2-t19-allowlist-family-scope): per-row family set from the entity's official
  lists (file, then registry; aliases resolved; programme facts now take the institution's region), fallback --family;
  provenance.allow_list_scope; `validate --allow-list DIR` (YAML, R-71 suspect rule; says DB suspect state unknown;
  "allow-list: NOT checked" without flag). 7 new tests fail on 84972b73 (helpers shimmed, no assertion changed);
  targeted 362 passed/6 skipped; tach OK; full tests/os NOT completed (hung >1h) -> must run before merge.
  Real data with W13 drafts, no --family: still source_not_on_allow_list B1 77, B2 66, B3 36, B4 31, B5 1, v5 0, v6 0
  (211). Finding: bodies (PK-REG/BRD/TST, xx-ADM and their facts) are on no list -> no family; with --family
  bachelor 56 left, intermediate 165; only 22 fail under both (admission.hed.gkp.pk 11, imcgf72 10, etea 1).
  Owner decision needed: family for bodies. Also: ibcc.edu.pk listed national only, never matches provincial rows
  (exact region match); seats workbooks can't be judged by validate (owner-accepted only). Review dispatched.
- T19 review PASS (briefs/T19-review.md): 0 blocking; full tests/os 2903 passed/24 skipped/1 xfailed after re-running
  2 parallel-load timeouts (crash_during_pack_build, rehearsal_short; untouched code); tach OK; fail-before 7/7
  verified. Should-fix S1: --refetch still uses the single --family (Refetcher(fetcher, family)) -> re-fetched rows
  of another family drop to unconfirmed. Fix round 1 sent to implementer (use provenance.allow_list_scope).
  Note for W4: check stored lists keep attrs.family. Test-count gap vs merge CI (3001) to re-check in full CI.
- T19 fix round 1 DONE 9d134fdc: refetch uses provenance.allow_list_scope family, else entity list families
  (new provenance allow_list_families), else --family; new test fails on 7e045a1d; 414 passed/20 skipped; tach OK.
  Re-review dispatched.
- T19 re-review 1 PASS with R1-S1: real PageGateway caches a refusal by URL only, so the 2nd family never gets a
  real fetch (lowers rows only). Fix round 2 sent: filter families by ctx.official before fetching + real-gateway test.
- FU-9 (from T19 re-review R1-S2, pre-existing): research/pages.py returns a cache hit before checking the allow-list
  for the asked scope, so a page cached under one scope is served to another (blocked=None). Own task: implementer +
  reviewer. T19 round-2 filter closes it for the import path.
- T19 fix round 2 DONE ef47d612: _apply_refetch keeps only families the host is listed for (ctx.official) before any
  fetch; none -> refetch_blocked:not_official without a gateway call. New real-PageGateway test fails on 9d134fdc;
  9/9, wider 444 passed/20 skipped; tach OK. Re-review 2 dispatched.
- T19 re-review 2 PASS (R1-S1 closed; minor: DB-suspect host now reads refetch_blocked:not_official). Squash-merged
  into local pai-connect as 68010d0b (7 files, +508/-54).
- T20 dispatched (briefs/T20-brief.md, worktree pai-connect-t20 @68010d0b, branch pc/p2-t20-allowlist-data): allow-list
  files in app/os/knowledge/sources/lists/ from W13 check1 drafts, only check-2 `yes` (hed.ajk.gov.pk out); report the
  ibcc national-only effect (no provincial copies without a controller decision); validate --allow-list real-data run.
- T20 implementer DONE 7a9d4466: 16 files / 56 entries in app/os/knowledge/sources/lists/ (only check-2 yes;
  hed.ajk.gov.pk out; reviewed_by both refs; body_ref ''; evidence + check2_evidence kept). Code fix: SourceDomains.sync
  race (UniqueViolation when several workers sync at start; 6 test_crash failures) -> insert skips a row another sync
  inserted; new test fails before. Gate test that assumed an empty folder now uses an empty tmp folder for that step
  (no assertion changed). Full tests/os 3016 passed/24 skipped/1 xfailed; tach OK. Real data identical to T19
  (211 rows). IBCC finding: the real gap is body family, not national scope; no national fallback in spec; a fallback
  would lift 0 rows. Review dispatched.
- T20 review PASS (briefs/T20-review.md): data diff 0 problems (56/56, hed.ajk out), race fix correct, gate change
  legit; tests/os 3014 passed/2 failed (order-dependent; pass alone and in default order). Should-fix: worker startup
  leaves 56 os_source_domains rows -> later downgrade tests refuse os_0028 (test_document_store; test_pack_store's
  os_reviewers case pre-existing). Fix round 1 sent: truncate_os_tables before downgrades.
- Docker down (WSL "finishing an upgrade"); owner restarted it. Owner (away) delegated all open decisions to the
  controller: "build the best of it ... do it by yourself". Controller decisions 2026-11-14:
  (1) body family: a body row (kind != institution, no list family) is judged against every family of the loaded
      official lists (--family first if given); institutions unchanged -> T21 (briefs/T21-brief.md), after T20 merge.
  (2) hed.ajk.gov.pk: stays OUT (only proof page compromised); (3) hed.gkp.pk & other not_proven hosts: research
      round 2 (check1b, free tools only) + independent check2b before any listing; else stay out.
  (4) No-region rows (34 foreign-board ibcc, 6 wildcard) and P4-034..036: left as rejected/held; no data guessed.
- T20 fix round 1 resumed after Docker restart (stale t20-pg/t20-net removed).
- W13 check 1b DONE (work/W13/check1b/check1b.yaml): proven hed.gkp.pk (kpese.gov.pk "Related links"), admission.hed.gkp.pk
  (subdomain, linked by hed.gkp.pk), etea.edu.pk (kptevta.gov.pk PDF + hed.gkp.pk link). Not proven: hed.ajk.gov.pk
  (ajk.gov.pk still has Rolex spam), jac.ajk.gov.pk, www.imcgf72.edu.pk (fde.gov.pk prospectus link unreachable),
  gcwg.punjab.gov.pk. Independent check 2b dispatched -> work/W13/check2b/.
- W13 check 2b DONE (work/W13/check2b/check2b.yaml): yes x3, clean pages. hed.gkp.pk regulator (1 proof:
  kpese.gov.pk; .gkp.pk suffix), admission.hed.gkp.pk admission_body (KP-ADM-002, 11 rows, Batch4), etea.edu.pk
  admission_body (2 proofs; PK-TST-005 + B5-F-035 -> PK-UNI-083 bachelor). -> T20b data: add to KP files after T20 merge.
- T20 fix round 1 DONE 7bdfb8cf: 9 downgrade tests take the `clean` fixture (no assertion change; also fixes the old
  test_pack_store os_reviewers order failure). Repro order passes; full tests/os 3016 passed/24 skipped/1 xfailed
  (4 sequential chunks); tach OK. Re-review dispatched.
- T20 re-review 1 PASS (coverage of downgrade tests complete). Squash-merged into local pai-connect as 321cc3fd.
- T21 dispatched (briefs/T21-brief.md, worktree pai-connect-t21 @321cc3fd, branch pc/p2-t21-body-family): code = body
  rows judged against every list family; data = hed.gkp.pk, admission.hed.gkp.pk, etea.edu.pk into KP files
  (checks 1b + 2b).
- T21 implementer DONE: 886b5293 (family_choice(): lists / body_any / run; body = known kind outside NAMES_A_LIST;
  provenance.family_basis; 7 tests fail on base; targeted 622 passed/20 skipped; tach OK) + ccc90417 (data: hed.gkp.pk
  KP bachelor+intermediate, admission.hed.gkp.pk KP intermediate, etea.edu.pk KP bachelor; 56 -> 60 entries).
  Real data: source_not_on_allow_list 211 -> 22 (code) -> 10 (data); the 10 are www.imcgf72.edu.pk (unproven).
  Findings: PK-TST-005 is checker2_rejected (never reaches the allow-list); calendars count as bodies (to judge);
  hed.gkp.pk placement vs check 2b empty regions. Full tests/os not run. Review dispatched.
- T21 review PASS w/ 2 should-fix (briefs/T21-review.md); full tests/os 3023 passed/24 skipped/1 xfailed, 0 failed;
  tach OK; fail-before 7/7. S1: body_any given to every kind not in NAMES_A_LIST (incl. calendar, seat_category,
  official_list) -> controller: positive tuple {regulator, board, admission_body, admission_system, entry_test}.
  S2: bare hed.gkp.pk entries rest on one check's family and list admission.hed.gkp.pk under bachelor via subdomain
  -> controller: remove them. Fix round 1 sent. PK-TST-005 is checker2_rejected (data, not allow-list).
- T21 fix round 1 DONE e20aaef9: SERVES_A_REGION positive tuple (registry/model.py); calendar test fails on
  ccc90417; bare hed.gkp.pk removed (58 entries). Real data unchanged (10 imcgf72 rows); targeted 623 passed/20
  skipped; tach OK. Re-review dispatched.
- T21 re-review 1 PASS. Squash-merged into local pai-connect as 37e061d0. Allow-list: 58 entries. Dry run: only 10 rows
  (www.imcgf72.edu.pk, IC-ADM-002 + B4-F-043..051) remain source_not_on_allow_list (from 821 at W4).
- W4 re-run 2026-11-14 on 37e061d0, fresh pai-w4-pg (old exited container replaced; previous outputs in W4/out-prev/),
  driver setup now also syncs the allow-list (load_allow_lists: 58). All 7 imports exit 0, Batch4 now imports.
  verified/both_checks: B1 361, B2 186, B3 111, B4 94, B5 55 = 807 (before: 0, all capped unconfirmed).
  Remaining unconfirmed: B2 no_quote 116, conflict 3, unclear 3; B3 unclear 2, conflict 1; B4 source_not_on_allow_list
  10 (imcgf72); B5 unclear 1, no_quote 1. Seats v5 74 / v6 34: unconfirmed `refetch_not_run` (reviewers mode needs
  --refetch = live page fetch through the app; not run: outbound calls need owner approval per CLAUDE.md).
  Gate 6 unchanged 686/2435 = 28.2% (list memberships; needs W12 registry batches, not the allow-list).
- Full local CI on 37e061d0 started -> .local-ci/work/ci-37e061d0.log
- T22 (FU-9) dispatched: briefs/T22-brief.md, worktree pai-connect-fu9 @37e061d0, branch pc/p2-t22-page-cache-scope.
- T22 implementer DONE 2d92c4fa (knowledge/research/pages.py): with a guard, allow-list checked for the asked scope
  before any cache lookup; not_official refusals no longer stored (no migration); cached redirect to an unlisted target
  refused. No-guard path unchanged. 6 new tests (5 fail on base; no-guard one is a regression guard); targeted 518
  passed/22 skipped; tach OK. Open (schema needed): cached render sub-request hosts; not_readable:render per URL.
  Review dispatched.
- T22 review PASS (briefs/T22-review.md): all cache paths closed under a guard (3 probes); no-guard unchanged; fail-
  before 5/6 verified; 623 passed/22 skipped; tach OK. S1 docs: Slice 2 spec §6 still says not_official is logged in
  os_pages -> fix round 1 (docs). Follow-ups FU-10: cached render sub-request hosts + not_readable:render per URL
  (schema needed; low risk); M2 integrity check judged with first caller's domains.
- T22 fix round 1 DONE 8d732d6d (docs only: dated notes in Slice 2 spec §6 and P2 spec §4.2; traceability OK). Controller checked the diff (docs-only S1, exactly as asked). Merge waits for the running CI (ci.sh archives HEAD per job).
- T23 (W11 handoff update) dispatched: briefs/T23-brief.md, worktree pai-connect-t23 @8d732d6d (T22 head), docs only.
- 2026-11-14 OWNER: "paisa lagana ka ilawa baki sara kam kar lo, proper engineering puri karo; testing mai ham paisa
  laga lai ga" -> do all non-paid engineering (rest of P2, then P3-P6); paid/billed runs wait for owner testing.
- Session restart: ci.sh orchestrator died; os job container still running (slow test, alive) -> output captured
  to work/ci-37e061d0-os.log; standalone/legacy/frontend jobs to re-run after. T23 resumed. W12 design study
  dispatched (Plan agent, read-only).
- T23 writer DONE d215b98e (p2-handoff.md +90/-1; W4 numbers recounted from CSVs: ledger line omitted B1 conflict 1, B4 conflict 2, B4 unclear 2; traceability OK). Review dispatched.
- W10 controller decisions (owner delegation 2026-11-14; for owner to confirm at sign-off): #1 R-15 build in P2 (T24);
  #2 Germany v3 with transcript (shown) + CGPA (stated), quotes word-for-word by 2 checks, student sentences left for
  the owner's reading (T25); #3 OCR: Tesseract draft-only, no paid OCR, deviation from P2-D13 recorded (docs);
  #4 parent table confirmed + board -> calendar (T26).
- T26 dispatched (briefs/T26-brief.md, worktree pai-connect-t26 @37e061d0).
- T23 review PASS w/ 2 should-fix (v5 seats 121 -> 74 rows; T22 not yet merged) + minors M1-M5 -> fix round 1 sent.
- T23 fix round 1 DONE 1f4a3a95 (S1 74 rows, S2 T22 not merged, M1-M5); controller verified the docs diff. T23 ready
  to merge after T22.
- W12 design study DONE -> work/W12-study.md. Identity = id only; same id overwrites columns (FU-2); aliases add no
  lists (FU-3). Plan: T27 FU-1 progress, T28 alias membership + list_evidence + required aliases, T29 os_list_sheet
  builder; data D-BIEK 355, D-PUNJAB 797, D-ALLOW, D-PMDC 190, D-AJK 177; opt T30 body membership. Expected gate 6
  ~90.6% after the 4 lists.
- PC/Docker went down again (session restart); Docker restarted elevated. The CI os run on 37e061d0 was lost at ~47%
  (no failure seen up to there). T26 (uncommitted work kept), T28, T29 resumed.
- T22 squash-merged as bde1c4c5; T23 handoff squash-merged as c8e12d3b (T22 hash filled in).
- 2026-11-15: PC restarted again (Docker down; RunAs UAC cancelled while the owner is away). A normal Docker Desktop
  launch works on this PC. RESUME.md rewritten for the current state. T26, T28, T29 resumed with "commit WIP often".
  T24/T25 briefs + worktrees ready (base c8e12d3b), held until fewer agents run.
- T26 implementer DONE eb28cf0b (board added to ALLOWED_PARENTS[calendar]; 2 tests fail on base; 73 registry/calendar + 210 sheets passed; tach OK; note: plan does not check parent kinds; roll-up follows admits links). Review dispatched.
- T29 implementer DONE e3f336da (scripts/os_list_sheet.py, public/private_college types, README, 16 tests; 314 passed/1 skipped targeted; tach OK). Open: validate shows list rows unconfirmed (owner-accepted mode); 6 choices incl. identical E1/E2 bytes accepted. Review dispatched.
- T26 review APPROVE (briefs/T26-review.md; fail-before verified; 93 + 210 passed; tach OK). Squash-merged as 0363d87d.
  FU-11: the import plan checks a parent's existence but not its kind for Institutions rows (plan.py:415-419), so the
  dry run accepts a wrong parent that the import refuses (pre-existing) -> plan-side parent_kind_not_allowed + tests.
  Owner question: a board's calendar never counts toward an institution's coverage (only admission_system has admits).
- T29 review APPROVE WITH CHANGES (briefs/T29-review.md; 311 passed/1 skipped; fail-before verified). S1 refuse
  identical E1/E2 (sha) unless --identical-extractions REASON; S2 list institution_type never checked -> refuse a
  mismatching mapping type. Fix round 1 sent (with minors). FU-12: `validate --reviewers --assume-attested REF...`
  so a reviewers-mode batch dry run shows accepted rows (precedent --assume-aliases-attested).
- D-BIEK extraction dispatched: E1 (html.parser) -> work/W12/BIEK/E1, E2 (other parser) -> work/W12/BIEK/E2 (brief briefs/D-BIEK-extract-brief.md); independent downloads.
- D-BIEK E1 DONE (work/W12/BIEK/E1): 181/181 + 174/174, serials clean; raw sha gov 778bebc9..., priv a6da0a0d...; mixed UTF-8/cp1252 bytes; 37 empty cities (only printed city kept); private 34 and 42 same name+address (possible duplicate line -> controller: hold 42 or alias it to 34 at build, never two entities).
- D-BIEK E2 DONE (lxml DOM; same raw sha256 as E1 for both pages). Controller pre-compare (casefold/whitespace/quote/dash normalised): 181/181 + 174/174 agree on name, quote and city; 0 disagreements. Next: alias candidates vs batch-3 SECCAP (needs T28), private 34/42 duplicate decision, then build with T29.
- T29 fix round 1 DONE c0de4bc9 (S1 identical refused unless --identical-extractions; S2 type check; required --e1/--e2-method; --force; narrowed catch; 22 new-file tests, 289 passed/1 skipped). Re-review dispatched.
- T28 implementer DONE a8c1a532 (alias_membership, 5 new reasons, RegistryStore.add_lists + attrs.list_evidence, required/target_evidence; 328 passed/1 skipped; 26/28 new tests fail on base, 2 are regression pins; renamed test_..._adds_that_list_to_the_target as the intended FU-3 change). Review dispatched.
- D-BIEK alias check 1 DONE (W12/BIEK/alias-check1.yaml): 93 candidates -> 13 same (gov 1,3-9,11,12,14,15,37 -> SD-COL-KQ*), 79 different, 1 unclear (gov 27 -> KQ2236 Campus-II). 4 same pairs rest on inferred shift / address mismatch (gov 4,6,7,12). BIEK internal: private 34/42 same; gov 95/181 and private 48/50 unclear. Check 2 dispatched.
- T29 re-review 1 APPROVE (22 + 289 passed/1 skipped; tach OK). Squash-merged as 2e9517fc. Minors R1-R3 noted; FU-12 (validate --reviewers --assume-attested) still open.
- D-BIEK alias check 2 DONE (W12/BIEK/alias-check2.yaml): agrees same on 11; disagrees on gov 6, gov 7 (area
  "Model Colony, Malir" vs district KARACHI KORANGI -> unclear) and gov 95/181 (says same; check 1 unclear). No new
  aliases found (40 extra pairs, all different).
  Controller ruling (both checks must say same): ALIAS 11 = gov 1->KQ2215, 3->KQ2172, 4->KQ2173, 5->KQ2193,
  8->KQ2167, 9->KQ2158, 11->KQ2207, 12->KQ2273, 14->KQ2194, 15->KQ2232, 37->KQ2339. Private 42 -> private 34 (same
  file target, both same). HELD (required alias, not accepted -> row rejected, no entity): gov 6, 7, 27, 181,
  private 50. Build after T28 merges.
- D-PUNJAB extraction dispatched (briefs/D-PUNJAB-extract-brief.md): E1 pdftotext -layout -> W12/PUNJAB/E1, E2 word coordinates -> W12/PUNJAB/E2; 9 division PDFs, 797 rows.
- T28 review APPROVE w/ 3 should-fix (tests for required alias on Programmes/parent_id; refetch overwrites membership reason / no promotion; first-wins evidence never refreshed) + minors. 328 passed/1 skipped; fail-before 26/28 verified. Fix round 1 sent.
- D-PUNJAB E2 DONE (W12/PUNJAB/E2): 9/9 lists match row_count (GRW 132 and MUL 70 now grid-backed; keys = position). pypdf content-stream walker (no poppler/pdfplumber available). Column order differs per PDF (BWP/DGK/FSD); quote joins cells in printed order. Waiting for E1.
- D-PUNJAB E1 DONE: counts 9/9 match, but E1's attribute columns drift in the text layer (each column a separate
  vertical run); quote unreliable. Names agree 794/797 (GRW 67, 71, 83 overlap text); cities agree on all 690 shared.
  Controller ruling (for owner to confirm): derive both extractions alike: quote = "<serial> | <name>" (name only for
  GRW/MUL), city only where both have one (derive.py). Tool built 794 rows, 3 held. Name check vs batches 1-5: no
  overlap. Data branch pc/p2-d1-w12-punjab-colleges commit b264a0f3 (9 workbooks + inputs + README). validate shows
  rows unconfirmed/check_unclear_or_missing (FU-12, validate cannot plan reviewers mode). Review dispatched.
- T24 implementer DONE 412b44e3: R-15 OS side (knowledge/fields.py reads excluded fields via StudentFacts each time;
  field_codes.yaml; replan proposal cancel_programme / support case when none left; programme list filters; empty field
  never filtered); old strict-xfail passes, marker removed; 10 new tests (8 fail on base); 766 passed/1 failed
  (phases) then fixed; R-15 built:true but phases stay [P1] (traceability ties to master §12; owner's spec).
  Open: pai_c/connect/places.py route builder not passing the student (Counsellor file, needs lead review) -> FU-13;
  no real programme has a field yet. Review dispatched.
- D-PUNJAB review PASS (all 794 names, 690 cities verified; derive.py reproducible; ids unique). README minors fixed. Squash-merged as 1b268d85.
- D-ALLOW check 1 dispatched (-> W12/ALLOW/check1.yaml): pmdc.pk per region (from PMDC PDF addresses), eadmissions.fde.gov.pk ICT-intermediate, hed.ajk.gov.pk clean-proof retry, PMDC list family bachelor basis.
- T28 fix round 1 DONE 45fe66d4 (required-alias tests; refetch level_reason + promotion; evidence upgrade via add_lists(upgrade); merged/renamed target rejected; concurrency test; 337 passed/1 skipped). Known limit -> FU-14: no list_evidence for a list the entity got from its own row (needs changing 2 pinned tests or a new evidence-only reason). Re-review dispatched.
- D-ALLOW check 1 DONE (W12/ALLOW/check1.yaml): pmdc.pk proven (HEC accreditation councils page); regions stated in PMDC addresses: AJK, Balochistan, Sindh (1 row), ICT; KP and GB not stated (need sourced district table). eadmissions.fde.gov.pk proven (fde.gov.pk link), tier TBD. hed.ajk.gov.pk: spam still on ajk.gov.pk; helplines page clean but same site -> keep off. PMDC family bachelor supported by walkthroughs. Check 2 dispatched.
- T28 re-review 1 APPROVE (337 passed/1 skipped; tach OK). Squash-merged as 2d22eab9. FU-14 (evidence for own-row lists)
  + minors N1-N3 (cap-cancelled upgrade marks list taken; report wording; trust rank defined twice) for a follow-up.
- D-ALLOW check 2 DONE (W12/ALLOW/check2.yaml), agrees with check 1 on all 4: pmdc.pk (regulator, bachelor) for AJK,
  Balochistan, Sindh, ICT (not KP/GB: no address states them); eadmissions.fde.gov.pk admission_body ICT
  intermediate; hed.ajk.gov.pk NO (spam persists, no independent page among 18 more sources); PMDC list family
  bachelor. Side findings: fde.gov.pk links a hostingersite.com staging portal (never add); ajkbise.net has hidden
  gambling links (stays out). -> D-ALLOW data commit (implementer + reviewer).
- T24 review: code approved but B1 blocking: requests.visible_programmes unfiltered (route_programmes, Replanner._suggestions swap, eligibility notes) -> swap could bring in an excluded field. S1 places.py (Counsellor lead, FU-13), S2 restored-field meaning (Counsellor lead). 705 passed; freeze OK; phases [P1] right. Fix round 1 sent (B1 + StudentFacts failure falls back to unfiltered + docstring).
- D-ALLOW data DONE (pc/p2-d2-w12-allowlist 7187e361+074d65ed): pmdc.pk regulator in AJK/Bal/Sindh/ICT bachelor; eadmissions.fde.gov.pk admission_body ICT intermediate; PMDC list family bachelor (national.yaml); 63 entries; 401 passed/1 skipped. Review dispatched.
- D-BIEK build dispatched (briefs/D-BIEK-build-brief.md, worktree pai-connect-d3 @2d22eab9): 2 workbooks SD-BIEK-GOV-/PVT-, alias files (11 accepted gov aliases, private 42->34; held gov 6,7,27,181, private 50 as required+unclear).
- D-BIEK build: tool refused (E1 and E2 CSVs byte-identical). Controller ruling (for owner to confirm): --identical-extractions allowed (independent downloads, same raw sha, two different parsers, same output spec, page-text hashes differ). Check-2 unclear on held aliases left empty (format allows only yes/approve/no/reject), verdict noted.
- D-BIEK build DONE (pc/p2-d3-w12-biek-colleges 03dd4d7c): gov 181 rows + private 174 rows; alias files (gov 15 aliases: 11 applied, 4 rejected; private 2: 1 applied, 1 rejected), all required. Dry run: gov 11 alias_membership / 4 alias_required_not_accepted / 166 new; private 1 aliased / 1 rejected / 172 new. Review dispatched.
- Combined check on merged head 2d22eab9 (T26+T29+T28 together): tests/os/sheets + registry 327 passed/1 skipped; tach OK. (ctl-pg/ctl-net left up for the next controller runs.)
- D-ALLOW review APPROVE (exactly 5 entries; quotes verbatim; 407 passed/1 skipped). Squash-merged as 781c464c. README nits (stray break; old hed.ajk bullet) left for the next README touch.
- D-PMDC extraction dispatched (briefs/D-PMDC-extract-brief.md): E1 x-cut -> W12/PMDC/E1, E2 other algorithm -> W12/PMDC/E2. T27 (FU-1) held until fewer agents run.
- D-BIEK review APPROVE (third parser agrees 355/355; aliases match both checks; dry run as expected). Squash-merged as 151e5459. Minors: E2 same strategy different library (independence = separate downloads + code); 'page-text hashes differ' is weak support; lowercase karachi capitalised in city.
- T27 (FU-1) dispatched (briefs/T27-brief.md, worktree pai-connect-t27 @151e5459).
- D-PMDC E1 DONE (W12/PMDC/E1): 190 rows, all checks pass; PDF sha 4193caa2...; 9 rows flagged (whole cell kept as name: 3,4,21,29,75,76,92,146,147); region-word rows: AJK 1,123,124; ICT 17,31,32,36,45,50,77,90,93,98,99,103,142,189 (+29,76 in name); Sindh 165; Balochistan 170-172. Waiting for E2.
- D-PMDC E2 DONE (clip-rectangle cells; same PDF sha). Compare: quote agrees 190/190, section 190/190, name differs on 11 (3,4,21,29,75,76,92,146,147,156,165: name/address boundary) -> held. Region: alias target region, else address province word (23 rows), else held (never national for a college). PMDC alias check 1 dispatched.
- D-PMDC alias check 1 DONE (W12/PMDC/alias-check1.yaml): 76/190 lines get a target (Punjab 66, Bal 4, Sindh 3, ICT 2, 1 'Punjab (federal)'); 6 unclear (104,141,145,163,164,166); city conflicts 18, 56 judged same; 68 lines with no candidate. Check 2 dispatched (told not to read pmdc-matches*.csv).
- D-PMDC alias check 2 DONE: agrees 120/122; 74 same agreed; keys 18, 56 -> unclear (city conflict). Held: 104,141,145,163,164,166,18,56 (required, not accepted). Region rule: region column only from a province word in the address (both extractions' quotes identical), alias rows inherit, rest empty -> rejected missing_region at import (no guessing). D-PMDC build dispatched (worktree pai-connect-d4).
- T27 implementer DONE 4bcc7577 (list progress counts only kept_lists; withdrawn rows out; closed/merged unchanged for owner; 3 fail on base + 4 pins; 402 passed/1 skipped; tach OK; list_progress now filters in Python). Review dispatched.
- D-PMDC build DONE (pc/p2-d4-w12-pmdc-colleges 0d7eb5b0): 179 rows written, 11 held; alias file 82 (74 accepted, 8 held). Controller confirms region from ADDRESS only (not remarks/names: avoids 7 wrong regions). Dry run: alias_membership 67, alias_required_not_accepted 8, missing_region 88, new 15 (ICT 12, AJK 3), alias_target_not_loaded 1 (155 -> IC-MED-02, upstream region 'Punjab (federal)'). Review dispatched. Later: a sourced district->province table (two checks) could place the 88.
- T24 fix round 1 DONE 0304ab36 (B1: visible_programmes excluded set in route list, eligibility suggestions, notes swaps, Replanner suggestions; StudentFacts failure -> unfiltered; 3 new tests; 808 passed; freeze OK). FU-13 places.py + S2 recorded in handoff. Re-review dispatched.
- D-PMDC review PASS (all 179 rows, all aliases verbatim, no traps, dry run exact). Squash-merged as a86de9f9. Notes: IC-MED-03 typed medical in batch 4 (dental school); 88 city-only rows wait for a sourced district table (FU-15).
- D-AJK extraction dispatched (briefs/D-AJK-extract-brief.md): 4 HED AJK HTML lists, 177 rows; E1 html.parser, E2 lxml/regex; injection check required (ajk.gov.pk compromised).
- D-AJK E2 DONE (W12/AJK/E2): 14/75/7/81 all match, serials clean; no injection on the 4 hed.ajk.gov.pk pages (only gmpg.org profile link + Google Maps embed off-site). Waiting for E1.
- D-AJK E1 DONE. Raw shas differ between E1/E2 only in Cloudflare's per-request data-cfemail footer attribute; with it blanked, all 4 pages are identical, and names/quotes agree 177/177. Controller ruling (owner to confirm): doc_sha256 = sha256 of the page with data-cfemail values blanked, same for both; raw shas kept in README. D-AJK build dispatched (worktree pai-connect-d5).
- T27 review APPROVE (402 passed/1 skipped; fail-before verified). Squash-merged as 903b3be1.
- T31 (FU-11 plan parent-kind check + FU-12 validate --reviewers --assume-attested) dispatched (briefs/T31-brief.md, worktree pai-connect-t31 @903b3be1).
- D-AJK build: tool refused (derived CSVs identical after the normalised doc hash). Controller ruling (owner to confirm): --identical-extractions allowed (independent downloads, different parsers, raw differs only in Cloudflare data-cfemail). Overlap check: 0 candidates against batches 1-5 + W12.
- D-AJK build DONE 71bc8d76: 4 workbooks, 177 rows, 0 held; dry run all unconfirmed (FU-12); rows will load source_not_on_allow_list but count for gate 6. Review dispatched.
- D-AJK review PASS (3rd parser 177/177; normalisation hides only the same footer email; no injection; no overlap). README minors fixed. Squash-merged as 0d81c0d2. W12 data lists done: Punjab 794, BIEK 355, PMDC 179, AJK 177.
- T31 implementer DONE 49990d25 (FU-11 parent_kind_not_allowed in plan; FU-12 validate --reviewers --assume-attested, ASSUMED line, import refuses flag; 13 tests, 10 fail on base; 394 passed/1 skipped). Real data with assumed refs: Punjab lhr 110 accepted; BIEK gov 177 accepted (166 both_checks + 11 alias_membership), 4 rejected. Deviation: checker-1-only assumed -> accepted/confirmed (same as import). Review dispatched.
- W4 re-run 2026-11-15 on 0d81c0d2 (fresh pai-w4-pg; first try failed only because pg was not ready for alembic;
  outputs W4/out, previous in out-2). All 23 imports exit 0; allow-list 63. W12 results: Punjab 794 verified;
  BIEK gov 166 verified + 11 alias_membership, 4 held-rejected; BIEK pvt 172 verified, 1 aliased, 1 rejected;
  PMDC 15 verified + 67 alias_membership, 8 alias_required_not_accepted, 88 missing_region; AJK 177 unconfirmed
  (source_not_on_allow_list).
  GATE 6: 2088/2435 = 85.7% (was 686 = 28.2%). By region: AJK 185/186, Bal 16/16, GB 29/29, ICT 30/112, KP 47/47,
  national 366/541, Punjab 974/1057, Sindh 441/447. Remaining: ICT (FDE HSSC list 82), national (PMDC 88
  missing_region + 11 held + 8 doubtful, other national lists), Punjab (UHS 2025-26/2026-27 lists, 3 GRW held).
- D-FDE extraction dispatched (briefs/D-FDE-extract-brief.md): ICT FDE HSSC list (82); E1 html.parser, E2 lxml/regex. IC-COL-001 (batch 4) will need an alias check.
- D-FDE E1+E2 DONE: 82/82 agree on name and quote (source per=200 page sha 20331e1e..., stored list url shows 50/page). Alias checks 1 and 2 dispatched in parallel (fully independent).
- D-FDE alias check 2 DONE: 1 same (key 78 = IC-COL-001, IMCG (PG) F-7/2), all others different; 81 new.
- D-FDE alias check 1 agrees: only 78 -> IC-COL-001. D-FDE build dispatched (worktree pai-connect-d6).
- T24 re-review 1 APPROVE (808 passed; freeze, traceability OK). R-15 built conditional on FU-13 before P2 sign-off (yaml comment), _check_programmes choice recorded. Squash-merged as a5341cd8.
- T31 review APPROVE (20 real-batch validate runs byte-identical base vs head; import refuses the flag; 394 passed).
  Squash-merged as 30d70d2b (handoff §4 conflict with T24 resolved, both kept). M1 -> FU-16: with --reviewers the --institutions-from file is also planned in reviewers mode
  (no effect on today's data). O1 (pre-existing): one-check non-high-stakes row gives confirmed, spec says verified
  -> owner/spec note.
- Full local CI on 30d70d2b started -> work/ci-30d70d2b.log (do not move pai-connect HEAD while it runs).
- D-FDE build: 82 rows; alias 78 -> IC-COL-001 cannot apply (IC-COL-001 rejected no_official_list in batch 4). Controller ruling (owner to confirm): no FDE alias; IC-FDECOL-78 loads as its own entity (no duplicate: IC-COL-001 never loads); identity recorded; FU-17: batch-4 alias IC-COL-001 -> IC-FDECOL-78 (two checks) so P4-038..041 load.
- T25 implementer DONE 313f1829 (germany_master.v3 = v2 + transcript shown + CGPA stated on 2 apply steps; S2 master's quote verbatim, sha 4ccf4a31... same as W10 check 2; row 6.21 on shipped v3; 11 new/moved tests fail on base; full tests/os 3289 passed/3 failed -> vocab test fixed (dotted keys), 2 crash tests pass alone). Open: CGPA ask citation (S2 has no CGPA sentence); vocab fix to confirm. Review + quote check 2 dispatched.
- D-FDE review APPROVE (3rd parser 82/82; ruling right; overlap only 78). M1 run.log added (-f). M2 cosmetic. Merge waits for the running CI.
- FU-15 (PMDC 88 missing_region) check 1 dispatched: official district->province table (PBS), exact district-name match only -> work/FU15/check1.yaml.
- FU-15 check 1 DONE (FU15/check1.yaml): PBS 2023 census Table 1 PDFs (5 files, 135 districts); 43/88 exact district matches (KP 28, Punjab 7, Sindh 7, Bal 1). Unmatched 45: Karachi 32 (printed as KARACHI DIVISION), Mirpurkhas 3 (space), Cantt 4, non-districts 8, AJK 1 (not in source). Controller rule (owner to confirm): also match division names printed in a province file and space-free equality when unique; no Cantt/misspelling. Check 2 dispatched.
- FU-15 check 2 DONE (FU15/check2.yaml): same PBS shas; 165 units (135 districts, 30 divisions); 74/88 matched under the extended rule (Sindh 38, KP 28, Punjab 7, Bal 1); 14 unmatched (Cantt, non-districts, misspellings, AJK). Agrees on all 43 strict matches; 31 rule_extension rows (Karachi 28, Mirpurkhas 3) need check 1 under the extended rule -> sent.
- FU-15 check 1 extended DONE: agrees 74/88 (43 district + 28 Karachi division + 3 Mirpurkhas space-free); 14 unmatched. D-PMDC v2 (region from the PBS table) dispatched (worktree pai-connect-d7).
- T25 review APPROVE (quote check 2 verbatim, sha 4ccf4a31..., 2026-11-15; v3 = v2 + 2 needs; CGPA cites S2 with a no-requirement note; vocab fix legit; 11 fail on base; 377 passed/1 xfail). Owner to read the 3 sentences at sign-off. Merge waits for the running CI (with D-FDE).
- P3 start: route-family ADR (R-81) design dispatched (Plan agent, read-only); controller saves the draft for the owner's approval (gate 'ADR approved' is the owner's).
- D-PMDC v2 DONE (pc/p2-d7-pmdc-district-regions ecbcfe3d): 74 region cells filled from the PBS table; dry run 128 accepted / 28 unconfirmed (KP: pmdc.pk not on KP allow-list) / 23 rejected; missing_region 88 -> 14. Controller confirms district step scope = the 88 judged rows only. Follow-up D-ALLOW-KP: pmdc.pk for khyber_pakhtunkhwa-bachelor (two checks; region basis now the PBS district table). Review dispatched.
- P3 ADR-001 draft saved -> work/P3/adr-001-route-families-DRAFT.md (recommended option C: one generic family playbook compiled per place from the registry; D1-D13; tasks T0-T15; 5 owner questions). Key finding: imported programmes (route_key=registry) are visible to no route today (D4 fixes). T0 = owner approval; P3 code waits for it, but T1-T3/T8 are 'after T0'. Controller: get an independent review of the ADR before presenting.
- D-PMDC v2 review PASS (all 165 units re-parsed; exactly 74 region cells; 5 tampers stop derive.py). Minors: derive.py writes before all checks pass; README '97 with region' counts CSV rows (94 in workbook). Merge waits for CI (queue: T25, D-FDE, D-PMDC v2).
- D-ALLOW-KP (pmdc.pk for khyber_pakhtunkhwa-bachelor) checks 1 and 2 dispatched in parallel -> work/ALLOW-KP/.
- D-ALLOW-KP check 1: yes (HEC accreditation page link; 28/28 KP rows confirmed against the PBS KP PDF, sha 8924fb1b...).
- ADR-001 review: needs changes (work/P3/adr-001-review.md). Option C right, 25 citations OK, key findings true, no migration needed. Required: A release flag D14 (route would go live before the P3 gate); B full D4 caller list incl. counsellor intake adapter; C family source; D domicile; E walkthrough citation fixes; F all R-40 docs; G board from StudentFacts; H mode provisional until verified; I task deps; J text. Add Q6-Q8. Revision sent to the designer.
- D-ALLOW-KP check 2: yes (nhsrc.gov.pk link; 30 KP-district rows incl. held rows 3, 4). Entry added on pc/p2-d7 as 4ae1388f (64 entries). Review dispatched.
- ADR-001 revision 2 saved (work/P3/adr-001-route-families-DRAFT.md): corrections A-J applied (D14 release flag CONNECT_FAMILY_<FAMILY> off by default; D4 full caller list via programmes_of(); family from --family; domicile/R-13; citation fixes; D13 table; Q5 from StudentFacts; mode provisional until verified; task deps; T9 session term); Q6-Q9 added. Ready for the owner's approval (T0). P3 code waits for T0.
- D-ALLOW-KP review APPROVE (64 entries; quotes verbatim live; dry run: 28 KP rows unconfirmed -> accepted, nothing else). Rows 3, 4 are held rows (name disagreement) so their empty region is expected. Merge with PMDC v2 after CI.
- P3-T1 (playbook family schema + D14 flag) dispatched on ADR defaults (owner approval pending; local only). briefs/P3-T1-brief.md, worktree pai-connect-p3t1 @30d70d2b.
- P3-T1 implementer DONE 0be5ce93 (schema fields, SystemsNotResolved, D14 CONNECT_FAMILY_<FAMILY> via OsSettings, also gates self-serve list + builder start; 57 new tests, byte-for-byte snapshot at base; 647 + 175 passed). Review dispatched.
- P3-T1 review APPROVE w/ minors (snapshot byte-identical base vs head; all start points gated, start_plan backstop; 548 + 168 passed). Fix round 1 sent: gate request_new (research could cost money later), docs brace line, format-spec refusal.
- P3-T1 fix round 1 DONE deb160a1 (request_new gated 422, no research queued; docs; format-spec refusal; no-pin upgrade fix; 131 passed). Re-review dispatched. Gap tests (_has_plan bypass, _adopt flag-off) -> T10/T15.
- P3-T1 re-review 1 APPROVE (275 passed; freeze clean). Merge after CI, with T25, D-FDE, D-PMDC v2 + KP.
- FULL LOCAL CI on 30d70d2b DONE: alembic-heads OK, traceability OK; os 3123 passed / 1 failed / 24 skipped
  (test_crash_during_research: timeout by 0.05 s with 5 of 6 tasks done, under heavy parallel agent load; rerun alone
  in progress); standalone 51 passed; legacy 4004 passed / 1733 skipped; frontend 602/602.
- Merged after CI: T25 -> 4455a7bb, D-FDE -> f0d5ecd3, D-PMDC v2 + KP -> 74d4be51, P3-T1 -> f8a9f5cd (ADR approval
  pending; flag off). Risk checked next: P3-T1's compile snapshot (taken before germany v3 existed) vs T25.
- test_crash.py rerun alone on 30d70d2b: 7 passed -> the CI failure was a load timeout, not a defect. CI on 30d70d2b counts green.
- P3-T2, T3, T8 dispatched (briefs P3-T2/T3/T8-brief.md, base 0d86901c), on ADR defaults (owner approval pending).
- Merged-head check: P3-T1 snapshot failed only because germany v3 (T25) was new; regenerated at 74d4be51 and head -> byte-identical (e44a4bae...), committed 0d86901c. Other 149 tests passed; tach OK.
- 2026-11-15 session restart: P3-T2/T3/T8 had saved nothing; resumed. The P3-T1 snapshot-fix test rerun was lost (rerun later in the next CI).
- 2026-11-15 OWNER: "please implement the core engineering of this plan real quick, aj ... phir pai os pai c ko aik
  jagah merge kar ka check karna hai". Controller plan: P3 core code (T2, T3, T8 running; T6, T7 now; T4 after T3;
  T5 after T4), each with implementer + reviewer; then local merge pai-connect -> local pai-merge (--no-ff merge
  commit, never pushed; owner's explicit instruction overrides P0-D14's "only when the whole plan is complete") and
  run the full app + full CI. P4-P6 are not in today's scope (told the owner).
- P3-T6 (region-aware intakes) and P3-T7 (R-39 events) dispatched (base 0d86901c).
- 2026-11-15 OWNER: 'mjy p6 tak sab kam chahiye ... the core engineering of it'. Scope = generic code for P4, P5 (code), P6 proven by fictional data/tests; real research data, approvals, paid runs excluded (told the owner). P4-P6 core design dispatched (Plan agent) -> to save as work/P4-P6/design-DRAFT.md.
- P4-P6 core design saved -> work/P4-P6/design-DRAFT.md. Findings: gate (b) vacuous (no first_live ever set); 'national' as global constant; family flag global; MeritCheck ignores system-owned formulas. Tasks P4-T0..T14, P5-T1..T7, P6-T1..T6. Startable now: P5-T1, P5-T2, P5-T5, P6-T1, P6-T3, P4-T2 (P3-T1 only).
- P5-T2 + P6-T3 (honest gate (b) with launch.yaml + route facts in the gate) dispatched (worktree pai-connect-p5t2). P6-T1 and P4-T2 wait for P3-T2/T3 merges (same files).
