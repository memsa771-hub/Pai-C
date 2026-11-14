# W12 Punjab public colleges: list workbooks (2026-11-15, LOCAL)

These are the nine HED Punjab division lists (`hed-punjab-public-colleges-*` in docs/research/lists/punjab.yaml),
797 lines in total. They are loaded as list workbooks
`docs/research/batches/PAI-Research-W12-hed-punjab-public-colleges-<division>.xlsx`, built with
`backend/scripts/os_list_sheet.py` from two independent extractions.

## The two extractions
Each extraction was made by a different agent, from its own curl download. The PDF sha256s are the same for both and
are recorded in every CSV and in each workbook's "Derived from" sheet.

| | Method | Raw output |
|---|---|---|
| E1 | `pdftotext -layout` (xpdf 4.06), then row split on serial and gender columns | `source-extractions/E1/` |
| E2 | pypdf 7.1.0 content-stream word coordinates, columns cut at the measured vertical grid lines, rows cut by the table grid | `source-extractions/E2/` |

Both found every list's row_count:
- 68 BWP, 76 DGK, 98 FSD, 132 GRW, 110 LHR, 70 MUL, 111 RWP, 95 SGD, 37 SWL;
- GRW and MUL print no serials, so their key is the 1-based position in reading order;
- the E2 grid check backs both counts (one row per table cell).

## Why the inputs in `E1/` and `E2/` are derived (controller ruling, for the owner to confirm)
In the PDF text layer, E1's District/Gender/Division/Contact values do not sit on the line of their row: each column is a
separate vertical run. So E1's `quote` (the whole printed row) cannot be compared with E2's. The names agree on
794 of 797 rows. The cities agree on all 690 rows where both extractions have one.

`derive.py` builds, for both extractions alike and only from each extraction's own cells:
- `quote = "<serial> | <name>"`. For GRW and MUL it is the name only, because they print no serial.
- `city` is kept only where both extractions have a non-empty city. The tool then compares it.

Nothing else is changed. The workbook rows therefore quote the serial and the college-name cell verbatim. They do not
quote gender, division or contact.

## Result
- 794 rows written: checker 1 `claude-w12-punjab-e1`, checker 2 `claude-w12-punjab-e2`.
- 3 rows held, where the extractions disagree on the name. See
  `PAI-Research-W12-hed-punjab-public-colleges-grw.held.csv`.
  - GRW 67 and 71: the name and district text are drawn over each other in the PDF.
  - GRW 83: E1 merged the district across a gap into the name.
  - E2's readings look right, but these rows need two new checks and a new run before they are written.
- No overlap with batches 1-5: name checks by the controller and the reviewer found only false matches.
  - One relation to note for later: LHR-42 "GOVT. COLLEGE OF HOME ECONOMICS GULBERG, LAHORE" and batch 1
    PK-UNI-182 "University of Home Economics, Lahore". They are two rows, possibly related, and not checked against a
    source.
- The import runs in reviewers mode. Both refs must be registered and must attest each workbook's batch ref.

## Provenance notes (review 2026-11-15)
- The mappings' `read_method` names E1's method. Both methods are in each workbook's "Derived from" sheet.
- "Derived from" hashes the derived inputs `E1/` and `E2/`. Those files can be rebuilt byte for byte with `derive.py`
  from `source-extractions/`, and the source extractions are byte-identical to the agents' original CSVs.
- About 41 names keep their characters verbatim, but double spaces are collapsed to one.
- The reviewer refs `claude-w12-punjab-e1` and `claude-w12-punjab-e2` must be registered
  (`backend/scripts/os_reviewers.py`), and each must attest every workbook's batch ref, before the import.
