# D-PMDC extraction E1: pmdc-colleges-with-hospitals

## Source
- List entry: `pmdc-colleges-with-hospitals` in docs/research/lists/national.yaml (read-only).
- URL (as written): https://pmdc.pk/Documents/Others/Recognised%20Institutes%20with%20attached%20Hospitals%20(Final%20List%20)%20%2007-11-2025%20for%20web%20-.pdf
- Downloaded with curl (`curl -sS -L`), HTTP 200, at 2026-11-15T00:02:19Z (UTC). 307407 bytes, `%PDF-1.7`, 17 pages.
- Raw bytes: `raw/pmdc.pdf`. Status: `raw/http_status.txt`. Time: `raw/fetch_time.txt`.
- **sha256: `4193caa23be4cdf4374cbb41928a225faf8fb44e371133b022c4cd2261d460e1`**

## Method (E1: cut the left column by x-coordinate, then group by serial)
- Tools: `docker run --rm pai-ci-py`, `python -I`, Python 3.12.16, pypdf 7.1.0. Nothing was installed.
  - Host xpdf pdftotext 4.06 was used only for a cross-check (`raw/host-pdftotext-layout.txt`). Every quote token appears in its output.
- `scripts/dump.py`: the pypdf `extract_text(visitor_text=...)` callback writes every text fragment to `raw/frags.json`, with its page, start x, y, font, size and right edge. The right edge is computed from the font's /Widths.
- `scripts/extract.py`: builds the CSV and `raw/checks.json`.
  - Excluded: the 15.96pt title; the four 14.04pt section headings (used only to set `section`); the column header rows on page 1 (y > 720); and the page-17 "Note:" block (from y of `Note:` down).
  - **Column cut (my measurement):** a fragment is in the left column when its start x is below **292.0**. On every page, the largest left-column right edge is below the smallest right-column start x. The tightest values are 289.33 (p1, 'Toll ') and 295.51 (p11, 'i.'). All 17 per-page pairs are in `checks.json` under `page_gap`, and no page overlaps.
  - **Serial column:** a fragment is in the serial column when its start x is below **76.5**. The name column starts at 97.7 on pages 1-7 and at 78.98 on pages 8-17. Serial fragments (some split as '7','8','.') are joined into `NN.`.
  - Lines: fragments with |dy| < 1 form one line, joined left to right. A space is added only where the fragment text has one or the gap is more than 1.0pt. This keeps 'Mirpur-AJ&K.' and 'Mohi-ud-Din' together.
  - **Grouping:** each left-column line goes to the nearest serial at or above it on the same page (serial y + 2.5 >= line y). On pages 4 and 5, a line above the first serial goes to the last serial of the previous page (rows 36 and 50).
  - `section` comes from the last 14.04pt heading before the serial in reading order.
  - `quote` holds all left-column lines of the row, joined with single spaces. It includes the bold remark lines.
  - `page` is the page of the printed serial.

## Name / address boundary rule
Work on the non-bold lines of the cell. The bold remark lines, "(Letter sent to M/o NHSR&C, ...)" and "(Provisionally recognized by erstwhile PMC)", stay in `quote` only. Scan left to right for a candidate name end. A candidate is either:
- a head word: College, Sciences, Medicine, Dentistry, University, Girls or Women, optionally followed by a parenthesised capital acronym such as "(CIMS)" or "(LIMHS)", and any closing ")"; or
- "/" followed by a capital acronym (KIMS, KIDS, JSMU).

A candidate is the boundary only if all of these hold:
1. It is followed by a line end or a comma, or it ends in a parenthesised acronym.
2. The next line does not start with "of", "&", "for" or "/".
3. The name so far is not only a generic unit. The generic units are: Dental Section, Dental College, Institute of Dentistry, School of Dentistry, Faculty of Dentistry, College of Dentistry.

- `name` is the text up to the boundary, without a trailing comma.
- `address` is the rest, without a leading comma.
- If no candidate passes, the whole cell goes into `name`, `address` stays empty, and the row is flagged.
- Rows where the rule fires but the next text could be part of the name are also flagged, with the whole cell in `name`. The name the rule alone would give is recorded below.

## Checks (all pass)
- 190 rows; serials 1..190, with no gaps or duplicates.
- Sections match the stated ranges: 1-77 private_medical, 78-122 private_dental, 123-172 public_medical, 173-190 public_dental.
- No name is empty.
- No hospital text appears in any name or quote:
  - By structure, only fragments with x < 292 are used.
  - A scan for "(Own)", "(Affiliated)" and roman-numeral item markers finds none.
- Mismatches: none.

## Flagged rows
Boundary not found by the rule (whole cell in name):
- 3: "Abbottabad International Medical College Mansehra Road, Abbottabad." ("College" is followed by a space, not a comma or line end)
- 92: "Dental College, Niazi Medical & Dental College Sargodha" (same reason)
- 146: "Narowal M.C, Narowal" (no head word)

Boundary unclear by reading (whole cell in name). The name the rule alone would give is in brackets:
- 4: line 2 "(Former Al-Razi Medical College)," may be part of the name [Muhammad College of Medicine]
- 21: line 2 "Superior University, ..." names an organisation [Azra Naheed Medical College]
- 29: line 2 "Air University" names an organisation [Fazaia Medical College]
- 75: line 2 "Rawalpindi Campus" may be part of the name [Akhtar Saeed Medical College]
- 76: "National University of Sciences & Technology (NUST)" may be part of the name [NUST School of Health Sciences]
- 147: "Hafiz Hayat Campus, University of Gujrat," may be part of the name [Nawaz Sharif Medical College]

Cell continues across a page break (`page` = the serial's page):
- 36: "Islamabad." is at the top of page 4
- 50: "Sector H-8/4, Islamabad." is at the top of page 5

Bold remark in quote only (not in name or address):
- "(Letter sent to M/o NHSR&C, Islamabad for notification but notification is still awaited)": rows 13, 55, 70, 109, 188
- "(Provisionally recognized by erstwhile PMC)": rows 71, 72, 73, 82, 108, 120, 121

Other observations, with the text kept verbatim:
- Typos as printed include 15 "Boulaverad", 160 "Karach.", 190 "Sawat." and 70 "Pfao".
- 15 and 87 have "Farooq Hospital" inside the left-column address. That is the institute's address text, not the hospital column.

## Rows whose address states a province or territory
The scan uses `address`, or the whole-cell `name` for flagged rows. It looks only for the allowed words, matched exactly, and no region is inferred from a city. Bold remarks are not scanned, so "Islamabad for notification" is not counted.

| key | word | exact text | field |
|---|---|---|---|
| 1 | AJ&K | D/4, Industrial Area, Mirpur-AJ&K. | address |
| 17 | Islamabad | Near Farash Town, Zone-IV, Islamabad. | address |
| 29 | Islamabad | Fazaia Medical College Air University Sector E-9, Islamabad | whole-cell name (flagged) |
| 31 | Islamabad | Defence Avenue, DHA, Phase-I, Islamabad | address |
| 32 | Islamabad | Lehtrar Road,Tarlai, Islamabad. | address |
| 36 | Islamabad | Wadi-ul-Ilm Bharakahu, Main Murree Road, Islamabad. | address |
| 45 | Islamabad | Lehtrar Road, Near Ali Trust College, Khanna Dak,Islamabad. | address |
| 50 | Islamabad | Pitrus Bukhari Road, Sector H-8/4, Islamabad. | address |
| 76 | Islamabad | NUST School of Health Sciences, National University of Sciences & Technology (NUST) Sector H-12 Islamabad | whole-cell name (flagged) |
| 77 | Islamabad | Islamabad | address |
| 90 | Islamabad | Wadi-ul-Ilm,Murree Road, Bahara Kahu, Islamabad | address |
| 93 | Islamabad | Lehtrar Road, Near Ali Trust College, Khanna Dak, Islamabad. | address |
| 98 | Islamabad | Islamabad. | address |
| 99 | Islamabad | Lehtrar Road, Tarlai, Islamabad | address |
| 103 | Islamabad | Sector G-7/4, Islamabad. | address |
| 123 | AJ&K | Jalalabad,Muzaffarabad (AJ&K) | address |
| 124 | AJ&K | Chiterparri,Mirpur (AJ&K) | address |
| 142 | Islamabad | Al Farabi Centre, Hanna Road, G-8/4, Islamabad. | address |
| 165 | Sindh | Thatta, Sindh, Pakistan. | address |
| 170 | Baluchistan | Khuzdar - Baluchistan | address |
| 171 | Baluchistan | Loralai - Baluchistan | address |
| 172 | Baluchistan | Turbat - Baluchistan | address |
| 189 | Islamabad | Islamabad | address |

"Azad" appears only in the name of row 123 ("Azad Jammu & Kashmir Medical College"), not in an address. Its address states AJ&K.

## Output
- `pmdc-colleges-with-hospitals.csv`: UTF-8, LF line endings, 190 data rows plus a header, with sha256 `5d274708b77c3976f89184b12dea4ae85dea8d8933709d16cb613c3f966d7efb`.
- Re-run from the E1 folder: `docker run --rm -v <E1>:/w pai-ci-py sh -c "python -I /w/scripts/dump.py /w/raw/pmdc.pdf /w/raw/frags.json && python -I /w/scripts/extract.py /w/raw/frags.json /w/raw/pmdc.pdf /w/pmdc-colleges-with-hospitals.csv /w/raw/checks.json"`
- `scripts/rows.py` was an earlier review pass (line structure dump). It is not used for the CSV.
