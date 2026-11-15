# W12 PMDC medical and dental colleges: list workbook and alias file (2026-11-15, LOCAL)

This is the PMDC list `pmdc-colleges-with-hospitals` in docs/research/lists/national.yaml: 190 lines (row_count 190,
serials 1-190 in four sections), from the PDF
https://pmdc.pk/Documents/Others/Recognised%20Institutes%20with%20attached%20Hospitals%20(Final%20List%20)%20%2007-11-2025%20for%20web%20-.pdf.

It is loaded as the list workbook `docs/research/batches/PAI-Research-W12-pmdc-colleges-with-hospitals.xlsx`, built with
`backend/scripts/os_list_sheet.py` (P2-T29) from two independent extractions. id_prefix `PK-PMDC-` (no existing id uses
it). An alias file sits next to it (`.aliases.yaml`).

## The two extractions
Each extraction was made by a different agent from its own curl download, made on 2026-11-15 at about 00:02 UTC. The
PDF sha256 is the same for both, 4193caa23be4cdf4374cbb41928a225faf8fb44e371133b022c4cd2261d460e1, and is in every CSV
row (`doc_sha256`) and in each workbook row's `checker_note`.

| | Method label | How |
|---|---|---|
| E1 | pypdf 7.1.0 fragment x-cut | text fragments with coordinates; left column cut at x < 292.0, rows grouped by serial |
| E2 | pypdf 7.1.0 clip-rectangle cells | each text chunk assigned to the PDF's own cell clip rectangle; only the institute cell read |

`source-extractions/E1/` and `source-extractions/E2/` hold the agents' CSVs, byte-identical to their originals
(5d274708... and e65bbaf7...), with each agent's `notes.md`. They agree on `quote` and `section` for 190/190 rows. `name`
differs on keys 3, 4, 21, 29, 75, 76, 92, 146, 147, 156 and 165 (where the name ends and the address starts). The tool
holds those 11 rows. They are not resolved here.

## Why the inputs in `E1/` and `E2/` are derived (controller rulings, for the owner to confirm)
`derive.py` adds two columns to each extraction alike, from that extraction's own cells. Nothing else is changed (key,
name, quote, page and doc_sha256 are copied verbatim):
- **type** (ruling 1): `section-types.yaml` maps the PMDC section to a format.yaml type of kind institution, spelled as
  batch 2 spells it: private_medical -> private_medical_college, private_dental -> private_dental_college,
  public_medical -> public_medical_college, public_dental -> public_dental_college.
- **region** (ruling 2): `region-words.yaml` maps the province or territory word printed in the row's address to a
  regions.yaml code: "AJ&K" -> azad_jammu_and_kashmir, "Islamabad" -> islamabad_capital_territory, "Sindh" -> sindh,
  "Baluchistan" -> balochistan.
  - The scanned text is the extraction's `address` cell, or its `name` cell where the address is empty (the
    extraction kept the whole cell as the name).
  - The bold remark "(Letter sent to M/o NHSR&C, Islamabad ...)" is in neither cell, so it never gives a region (rows
    13, 55, 70, 109, 188).
  - A word in the college name before the address is not used: 168 "Sindh Medical College ... Karachi." and 187 "Sindh
    Institute of Oral Health Sciences/ JSMU Karachi." get an empty region.
  - No region is taken from a city. 23 rows get a region, the same 23 rows as both agents' own region tables. E1 and E2
    agree on region for 190/190 rows.

The mapping (`mapping.yaml`) uses `type_column: type` and `region: column` with `region_column: region`. The list is
national, but a college is never given `national`. An empty region is written empty:
- an alias row inherits its target's region (T28 rule 4);
- any other row is rejected `missing_region` at import.

## Build
Run `build.sh` from `backend/`, in `docker run --rm pai-ci-py`.
- read_method: "curl + pypdf 7.1.0 (PDF text layer)". It maps to fetch, and neither extraction used pdftotext.
- retrieved: 2026-11-15.
- Checkers: `claude-w12-pmdc-e1` and `claude-w12-pmdc-e2`, both dated 2026-11-15.
- The CSVs differ, so `--identical-extractions` is not used. Both have 190 rows (row_count 190), so no override is
  needed.

Result:
- 179 rows written: 71 private_medical_college, 44 private_dental_college, 46 public_medical_college and 18
  public_dental_college.
- 11 rows held (`name_disagrees`; see the `.held.csv` file).

The xlsx bytes are not reproducible (zip timestamps). The alias file is bound to the committed workbook's sha256, so
rebuild the workbook only together with the alias file.

## Alias file
Run `make_aliases.py` from `backend/`. The verdicts come from `checks/alias-check1.yaml` (ref
`claude-w12-pmdc-alias-check-1`) and `checks/alias-check2.yaml` (ref `claude-w12-pmdc-alias-check-2`, independent),
both dated 2026-11-15. The script stops on any difference from the ruling.

**Accepted:** 74 aliases, the pairs both checks judge `same` for the same target.
- Targets: 64 batch 2 PB-MED-* (Punjab), 4 BL-MED-* (Balochistan), 3 SD-MED-* (Sindh), and 3 batch 4 IC-MED-*. Of
  those three, IC-MED-01 and -03 have region ICT, and IC-MED-02's region cell is "Punjab (federal)".
- Six of them (21, 75, 92, 146, 147, 156) are lines the workbook holds. Their evidence quote is the `quote` cell, which
  is the same in E1 and E2.

**Held:** 18, 56, 104, 141, 145, 163, 164 and 166 are required and not accepted, so their rows are rejected
`alias_required_not_accepted`.
- 18 -> PB-MED-054 and 56 -> PB-MED-048: check 1 says same, check 2 says unclear (the PMDC address and the batch city
  differ).
- 104 -> PB-MED-071 and 163 -> SD-MED-06: check 1 names no alias_target, so its only candidate is used.
- 141 -> PB-MED-004, 145 -> PB-MED-001, 164 -> SD-MED-03 and 166 -> SD-MED-04: check 1 names no single target, so its
  first listed candidate is used. This is noted on each alias.

Mapping: check 1 same -> `correct` and unclear -> `unclear`. Check 2 same -> `yes`. For check 2 unclear, `approved` is
left empty and the verdict is kept in a YAML comment.

`evidence` is the PMDC list URL and the line's quote. `target_evidence` is the target row's source_url and source_quote
in its batch v4 file.

## Dry run (validate, 2026-11-15)
The command was `validate` with `--country PK --lists --allow-list`, `--institutions-from` for each of batches 1-5 v4
(the option repeats), `--aliases` and `--assume-aliases-attested`.

- **Aliases:** 74 `alias_applied` and 8 `alias_required_not_accepted`.
- **Institutions (179):**
  - 67 `alias_membership`;
  - 15 new: ICT 12 (17, 31, 32, 36, 45, 50, 77, 90, 93, 98, 99, 103) and AJK 3 (1, 123, 124);
  - 88 rejected `missing_region`;
  - 8 rejected `alias_required_not_accepted`;
  - 1 rejected `alias_target_not_loaded` (155 -> IC-MED-02). In batch 4, IC-MED-02 itself is rejected
    `region_conflicts_with_list`: its region cell is "Punjab (federal)", and its list is ICT.
- Every planned row is `unconfirmed` (`check_unclear_or_missing`). validate runs in owner-accepted mode, which does not
  know the W12 checker refs (FU-12).

## Before the import
- Register `claude-w12-pmdc-e1` and `claude-w12-pmdc-e2` (`backend/scripts/os_reviewers.py`). Each must attest the
  workbook's batch ref.
- `claude-w12-pmdc-alias-check-1` and `-2` must attest `aliases-<sha256 of the alias file>`.
