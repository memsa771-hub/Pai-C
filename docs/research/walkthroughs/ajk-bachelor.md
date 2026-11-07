# Azad Jammu and Kashmir walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Azad Jammu and Kashmir. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (hed.ajk.gov.pk, jac.ajk.gov.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AB-01 | the committee's page announces MBBS / BDS admissions for Government Medical Colleges of Azad Jammu & Kashmir (AJ&K) and reserved seats for AJ&K nationals in Pakistan, session 2026-2027. | https://jac.ajk.gov.pk/ | `MBBS / BDS ADMISSIONS Government Medical Colleges of Azad Jammu & Kashmir (AJ&K) and Reserved Seats for AJ&K Nationals in Pakistan, Session 2026-2027` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AB-02 | its mission is a merit-based medical admissions process through an online portal for students of AJ&K. | https://jac.ajk.gov.pk/ | `To facilitate a transparent and merit-based medical admissions process for students of AJ&K, ensuring equal opportunity and access through an efficient online portal.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; follows | correct: quote found word for word (html, visible text, HTTP 200) |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AB-06 | non-medical university admission in AJK: per university (batch 5). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line | n/a: no URL: gap line |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AB-03 | the committee publishes college allocation merit lists by category, e.g. AJK State Subject BDS. | https://jac.ajk.gov.pk/ | `Provisional 6th College Allocation Merit List AJK State Subject BDS` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: verbatim in visible text; 'by category' is a mild gloss on 'AJK State Subject BDS' but not wrong | correct: quote found word for word (html, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AB-04 | recognised list items with Province='Azad Jammu & Kashmir' (count in Lists table). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `Province='Azad Jammu & Kashmir'` | 2026-11-07 | curl + count of list items in the HTML markup | unclear: the quote Province='Azad Jammu & Kashmir' is not in the visible text, only in an HTML attribute (visible text shows 'Azad Jammu & Kashmir'). My recount of li elements with that Province: 9 (7 public, 2 private), matches the list | correct: quote found word for word (html, markup, HTTP 200) |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| AB-05 | JAC 2026-27 schedule, eligibility and fees: in a notice not read as text (batch 4 lead was a news-site image, not usable). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line | n/a: no URL: gap line |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Azad Jammu & Kashmir | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date | **9** (7 public, 2 private) | counted items in the markup |

## Gaps

- AB-05: JAC 2026-27 schedule, eligibility and fees: in a notice not read as text (batch 4 lead was a news-site image, not usable).
- AB-06: non-medical university admission in AJK: per university (batch 5).

## Check summary

- Lines: 6; cited: 4; gaps: 2.
- Check 2: correct 4, wrong 0, unclear 0, n/a 2 (run 2026-11-07T20:02:18.437980+00:00).
- Check 1 (blind, 2026-11-07): correct 3, wrong 0, unclear 1, n/a 2. Lists recounted: matches.
