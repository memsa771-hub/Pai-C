# Dry-run validation of the v4 batches (2026-11-12)

Run with the T6 validator (`python -m scripts.os_import_batch validate FILE --country PK --lists docs/research/lists
--decision-ref "P2 spec §11.3"`, code of `pc/p2-t6-sheets`). A dry run: no database, nothing imported. The sha256 of
each v4 file matches the §11.3 waiver list in `app/os/knowledge/sheets/format.yaml`.

## Counts with the official lists on this branch

| File | Institutions accepted / rejected | Programmes accepted / queued / rejected | Facts accepted / unconfirmed / queued / rejected |
|---|---|---|---|
| Batch 1 national | 331 / 3 (19 skipped) | 0 / 0 / 1 | 27 / 1 / 9 / 5 (23 skipped) |
| Batch 2 Punjab | 3 / 75 | 0 / 2 / 160 | 63 / 6 / 9 / 1 |
| Batch 3 Sindh | 63 / 9 | 0 / 36 / 110 | 33 / 3 / 2 / 8 |
| Batch 4 KP, Bal, ICT, AJK, GB | 31 / 12 | 3 / 1 / 37 | 27 / 2 / 14 / 40 |
| Batch 5 universities | 0 / 18 | 0 / 1 / 12 | 0 / 0 / 2 / 58 |

## Why rows are rejected

- **`no_official_list` (Punjab 75, Sindh 9, Batch 4 10):** the institution's source is not on a loaded official list.
  With `--no-list-needed` (what if every list were loaded) these institutions are accepted: Punjab 78, Sindh 72,
  Batch 4 41. Most programme rejections follow from this (`institution_not_loaded`).
- **Sindh programmes, `no_value` (110):** 121 rows of the Programmes sheet are MBBS/BDS seat allocations
  (`Session 2026-27`) with an empty `cut_off_out_of_550`; the seat number is only in the quote. The re-entered seats are
  in `PAI-Research-Batch3-Sindh-v5-seats.csv` with check 1 and check 2, but that file is not in the T6 sheet format, so
  the import cannot read it yet. A mapping is needed (not done here; no values were typed by hand).
- **Batch 5:** 13 institutions have no quote (`no_quote`), 5 have a region outside the vocabulary (for example
  `ICT (multi-campus)`), so all its programmes and facts fail (`institution_not_loaded`, `entity_unknown`). Batch 5's
  universities are the HEC universities of batch 1 under other ids; the file needs a fix by the research lane.
- **Batch 4 facts `entity_unknown` (40), batch 1 `entity_not_single` (5):** facts that name an entity the file does
  not load, or several at once.

## Spike 1 answer keys: not made

The Spike 1 harness (`app/os/gate/spike1.py`) needs, per region, at least 5 distinct institutions whose facts are held at
`confirmed` or above. Every fact the validator accepts is about an admission body or system (`body:`, `sys:`, `board:`
refs, 1 to 4 per region), none about an institution. So no region can reach the sample from this data, and a key built
now would only score `missing`. Keys need institution-level facts and a checker who did not verify those rows (H6);
that is the people lane. `python -m scripts.os_spike1_rerun plan` refuses without a key, so there is no cost estimate
yet.
