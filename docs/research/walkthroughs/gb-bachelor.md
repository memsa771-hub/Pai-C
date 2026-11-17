# Gilgit-Baltistan walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Gilgit-Baltistan. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (doecgb.gov.pk, examinations.kiu.edu.pk, dapr.kiu.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GB-01 | the DoE (colleges) handles nomination of about 800 reserved seats for Gilgit-Baltistan in institutions of the country. | https://www.doecgb.gov.pk/nominations/medical/criteria | `The DoE (colleges) also deals with the nomination of about 800 reserved seats for Gilgit-Baltistan in different institution of the country.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GB-02 | basic eligibility: minimum sixty five percent marks (65%) in HSSC, F.Sc (Pre-Medical) or equivalent, with a minimum of twelve years of education or as per PMC criteria. | https://www.doecgb.gov.pk/nominations/medical/criteria | `the basic eligibility criteria for admission follows: The applicant shall have passed, obtaining minimum sixty five percent marks (65%) in Higher Secondary School Certificate (HSSC), F.Sc (Pre-Medical) or equivalent examination having a minimum of twelve years of education or as per PMC criteria` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found in visible text; statement follows | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GB-09 | not eligible: ‘third division’ in the annual system, or less than 50% marks or equivalent for other than annual system, in the required qualification. | https://dapr.kiu.edu.pk/semester-rule/mission-procedure-bs-4-years/ | `Who have got a degree/certificate with ‘third division’ in annual system or ’less than 50% marks or equivalent for other than annual system’ in the required qualification` | 2026-11-07 | curl + HTML text strip (comments removed) | unclear: quote found in visible text, but 'not eligible' is not in the quote; it comes from the preceding sentence 'The following categories of candidates shall not be eligible for admission:' which the quote omits. Extend the quote to include it | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GB-03 | reserved seats of Gilgit-Baltistan need a Domicile of Gilgit-Baltistan. | https://www.doecgb.gov.pk/nominations/medical/criteria | `applying for reserved seats of Gilgit-Baltistan must possess Domicile of Gilgit-Baltistan.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |
| GB-05 | seats by course: BACHELOR OF MEDICINE, BACHELOR OF SURGERY 82; BACHELOR OF DENTAL SURGERY 6; ON ROTATION 1. | https://www.doecgb.gov.pk/nominations/medical/seatsdistributions | `Seats By Courses # Course Name Total Seats 1 BACHELOR OF MEDICINE, BACHELOR OF SURGERY 82 2 BACHELOR OF DENTAL SURGERY 6 3 BACHELORS OF MEDICINE, BACHELOR OF SURGERY - (ON ROTATION) 1` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; figures match | correct: quote found word for word (html, visible text, HTTP 200) |
| GB-06 | district seats for BACHELOR OF MEDICINE, BACHELOR OF SURGERY: GILGIT 7, GHIZER 6, ASTORE 4. | https://www.doecgb.gov.pk/nominations/medical/seatsdistributions | `1 BACHELOR OF MEDICINE, BACHELOR OF SURGERY GILGIT 7 2 BACHELOR OF MEDICINE, BACHELOR OF SURGERY GHIZER 6 3 BACHELOR OF MEDICINE, BACHELOR OF SURGERY ASTORE 4` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; figures match | correct: quote found word for word (html, visible text, HTTP 200) |
| GB-07 | the university takes 80% of seats from Gilgit Baltistan and 20% from all over Pakistan (excluding Gilgit-Baltistan). | https://dapr.kiu.edu.pk/semester-rule/mission-procedure-bs-4-years/ | `From Gilgit Baltistan 80% of total seats in each discipline in each department. From all over Pakistan (excluding Gilgit-Baltistan) 20% of total seats in each discipline in each department.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; 'the university' comes from the page, quote itself says 'Admission'; accepted | correct: quote found word for word (html, visible text, HTTP 200) |
| GB-11 | reserved seats: Sports, Hafiz-e-Quran, Disable persons 01 seat per program per department each. | https://dapr.kiu.edu.pk/semester-rule/mission-procedure-bs-4-years/ | `Sports 01 seat per program per department Hafiz-e-Quran 01 seat per program per department Disable persons 01 seat per program per department` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; the page lists a fourth reserved category (KIU employee children) not claimed here | correct: quote found word for word (html, visible text, HTTP 200) |

## Tests

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GB-04 | the applicant must pass the entry test for the current session as per PMC criteria. | https://www.doecgb.gov.pk/nominations/medical/criteria | `The applicant must pass the entry test for the current session as per PMC criteria.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |
| GB-10 | where an entry test is held: 80% weightage academic performance and 20% Entry Test & interview. | https://dapr.kiu.edu.pk/semester-rule/mission-procedure-bs-4-years/ | `Admission shall be made on the basis of 80% weightage for academic performance and 20% weightage in the Entry Test & interview.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; the page makes this conditional on the university deciding to hold an entry test, so 'where an entry test is held' is right | correct: quote found word for word (html, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GB-12 | visible entries carry a province label, e.g. this row; the count in the Lists table is a markup_count (unconfirmed on import). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `Karakurum International University Gilgit Baltistan` | 2026-11-07 | markup_count (count from HTML attributes; the quote is a visible row showing the province label) | correct: quote found word for word in visible HTML text (HTTP 200, 2026-11-07); statement says it is a markup count and the quote is a real visible HEC row, the province label is in the row's li text | correct: quote found word for word (html, markup, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GB-08 | BS/Bachelor (4 years) admissions are for fall semester only. | https://dapr.kiu.edu.pk/semester-rule/mission-procedure-bs-4-years/ | `Admissions for BS/Bachelor (4 years) degree programs shall be made every year for fall semester only.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |
| GB-13 | 2026-27 nomination last dates: on a page not re-read in this pass (batch 4 lead). | — | **no official source found** | 2026-11-07 | no official source read | n/a: gap line | n/a: no URL: gap line |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Gilgit Baltistan | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date | **2** (2 public) | markup_count: counted HTML attributes (unconfirmed on import) |

## Gaps

- GB-13: 2026-27 nomination last dates: on a page not re-read in this pass (batch 4 lead).

## Check summary

- Lines: 13; cited: 12; gaps: 1.
- Check 2: correct 12, wrong 0, unclear 0, n/a 1 (run 2026-11-07T20:03:38.600627+00:00).
- Check 1 (blind, 2026-11-07): correct 9, wrong 0, unclear 3, n/a 1. Lists recounted: matches.
