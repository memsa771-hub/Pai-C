# Islamabad Capital Territory walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Islamabad Capital Territory. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (imcgf72.edu.pk, fbise.edu.pk, szabmu.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| IB-01 | Merit Determination Criteria: MDCAT of PM&DC 50%, F.Sc(Pre-Medical)/HSSC 40%, SSC 10%. | http://www.szabmu.edu.pk/admission/mbbs-admission | `Merit Determination Criteria MDCAT of PM&DC = 50% F.Sc(Pre-Medical)/HSSC/Equivalent = 40% SSC/Matriculation/Equivalent = 10%` | 2026-11-07 | curl + HTML text strip (comments removed) | re-check needed | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| IB-08 | federal universities' own admission rules: per university (batch 5). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| IB-03 | all Pakistani citizens (including AJK and Gilgit-Baltistan) may compete for Open Merit Seats. | http://www.szabmu.edu.pk/admission/mbbs-admission | `All Pakistani citizens (including AJK and Gilgit-Baltistan) are eligible to compete for Open Merit Seats.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| IB-04 | Federal Medical College, Islamabad seats: Open Merit 06, Islamabad Capital Territory 25, Punjab 29, Sindh (R) 07, Sindh (U) 05, Khyber Pakhtunkhwa 07, Balochistan 04, Gilgit Baltistan 02, FATA 02, Azad Jammu and Kashmir 02, Federal Government Employee 09. | http://www.szabmu.edu.pk/admission/mbbs-admission | `Revised Seats Allocation for Federal Medical College, Islamabad Open Merit 06 Islamabad Capital Territory 25 Punjab 29 Sindh (R) 07 Sindh (U) 05 Khyber Pakhtunkhwa 07 Balochistan 04 Gilgit Baltistan 02 FATA 02 Azad Jammu and Kashmir 02 Federal Government Employee 09` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Tests

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| IB-02 | eligibility needs minimum 60% in HSSC or F.Sc (Pre-medical) and minimum 55% in MDCAT 2026 by the Pakistan Medical and Dental Council. | http://www.szabmu.edu.pk/admission/mbbs-admission | `Minimum 60% marks, in HSSC or F.Sc (Pre-medical) or equivalent examination having minimum twelve years of education, and 2. Minimum 55% marks in the MDCAT 2026 examination conducted by the Pakistan Medical and Dental Council` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| IB-05 | domicile applicants also give proof of residence/property/education in the region of domicile. | http://www.szabmu.edu.pk/admission/mbbs-admission | `in addition to domicile certificate, proof of residence/property/education or any tangible evidence of stay in region of domicile.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| IB-06 | visible entries carry a province label, e.g. this row; the count in the Lists table is a markup_count (unconfirmed on import). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `Air University Islamabad Capital Territory` | 2026-11-07 | markup_count (count from HTML attributes; the quote is a visible row showing the province label) | re-check needed | correct: quote found word for word (html, markup, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| IB-07 | SZABMU 2026-27 MBBS dates: the notice is an image (batch 4 lead); not read as text in this pass. | — | **no official source found** | 2026-11-07 | not_readable | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Islamabad Capital Territory | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date | **27** (17 public, 10 private) | markup_count: counted HTML attributes (unconfirmed on import) |

## Gaps

- IB-07: SZABMU 2026-27 MBBS dates: the notice is an image (batch 4 lead); not read as text in this pass.
- IB-08: federal universities' own admission rules: per university (batch 5).

## Check summary

- Lines: 8; cited: 6; gaps: 2.
- Check 2: correct 6, wrong 0, unclear 0, n/a 2 (run 2026-11-07T19:59:31.246338+00:00).
- Check 1 (blind, 2026-11-07): correct 4, wrong 0, unclear 2, n/a 2.
