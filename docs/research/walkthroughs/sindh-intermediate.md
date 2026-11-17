# Sindh walkthrough: intermediate family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Sindh. Family: `intermediate` (master R-38). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (seccap.dgcs.gos.pk, sindheducation.gov.pk, biek.edu.pk, admissions.smbbmu.edu.pk, neduet.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 3 v4 served only as a lead. National rules are in `national.md`.

SECCAP pages are a JavaScript app. Only the text in the static HTML was read (`JavaScript app; static text only`); live counters on it (applications, participating colleges) show 0 in the static HTML and were not used.

**Check 2 (independent):** a separate script re-downloaded every URL into a new folder, searched each quote word for word without the draft's statements, and recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SI-01 | SECCAP is the College Education Department's official admission portal for public colleges in Sindh. | https://seccap.dgcs.gos.pk/ | `Sindh Electronic Centralized College Admission Programme — the official admissions portal of the College Education Department (DGCS), Government of Sindh.` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |
| SI-02 | Sindh's school education site lists BISE boards (Larkana, Mirpurkhas, Karachi, Hyderabad, Sukkur) in its menu; it is a menu, not a full official list. | https://sindheducation.gov.pk/ | `Boards BISE Larkana Board BISE Mirpurkhas Board BISE Karachi Board BISE Hyderabad Board BISE Sukkur Board` | 2026-11-07 | curl + HTML text strip | correct: quote on page word for word; lists the five boards named | correct: quote found word for word (html, HTTP 200) |
| SI-03 | the board members list includes the Chairman, Board of Secondary Education, Karachi. | https://www.biek.edu.pk/bmembers.asp | `MR. GHULAM HUSSAIN SOHOO Designation: Chairman Organization: Board of Secondary Education, Karachi` | 2026-11-07 | curl + HTML text strip | correct: quote on page under BOARD MEMBERS; the entry is Chairman, Board of Secondary Education, Karachi | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SI-04 | SECCAP admits SSC passers to first year (HSC Part-I) in government colleges through one form. | https://seccap.dgcs.gos.pk/ | `It lets students who have passed Matriculation (SSC) — or an equivalent examination — apply for first-year (11th class / HSC Part-I) admission in government colleges across Sindh through a single form.` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |
| SI-05 | Students may apply with the 9th-class marksheet before the matric result. | https://seccap.dgcs.gos.pk/ | `You can apply using your 9th-class marksheet without waiting for your Matric result` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |
| SI-06 | Up to five colleges in order of preference. | https://seccap.dgcs.gos.pk/ | `Choose up to five colleges in order of preference.` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |
| SI-07 | Merit is normalised to a 550-mark scale across boards. | https://seccap.dgcs.gos.pk/admission-policy | `Results from every board are normalised to a 550-mark scale` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |
| SI-08 | Admissions run in rounds; an unadmitted application carries forward. | https://seccap.dgcs.gos.pk/admission-policy | `Admissions run in rounds. If you are not admitted in one round, your application automatically carries forward to the next.` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SI-09 | Minimums: pre-medical 70% (science with Biology), pre-engineering 70% (science with Mathematics), computer science 60%. | https://seccap.dgcs.gos.pk/admission-policy | `Pre-Medical 70% Science group with Biology Pre-Engineering 70% Science group with Mathematics Computer Science / IT 60% Science group` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SI-10 | Matric grade sets the zone: A+/A apply Sindh-wide; B–E own zone only. | https://seccap.dgcs.gos.pk/admission-policy | `A+ / A Unrestricted — apply Sindh-wide B – E Own zone (district catchment) only` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; 'matric grade' is from the heading beside the quote, not in the quote | correct: quote found word for word (html, HTTP 200) |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SI-11 | SECCAP registration uses CNIC or B-Form plus 9th and matric enrolment numbers. | https://seccap.dgcs.gos.pk/ | `Your CNIC or B-Form plus your 9th class and matric enrollment numbers.` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |
| SI-12 | SECCAP application is free. | https://seccap.dgcs.gos.pk/admission-policy | `Submitting a SECCAP application is free of charge` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SI-17 | BIEK affiliated government colleges (Karachi), count in Lists table. | https://www.biek.edu.pk/gmaleCol.asp | `GOVERNMENT AFFILIATED COLLEGES 1. Abdullah Govt. College for Women` | 2026-11-07 | curl + HTML text strip | correct: quote on page word for word; recount 181 (serials 1-181, no gaps, no duplicates) | correct: quote found word for word (html, HTTP 200) |
| SI-18 | BIEK affiliated private colleges (Karachi), count in Lists table. | https://www.biek.edu.pk/PMaleCol.asp | `PRIVATE AFFILIATED COLLEGES 1. A.S.F. Intermediate College` | 2026-11-07 | curl + HTML text strip | correct: quote on page word for word; recount 174 (serials 1-174, no gaps, no duplicates) | correct: quote found word for word (html, HTTP 200) |
| SI-19 | SECCAP college directory: JavaScript-only; no count in static page (batch 3 read 364 vs 376). | https://seccap.dgcs.gos.pk/colleges | `Explore the government colleges participating in SECCAP.` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; static page has no count (directory list loads by JavaScript) | correct: quote found word for word (html, HTTP 200) |
| SI-20 | College affiliation lists of BISE Hyderabad, Sukkur, Larkana, Mirpurkhas, Shaheed Benazirabad: not read in this pass. | — | **no official source found** | 2026-11-07 | no official source read | n/a: gap line, no URL | n/a: no URL: gap line |
| SI-21 | A-level schools in Sindh (P2 §11 Q4): no official list found. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL | n/a: no URL: gap line |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| SI-13 | 2026 Round 1 opened 1 Aug 2026 (announcement). | https://seccap.dgcs.gos.pk/ | `1 Aug 2026 Round 1 applications are now open` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows (item dated 1 Aug 2026) | correct: quote found word for word (html, HTTP 200) |
| SI-14 | Claim window: 24 hours after each merit list. | https://seccap.dgcs.gos.pk/ | `Confirm or change your allotted college within 24 hours of the merit list` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; 'each' comes from the headline beside the quote, not in the quote | correct: quote found word for word (html, HTTP 200) |
| SI-15 | Exact 2026 dates: the portal says 'as announced by the department'. | https://seccap.dgcs.gos.pk/ | `Applications open As announced by the department Last date to apply As announced by the department` | 2026-11-07 | curl + HTML text strip (JavaScript app; static text only) | correct: quote on page word for word; statement follows | correct: quote found word for word (html, HTTP 200) |
| SI-16 | 2026 results: Science Pre-Engineering Part-II 17-08-2026; Science Pre-Medical Part-II 31-07-2026. | https://www.biek.edu.pk/results.asp | `Science Pre-Engineering Part-II ( 17-08-2026) Humanities Regular Part-II ( 07-08-2026) Science Pre-Medical Part-II (31-07-2026)` | 2026-11-07 | curl + HTML text strip | correct: quote on page under RESULTS OF ANNUAL EXAMINATIONS 2026; the two dates match the statement | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| BIEK | Government affiliated colleges (Karachi) | https://www.biek.edu.pk/gmaleCol.asp | not stated | **181** | counted serials 1–181, no gaps |
| BIEK | Private affiliated colleges (Karachi) | https://www.biek.edu.pk/PMaleCol.asp | not stated | **174** | counted serials 1–174, no gaps |
| College Education Dept (SECCAP) | List of participating colleges | https://seccap.dgcs.gos.pk/colleges | not stated | **not readable** (JavaScript) | batch 3 v4 read 364 on the home page vs 376 in the directory; a checker must read it in a browser |

## Gaps

- SI-20: College affiliation lists of BISE Hyderabad, Sukkur, Larkana, Mirpurkhas, Shaheed Benazirabad: not read in this pass.
- SI-21: A-level schools in Sindh (P2 §11 Q4): no official list found.
- SECCAP's own schedule: the portal says dates are 'as announced by the department'; no department notification was found.
- Board result calendars of the boards other than BIEK: not read.

## Check summary

- Lines: 21; cited: 19; gaps: 2.
- Check 2: correct 19, wrong 0, unclear 0, n/a 2 (run 2026-11-07T19:49:35.227116Z; SB-06 re-run 2026-11-07T19:50:56.468534+00:00).
- Check 1: done (AI check 1, 2026-11-07): correct 17, wrong 2, unclear 0, n/a 2 (SI-03, SI-16 wrong: statement goes beyond the quote).
