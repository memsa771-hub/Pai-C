# D-PMDC extraction, E2

## Source and download
- List entry: `pmdc-colleges-with-hospitals` (docs/research/lists/national.yaml); the URL was used exactly as written there.
- URL: https://pmdc.pk/Documents/Others/Recognised%20Institutes%20with%20attached%20Hospitals%20(Final%20List%20)%20%2007-11-2025%20for%20web%20-.pdf
- Downloaded with curl 8.21.0 (mingw64), `curl -sS -L`. HTTP 200, 307407 bytes, at 2026-11-15T00:02:18Z (UTC).
- Raw file: `raw/pmdc.pdf` (header `%PDF-1.7`, 17 pages, MediaBox 595.56 x 842.04).
- **PDF sha256: `4193caa23be4cdf4374cbb41928a225faf8fb44e371133b022c4cd2261d460e1`**
- Output CSV sha256: `e65bbaf7ce554b48a0b9625546c1a6103c3684512ccb136338905f4808ea42a3` (190 data rows plus the header).

## Method (E2: clip-rectangle cells, not an x-cut)
- Tools: `docker run --rm pai-ci-py` (image sha256:e76d8e80a538...), Python 3.12.16, pypdf 7.1.0, every script run with `python -I`.
  Nothing was installed. pdftotext was not used.
- The page content streams draw every table cell's text inside its own clip path (`x y w h re W* n`, inside `q ... Q`).
- `scripts/cells.py`: one `page.extract_text()` pass with two visitors.
  - `visitor_operand_before` follows `q`/`Q` (a stack), `re` (the rectangle, mapped through the cm) and `W`/`W*` (the clip is set to that rectangle, intersected with the current clip).
  - `visitor_text` records each text chunk with the clip rectangle active when it is drawn.
  - So each chunk's cell comes from the PDF's own cell geometry, not from a measured x boundary.
- `scripts/rows.py`: groups chunks by (page, clip rect) into cells. A cell's text is its chunks joined in stream order and split
  on newlines. Text under the full-page clip (0,0,595.6,842.0) is "free" text: the title, section headings and the end note.
- `scripts/build.py`:
  - Cells that share a y-band (same page, same clip y0/y1) form one table row.
  - Inside a band the cells are ranked by x0: serial cell, then institute cell, then hospital cell. The cell rectangles I
    measured differ by page group:
    - serial 46.8-91.9 / institute 92.4-296.6 / hospital 297.1-549.2;
    - 35.8-73.2/74.9 / 73.7-286.8 (or 284.6) or 75.4-291.6 / hospital 285.1-292.0 to 538.2;
    - page-number box 525.8-542.9 (ignored).
  - Only the institute cell (rank 2) is used. The hospital cell is never read into any field.
  - A band whose serial cell is empty continues the previous row. Rows 36 (p3 to p4) and 50 (p4 to p5) gained address
    lines this way. The empty bands at the tops of p3 and p7, and the hospital-only bands on p10, p14, p15 and p17, added
    no left-column text.
  - Section: the nearest section heading above the band (an earlier page, or the same page with heading y > band top).
    Stream order alone was wrong here: the p16 heading "Public Dental Colleges:" is drawn before rows 171-172, which sit
    above it.
- `key` = the printed serial without its trailing ".". `quote` = all lines of the institute cell joined with single
  spaces, including any trailing remark. `page` = the page of the serial cell.
- `scripts/regions.py`: the region-word scan.

## Name/address boundary rule (applied mechanically)
1. Remark lines are removed from the name/address split. A remark line starts with "(Letter sent" or "(Provisionally",
   and it and everything after it in the cell count as remark. The remark stays in `quote` but is NOT in `address`.
   Rows with a remark: 13, 55, 70, 71, 72, 73, 82, 108, 109, 120, 121, 188.
2. Head terms: College, Medicine, Dentistry, Sciences, University, KIMS, KIDS, JSMU, Girls, Women, (CIMS), (NUST), M.C.
   Trailing `,` `.` `)` are ignored when matching.
3. Line-end rule: the name ends at the end of the first cell line that ends in a head term, except in two cases:
   - the line is the first line and is only a prefix ("Dental College", "Dental Section", "Institute of Dentistry",
     "School of Dentistry");
   - the next line begins with a continuation word: "(Former", "&", "for", "of", a lowercase word, or a head term.
4. Mid-line fallback, used when no line end qualifies: the name ends at the LAST head-term token in the cell body,
   unless the next token is glued punctuation (`,x` or `)x`).
5. If neither rule finds a clean boundary, the whole cell goes in `name`, `address` is left empty and the row is flagged.
6. One trailing comma is dropped from `name`. All other text is verbatim, including glued text such as "Road,Lahore.".

## Checks (all run in build.py)
- 190 rows: PASS
- serials 1..190, no gaps and no duplicates: PASS
- section ranges 1-77 / 78-122 / 123-172 / 173-190 match the headings: PASS (after the positional-heading fix above)
- no empty name: PASS
- no hospital text in a name or quote: PASS. Hospital cells are never read. A regex check also found no "(Own)", no
  "(Affiliated)" and no roman-numeral item markers in any name or quote.
- name + address + remark equals quote (ignoring commas): PASS for all rows
- Mismatches: none.

## Flagged rows
**Boundary not clear: the whole cell is in `name` and `address` is empty**
- 156: "Sheikh Zayed Medical College,Rahim Yar Khan." The comma is glued ("College,Rahim").
- 165: "Liaquat Institute of Medical & Health Sciences (LIMHS)Thatta, Sindh, Pakistan." The text is glued ("(LIMHS)Thatta,").

**Mid-line boundary (the fallback rule was used; the split falls inside a printed line)**
- 3: "Abbottabad International Medical College" / "Mansehra Road, Abbottabad."
- 77: "Bahria University College of Medicine" / "Islamabad"
- 92: "Dental College, Niazi Medical & Dental College" / "Sargodha"
- 122: "Rahbar College of Dentistry" / "Lahore"
- 141: "Fatima Jinnah Medical College for Women (Fatima Jinnah Medical University)" / "Queens Road,Lahore."
- 146: "Narowal M.C" / "Narowal"
- 167: "Shaheed Mohtarma Benazir Bhutto Medical College" / "Behind Lyari General Hospital, Tamery Road, Lyari, Karachi."
  "Hospital" here is left-column address text.
- 186: "Faculty of Dentistry, Liaquat University of Medical & Health Sciences" / "Jamshoro"
- 190: "Saidu College of Dentistry" / "Saidu Sharif, Sawat."

**The first address line has an institution word, so the name may continue there (the rule cut before it)**
- Genuinely ambiguous:
  - 29: "Air University"
  - 75: "Rawalpindi Campus"
  - 76: "National University of Sciences & Technology (NUST)"
  - 147: "Hafiz Hayat Campus, University of Gujrat"
  - 183: "Ojha Campus,"
- Almost certainly address, flagged by the word check only:
  - 7: "University Town"
  - 21: "Superior University"
  - 45 and 93: "Near Ali Trust College"
  - 153: "University Road"

**Other**
- 4: the name includes the former name, "Muhammad College of Medicine, (Former Al-Razi Medical College)". The "(Former"
  line counts as a continuation under rule 3.
- 36 and 50: the cell continues onto the next page. `page` is the start page.

## Region words stated in the address (verbatim; no region inferred from a city)
Only the `address` field was scanned. For the 2 whole-cell rows, the whole cell was scanned. Remark text and names were
not counted.

| key | word | exact text |
|---|---|---|
| 1 | AJ&K | D/4, Industrial Area, Mirpur-AJ&K. |
| 17 | Islamabad | Near Farash Town, Zone-IV, Islamabad. |
| 29 | Islamabad | Air University Sector E-9, Islamabad |
| 31 | Islamabad | Defence Avenue, DHA, Phase-I, Islamabad |
| 32 | Islamabad | Lehtrar Road,Tarlai, Islamabad. |
| 36 | Islamabad | Wadi-ul-Ilm Bharakahu, Main Murree Road, Islamabad. |
| 45 | Islamabad | Lehtrar Road, Near Ali Trust College, Khanna Dak,Islamabad. |
| 50 | Islamabad | Pitrus Bukhari Road, Sector H-8/4, Islamabad. |
| 76 | Islamabad | National University of Sciences & Technology (NUST) Sector H-12 Islamabad |
| 77 | Islamabad | Islamabad |
| 90 | Islamabad | Wadi-ul-Ilm,Murree Road, Bahara Kahu, Islamabad |
| 93 | Islamabad | Lehtrar Road, Near Ali Trust College, Khanna Dak, Islamabad. |
| 98 | Islamabad | Islamabad. |
| 99 | Islamabad | Lehtrar Road, Tarlai, Islamabad |
| 103 | Islamabad | Sector G-7/4, Islamabad. |
| 123 | AJ&K | Jalalabad,Muzaffarabad (AJ&K) |
| 124 | AJ&K | Chiterparri,Mirpur (AJ&K) |
| 142 | Islamabad | Al Farabi Centre, Hanna Road, G-8/4, Islamabad. |
| 165 | Sindh | Liaquat Institute of Medical & Health Sciences (LIMHS)Thatta, Sindh, Pakistan. (whole cell, flagged) |
| 170 | Baluchistan | Khuzdar - Baluchistan |
| 171 | Baluchistan | Loralai - Baluchistan |
| 172 | Baluchistan | Turbat - Baluchistan |
| 189 | Islamabad | Islamabad |

Not counted, for reference:
- "Islamabad" appears only inside the remark "(Letter sent to M/o NHSR&C, Islamabad ...)" in rows 13, 55, 70, 109 and 188.
- Region words that appear only in names: 36 and 90 (Islamabad), 123 (Azad), 149 and 180 (Punjab), 168 and 187 (Sindh).
- No row has Punjab, KP/KPK/Khyber Pakhtunkhwa, Balochistan (that spelling), GB or Gilgit in its address.

## Files
- `raw/pmdc.pdf`: the raw download
- `scripts/cells.py`, `scripts/rows.py`, `scripts/build.py`, `scripts/regions.py` (`scripts/probe.py` and `scripts/dumpcells.py` were exploration only)
- `chunks.json`, `cells.json`, `build.json`, `regions.tsv`, `celldump.txt`, `rowdump.txt`: intermediate files
- `pmdc-colleges-with-hospitals.csv`: the output
