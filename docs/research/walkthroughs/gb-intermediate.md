# Gilgit-Baltistan walkthrough: intermediate family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Gilgit-Baltistan. Family: `intermediate` (master R-38). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (doecgb.gov.pk, examinations.kiu.edu.pk, dapr.kiu.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GI-01 | the Directorate of Education (Colleges) Gilgit Balistan supervises college/higher level education in Gilgit-Baltistan. | https://www.doecgb.gov.pk/institutions | `The Directorate of Education (Colleges) Gilgit Balistan is attached Department, facilitating and supervising the College/Higher level Education in Gilgit-Baltistan.` | 2026-11-07 | curl + HTML text strip (comments removed) | | correct: quote found word for word (html, visible text, HTTP 200) |
| GI-02 | the examinations site lists the Date Sheet HSSC 1st Annual Examination 2026. | https://examinations.kiu.edu.pk/ | `Date Sheet HSSC 1st Annual Examination 2026` | 2026-11-07 | curl + HTML text strip (comments removed) | | correct: quote found word for word (html, visible text, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GI-04 | each listed college has an 'Apply Online for Admission' link. | https://www.doecgb.gov.pk/institutions | `S.No Institution Name Email Apply Online for Admission` | 2026-11-07 | curl + HTML text strip (comments removed) | | correct: quote found word for word (html, visible text, HTTP 200) |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GI-06 | intermediate merit rules, quotas and calendar for GB colleges: no official source found. | — | **no official source found** | 2026-11-07 | no official source found | | n/a: no URL: gap line |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GI-03 | public college list: last serial 27 (count in Lists table). | https://www.doecgb.gov.pk/institutions | `27 Govt. Boys I/C Chatorkhand, Ghizar` | 2026-11-07 | curl + HTML text strip (comments removed) | | correct: quote found word for word (html, visible text, HTTP 200) |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| GI-05 | Registration Notification of SSC-I for the Session 2026-2028 dated 06 Jul, 2026. | https://examinations.kiu.edu.pk/ | `06 Jul, 2026 Registration Notification of SSC-I for the Session 2026-2028` | 2026-11-07 | curl + HTML text strip (comments removed) | | correct: quote found word for word (html, visible text, HTTP 200) |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| Directorate of Education (Colleges) GB | List of Public Sector Govenment Colleges in Gilgit Baltistan | https://www.doecgb.gov.pk/institutions | not stated | **27** | counted rows (serials 1–27) |

## Gaps

- GI-06: intermediate merit rules, quotas and calendar for GB colleges: no official source found.
- The KIU examinations page names 'Affiliated Institutions'; that list was not opened (A-level / private colleges, P2 §11 Q4).

## Check summary

- Lines: 6; cited: 5; gaps: 1.
- Check 2: correct 5, wrong 0, unclear 0, n/a 1 (run 2026-11-07T20:03:38.600627+00:00).
- Check 1: not done yet.
