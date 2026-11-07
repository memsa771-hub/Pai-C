# Khyber Pakhtunkhwa walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Khyber Pakhtunkhwa. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (admission.hed.gkp.pk, hed.gkp.pk, bisep.edu.pk, cas.kmu.edu.pk, etea.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-01 | eligibility: minimum 65% in Higher Secondary School Certificate or F.Sc (Pre-Medical) or equivalent from any BISE in Pakistan or abroad. | https://cas.kmu.edu.pk/ | `The candidate must have passed obtaining minimum 65% marks in Higher Secondary School Certificate or F.Sc (Pre-Medical) or equivalent qualification from any BISE in Pakistan or abroad.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KB-04 | Aggregate Percentage weightage: SSC 10%, Intermediate Pre-Medical (HSSC) 40%, MDCAT 50%. | https://cas.kmu.edu.pk/ | `The weightage criteria for calculation of Aggregate Percentage shall be as follows: Secondary School Certificate (SSC) or equivalent = 10% Intermediate Pre-Medical / (HSSC) or equivalent = 40% MDCAT = 50%` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found in visible text; 10/40/50 follow from it | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |
| KB-11 | for BS / AD 1st semester, merit is the aggregate percentage in the qualifying examination, Intermediate. | https://admission.hed.gkp.pk/admission.php | `Merit shall be determined by the aggregate percentage in the qualifying examination (Matriculation for Intermediate, Intermediate for BS / AD 1 st semester` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found in visible text; the 1st-semester merit rule follows from the cut-off quote | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-12 | per-university admission rules (non-medical): per university, batch 5; no KP-wide rule found. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |
| KB-13 | ETEA's own engineering/medical test rules and schedule: not read (portal only lists links). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-03 | under ELIGIBILITY: candidates having domicile of Khyber Pakhtunkhwa/ Newly Merged Districts (NMTD). | https://cas.kmu.edu.pk/ | `ELIGIBILITY The candidate must have passed obtaining minimum 65% marks in Higher Secondary School Certificate or F.Sc (Pre-Medical) or equivalent qualification from any BISE in Pakistan or abroad. The candidates who have passed the Medical & Dental Colleges Admission Test (MDCAT) 2024/2025/2026 with minimum 55% marks for MBBS and 50% marks for BDS. The candidates having domicile of Khyber Pakhtunkhwa/ Newly Merged Districts (NMTD).` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found in visible text; domicile sentence follows from it | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |
| KB-06 | quotas include Open Merit, Self Finance, Receiprocal, Disabled, Backward, NMTD, OPF, Minorities, Army Public School Victims, Afghan Nationals, Foreign Self Finance. | https://cas.kmu.edu.pk/ | `Open Merit Self Finance Receiprocal Disabled Backward Newly Merged Area District (NMTD) OPF (Overseas Pakistan Foundation) Minorities General Self Finance Minorities Army Public School Victims Afghan Nationals Foreign Self Finance` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Tests

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-02 | MDCAT 2024/2025/2026 with minimum 55% for MBBS and 50% for BDS. | https://cas.kmu.edu.pk/ | `The candidates who have passed the Medical & Dental Colleges Admission Test (MDCAT) 2024/2025/2026 with minimum 55% marks for MBBS and 50% marks for BDS.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KB-09 | entrance-test listing on the testing agency portal: only in hidden markup (an HTML comment); no visible official source read. | — | **no official source found** | 2026-11-07 | no official source found (hidden markup only) | n/a: gap line, no source or quote to check | n/a: no URL: gap line; check 2 v2 re-run 2026-11-07 on changed lines only |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-05 | separate Application Processing Fee for MBBS and BDS: MBBS = 3000/-, BDS = 3000/- (no currency stated). | https://cas.kmu.edu.pk/ | `Separate Application Processing Fee will be charge for MBBS and BDS Programs MBBS = 3000/- BDS = 3000/-` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found in visible text; 3000/- each, no currency in quote | correct: quote found word for word (html, visible text, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |
| KB-08 | documents include the domicile certificate of the father (or mother and father's death certificate). | https://cas.kmu.edu.pk/ | `Domicile certificate of father of the applicant. If father is not alive, then domicile certificate of mother and the death certificate of father.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-10 | visible entries carry a province label, e.g. this row; the count in the Lists table is a markup_count (unconfirmed on import). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `Abasyn University Khyber Pakhtunkhwa` | 2026-11-07 | markup_count (count from HTML attributes; the quote is a visible row showing the province label) | correct: quote found word for word in visible HTML text (HTTP 200, 2026-11-07); statement says it is a markup count and the quote is a real visible HEC row, the province label is in the row's li text | correct: quote found word for word (html, markup, HTTP 200); check 2 v2 re-run 2026-11-07 on changed lines only |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-07 | admission form available on cas.kmu.edu.pk from 01.10.2026; last date 21.10.2026. | https://cas.kmu.edu.pk/ | `Availability of Admission form on https://cas.kmu.edu.pk 01.10.2026 2 Last date for submission of admission Forms 21.10.2026` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Khyber Pakhtunkhwa | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date | **47** (36 public, 11 private) | markup_count: counted HTML attributes (unconfirmed on import) |

## Gaps

- KB-12: per-university admission rules (non-medical): per university, batch 5; no KP-wide rule found.
- KB-13: ETEA's own engineering/medical test rules and schedule: not read (portal only lists links).
- KB-09 was marked wrong by check 2: the ETEA test link text sits inside an HTML comment on the page, so it is not visible text. Not used.

## Check summary

- Lines: 13; cited: 11; gaps: 2.
- Check 2: correct 10, wrong 1, unclear 0, n/a 2 (run 2026-11-07T19:58:01.129271+00:00).
- Check 1 (blind, 2026-11-07): correct 5, wrong 2, unclear 4, n/a 2.
