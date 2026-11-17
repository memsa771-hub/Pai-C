# Balochistan walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Balochistan. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (bbiseqta.edu.pk, bmc.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| LB-01 | the prospectus applies to medical and dental institutions listed alphabetically, starting with "a. Bolan Medica" (cut in the quote). | https://bmc.edu.pk/wp-content/uploads/2025/12/Prospectus-2025-261.pdf | `The admission policy contained in the prospectus shall be applicable to following medical and dental institutions (Note: The following list is in alphabetical order): a. Bolan Medica` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (pdf, visible text, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| LB-03 | merit: Matriculation/SSC 10%, HSSC Pre-Medical 40%, MDCAT 50%; candidates freshly qualified MDCAT Result of 2025. | https://bmc.edu.pk/wp-content/uploads/2025/12/Prospectus-2025-261.pdf | `The candidates freshly qualified MDCAT Result of 2025. The merit for the purpose of admission the merit will be calculated as an Aggregate of the exams qualified by the candidate as under: • Matriculation/SSC/Equivalent - 10% • HSSC Pre-Medical /Equivalent - 40% • MDCAT - 50%` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (pdf, visible text, HTTP 200) |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| LB-10 | non-medical university admission rules: per university (batch 5). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| LB-04 | Open Merit Seats need a valid Local / Domicile certificate of any district of Balochistan. | https://bmc.edu.pk/wp-content/uploads/2025/12/Prospectus-2025-261.pdf | `Open Merit Seats: These seats are open to applicants having valid Local / Domicile certificate of any district of Balochistan` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (pdf, visible text, HTTP 200) |
| LB-05 | MBBS seats for academic session 2025-2026: 336. | https://bmc.edu.pk/wp-content/uploads/2025/12/Prospectus-2025-261.pdf | `The total number of MBBS seats during the academic session 2025-2026 shall be 336.` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (pdf, visible text, HTTP 200) |
| LB-06 | BDS seats for academic session 2025-2026: Fifty-Eight (58). | https://bmc.edu.pk/wp-content/uploads/2025/12/Prospectus-2025-261.pdf | `The total number of BDS Seats during the Academic Session 2025-2026 shall be Fifty-Eight (58).` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (pdf, visible text, HTTP 200) |
| LB-07 | Bolan Medical College, Quetta: 17 provincial merit MBBS seats; districts merit MBBS seats 227. | https://bmc.edu.pk/wp-content/uploads/2025/12/Prospectus-2025-261.pdf | `Provincial merit MBBS seats in BMC, Quetta 17 Divisional merit MBBS seats in Bolan Medical College, Quetta. 2 16 3 Districts Merit MBBS Seats in Bolan Medical College, Quetta. 227` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote; also checked against page 13 image of the PDF (matches) | correct: quote found word for word (pdf, visible text, HTTP 200) |

## Tests

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| LB-02 | MBBS needs minimum 55% and BDS minimum 50% in MDCAT 2025-2026, and 65% or above in F. Sc equivalent. | https://bmc.edu.pk/wp-content/uploads/2025/12/Prospectus-2025-261.pdf | `it is mandatory for candidates with MBBS minimum 55% percent marks, BDS minimum 50% in MDCAT 2025-2026 test and 65% percent marks or above in F. Sc equivalent.` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (pdf, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| LB-08 | visible entries carry a province label, e.g. this row; the count in the Lists table is a markup_count (unconfirmed on import). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `University of Balochistan Balochistan` | 2026-11-07 | markup_count (count from HTML attributes; the quote is a visible row showing the province label) | correct: quote found word for word in visible HTML text (HTTP 200, 2026-11-07); statement says it is a markup count and the quote is a real visible HEC row, the province label is in the row's li text | correct: quote found word for word (html, markup, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| LB-09 | 2026-27 MBBS/BDS prospectus or schedule for Balochistan: not found; the latest read is 2025-2026. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Balochistan | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date | **12** (11 public, 1 private) | markup_count: counted HTML attributes (unconfirmed on import) |

## Gaps

- LB-09: 2026-27 MBBS/BDS prospectus or schedule for Balochistan: not found; the latest read is 2025-2026.
- LB-10: non-medical university admission rules: per university (batch 5).
- The medical prospectus read is for session 2025-26 (uploaded 2025-12); it is the latest cycle found, labelled with its year.

## Check summary

- Lines: 10; cited: 8; gaps: 2.
- Check 2: correct 8, wrong 0, unclear 0, n/a 2 (run 2026-11-07T20:00:29.348765+00:00).
- Check 1 (blind, 2026-11-07): correct 7, wrong 0, unclear 1, n/a 2.
