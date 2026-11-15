# W12 PMDC medical and dental colleges: list workbook and alias file (2026-11-15, LOCAL)

This is the PMDC list `pmdc-colleges-with-hospitals` in docs/research/lists/national.yaml: 190 lines (row_count 190,
serials 1-190 in four sections), from the PDF
https://pmdc.pk/Documents/Others/Recognised%20Institutes%20with%20attached%20Hospitals%20(Final%20List%20)%20%2007-11-2025%20for%20web%20-.pdf.

It is loaded as the list workbook `docs/research/batches/PAI-Research-W12-pmdc-colleges-with-hospitals.xlsx`, built with
`backend/scripts/os_list_sheet.py` (P2-T29) from two independent extractions. id_prefix `PK-PMDC-` (no existing id uses
it). An alias file sits next to it (`.aliases.yaml`).

**v2 (FU-15, 2026-11-15):** 74 more rows get a region from the PBS 2023 district table (see "Region from the district
table"). The workbook keeps its name, because v1 was never imported outside local test DBs. It was rebuilt, and the
alias file was re-bound to the new sha256 (its aliases are unchanged).

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
- **region** is filled in this order (v2, FU-15; see "Region from the district table" below):
  1. a province or territory word in the address (ruling 2, below);
  2. else, for the rows both FU-15 checks judged, the PBS 2023 district or division the address names
     (`district-regions.yaml`);
  3. else empty.
- **Step 1** (ruling 2): `region-words.yaml` maps the province or territory word printed in the row's address to a
  regions.yaml code: "AJ&K" -> azad_jammu_and_kashmir, "Islamabad" -> islamabad_capital_territory, "Sindh" -> sindh,
  "Baluchistan" -> balochistan.
  - The scanned text is the extraction's `address` cell, or its `name` cell where the address is empty (the
    extraction kept the whole cell as the name).
  - The bold remark "(Letter sent to M/o NHSR&C, Islamabad ...)" is in neither cell, so it never gives a region (rows
    13, 55, 70, 109, 188).
  - A word in the college name before the address is not used: 168 "Sindh Medical College ... Karachi." and 187 "Sindh
    Institute of Oral Health Sciences/ JSMU Karachi." get no region from step 1 (step 2 gives them sindh, from Karachi).
  - Step 1 gives 23 rows a region, the same 23 rows as both agents' own region tables.
- With step 2, 97 rows have a region (23 + 74). E1 and E2 agree on region for 190/190 rows. No region is taken from a
  city that is not a PBS district or division name.

The mapping (`mapping.yaml`) uses `type_column: type` and `region: column` with `region_column: region`. The list is
national, but a college is never given `national`. An empty region is written empty:
- an alias row inherits its target's region (T28 rule 4);
- any other row is rejected `missing_region` at import.

## Region from the district table (v2, FU-15, controller rule, for the owner to confirm)
The D-PMDC dry run rejected 88 rows `missing_region`: they have no province word and no alias. Two independent checks
judged those 88 rows against the official district table:
- `checks/district-check1.yaml` (ref `claude-fu15-district-check-1`, with its `extended_rule` section);
- `checks/district-check2.yaml` (ref `claude-fu15-district-check-2`).

Both are byte-identical copies of `.local-ci/work/FU15/check1.yaml` and `check2.yaml` (sha256 341bcfa1... and
c305507f...).

**Source:** Pakistan Bureau of Statistics, 7th Population and Housing Census 2023, Table 1, one PDF per province plus
Islamabad, retrieved 2026-11-15 by both checks with the same sha256:

| File (https://pbs.gov.pk/wp-content/uploads/census_tables/tables/) | sha256 | region |
|---|---|---|
| table_1_punjab_province.pdf | 63df3bec54bdc753d4462f830484bf57dc4ceb34eca2b37dce479c02421ff54c | punjab |
| table_1_sindh_province.pdf | c066bb906bdacef9bf989c0c64870c30ca9d7e7f8c9abd8a07271072600defb1 | sindh |
| table_1_kp_province.pdf | 8924fb1b927751c0df902272f70e422ce88a7d5b5857cbb2daadf540232c3b24 | khyber_pakhtunkhwa |
| table_1_balochistan_province.pdf | 34fcfbf77dca2ed90f2cbbe5d6536e7ca916254c2f96549bdc9fa310cbeedaa1 | balochistan |
| table_1_islamabad.pdf | 8deb2282dd70fc564a863c26c7a0adbd7651379aade08dbcc7f8279426423da3 | islamabad_capital_territory |

The tables cover the four provinces and Islamabad only. AJK and Gilgit-Baltistan are not in them.

**Data file:** `district-regions.yaml` holds the source, both check refs, the rule and the 165 units (135 districts and
30 divisions). Each unit has its name as printed (the word DISTRICT or DIVISION dropped), unit, region, file and page.
It was written from check 2's `unit_table`. check 1's `district_table` plus `extended_rule.division_table` is the same
set of (name, unit, region, file, page), and no name is printed in two regions.

**Rule (step 2):**
- It applies only to the 88 rows both checks judged, and only where step 1 found no word.
- Take the last comma part of the address cell (the name cell where the address is empty). Lower-case it, turn every
  non-alphanumeric character into a space, and collapse the whitespace.
- It matches a unit name normalised the same way, either exactly or, when that fails, with all spaces removed on both
  sides, provided exactly one unit name has that space-free form. A name printed in two regions never matches.
- Nothing else is loosened: no Cantt, no abbreviation, no misspelling, no town that is not a district or division.

`derive.py` stops unless:
- `units` equals both checks' tables and the source files equal both checks' files;
- both checks judged the same 88 rows with the same result, and each row's address in E1 and E2 is the checks' address;
- step 2 gives, in E1 and in E2, exactly both checks' per-row result (matched or not, the unit name, the region), and 74
  of 88 match.

**Result:** 74 of 88 match: Sindh 38, KP 28, Punjab 7 and Balochistan 1.
- Of these, 43 match a district name exactly. 28 match the division KARACHI (Karachi is printed only as KARACHI
  DIVISION plus its seven districts). 3 match MIRPUR KHAS in its space-free form ("Mirpurkhas").
- Rows: Sindh 57-60, 62, 64-72, 110-121, 157-159, 162, 168, 182-188; KP 5-13, 78-83, 127-130, 132-136, 174-177; Punjab
  24, 37, 100, 101, 109, 139, 179; Balochistan 173.
- 168 "Sindh Medical College ... Karachi." and 187 "Sindh Institute ... JSMU Karachi." get sindh from Karachi, not from
  the word in the name.

**Still unplaced (14), with the reason both checks give** (the last comma part names no district or division):

| Key | Last part of the address | Why it does not match |
|---|---|---|
| 2 | Quetta-Cantt. | cantonment wording; not a unit name |
| 25 | Kharian Cantt | cantonment; Kharian is not a district or division in the table |
| 26 | Lahore Cantt. | cantonment wording; not a unit name |
| 27 | Multan Cantt. | cantonment wording; not a unit name |
| 33 | Taxila | not a district or division in the table |
| 54 | Wah Cantt. | cantonment; Wah is not a district or division in the table |
| 61 | Tando M.Khan | abbreviation of TANDO MUHAMMAD KHAN; not equal |
| 63 | Malir Cantt. Karachi. | the address has no comma; "malir cantt karachi" is not a unit name |
| 73 | Tando Adam. | not a district or division in the table |
| 89 | Taxila Cantt. | cantonment; Taxila is not a district or division in the table |
| 125 | Rawalakot | AJK; AJK is not in the PBS 2023 tables |
| 131 | D. I. Khan | abbreviation of DERA ISMAIL KHAN; not equal |
| 160 | Karach. | misspelling of Karachi; not equal |
| 190 | Sawat. | misspelling of Swat; not equal |

They stay `missing_region`. None of them is guessed.

**Limited to the 88 judged rows (decision for the controller to confirm).** 167 rows have no province word. The other
79 are alias rows and held rows, and the checks did not judge them. Applied to them, the same rule would also match 71
of them in E1 and 72 in E2. An alias row takes its target's region (T28 rule 4), so step 2 leaves these rows empty, and
every alias row is unchanged.

## Build
Run `python -I ../docs/research/batches/w12/pmdc/derive.py ../docs/research/batches/w12/pmdc` and then `build.sh` from
`backend/`, in `docker run --rm pai-ci-py`. Extra arguments go to the tool: v2 was built with `sh build.sh --force`
over the v1 file.
- read_method: "curl + pypdf 7.1.0 (PDF text layer)". It maps to fetch, and neither extraction used pdftotext.
- retrieved: 2026-11-15.
- Checkers: `claude-w12-pmdc-e1` and `claude-w12-pmdc-e2`, both dated 2026-11-15.
- The CSVs differ, so `--identical-extractions` is not used. Both have 190 rows (row_count 190), so no override is
  needed.

Result:
- 179 rows written: 71 private_medical_college, 44 private_dental_college, 46 public_medical_college and 18
  public_dental_college.
- 11 rows held (`name_disagrees`; see the `.held.csv` file).
- v2 against v1: the only changed Institutions cells are 74 region cells, empty -> sindh 38, khyber_pakhtunkhwa 28,
  punjab 7 and balochistan 1. On the "Derived from" sheet, the E1/E2 CSV sha256s and the recorded command (`--force`)
  changed. The `.held.csv` file is byte-identical.
- v2 sha256: workbook 44a6bdc0004263d74e02fd31fa950cf797d43b2165201464421b3af1bd9e8b90 (v1 2b97d5b1...). E1 CSV
  4c5cc21b..., E2 CSV 12dd5bab....

The xlsx bytes are not reproducible (zip timestamps). The alias file is bound to the committed workbook's sha256, so
rebuild the workbook only together with the alias file. For v2, `make_aliases.py` was re-run, and the only line of the
alias file that changed is `sha256:`.

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

## Dry run (validate, v2, 2026-11-15)
The command, from `backend/` in `docker run --rm pai-ci-py`:

```
python -m scripts.os_import_batch validate ../docs/research/batches/PAI-Research-W12-pmdc-colleges-with-hospitals.xlsx \
  --country PK --lists ../docs/research/lists --allow-list app/os/knowledge/sources/lists \
  --institutions-from <each of batches 1-5 v4> \
  --aliases ../docs/research/batches/PAI-Research-W12-pmdc-colleges-with-hospitals.aliases.yaml --assume-aliases-attested \
  --reviewers --assume-attested claude-w12-pmdc-e1 claude-w12-pmdc-e2
```

The same command was run on the v1 workbook and alias file first.

| Row result | v1 | v2 |
|---|---|---|
| Aliases `alias_applied` | 74 | 74 |
| Aliases `alias_required_not_accepted` | 8 | 8 |
| Institutions `alias_membership` (accepted) | 67 | 67 |
| Institutions new, accepted (`both_checks`) | 15 | 61 |
| Institutions new, unconfirmed (`source_not_on_allow_list`) | 0 | 28 |
| Institutions rejected `missing_region` | 88 | 14 |
| Institutions rejected `alias_required_not_accepted` | 8 | 8 |
| Institutions rejected `alias_target_not_loaded` (155 -> IC-MED-02) | 1 | 1 |

- Every row adds up: 67 + 61 + 28 + 14 + 8 + 1 = 179.
- Only the 74 rows that were `missing_region` change. Every alias row and every other row has the same result as in v1.
- New rows (89):
  - v1 rows: ICT 12 (17, 31, 32, 36, 45, 50, 77, 90, 93, 98, 99, 103) and AJK 3 (1, 123, 124);
  - added in v2: Sindh 38, Punjab 7 and Balochistan 1 (accepted), and KP 28 (unconfirmed).
- **KP 28 are `unconfirmed` (`source_not_on_allow_list`, "scopes tried: khyber_pakhtunkhwa/bachelor").**
  `app/os/knowledge/sources/lists/khyber_pakhtunkhwa-bachelor.yaml` has no pmdc.pk entry. The punjab, sindh,
  balochistan, ICT, AJK and national bachelor files do have one. This is not changed here. A KP entry needs its own
  two checks.
- Row 155 -> IC-MED-02 is unchanged. In batch 4, IC-MED-02 itself is rejected `region_conflicts_with_list`: its region
  cell is "Punjab (federal)", and its list is ICT.
- The reviewer attestations are only assumed in this run (`--assume-attested`), and so are the alias attestations
  (`--assume-aliases-attested`).

## Before the import
- Register `claude-w12-pmdc-e1` and `claude-w12-pmdc-e2` (`backend/scripts/os_reviewers.py`). Each must attest the
  workbook's batch ref.
- `claude-w12-pmdc-alias-check-1` and `-2` must attest `aliases-<sha256 of the alias file>`.
  - For v2, that sha256 is aa54bd8590fb7a8937a7106da80a1cc0740abe7650ecc0449ccc118ab2da6dd5.
  - A v1 attestation does not carry over.
- The 28 KP rows stay `unconfirmed` until pmdc.pk is on the khyber_pakhtunkhwa bachelor allow-list, with two checks.
