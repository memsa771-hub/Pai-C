# Research batches 1–5 (v2)

The owner returned these five files on 2026-11-06 as the batches researched at the start of the connection plan (master spec §8.6, R-67 to R-69).

| File | Institutions | Programmes | Facts (high-stakes) |
|---|---|---|---|
| Batch 1, national | 354 | 0 | 65 (58) |
| Batch 2, Punjab | 79 | 96 | 79 (75) |
| Batch 3, Sindh | 72 | 146 | 46 (40) |
| Batch 4, KP, Balochistan, ICT, AJK, GB | 46 | 41 | 86 (78) |
| Batch 5, universities (bachelor's) | 19 | 13 | 60 (52) |

## What state the rows are in (checked 2026-11-06)

- Each file has a "Verification v2" sheet. It records Claude's own re-check of 2026-11-03, not a person's check.
- In every file, the person-checker columns are empty on every row: `checker1_result`, `checker1_name`, `checker2_approved`, `checker2_name` and the rest.
- Some facts were read by a model, from an image or from a search excerpt (WebFetch, image, search_excerpt). There are 109 such rows in all.

So, under R-68, the import loads these rows with Claude's status (`found`, `unconfirmed`, `conflict` and so on) as their trust level.

- No row becomes `verified` until checker 1 and checker 2 are filled in.
- Rows that a model read must be re-fetched, and their quote matched word for word, before they can become `confirmed`.
- Older column layouts (the batch 2 and 3 Programmes sheets) are mapped into the canonical layout by the import (R-67), not by hand.

The files are kept unchanged as the source record. The P2 import (R-68) reads them from here.

## v3 (returned by the owner on 2026-11-06)

The v3 files add an AI first check on every row. Its name is "Claude – check 1". Checker 2 is empty everywhere. That check reported many tool limits: its web-reading credits ran out, some pages were blocked, and some pages were JavaScript-rendered. These are its results:

| | correct | unclear | not_readable | wrong |
|---|---|---|---|---|
| Institutions (570) | 400 | 102 | 68 | 0 |
| Programmes (296) | 75 | 195 | 26 | 0 |
| Facts (336) | 92 | 199 | 44 | 1 |
| of which high-stakes facts (303) | 89 | 175 | 39 | 0 |

One programme row has no check result.

**Owner decision (chat, 2026-11-06).** The batches are verified by AI, and both developers have viewed them and are comfortable with them, so they are to be used. The import applies the decision this way:

- **Rows the check marked `correct`** are accepted. The record says `checked_by: "Claude – check 1"` and `accepted_by: owner, 2026-11-06`.
- **Rows marked `unclear` or `not_readable`** are loaded as `unconfirmed`. The student sees them labelled "not confirmed yet". The P2 re-fetch and quote match (R-68) promotes a row automatically when the official page still carries the exact quote.
- **The row marked `wrong`** goes to the review queue and is not used.

v3 is the version to import. v2 is kept as history.

## v4 (returned by the owner on 2026-11-07)

The v4 files fill both checker columns on every row. The names in the files are "Claude – check 1" and "Claude – check 2 (independent)", both dated 2026-11-07. So both checks are AI checks, not two people. `PAI-v4-rows-needing-review.csv` lists the 73 rows the checks did not settle.

**Owner decision (chat, 2026-11-07).** "They have been verified and the developers have reviewed it as well, so you can use them." This extends the v3 decision to check 2. The import applies it this way:

- **A row accepted by both checks** (check 1 `correct`, check 2 `yes`) is loaded as `verified`. The record keeps who checked it: `checker1: "Claude – check 1"`, `checker2: "Claude – check 2 (independent)"`, `accepted_by: owner, 2026-11-07`, plus a note that the developers reviewed it. The audit log never names a person who did not check the row.
- **A row check 1 marked `unclear` or `not_readable`, or with no result,** is loaded as `unconfirmed` and shown as "not confirmed yet". The R-68 re-fetch and quote match can promote it to `confirmed`.
- **A row check 1 marked `correct` but check 2 did not approve (`no`)** goes to the review queue and is not used until a checker settles it.
- **A row check 1 marked `wrong`** goes to the review queue. Its corrected value is also an AI reading, so it is not used until a checker approves it.

| | accepted by both | unconfirmed | review queue |
|---|---|---|---|
| Institutions (570) | 563 | 6 | 1 |
| Programmes (297 rows, 1 empty) | 281 | 2 | 14 |
| Facts (336) | 285 | 38 | 13 |
| of which high-stakes (303) | 257 | 35 | 11 |

Rows that cite a non-official copy (news, Google Drive, Facebook, Instagram, Wikipedia, a compromised board site) are never loaded as fact, whatever the checks say (R-72). These include the AJK Joint Admission Committee rows copied from educationinkarachi.net and ajkbise.net.

v4 is the version to import. v2 and v3 are kept as history.

## Programmes under an entity that is not an institution

A programme is placed only under an entity of registry kind `institution`. A Programmes row whose `inst_id` names an
entity (in the file, or already in the registry) of another kind (an `admission_system`, a board, a body; see `type_kinds` in format.yaml) is
rejected with reason `parent_not_institution`. The detail names the id and its kind. `validate` and `import` reject the
row alike, and the rest of the file loads. Facts rows on that programme are rejected `programme_not_loaded`, as for any
programme that is not loaded. A programme row whose institution the registry still refuses at load time is rejected
`registry_refused`, and the import goes on (the same backstop as for Institutions rows).

## A parent of the wrong kind (P2-T31)

An Institutions row's `parent_id` must name an entity of a kind the registry allows under the row's kind
(`ALLOWED_PARENTS` in `backend/app/os/registry/model.py`; for example a campus or an institution under an institution,
a calendar under an admission system, admission body, board or institution). Otherwise the row is rejected with reason
`parent_kind_not_allowed`; the detail names the row's kind, the parent's kind and the allowed kinds. The parent's kind
comes from its row in the same file, else from the registry. `validate` and `import` reject the row alike (before T31
the dry run accepted it and the import refused it as `registry_refused`). When the parent's kind is unknown the row is
not checked, as before, and its detail says "kind unknown, not checked"; the registry still refuses a wrong parent at
load time (`registry_refused`).

## Dry run of a reviewers-mode batch (P2-T31)

`validate` plans in the owner-accepted mode unless `--reviewers` is given. `validate --reviewers` plans as
`import --reviewers` would: the batch ref is `--batch-ref`, else the file's stem (as in the import). The dry run has no
review queue, so `--assume-attested REF [REF ...]` assumes, without checking, that those reviewer refs attested the
batch ref; the output says on its own line that the attestation is ASSUMED, NOT checked. With both checkers of a row
assumed, the row plans as an import with both refs attested would (`accepted`, `verified`); with only checker 1
assumed it is `confirmed` (one check), with only checker 2 or nobody `unconfirmed`. `--assume-attested` needs
`--reviewers`; it combines with `--assume-aliases-attested`. `import` has no assume flag: it reads attestations from the
review queue (`scripts/os_reviewers.py`).

## Alias files

A returned file is kept unchanged as the source record. When a file uses its own id for an entity that another batch already lists under a different id, the link between the two ids goes in an **alias file**. The returned file is never edited. An alias file is YAML that is supplied with the batch:

```yaml
file: <the returned file's name>
sha256: <sha256 of that returned file>
aliases:
  - from: <the id used inside the returned file>
    to: <the inst_id the entity was loaded under, as its own file writes it>
    evidence: {url: <official page>, quote: <text showing the two are the same entity>}
    check1: {result: correct, name: <reviewer ref>, date: <YYYY-MM-DD>}
    check2: {approved: yes, name: <another reviewer ref>, date: <YYYY-MM-DD>}
    required: true                      # optional (P2-T28); also allowed once at the top of the file for every alias
    target_evidence: {url: <the target's own official page>, quote: <text on it>}   # optional (P2-T28)
```

Both optional keys are new in P2-T28. Old alias files without them stay valid; the format has no version number to bump.

- **Bound to one file.** The import refuses an alias file whose `sha256` is not the sha256 of the file it is used with, and then nothing is imported. It also refuses a malformed alias file, and an id aliased twice.
- **Acceptance.** An alias is applied only when check 1 is `correct` and check 2 is `yes`, and both checkers have attested the alias file's own ref in the review queue. Checker 2 must not be checker 1. The ref is `aliases-<sha256 of the alias file>`, so it covers that exact file. This holds whatever mode the batch rows import in. The owner-accepted AI check names do not accept an alias: those names cover the rows checked on 2026-11-07, not later checks. An alias that is not accepted is ignored. The rows then behave exactly as they would without the alias file.
- **What it does.** An Institutions row whose `inst_id` is an applied alias loads no entity. If its `source_url` is not the URL of a loaded official list, it loads nothing at all (`aliased`), as before. Where `Programmes.inst_id`, `Facts.entity_id` or `Institutions.parent_id` equals an applied alias, it is replaced by the target before any other check. The target must be an Institutions-sheet entity that is planned in the same file or already in the registry. A Facts alias never resolves to a programme.
- **Membership rows (P2-T28).** An Institutions row whose `inst_id` is an applied alias and whose `source_url` is an official list URL is a line of that list naming the target. It adds the list to the target, so the list counts for gate 6. It never loads a second entity and never changes the target's name, type, source, quote or domains. The rules:
  - The row goes through the usual status and check rules. An `accepted` or `unconfirmed` row adds the list at that level. A queued or skipped row adds nothing. A queued row (check 1 `wrong`, check 2 `no`, or `not_readable`) opens a review item (`import_dispute` or `collect`) with the alias id as its subject, like any queued row.
  - The target must be an `institution` or `campus`: planned in the same file (in any order) or already in the registry, and `active` (not closed, merged or renamed: a list never lands on a predecessor). Otherwise the row is rejected (`alias_target_not_loaded`).
  - The row's `type` must give the target's kind (`alias_kind_conflict`).
  - An empty `region` takes the target's region. A different region is rejected (`region_conflicts_with_alias`). The list must serve the target's region (`region_conflicts_with_list`).
  - The allow-list check uses the target's region and the families of all of the target's lists, the new one included.
  - If the target already names every list of the row, nothing is added and the row is `aliased`, as before. Exception (fix round 1): when the stored `list_evidence` of such a list is weaker than this row's level (unconfirmed < confirmed < verified), the row is `alias_membership` and its evidence replaces the weaker entry (`evidence upgraded` in the detail), with one `change` revision and nothing else moved. If the allow-list or a re-fetch then leaves the row no stronger than the stored entry, nothing is written.
  - Re-fetch: for a membership row the reason stays `alias_membership`. Its level reason (for example `quote_not_found` or `quote_matched_on_refetch`) is the second part of the detail. An unclear row whose quote matches on re-fetch is promoted to `confirmed`, like any row.
  - A second row of the file that adds the same list to the same target is rejected (`duplicate_membership`).
  - A loaded membership row is reported as `alias_membership`. Its detail names the target and the lists it adds, then the level reason (for example `source_not_on_allow_list`).
  - The import calls `RegistryStore.add_lists`, which writes one `change` revision. Only `list_ids` and `attrs` change. `attrs.list_evidence[<list id>]` keeps the line's evidence: url, quote, date, read method, level, the row's id, the checks and the alias. Undo by import id restores the entity as it was. `validate` plans these rows exactly as the import does. Give `--institutions-from` when the target comes from another file.
  - Known limits:
    - **Lists without evidence.** A list that the entity got from its own row (not from a list line of an alias) has no `list_evidence` entry. Its evidence is the entity's own source, quote and provenance, and a later entity row overwrites those (`record`). A list line for such a list stays `aliased` and adds no entry. Adding one would change the plan of rows the earlier tests pin as `aliased`.
    - **First evidence wins**, except for the upgrade above. A line of the same or a lower level never replaces a stored entry. The older entries stay in the revisions.
    - **validate with two files.** `--institutions-from` reads only the entity rows of the other file, not its membership rows. If file 1 adds list B to T through an alias line and file 2 has another line on B for T, validate says `alias_membership` for file 2, while the import after file 1 says `aliased`.
- **Required aliases (P2-T28).** With `required: true`, the file's id must never load as an entity of its own. If such an alias is not accepted, its `Aliases` row is rejected (`alias_required_not_accepted`), and so is every Institutions, Programmes and Facts row naming the id (`inst_id`, `parent_id`, `entity_id`). Without `required`, an alias that is not accepted is ignored as before, and its row may load as a new, duplicate entity. `target_evidence` (the target's own page) is kept with the alias in provenance.
- **Report reasons.** The import report has an `Aliases` sheet with one row per alias: `alias_applied` (accepted) or `alias_not_accepted` (skipped, with the reason). An aliased Institutions row is skipped with reason `aliased`, and its detail is the target. A row whose alias target is not loaded is rejected with reason `alias_target_not_loaded`.
- **Record.** Each row loaded through an alias records the alias in its provenance: from, to, the evidence, both checkers, and the alias file's name and sha256. The import log (`os_imports.aliases`, migration os_0034) keeps every alias file used and the aliases it applied. Undo by import id works unchanged. The §11.3 re-fetch waiver still applies, because the returned file's sha256 does not change.
- **Use.** Pass alias files with `--aliases FILE` (repeatable) on `scripts/os_import_batch.py validate` or `import`. `validate` has no review queue, so `--assume-aliases-attested` shows the plan as if the alias checkers had attested. Aliases are command-line only: the admin upload in the API does not take alias files. The API's import record does show the `aliases` it used.

## v6 seat re-entry (local research, 2026-11-13)

`PAI-Research-Batch3-Sindh-v6-seats-reentry.csv` re-enters 34 of the 37 v5 seat rows that had no value. Their quotes
hold more than one number because each table splits one programme by seat category (Merit vs UEAP, CEAP,
self-finance, overseas); the value entered is the open/general merit figure, with `seat_category: open_merit` written
explicitly (not empty), so a category subset is never shown as a total. Check 1 and an independent check 2 (own
download, page images where the text layer shifts cells) agree on all 34 values and column headers
(`-check1.csv`, `-check2.csv`; the full check records are in `docs/research/lists/checks/`). Held for review:
SD-PRG-142 and SD-PRG-146 (the quote does not hold the row's figure; re-quote or re-scope), SD-PRG-144 (237 Karachi
District inside the 238 open-merit cell that adds one reserved seat). UEAP/CEAP/self-finance seats are not entered.

`PAI-Research-Batch3-Sindh-v6-seats.xlsx` is built from these files with `scripts/os_values_sheet.py` (mapping
`-v6-seats.mapping.yaml`; command and input sha256 in its "Derived from" sheet): 34 rows, check 1 `correct` and
check 2 `yes` on each.

### Checker names are reviewer refs (2026-11-14)

In the reviewers mode a checker name must be the `--ref` of a reviewer registered with `scripts/os_reviewers.py` who
attested the batch (or alias file) ref; a ref is lower-case letters, digits, `_`, `.`, `-`. The alias files and the
two seats workbooks first carried display names ("Claude local - check 1", "Claude research – seats check 1", ...),
which can never be refs, so those checks could not count in a real import. They now carry refs, with no other
change: `claude-local-check-1` / `claude-local-check-2` (alias files; check records in `docs/research/lists/checks/`
keep the display names "Claude local - check 1" / "Claude local - check 2 (independent)"),
`claude-research-seats-check-1` / `-2` (v5 seats) and `claude-research-v6-seats-check-1` / `-2` (v6 seats). Editing an
alias file changes its sha256 and so its attest ref.

## Allow-list family per row, and the dry run with an allow-list (P2-T19, 2026-11-14)

- **How the family is chosen.** An allow-list file is per region and family, so the import judges a row's source
  against (row region, family). The families tried are the `family` of every official list the row's entity is on
  (`docs/research/lists/*.yaml`; the registry keeps it as the list's `attrs.family`). An Institutions row uses the lists
  the import gives it: the lists the entity already names, then its own. A Programmes row, and a Facts row on an
  entity or on a programme, uses the lists (and region) of the entity it hangs on, planned in the same file or stored;
  a programme's facts use its institution. Aliases are resolved first. The source passes when its host is listed for
  the row's region and any of those families; the row's provenance records the scope that accepted it
  (`allow_list_scope: {region, family}`). When the entity is on no list with a family (a body, a board, a test, a
  calendar), `--family` is used; with no `--family` the family is `''`, which no region file matches. The detail of a
  `source_not_on_allow_list` row names the scopes tried. Since P2-T21 a body is judged against every family of the run
  (next section); an institution keeps this rule.
- **Dry run with an allow-list.** `validate FILE --country PK --lists ../docs/research/lists --allow-list DIR` loads the
  allow-list YAML files in DIR (`load_allowlist`, no database) and judges every source as the import does against the
  same entries, including the one-body-one-domain rule (R-71) of those files. `--lists` is needed for the families.
  The files carry no database state: a domain marked suspect in the database (monitoring, a person) is refused by
  the import but not by the dry run, and the output says so. Without `--allow-list` the output says that the
  allow-list was not checked.

## The allow-list family of a body (P2-T21, 2026-11-14)

- **Decision.** A controller decision under the owner's delegation of 2026-11-14, after the T19 and T20 real-data runs
  left 211 rows `source_not_on_allow_list`, almost all of them rows of bodies or facts on bodies.
- **The rule.** A body is an entity of one of the kinds that serve a whole region: regulator, board, admission_body,
  admission_system and entry_test (the registry's `SERVES_A_REGION`, a positive list, so a kind added later is not a
  body by default). When a body is on no list with a family, its source is judged against every family the
  run knows from its official lists: the families of the loaded lists (`--lists` for `validate`, the registry lists'
  `attrs.family` for the import), the `--family` given first, then the others sorted. The source passes when its host
  is listed for (row region, f) for any of them. This holds for the body's Institutions row, for Facts on the body
  (planned in the file or stored; the kind comes from the file, else the registry), and for the families a row is
  re-fetched under (`allow_list_families`). Aliases are resolved first.
- **Why.** The allow-list entries were researched and checked per region and family for the domains these bodies cite.
  A body serves the whole region, not one programme family. The family split keeps institutions' programme facts
  scoped, and that does not change.
- **What does not change.** Every other kind keeps the P2-T19 rule: the families of its lists, else `--family`. That
  is an institution, a campus, a calendar (an institution's own admission calendar and its dates stay scoped to the
  run's family), a seat category and an official list, and so is an entity of unknown kind. The region must still match exactly, the host must be on an
  active entry, the R-71 suspect rule still holds, and the re-fetch still asks the allow-list before any fetch.
- **Provenance.** `allow_list_scope` records the accepting scope, as before. `family_basis` says why those families
  were tried: `lists` (the entity's lists), `body_any` (a body, every family of the run) or `run` (`--family`).
- **Validate and import.** Both read the run's families from the official lists: `validate` from the `--lists`
  files, the import from every official list in the registry. They agree while the registry holds the same lists.

## Allow-lists in the repo (P2-T20, 2026-11-14)

- **Where they are.** `backend/app/os/knowledge/sources/lists/<region>-<family>.yaml`: 16 files (7 regions and
  `national`, each `bachelor` and `intermediate`), 63 entries (56 from round a, 2 from round b, 5 from the W12 round,
  below). The worker
  loads them into `os_source_domains` at start.
- **Where they came from.** The W13 allow-list review of 2026-11-14. Check 1 (`claude-allowlist-check-1`) drafted one
  entry per proven host, each with the official page that names the domain (HEC recognised-university profile pages,
  the federal and provincial government and department pages, the IBCC forum-members page). Check 2
  (`claude-allowlist-check-2`) fetched every proof page again on its own and approved 56 of the 57 entries. Owner
  ruling 2026-11-14: for allow-list files, both AI checks are enough review. Each entry's `reviewed_by` names both
  checks; `evidence` is check 1's link text and href, `check2_evidence` is check 2's. Check 2 changed no domain, tier
  or `list_ref`. `body_ref` is `''` until the bodies are in the registry.
- **Round b (P2-T21, 2026-11-14).** Check 1b (`claude-allowlist-check-1b`) proved 3 of the 7 hosts left out above;
  check 2b (`claude-allowlist-check-2b`) re-fetched every proof page on its own and approved all 3. Both checks give the
  same host and tier for each, and the same region where check 2b names one (it lists regions and families only from
  the citing rows); `evidence` is check 1b's quote and `check2_evidence` check 2b's. Two of the three are listed:
  - `admission.hed.gkp.pk`, admission_body, khyber_pakhtunkhwa intermediate (placed as ocas.punjab.gov.pk). Proof:
    hed.gkp.pk links it ("OCAS KP Colleges"); hed.gkp.pk is its `list_ref`.
  - `etea.edu.pk`, admission_body, khyber_pakhtunkhwa bachelor. Proof: a KP-TEVTA PDF on kptevta.gov.pk names it; check
    2b also found hed.gkp.pk linking it. B5-F-035's entity (UNI-UETP, aliased to PK-UNI-083) is on hec-recognised-kp
    (bachelor).
  - `hed.gkp.pk` is proven by both checks as the domain of the KP Higher Education Department (regulator; proof:
    kpese.gov.pk, the KP Elementary & Secondary Education Department, links it), but it is **not listed on its own**
    (controller, T21 fix round 1): its families rest on check 1b alone (check 2b gave none, since no row cites the bare
    host and the department is on no official list), no row needs it, and a listed domain covers its subdomains, so an
    entry for it under bachelor would also list admission.hed.gkp.pk under bachelor. It stays the proof page
    (`list_ref`) of admission.hed.gkp.pk. Add it when a row cites it and both checks give its families.
  - Still left out: hed.ajk.gov.pk, jac.ajk.gov.pk, www.imcgf72.edu.pk, gcwg.punjab.gov.pk.
- **W12 round (2026-11-15).** Check 1 (`claude-w12-allow-check-1`) and an independent check 2
  (`claude-w12-allow-check-2`) re-fetched every page; only what both agree on is added (5 entries). `reviewed_by`
  names both; `evidence` is check 1's quote, `check2_evidence` check 2's, `notes` the region basis.
  - `pmdc.pk`, regulator, bachelor of `azad_jammu_and_kashmir`, `balochistan`, `sindh` and
    `islamabad_capital_territory` (it was only in `national` and `punjab`). Proof (`list_ref`): the HEC Accreditation
    Councils page links it. Region basis: rows of the PMDC colleges-with-hospitals PDF whose address states the region
    (for example '165. ... Thatta, Sindh, Pakistan.'). Check 1's quote of the page's `<h1>` was not verbatim; the
    evidence keeps only the verbatim link, and `check2_evidence` has check 2's corrected quote.
  - Not `khyber_pakhtunkhwa` or `gilgit_baltistan`: no PDF row states that province (addresses give only cities such
    as Peshawar; 'Khyber' is only in college names), and no row names Gilgit-Baltistan at all. Add them only with a
    sourced city-to-region basis.
  - `eadmissions.fde.gov.pk`, admission_body, `islamabad_capital_territory` intermediate (HSSC admissions). Proof:
    fde.gov.pk (Federal Directorate of Education) links it. Tiered like the other admission portals.
  - `pmdc-colleges-with-hospitals` in `docs/research/lists/national.yaml` now has `family: bachelor` (H3 data): the
    Sindh and Punjab bachelor walkthroughs name it as the denominator for MBBS/BDS colleges.
  - Left out again: `hed.ajk.gov.pk`. ajk.gov.pk still carries hidden spam (a Replica Rolex `<h1>` on the home page);
    its spam-free helplines page is on the same compromised site, so it is not independent proof, and no independent
    official page names it. `magenta-sheep-235554.hostingersite.com`: fde.gov.pk's 'Admissions' box links it, but it
    is a Hostinger staging host (HTTP 500), never listable. `ajkbise.net`: its home page now has hidden 'slot gacor'
    links (check 2), so it stays out.
- **Left out.**
  - `hed.ajk.gov.pk` (AJK, intermediate): check 2 marked it unclear. Its only proof page, ajk.gov.pk, carried
    injected spam on 2026-11-14. Owner question open.
  - The hosts check 1 could not prove: admission.hed.gkp.pk, etea.edu.pk, jac.ajk.gov.pk, www.imcgf72.edu.pk and
    gcwg.punjab.gov.pk (no independent official page names them; check 2's retry found none either). Round b (above)
    later proved admission.hed.gkp.pk and etea.edu.pk.
  - ajkbise.net: named by the IBCC forum-members page, but its homepage still carried injected gambling links on
    2026-11-14 (R-71). It stays out until a person confirms it is clean.
  - Never listable: educationinkarachi.net, unioncouncil.com.pk, drive.google.com, en.wikipedia.org, facebook.com,
    instagram.com.

## Making a list workbook from two extractions (P2-T29, 2026-11-15)

A list batch (all the rows of one official list) is built with `backend/scripts/os_list_sheet.py`, not typed by hand.

- **The two-extraction rule.** Every row comes from two independent extractions of the same downloaded document: E1
  and E2, made with two different methods (for example two different parsers). A row is written only when both
  extractions have it and agree on it. Nothing is parsed from the web by the tool and nothing is invented: it only
  combines the two CSVs and the list's own data.
- **What the tool enforces, and what it does not.** It refuses:
  - one file given twice;
  - two files with the same sha256 (a copy is not a second extraction), unless `--identical-extractions REASON` is
    given, and the reason is recorded;
  - the same method label twice (`--e1-method`, `--e2-method`, both recorded).

  It cannot see who made a file. That the two extractions were run by two agents that shared no files (W12) is the
  process rule; the method labels and the sha256s in "Derived from" are what an auditor checks it against.
- **Inputs.**
  - `--lists ../docs/research/lists --list <list id> --country PK`: the list's url, region, family, institution_type,
    row_count and count_confirmed come from the H3 list file.
  - `--e1 E1.csv --e2 E2.csv`: columns `key`, `name`, `quote`, `doc_sha256` (the sha256 of the document read, 64 hex
    characters), and optionally `city` and `page`. `--e1-method TEXT --e2-method TEXT`: how each was made.
  - `--mapping MAP.yaml` (data):
    - `id_prefix`: inst_id = prefix + key. It is a new, stable id, never a batch 1-5 id.
    - `type`, which must be the list's `institution_type` and a type of kind institution or campus in format.yaml;
      or `type_column`, for a per-section type. Its values must be spelled exactly as format.yaml spells them, and
      the rows per type are recorded.
    - `region: list` (the list file's region), or `region: column` with `region_column`.
    - optional `city_column`.
    - `read_method`: it must map to `fetch` in format.yaml, for example "curl + pdftotext (PDF text layer)".
    - `retrieved`: the day the document was downloaded, not after a checker date.
  - `--checker1 REF DATE --checker2 REF DATE`: two different reviewer refs. `--out OUT.xlsx`, and `--force` to
    overwrite an existing output.
- **Refused (exit 2), with nothing written:**
  - the two extractions name different documents (doc_sha256);
  - either extraction's row count is not the list's row_count. `--allow-count-mismatch` is accepted only when the
    list's count is not confirmed, and its use is recorded in the "Derived from" sheet;
  - a read_method that does not map to `fetch`;
  - a mapping type that is not the list's;
  - an existing OUT or held file without `--force`.

  With `--force`, old outputs are removed first, so a refused run leaves none behind.
- **Matching.** Rows are matched by key. Name and quote (and the mapped type, region and city columns) are compared
  after normalising: casefold, whitespace collapsed, quotes and dashes unified. The normalising is for the comparison
  only: the cells written are E1's verbatim text.
- **Written rows.**
  - `source_url` is exactly the list URL, so the import puts the row on the list.
  - `retrieved` and `read_method` come from the mapping. `claude_status` is `found`.
  - check 1 is `correct` and check 2 is `yes`, with the two refs and dates.
  - `checker_note` holds both documents' sha256.
- **Held rows.** These go to `OUT.held.csv` (next to OUT, with the reason and both readings) and are not written:
  - a row the two extractions disagree on, including a row read from different documents;
  - a row in one extraction only;
  - a key twice in one extraction;
  - a row with no key;
  - a row with an empty name or quote.

  A held row is settled with two checks and a new run, never guessed.
- **Provenance.** The "Derived from" sheet records:
  - the sha256 of the list file, E1, E2 and the mapping;
  - the two methods;
  - the list's type, and with `type_column` the rows per type;
  - the checkers, any override and the command.

  Formula-like cells are neutralised in the workbook and in the held CSV.
- **Validate.** `python -m scripts.os_import_batch validate OUT.xlsx --country PK --lists ../docs/research/lists`
  plans every written row onto the list. Without `--reviewers` the dry run plans in the owner-accepted mode, where
  reviewer refs are not checks, so the rows show as `unconfirmed`. Add `--reviewers --batch-ref REF --assume-attested
  E1REF E2REF` to see the reviewers-mode import with both refs attested (verified); see "Dry run of a reviewers-mode
  batch" above.
- **Types.** `public_college` and `private_college` (the H3 list types of college lists) are institution types in
  format.yaml.
