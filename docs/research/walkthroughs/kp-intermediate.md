# Khyber Pakhtunkhwa walkthrough: intermediate family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Khyber Pakhtunkhwa. Family: `intermediate` (master R-38). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** as in `national.md`: official URLs only (admission.hed.gkp.pk, hed.gkp.pk, bisep.edu.pk, cas.kmu.edu.pk, etea.edu.pk, hec.gov.pk), verbatim quotes with whitespace collapsed, date read, read method. Nothing from memory; batch 4 v4 served only as a lead. National rules are in `national.md`. Each statement says only what its own quote says.

**Check 2 (independent, v2):** a separate script re-downloaded every URL into a new folder and, using only the URL, quote and statement: (1) listed every number, date and proper name in the statement and failed the line if any is missing from the quote; (2) searched the quote word for word in the page's visible text (HTML comments and scripts removed; raw markup only for markup counts). It also recounted the lists. **Check 1** is blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KI-01 | the admission portal is run by the HEMIS Cell of the Higher Education, Archives & Libraries Department, Government of Khyber Pakhtunkhwa. | https://admission.hed.gkp.pk/colleges.php | `HEMIS CELL - Higher Education, Archives & Libraries Department , Government of Khyber Pakhtunkhwa` | 2026-11-07 | curl + HTML text strip (comments removed) | unclear: (a) quote found in visible text; (b) quote only names the cell (footer credit), it does not say the cell runs the portal | correct: quote found word for word (html, visible text, HTTP 200) |
| KI-10 | the Board of Intermediate & Secondary Education Peshawar (BISEP) has its own site. | https://www.bisep.edu.pk/ | `Board of Intermediate & Secondary Education Peshawar :: BISEP` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KI-02 | the online admission system covers Intermediate, Associate Degree and Bachelors programs. | https://admission.hed.gkp.pk/ | `Online Admission System Door step to Higher Education Intermediate Programs Associate Degree Programs Bachelors Programs` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Eligibility rules

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KI-05 | for the 1st year of Intermediate, minimum marks follow the relevant Board (BISE). | https://admission.hed.gkp.pk/admission.php | `For admission to the 1st year of Intermediate, the minimum marks shall align with the policy of the relevant Board (BISE).` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KI-06 | merit is the aggregate percentage in the qualifying examination (Matriculation for Intermediate, Intermediate for BS / AD 1st semester). | https://admission.hed.gkp.pk/admission.php | `Merit shall be determined by the aggregate percentage in the qualifying examination (Matriculation for Intermediate, Intermediate for BS / AD 1 st semester` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KI-07 | Hafiz-e-Quran candidates get twenty (20) additional marks at Intermediate Part-I, AD 1st semester and BS 1st semester. | https://admission.hed.gkp.pk/admission.php | `Twenty (20) additional marks shall be awarded to the Hafiz-e-Quran candidates for admission at Intermediate Part-I, AD 1 st semester and BS 1 st semester.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KI-08 | five (05) marks per year/session are deducted for candidates who passed in previous year(s). | https://admission.hed.gkp.pk/admission.php | `Five (05) marks per year/session shall be deducted from candidates’ who passed their last examination in previous year(s).` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KI-09 | upper age limit for male candidates: Intermediate Part-I 19 years; AD/BS 1st semester 22 years; BS 5th semester 25. | https://admission.hed.gkp.pk/admission.php | `Intermediate Part-I 19 years AD 1 st Semester/ BS 1 st Semester 22 years BS 5 th Semester 25` | 2026-11-07 | curl + HTML text strip (comments removed) | wrong: (a) quote found; (b) 'upper age limit' and 'male candidates' are not in the quote (they are in the preceding page sentence); 'years' for BS 5th also not in quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KI-03 | Open Merit is forty percent (40%) of seats, for Pakistani citizens on merit. | https://admission.hed.gkp.pk/admission.php | `Open Merit: Forty percent (40%) of the total seats are reserved for Pakistani citizens on merit basis.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KI-04 | Local Quota is forty five percent (45%) of seats, for the college's jurisdictional area. | https://admission.hed.gkp.pk/admission.php | `Local Quota: Forty Five percent (45%) of the total seats are reserved for candidates belonging to the jurisdictional area of the college.` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KI-11 | participating colleges list on the admission portal: dynamic, showed 'No Participant College...' to a plain download; not countable. | https://admission.hed.gkp.pk/colleges.php | `Participating Colleges All Colleges (Both Commerce & Degree Colleges) No Participant College...` | 2026-11-07 | curl + HTML text strip (comments removed) | correct: quote found word for word in visible text (HTTP 200); statement follows from quote | correct: quote found word for word (html, visible text, HTTP 200) |
| KI-12 | official list of KP's BISE boards: no official source read (HED page has no list; the board pages read are single boards). | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |
| KI-13 | private colleges / A-level schools in KP: no official list found. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| KI-14 | intermediate 2026 admission dates: no official source read. | — | **no official source found** | 2026-11-07 | no official source found | n/a: gap line, no URL or quote to check | n/a: no URL: gap line |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HED KP (HEMIS) | Participating colleges | https://admission.hed.gkp.pk/colleges.php | not stated | **not readable** | dynamic page; plain download shows none |

## Gaps

- KI-12: official list of KP's BISE boards: no official source read (HED page has no list; the board pages read are single boards).
- KI-13: private colleges / A-level schools in KP: no official list found.
- KI-14: intermediate 2026 admission dates: no official source read.
- KMU's 2026-27 provisional merit list rows on the page were inside HTML comments (an old 2024 date); not used.

## Check summary

- Lines: 14; cited: 11; gaps: 3.
- Check 2: correct 11, wrong 0, unclear 0, n/a 3 (run 2026-11-07T19:58:01.129271+00:00).
- Check 1 (blind, 2026-11-07): correct 9, wrong 1, unclear 1, n/a 3.
