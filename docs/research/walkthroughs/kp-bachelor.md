# Khyber Pakhtunkhwa walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Khyber Pakhtunkhwa. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (admission.hed.gkp.pk, hed.gkp.pk, bisep.edu.pk, cas.kmu.edu.pk, etea.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-01 | eligibility: minimum 65% in Higher Secondary School Certificate or F.Sc (Pre-Medical) or equivalent from any BISE in Pakistan or abroad. | https://cas.kmu.edu.pk/ | `The candidate must have passed obtaining minimum 65% marks in Higher Secondary School Certificate or F.Sc (Pre-Medical) or equivalent qualification from any BISE in Pakistan or abroad.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KB-04 | aggregate: SSC 10%, Intermediate Pre-Medical (HSSC) 40%, MDCAT 50%. | https://cas.kmu.edu.pk/ | `Secondary School Certificate (SSC) or equivalent = 10% Intermediate Pre-Medical / (HSSC) or equivalent = 40% MDCAT = 50%` | 2026-11-07 | curl + HTML text strip (comments removed) | unclear: (a) found; (b) the word 'aggregate' is not in the quote (page heading says Aggregate Percentage just before the quote) | correct: quote found word for word (html, visible text, HTTP 200) |
| KB-11 | for BS / AD 1st semester, the qualifying examination is Intermediate. | https://admission.hed.gkp.pk/admission.php | `Intermediate for BS / AD 1 st semester` | 2026-11-07 | curl + HTML text strip (comments removed) | unclear: (a) found; (b) 'qualifying examination' is not in the quote, which is only 'Intermediate for BS / AD 1 st semester' | correct: quote found word for word (html, visible text, HTTP 200) |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-12 | per-university admission rules (non-medical): per university, batch 5; no KP-wide rule found. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |
| KB-13 | ETEA's own engineering/medical test rules and schedule: not read (portal only lists links). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-03 | candidates need a domicile of Khyber Pakhtunkhwa / Newly Merged Districts (NMTD). | https://cas.kmu.edu.pk/ | `The candidates having domicile of Khyber Pakhtunkhwa/ Newly Merged Districts (NMTD).` | 2026-11-07 | curl + HTML text strip (comments removed) | unclear: (a) found; (b) quote says candidates having domicile, 'need' (requirement) is not stated in the quote alone (page lists it under ELIGIBILITY) | correct: quote found word for word (html, visible text, HTTP 200) |
| KB-06 | quotas include Open Merit, Self Finance, Receiprocal, Disabled, Backward, NMTD, OPF, Minorities, Army Public School Victims, Afghan Nationals, Foreign Self Finance. | https://cas.kmu.edu.pk/ | `Open Merit Self Finance Receiprocal Disabled Backward Newly Merged Area District (NMTD) OPF (Overseas Pakistan Foundation) Minorities General Self Finance Minorities Army Public School Victims Afghan Nationals Foreign Self Finance` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Tests

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-02 | MDCAT 2024/2025/2026 with minimum 55% for MBBS and 50% for BDS. | https://cas.kmu.edu.pk/ | `The candidates who have passed the Medical & Dental Colleges Admission Test (MDCAT) 2024/2025/2026 with minimum 55% marks for MBBS and 50% marks for BDS.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KB-09 | the portal lists the UET - ETEA Entrance Test 2026 (Test-II). | https://etea.edu.pk/ | `UET - ETEA Entrance Test 2026 (Test-II)` | 2026-11-07 | curl + HTML text strip (comments removed) | wrong: (a) quote appears only inside an HTML comment <!--<li>...-->, not visible text; line is already declared 'not used' | wrong: quote only in hidden markup (HTML comment/script), not visible text (HTTP 200) |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-05 | application processing fee: MBBS 3000, BDS 3000. | https://cas.kmu.edu.pk/ | `MBBS = 3000/- BDS = 3000/-` | 2026-11-07 | curl + HTML text strip (comments removed) | wrong: (a) found; (b) 'application processing fee' is not in the quote, which only gives 'MBBS = 3000/- BDS = 3000/-' (no currency, no fee label) | correct: quote found word for word (html, visible text, HTTP 200) |
| KB-08 | documents include the domicile certificate of the father (or mother and father's death certificate). | https://cas.kmu.edu.pk/ | `Domicile certificate of father of the applicant. If father is not alive, then domicile certificate of mother and the death certificate of father.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-10 | recognised list items with Province='Khyber Pakhtunkhwa' (count in Lists table). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `Province='Khyber Pakhtunkhwa'` | 2026-11-07 | curl + count of list items in the HTML markup | unclear: (a) quote is an HTML attribute (Province='Khyber Pakhtunkhwa'), not visible text; markup-count line. My recount: 47 (36 public, 11 private), matches | correct: quote found word for word (html, markup, HTTP 200) |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KB-07 | admission form available on cas.kmu.edu.pk from 01.10.2026; last date 21.10.2026. | https://cas.kmu.edu.pk/ | `Availability of Admission form on https://cas.kmu.edu.pk 01.10.2026 2 Last date for submission of admission Forms 21.10.2026` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Khyber Pakhtunkhwa | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date | **47** (36 public, 11 private) | counted items in the markup (check 2 recount) |

## Gaps

- KB-12: per-university admission rules (non-medical): per university, batch 5; no KP-wide rule found.
- KB-13: ETEA's own engineering/medical test rules and schedule: not read (portal only lists links).
- KB-09 was marked wrong by check 2: the ETEA test link text sits inside an HTML comment on the page, so it is not visible text. Not used.

## Check summary

- Lines: 13; cited: 11; gaps: 2.
- Check 2: correct 10, wrong 1, unclear 0, n/a 2 (run 2026-11-07T19:58:01.129271+00:00).
- Check 1 (blind, 2026-11-07): correct 5, wrong 2, unclear 4, n/a 2.
