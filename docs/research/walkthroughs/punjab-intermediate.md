# Punjab walkthrough: intermediate family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Punjab. Family: `intermediate` (master R-38). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** are the same as in `national.md`: every line has an official URL (hed.punjab.gov.pk, ocas.punjab.gov.pk, biselahore.com, uhs.edu.pk, uet.edu.pk, hec.gov.pk), a verbatim quote, the date read and the read method (`curl + HTML text strip` or `curl + pdftotext`); whitespace is collapsed in quotes. Nothing is from memory; the batch 2 v4 workbook served only as a lead. National rules (IBCC equivalence, MDCAT, HEC lists) are in `national.md` and are not repeated.

**Check 2 (independent):** a separate script re-downloaded every URL into a new folder and searched each quote word for word, without the draft's statements; it also recounted the lists. **Check 1** is left blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PI-01 | Punjab's Higher Education Department (HED) has nine BISEs that examine intermediate classes. | https://hed.punjab.gov.pk/boards | `The Higher Education Department has a network of 09 Boards of Intermediate and Secondary Education to cater to the examination of Intermediate classes in public and private sector colleges across Punjab.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PI-02 | The nine boards: Bahawalpur, D.G. Khan, Faisalabad, Gujranwala, Lahore, Multan, Rawalpindi, Sahiwal, Sargodha. | https://hed.punjab.gov.pk/boards | `Bahawalpur D.G. Khan Faisalabad Gujranwala Lahore Multan Rawalpindi Sahiwal Sargodha` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PI-03 | HED runs the Online College Admission System (OCAS) for intermediate admission in public colleges. | https://hed.punjab.gov.pk/ocas | `The Higher Education Department has introduced an important service for public sector colleges for the admissions in Intermediate programs (F.A./F.Sc./ICS etc.).` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PI-04 | OCAS covers 200+ public colleges (as of 2013, per HED). | https://hed.punjab.gov.pk/ocas | `was gradually implemented in 71 and 200+ public sector colleges during 2012 and 2013 respectively.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PI-05 | OCAS application fee: Rs 25 per application. | https://ocas.punjab.gov.pk/ | `Nominal application fee (Rs 25 per application)` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PI-06 | OCAS takes BISE results directly. | https://ocas.punjab.gov.pk/ | `Integration with BISE results, minimizing data entry and reducing errors` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PI-10 | HED publishes public college lists per division (9 PDFs); counts in the Lists table. | https://hed.punjab.gov.pk/colleges | `The lists of public colleges of Punjab are linked with their respective divisions given in the following:` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PI-Lbwp | HED public college list, bwp division (PDF). | https://hed.punjab.gov.pk/system/files/Bahawalpur_Colleges_0.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Ldgk | HED public college list, dgk division (PDF). | https://hed.punjab.gov.pk/system/files/DGKhan_Colleges.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Lfsd | HED public college list, fsd division (PDF). | https://hed.punjab.gov.pk/system/files/Faisalabad_Colleges_0.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Lgrw | HED public college list, grw division (PDF). | https://hed.punjab.gov.pk/system/files/Gujranwala_Division.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Llhr | HED public college list, lhr division (PDF). | https://hed.punjab.gov.pk/system/files/Lahore_Division_Colleges_0.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Lmul | HED public college list, mul division (PDF). | https://hed.punjab.gov.pk/system/files/Multan_division_Colleges.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Lrwp | HED public college list, rwp division (PDF). | https://hed.punjab.gov.pk/system/files/Rawalpindi_division_Colleges.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Lswl | HED public college list, swl division (PDF). | https://hed.punjab.gov.pk/system/files/Sahiwal_division_Colleges.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-Lsgd | HED public college list, sgd division (PDF). | https://hed.punjab.gov.pk/system/files/Sargodha_division_Colleges.pdf | `College Name` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PI-14 | Private colleges and A-level schools (board affiliation lists): no official list found. | — | **no official source found** | 2026-11-07 | no official source found | | n/a: no URL: gap line |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PI-13 | Documents for intermediate admission: no official source found. | — | **no official source found** | 2026-11-07 | no official source found | | n/a: no URL: gap line |

## Rules not found

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PI-11 | Merit rules for intermediate admission in public colleges: no official source read (college policy page refused the connection). | — | **no official source found** | 2026-11-07 | no official source found | | n/a: no URL: gap line |
| PI-12 | Seat categories / quotas for intermediate admission: no official source found. | — | **no official source found** | 2026-11-07 | no official source found | | n/a: no URL: gap line |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PI-07 | The 2026 OCAS intermediate cycle opened by 23 Sep 2026. | https://ocas.punjab.gov.pk/ | `Sep 23, 2026 OCAS Portal is Live for Intermediate Admissions.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PI-08 | BISE Lahore published the 11th-class registration schedule for session 2026-28 (dates in a linked PDF, not read here). | https://biselahore.com/notifications | `Revised Online Registration / Admission Schedule for Intermediate (11th-Class) Academic Session 2026-28` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PI-09 | BISE Lahore's 2026 exams had first and second annual sittings. | https://biselahore.com/notifications | `Date Sheet Intermediate (Second Annual) Examination 2026` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

### Lists table (public colleges, HED division PDFs)

| Division | URL | PDF date (metadata) | Rows (college lines with a gender column) | Highest serial | Note |
|---|---|---|---|---|---|
| bwp | https://hed.punjab.gov.pk/system/files/Bahawalpur_Colleges_0.pdf | 2021-11-09 | 68 | 68 | serials agree |
| dgk | https://hed.punjab.gov.pk/system/files/DGKhan_Colleges.pdf | 2021-11-09 | 76 | 76 | serials agree |
| fsd | https://hed.punjab.gov.pk/system/files/Faisalabad_Colleges_0.pdf | 2021-11-09 | 98 | 98 | serials agree |
| grw | https://hed.punjab.gov.pk/system/files/Gujranwala_Division.pdf | 2019-04-10 | 132 | — | no serial numbers in the text layer |
| lhr | https://hed.punjab.gov.pk/system/files/Lahore_Division_Colleges_0.pdf | 2019-04-16 (modified 2022-06-08) | 108 | 110 | serial and row count differ: a checker must count by hand |
| mul | https://hed.punjab.gov.pk/system/files/Multan_division_Colleges.pdf | 2019-04-16 | 70 | — | no serial numbers in the text layer |
| rwp | https://hed.punjab.gov.pk/system/files/Rawalpindi_division_Colleges.pdf | 2019-04-16 | 110 | 111 | serial and row count differ: a checker must count by hand |
| swl | https://hed.punjab.gov.pk/system/files/Sahiwal_division_Colleges.pdf | 2019-04-16 | 37 | 37 | serials agree |
| sgd | https://hed.punjab.gov.pk/system/files/Sargodha_division_Colleges.pdf | 2019-04-16 | 95 | 95 | serials agree |

Sum of rows: **794** public colleges. These PDFs date from 2019–2021, so the list is old; HED gives no newer list on the page. The OCAS 'Participating Colleges' list and the `cis.punjab.gov.pk` college search refused the connection, so they were not read.

## Gaps

- PI-11: Merit rules for intermediate admission in public colleges: no official source read (college policy page refused the connection).
- PI-12: Seat categories / quotas for intermediate admission: no official source found.
- PI-13: Documents for intermediate admission: no official source found.
- PI-14: Private colleges and A-level schools (board affiliation lists): no official list found.
- Exact dates of the 2026-28 11th-class registration (BISE Lahore PDF not opened) and of the other eight boards: not read.
- OCAS participating colleges, merit lists and college search (`cis.punjab.gov.pk`, `hep.punjab.gov.pk`, `ocas.pitb.gov.pk`): connection reset, not readable.

## Check summary

- Lines: 23; cited: 19; gaps: 4.
- Check 2: correct 19, wrong 0, unclear 0, n/a 4 (run 2026-11-07T19:46:14.935780Z).
- Check 1: not done yet.
