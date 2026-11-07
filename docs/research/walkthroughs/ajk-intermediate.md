# Azad Jammu and Kashmir walkthrough: intermediate family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Azad Jammu and Kashmir. Family: `intermediate` (master R-38). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (hed.ajk.gov.pk, jac.ajk.gov.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AI-01 | the info desk says the secondary/intermediate examination is conducted by BISE Mirpur (its sentence begins 'in Punjab', verbatim). | https://hed.ajk.gov.pk/info-desk/ | `Examination of secondary/intermediate level in Punjab Examination is conducted by BISE Mirpur.` | 2026-11-07 | curl + HTML text strip (comments removed) | wrong: the parenthetical says the sentence begins 'in Punjab'; on the page it begins 'Examination of secondary/intermediate level in Punjab'. Quote is verbatim in visible text (HTTP 200); BISE Mirpur part follows from the quote | correct: quote found word for word (html, visible text, HTTP 200) |
| AI-09 | AJK BISE site (ajkbise.net): its home page carries injected gambling spam ('situs toto', 'slot gacor'); treated as suspect (R-71), nothing taken from it. | — | **no official source found** | 2026-11-07 | suspect domain; not used | n/a: gap line | n/a: no URL: gap line |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AI-02 | admission in Government Colleges for F.A/F.Sc starts immediately after the Secondary School Certificate results. | https://hed.ajk.gov.pk/info-desk/ | `Admission in Government Colleges for F.A/F.Sc shall commence immediately after the declaration of Secondary School Certificate results.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |
| AI-03 | admission is made by the head of institution within the days the head declares. | https://hed.ajk.gov.pk/info-desk/ | `will be made by the head of institution within the number of days declared by the head of institute for admission application.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AI-11 | intermediate seat categories / quotas: no official source found. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line | n/a: no URL: gap line |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AI-04 | British/American system students may seek F.A / F.Sc admission but must get certificates attested by BISE and apply for Equivalence. | https://hed.ajk.gov.pk/info-desk/ | `Foreign, Nationals or Pakistanis who have studied under British /American or similar system of education and have obtained equivalent certificates of Higher Secondary School Certificate may seek admission at F.A / F.Sc but shall have to get certificates attested by BISE and apply for Equivalence of certificates.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AI-05 | list of post graduate colleges: last row is 14 (count in Lists table). | https://hed.ajk.gov.pk/post-graduate-colleges/ | `14 POST GRADUATE COLLEGE FOR BOYS BHIMBER` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; 'last row' is not in the quote, but my recount of the table gives serials 1-14 in order | correct: quote found word for word (html, visible text, HTTP 200) |
| AI-06 | list of degree colleges: last row is 75. | https://hed.ajk.gov.pk/degree-colleges/ | `75 GIRLS Degree COLLEGE KEL` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim; my recount gives serials 1-75 in order ('last row' from recount, not quote) | correct: quote found word for word (html, visible text, HTTP 200) |
| AI-07 | list of model science colleges: last row is 7. | https://hed.ajk.gov.pk/model-science-colleges/ | `7 MODEL SCIENCE COLLEGE MIRPUR` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim; my recount gives 7 rows ('last row' from recount, not quote) | correct: quote found word for word (html, visible text, HTTP 200) |
| AI-08 | list of inter colleges: last row is 81. | https://hed.ajk.gov.pk/inter-colleges/ | `81 GIRLS INTER SCIENCE COLLEGE NARYOLA BAGH` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim; my recount gives serials 1-81 in order ('last row' from recount, not quote) | correct: quote found word for word (html, visible text, HTTP 200) |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AI-10 | 2026 intermediate admission dates: no official source found. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line | n/a: no URL: gap line |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HED AJ&K | Post Graduate Colleges | https://hed.ajk.gov.pk/post-graduate-colleges/ | not stated | **14** | counted table rows (serials 1–14) |
| HED AJ&K | Degree Colleges | https://hed.ajk.gov.pk/degree-colleges/ | not stated | **75** | counted table rows (serials 1–75) |
| HED AJ&K | Model Science Colleges | https://hed.ajk.gov.pk/model-science-colleges/ | not stated | **7** | counted table rows |
| HED AJ&K | Inter Colleges | https://hed.ajk.gov.pk/inter-colleges/ | not stated | **81** | counted table rows |
| HED AJ&K | all four lists | — | — | **177** | sum |

## Gaps

- AI-09: AJK BISE site (ajkbise.net): its home page carries injected gambling spam ('situs toto', 'slot gacor'); treated as suspect (R-71), nothing taken from it.
- AI-10: 2026 intermediate admission dates: no official source found.
- AI-11: intermediate seat categories / quotas: no official source found.
- Each HED AJ&K college page carries the banner 'The tests and interviews have been postponed due to a court stay order.' with no date or subject; not interpreted.

## Check summary

- Lines: 11; cited: 8; gaps: 3.
- Check 2: correct 8, wrong 0, unclear 0, n/a 3 (run 2026-11-07T20:02:18.437980+00:00).
- Check 1 (blind, 2026-11-07): correct 7, wrong 1, unclear 0, n/a 3. Lists recounted: matches.
