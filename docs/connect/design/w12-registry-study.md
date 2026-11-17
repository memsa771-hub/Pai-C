# W12 design study: raising P2 gate 6 with list batches (Plan agent, 2026-11-14, commit 37e061d0)

Saved by the controller from the agent's report. The line refs are at commit 37e061d0.

## Key facts
- **Identity is the id only.** `eid = KIND_PREFIX[kind]:slug(inst_id)` (plan.py:402). There is no name, alias or
  domain matching anywhere. The `aliases` column is never filled.
- **Same id, second file.** `_load_institution` with `keep_lists=True` keeps and adds lists (store.py:186-187), but it
  overwrites every other column (store.py:175-180): name, type, source, quote, domains and attrs. This is FU-2.
- **Aliases add no lists.** An aliased Institutions row is skipped as `aliased` and adds no list
  (plan.py:347-349; test_list_union.py:148). This is FU-3. An alias that is not accepted falls back to loading a NEW
  entity, so a duplicate is created.
- **How a row joins a list.** A row joins a list only when its `source_url` equals the list URL exactly (plan.py:94-106).
  Only the kinds institution and campus get lists (plan.py:403-409). Body lists (IBCC forum 40, QABs 11, councils 15,
  HED Punjab boards 9) can never count.
- **Gate 6 "loaded".** It counts the registry rows whose list_ids contain the list, unconfirmed rows included
  (store.py:360-387). Closed or undone rows still count (FU-1). It counts memberships, not distinct entities.

## Planned tasks (renumbered by the controller; T24-T26 were already taken)
| # | Task | Kind | Size |
|---|---|---|---|
| T27 | FU-1: list progress ignores withdrawn rows. Tests: import then undo, re-import, reactivated. | code | S |
| T28 | Alias membership, plus `attrs.list_evidence`, plus `required` aliases. See the rules below. | code | M-L |
| T29 | The `scripts/os_list_sheet.py` builder (E1/E2 extraction CSVs to a T6 workbook, held.csv, Derived-from sheet), plus `public_college`/`private_college` in format.yaml type_kinds.institution | code | M |
| D-BIEK | 355 rows. E1 is stdlib html.parser; E2 is a different parser. Aliases against batch 3 SECCAP (about 14). | data | M |
| D-PUNJAB | 797 rows over 9 PDFs. E1 is `pdftotext -layout`; E2 is `-bbox-layout` or pdfplumber. GRW 132 and MUL 70 have no serials, so check their counts first. | data | M-L |
| D-ALLOW | Add pmdc.pk to the other regions' bachelor files. Add eadmissions.fde.gov.pk to ICT intermediate. Retry a clean proof of hed.ajk.gov.pk. Add `family: bachelor` to PMDC in national.yaml. | data | S-M |
| D-PMDC | 190 rows. The PDF has two interleaved columns; crop the left column. More than 80 aliases are expected. The region source must be inherited from the alias target, or the address must state a province, or a sourced district table (two checks) must give it; otherwise the row is held. Never use `national` for a college. | data | L |
| D-AJK | 177 rows, from HTML tables. hed.ajk.gov.pk is not on the allow-list, so these rows stay unconfirmed but still count. | data | S |
| T30 (opt) | Body-kind list membership (SERVES_A_REGION plus regulator), then the small lists: UHS, FDE, IBCC, councils. | code+data | S-M |
| W4 | Re-run on a fresh DB, then measure gate 6 per region. | controller | S |

### T28 rules
1. An Institutions row whose inst_id is an applied alias AND whose source_url is a list URL becomes a membership row
   (`alias_membership`).
2. The target must be planned in this file or already stored, with kind institution or campus. Otherwise the row is
   rejected as `alias_target_not_loaded`.
3. The row kind must equal the target kind (`alias_kind_conflict`).
4. An empty region takes the target's region. A different region is rejected as `region_conflicts_with_alias`.
5. The list must serve the target's region.
6. The allow-list check uses the target's region and the union of the target's families.
7. A new method `RegistryStore.add_lists(entity_id, list_ids, evidence, ...)` appends lists under a lock, merges
   `attrs.list_evidence[list_id]`, writes one `change` revision and touches no other column. Undo restores it.
8. Two identical memberships in one file: the second is rejected as `duplicate_membership`.
9. The alias file gets an optional `required: true`. A required alias that is not accepted is rejected as
   `alias_required_not_accepted`, so no duplicate is created.
10. Optional `target_evidence: {url, quote}`.
11. Aliased rows that are not on a list behave as today.
12. validate equals import.

## Extraction rules (never invent data)
- Download with curl. Parse in Docker Python or with pdftotext. Use two methods, run by two agents that share no
  files.
- WebFetch is only a count sanity check, because it is model-read and would leave rows unconfirmed.
- read_method must map to `fetch` (for example "curl + pdftotext (PDF text layer)").
- Names are kept verbatim. Type comes from the list or its section; region comes from the list.
- Disagreements are held, never guessed. A count mismatch against row_count is fixed in H3 with two checks first.
- Ids are new and stable: list prefix plus the printed serial, or the position if there is no serial. Never reuse a
  batch 1-5 id.
- Rows of doubtful identity are held.

## Expected gate 6
- After BIEK, Punjab, PMDC and AJK: about 2205/2435 = 90.6%.
- With UHS and FDE: about 96.8%.
- With T30 and the bodies: about 2433.
