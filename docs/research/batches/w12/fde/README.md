# W12 FDE HSSC participating colleges: list workbook (2026-11-15, LOCAL)

This is the ICT list `fde-hssc-participating-colleges` in docs/research/lists/ict.yaml. It has 82 lines (row_count 82,
"Showing 1–82 of 82"). The stored list url is https://eadmissions.fde.gov.pk/hssc/institutes.

It is loaded as the list workbook `docs/research/batches/PAI-Research-W12-fde-hssc-participating-colleges.xlsx`. The
workbook was built with `backend/scripts/os_list_sheet.py` (P2-T29) from two independent extractions:
- id_prefix `IC-FDECOL-`. No cell of any other workbook in docs/research/batches uses it.
- type public_college, region `list` (islamabad_capital_territory).

No alias file is used (see below).

## The document read
- Every row's `source_url` is the stored list url, https://eadmissions.fde.gov.pk/hssc/institutes, exactly, so the
  import puts each row on the list.
- That default view shows only 50 rows a page ("Showing 1–50 of 82"). The document both extractions read is the
  **per=200 view of the same list**: https://eadmissions.fde.gov.pk/hssc/institutes.php?per=200&page=1, which shows
  "Showing 1–82 of 82".
  - Its sha256 is 20331e1e0dfd9e17e48b68224d0318f5626ee1186a652b7e2c0d243b6e418f81 (59456 bytes). This is the
    `doc_sha256` of every CSV row and is in each workbook row's `checker_note`.
  - Each extraction downloaded it twice, and got byte-identical bodies. E1 also got the same bytes from
    `/hssc/institutes?per=200&page=1`.
- **Cross-check of the default view.** Both extractions also downloaded the default view (`/hssc/institutes`, sha256
  cb1a2305...be5d) and its page 2 (`?page=2`, sha256 3236a0c3...4a45). Each found that pages 1 + 2 (50 + 32 rows) are
  identical to the per=200 page in S#, name and address. E1's paged CSV is `E1/crosscheck/crosscheck_paged.csv`.
- `raw/` holds the three pages (E1's downloads; E2's have the same sha256): `per200.html`, `default.html` and
  `default_p2.html`.

## The two extractions
Each extraction was made by a different agent from its own curl download, on 2026-11-15 at about 01:21 UTC.

| | Method label | How |
|---|---|---|
| E1 (`E1/`) | python stdlib html.parser | `scripts/extract_htmlparser.py`: each `<tr>` of `table.c-table` tbody |
| E2 (`E2/`) | lxml XPath table rows | `scripts/extract_lxml.py`: `//table[1]/tbody/tr` |

Both follow the same output spec:
- key = S#; name = the `<strong>` text of the College cell;
- quote = `"<S#> | <name>"`, plus `" | <address>"` where the cell prints the muted address line (52 of 82 rows);
- city and page are empty, because the table has no city column.

Each extraction's `notes.md` describes its checks. They agree on name and quote for 82/82 rows. The CSVs are not
byte-identical (E1 ee306f69..., CRLF line ends; E2 b361f7d0..., LF), so `--identical-extractions` was not needed. The
files are kept byte-identical to the agents' originals.

## Build
Run `build.sh` from `backend/`, in `docker run --rm pai-ci-py`. It uses:
- `mapping.yaml`, with read_method "curl + HTML text strip" and retrieved 2026-11-15;
- checkers `claude-w12-fde-e1` / `claude-w12-fde-e2`, both dated 2026-11-15.

Result: 82 rows written (public_college) and 0 held. The `.held.csv` file has only the header.

The xlsx bytes are not reproducible (zip timestamps).

## Alias checks, and why no alias is used (controller ruling 2026-11-15, for the owner to confirm)
Two independent alias checks compared all 82 lines with every batch 1-5 v4 and W12 workbook row:
- `checks/alias-check1.yaml` (ref `claude-w12-fde-alias-check-1`);
- `checks/alias-check2.yaml` (ref `claude-w12-fde-alias-check-2`).

Both agree that exactly one line names an institution already in a batch:
- **IC-FDECOL-78** ("ISLAMABAD MODEL COLLEGE FOR GIRLS (POSTGRADUATE)F-7/2,ISLAMABAD") is the same institution as
  **IC-COL-001** in batch 4 v4 ("Islamabad Model College for Girls (PG) F-7/2").
- Every other candidate pair is `different` in both checks. Check 1's summary has 197 pairs: 1 same and 196 different.

No alias file is used:
- **IC-COL-001 is never loaded.** Batch 4 rejects it `no_official_list`: its source is the college's own page
  (https://www.imcgf72.edu.pk/Admissin_Policy.aspx), not a list url. It is not in the registry.
- **What an alias would do.** An alias 78 -> IC-COL-001 would make line 78 a membership row on a target that is not
  loaded. The row would then be rejected `alias_target_not_loaded`, and the college would load from neither file.
- **What happens instead.** Line 78 is the official list line for the college, so it loads as its own entity,
  IC-FDECOL-78. This makes no duplicate, because IC-COL-001 is not in the registry.

`make_aliases.py` is kept as the record of the alias that was built from the two checks and then withdrawn. Its output
is not committed and must not be imported.

### Follow-up FU-17
- **The alias.** Add a **batch-4 alias IC-COL-001 -> IC-FDECOL-78**, so that IC-COL-001's programmes P4-038..041 can
  load. They are rejected `institution_not_loaded` today.
- **Its checks.** The alias needs its own two checks.
- **Its binding.** It must be bound to batch 4 v4, in the batch 4 alias file or a new one for that file.

## Dry run (validate, 2026-11-15)
The command was `validate` with:
- `--country PK --lists ../docs/research/lists --allow-list app/os/knowledge/sources/lists`;
- `--institutions-from` batch 1 v4 and batch 4 v4;
- no alias file.

Results:
- **Institutions:** 82 planned, 0 rejected, 0 skipped.
- All 82 are `unconfirmed` (`check_unclear_or_missing`). validate runs in owner-accepted mode, which does not know the
  W12 checker refs (FU-12).
- No row is capped by the allow-list.

## Before the import
- Register `claude-w12-fde-e1` and `claude-w12-fde-e2` (`backend/scripts/os_reviewers.py`). Each must attest the
  workbook's batch ref.
- Do not pass an FDE alias file.
