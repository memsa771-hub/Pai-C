# Sindh walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Sindh. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (seccap.dgcs.gos.pk, sindheducation.gov.pk, biek.edu.pk, admissions.smbbmu.edu.pk, neduet.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 3 v4 served only as a lead. National rules are in `national.md`.

SECCAP pages are a JavaScript app. Only the text in the static HTML was read (`JavaScript app; static text only`); live counters on it (applications, participating colleges) show 0 in the static HTML and were not used.

**Check 2 (independent):** a separate script re-downloaded every URL into a new folder, searched each quote word for word without the draft's statements, and recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-01 | Sindh's 2026-27 MBBS/BDS prospectus names the processing universities (DUHS, LUMHS, PUMHS, SMBBMU, KMDC and others). | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `Liaquat University of Medical & Health Sciences, Jamshoro` | 2026-11-07 | curl + pdftotext (PDF text layer) | wrong: quote names only LUMHS; the other bodies in the statement (DUHS, PUMHS, SMBBMU, KMDC) are in the prospectus contents but not in the quote | correct: quote found word for word (pdf, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-03 | HSSC pre-medical 60% (660/1100), unadjusted; grace marks not counted. | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `60% 660/1100) marks in aggregate or an equivalent examination from any other Board or Institution recognized by IBCC with at least 60% (unadjusted) marks. Grace marks will not be considered.` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote in PDF text layer word for word; statement follows | correct: quote found word for word (pdf, HTTP 200) |
| SB-04 | Merit: SSC 10%, HSSC 40%, MDCAT 50%. | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `a. SSC/Matriculation/Equivalent (10%). b. HSSC/F.Sc (Pre Medical) or Equivalent (40%). c. MDCAT (50%).` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote in PDF text layer word for word; statement follows | correct: quote found word for word (pdf, HTTP 200) |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-15 | Central admission for non-medical public universities in Sindh: no official source found (per university, batch 5). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL | n/a: no URL: gap line |
| SB-16 | Sindh Universities & Boards Department site (ubd.gos.pk): not readable (proxy 502). | — | **no official source found** | 2026-11-07 | not_readable | n/a: gap line, no URL | n/a: no URL: gap line |
| SB-17 | Bachelor's admission in Sindh public colleges (BS/ADP): no official source found. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL | n/a: no URL: gap line |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-05 | Seats are tagged to districts/boards; e.g. 46 seats reserved for interior Sindh on merit-cum-choice. | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `Forty-six (46) seats have been reserved for students from interior Sindh, on merit-cum-choice criterion.` | 2026-11-07 | curl + pdftotext (PDF text layer) | unclear: 46 interior-Sindh seats follows; 'tagged to districts/boards' is not in the quote | correct: quote found word for word (pdf, HTTP 200) |
| SB-06 | Admission needs PRC (Form C) and domicile of the tagged area (the quote keeps the PDF text layer's private-use glyph U+F001 inside 'Certi?cate'). | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `Candidate for admission must have Permanent Residence Certicate on Form 'C' and Domicile certicate` | 2026-11-07 | curl + pdftotext (PDF text layer) | wrong: the current quote (with U+F001) matches the PDF text layer, but the page image reads 'Certificate' (U+F001 is the lost fi ligature); the statement also adds 'of the tagged area', and the rule is stated for SMBBMC Lyari tagged districts (page 101), not in the quote | correct: quote found word for word (pdf, HTTP 200); re-run on this line only |
| SB-07 | O/A-level students who studied in Pakistan are not eligible for the overseas quota. | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `Pakistani students having passed from foreign education system (i.e. O Levels, A Levels etc) in Pakistan shall not be eligible for overseas Pakistani quota seats.` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote in PDF text layer word for word; statement follows | correct: quote found word for word (pdf, HTTP 200) |

## Tests

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-02 | Sindh MBBS/BDS needs MDCAT 2026/2025/2024 by IBA Sukkur: 55% for MBBS, 50% for BDS. | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `Candidate must have passed MDCAT 2026/2025/2024 conducted by IBA-Sukkur with at least 55% marks for admission in MBBS and 50% marks for admission in BDS.` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote in PDF text layer word for word; statement follows | correct: quote found word for word (pdf, HTTP 200) |
| SB-10 | NED UET merit: 40% HSC Part-I / O-level + 60% NED entry test. | https://www.neduet.edu.pk/sites/default/files/Admissions-2026/ADMISSIONS_SCHEDULE_2026.pdf | `MS = 40% (HSC Part I/ O-level Marks/ Equivalent Examinations)* + 60% (NED Entry Test Marks)` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote in PDF text layer and page image word for word; statement follows | correct: quote found word for word (pdf, HTTP 200) |
| SB-11 | NED entry test pass mark 50%. | https://www.neduet.edu.pk/sites/default/files/Admissions-2026/FAQ.pdf | `50% marks in entry test are required to qualify for admission.` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote in PDF text layer word for word; statement follows | correct: quote found word for word (pdf, HTTP 200) |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-13 | NED documents include IBCC equivalence (foreign exams), domicile and CNIC/B-Form. | https://www.neduet.edu.pk/sites/default/files/Admissions-2026/ADMISSIONS_SCHEDULE_2026.pdf | `d) IBCC Equivalent Certificate (For Foreign examinations) ORIGINAL* and photocopies (02) e) Domicile ORIGINAL* and photocopy (01)` | 2026-11-07 | curl + pdftotext (PDF text layer) | wrong: quote covers IBCC equivalence and domicile only; CNIC/B-Form is on the page (item g) but not in the quote | correct: quote found word for word (pdf, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-14 | HEC recognised list, Province = Sindh (count in Lists table). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `Province='Sindh'` | 2026-11-07 | curl + count of list items in the HTML markup | correct: quote is in the page markup (HTML attribute); recount 83 items with Province='Sindh' (35 Public, 48 Private) | correct: quote found word for word (html, HTTP 200) |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SB-08 | 2026-27 tentative: last date for forms 26 Oct 2026; final MBBS merit list 6 Nov 2026. | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `Last Date for Submission of MBBS & BDS Forms 26 October 2026` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote in PDF text layer word for word; page image shows 26th October 2026; statement's 6 Nov follows from SB-09 | correct: quote found word for word (pdf, HTTP 200) |
| SB-09 | Final merit list of MBBS: 6 November 2026 (superscript split by PDF layer). | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | `6. Display of Final Merit List of MBBS 6 November 2026` | 2026-11-07 | curl + pdftotext (PDF text layer) | correct: quote word for word on page image (6th November 2026); text layer splits the superscript | correct: quote found word for word (pdf, HTTP 200) |
| SB-12 | NED 2026: merit/call list 16-07-2026; classes 17-08-2026. | https://www.neduet.edu.pk/sites/default/files/Admissions-2026/ADMISSIONS_SCHEDULE_2026.pdf | `Display of Merit/Call List 16-07-2026` | 2026-11-07 | curl + pdftotext (PDF text layer) | wrong: quote carries only merit/call list 16-07-2026; 'classes 17-08-2026' is on the page but not in the quote | correct: quote found word for word (pdf, HTTP 200) |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Sindh | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date | **83** (35 public, 48 private) | counted `Province='Sindh'` items in the markup |
| Sindh processing universities | MBBS/BDS institutions in the 2026-27 prospectus | https://admissions.smbbmu.edu.pk/download/ProspectusMBBS-BDS2026-27.pdf | Session 2026-27 | not counted | the PMDC national list (190) is the national denominator |

## Gaps

- SB-15: Central admission for non-medical public universities in Sindh: no official source found (per university, batch 5).
- SB-16: Sindh Universities & Boards Department site (ubd.gos.pk): not readable (proxy 502).
- SB-17: Bachelor's admission in Sindh public colleges (BS/ADP): no official source found.
- SB-06: the first check 2 run marked it `wrong` because the draft quote dropped a private-use glyph (U+F001) that the PDF text layer has inside `Certi?cate`. The quote was corrected to keep the glyph, and check 2 was re-run on this line only (see `reruns` time below): now correct.
- The UDP self-finance and LUMHS-specific rules in batch 3: not re-read in this pass.

## Check summary

- Lines: 17; cited: 14; gaps: 3.
- Check 2: correct 14, wrong 0, unclear 0, n/a 3 (run 2026-11-07T19:49:35.227116Z; SB-06 re-run 2026-11-07T19:50:56.468534+00:00).
- Check 1: done (AI check 1, 2026-11-07): correct 9, wrong 4, unclear 1, n/a 3 (SB-01, SB-06, SB-12, SB-13 wrong; SB-05 unclear).
