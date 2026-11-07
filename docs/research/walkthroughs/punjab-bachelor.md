# Punjab walkthrough: bachelor family

P2 people-lane item H2 (master spec §8.4; P2 spec §6.2). Region: Punjab. Family: `bachelor` (master R-37). Researched and drafted by Claude on 2026-11-07.

**Rules and methods** are the same as in `national.md`: every line has an official URL (hed.punjab.gov.pk, ocas.punjab.gov.pk, biselahore.com, uhs.edu.pk, uet.edu.pk, hec.gov.pk), a verbatim quote, the date read and the read method (`curl + HTML text strip` or `curl + pdftotext`); whitespace is collapsed in quotes. Nothing is from memory; the batch 2 v4 workbook served only as a lead. National rules (IBCC equivalence, MDCAT, HEC lists) are in `national.md` and are not repeated.

**Check 2 (independent):** a separate script re-downloaded every URL into a new folder and searched each quote word for word, without the draft's statements; it also recounted the lists. **Check 1** is left blank for a separate blind pass.

## Bodies

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-01 | UHS Lahore is the admitting university for public medical and dental colleges in Punjab. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `The University of Health Sciences (UHS), Lahore, as the Admitting University for Punjab, is entrusted with the responsibility of conducting admissions to public sector medical and dental colleges across the province.` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |

## How admission works

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-02 | UHS merit: SSC 10%, HSSC 40%, MDCAT 50%. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Matriculation/SSC/Equivalent – 10% F.Sc./HSSC Pre-Medical / equivalent – 40% MDCAT – 50%` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-03 | MBBS/BDS in Punjab needs at least 60% in HSSC pre-medical or equivalent. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `The applicant must have passed, obtaining minimum 60 percent marks, in Higher Secondary School Certificate (HSSC) Pre-Medical Group or equivalent examination having minimum twelve years of education.` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-04 | Applicants with foreign qualifications must get IBCC equivalence themselves. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `It shall be the responsibility of the candidates having foreign qualifications to settle their cases with IBCC and should get equivalence certificate from IBCC for recognition of their qualification and score.` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-05 | Public-sector applicants must rank all colleges in order of preference. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Choose all colleges in order of preference from the dropdown menu; It is mandatory that ALL options must be selected according to the seat category.` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-06 | There may be three or more selection lists. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `There may be three or more rounds/lists of selection of candidates depending on the availability of vacant seats.` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-20 | OCAS also takes BS/ADP admission to Punjab's public colleges. | https://ocas.punjab.gov.pk/ | `Online College Admissions System (OCAS) is built to provide easy, convenient, efficient and reliable access to students for Bachelors and Intermediate admissions in the public colleges of Punjab.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

## Seat categories

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-07 | Open merit seats need a domicile of any Punjab district. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Open Merit Seats: These seats are open to applicants having valid domicile certificate of any district of Punjab` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-08 | Punjab-domiciled categories: open merit, under-developed districts, disabilities, Cholistan, reciprocal. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Open Merit, Under-Developed Districts, Students with Disabilities, Cholistan, and Reciprocal (for Punjab-domiciled candidates in other provinces/regions) categories of seats.` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-09 | Overseas Pakistanis / dual nationals need no domicile for their quota seats. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Overseas Pakistanis/residents with dual nationality do not require a domicile for applying to their quota seats.` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-10 | Public MBBS+BDS seats 2026-27: grand total 4491 in the seat table (batch 2 also noted 4391 in the policy annex; not re-read here). | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Grand Total 4081 20 1 66 66 27 39 60 5 20 30 38 38 4491` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-18 | UET Lahore admission categories include A1, A2 and A1-M/A2-M. | https://admission.uet.edu.pk/downloads | `covering A1, A2, and A1-M/A2-M categories.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

## Tests

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-15 | UET runs ECAT; ECAT Fall 2026 (Second) fee Rs 3000. | https://ecat.uet.edu.pk/ | `Fee - Rs. 3000 /- Last Date - Jun 13, 2026` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PB-16 | ECAT Fall 2026 (Second) exam window 16-21 June 2026; result 30 June 2026. | https://ecat.uet.edu.pk/ | `Jun 16, 2026 -- Jun 21, 2026` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

## Official lists

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-22 | HEC recognised list: universities/DAIs with Province='Punjab' (count in Lists table). | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | `Province='Punjab'` | 2026-11-07 | curl + count of list items in the HTML markup | | correct: quote found word for word (html, HTTP 200) |
| PB-23 | HED's own list of public universities under HED (not counted; it is a partial list by city). | https://hed.punjab.gov.pk/public-universities | `The public sector universities working under the umbrella of HED are as follows:` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PB-24 | UHS list of private medical and dental colleges: in the prospectus, not counted in this pass. | — | **no official source found** | 2026-11-07 | not counted (see batch 2 Institutions sheet) | | n/a: no URL: gap line |

## Documents

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-11 | UHS application processing fee Rs 2000, non-refundable. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Generate a fee challan of Rs. 2000/- for the non-refundable application processing fee` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-17 | ECAT photo ID may be CNIC, passport, matric/first-year certificate or domicile. | https://ecat.uet.edu.pk/ | `Original Photo ID may be CNIC or Passport or Matric/First Year Certificate or Domicile.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |
| PB-19 | UET admission documents include CNIC copies, academic documents, domicile, NOC where applicable. | https://admission.uet.edu.pk/downloads | `bank challan, medical certificate, biodata form, photographs, undertaking, CNIC copies, academic documents, domicile, and NOC where applicable.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

## Rules not found

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-25 | Per-university admission rules for non-medical, non-UET universities: per university, batch 5; no Punjab-wide rule found. | — | **no official source found** | 2026-11-07 | no official source found | | n/a: no URL: gap line |
| PB-26 | Punjab domicile issuance rules: no official source read. | — | **no official source found** | 2026-11-07 | no official source found | | n/a: no URL: gap line |

## Calendar

| # | Line | Source URL | Verbatim quote | Read | Method | Check 1 | Check 2 |
|---|---|---|---|---|---|---|---|
| PB-12 | UHS MBBS 2026-27 online application opens Friday 16 October 2026 (tentative schedule). | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Friday, 16 October, 2026` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-13 | UHS MBBS final order of merit Monday 16 Nov 2026; first selection list Tuesday 17 Nov 2026. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Final Order of Merit Monday, 16th November, 2026 Saturday, 9th January, 2027 6. First College-wise Selection List Tuesday, 17th November, 2026` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-14 | MBBS classes start Monday 1 Feb 2027; BDS Monday 1 Mar 2027. | https://www.uhs.edu.pk/images/Prospectus26.pdf | `Commencement of classes Monday, 1st February, 2027 Monday, 1st March, 2027` | 2026-11-07 | curl + pdftotext (PDF text layer) | | correct: quote found word for word (pdf, HTTP 200) |
| PB-21 | OCAS opened for bachelor admissions by 7 Oct 2026. | https://ocas.punjab.gov.pk/ | `Oct 07, 2026 OCAS Portal is Live for Intermediate and Bachelor Admissions.` | 2026-11-07 | curl + HTML text strip | | correct: quote found word for word (html, HTTP 200) |

### Lists table

| Body | List | URL | Date | Rows | How |
|---|---|---|---|---|---|
| HEC | Recognised universities/DAIs, Province = Punjab | https://www.hec.gov.pk/english/universities/pages/recognised.aspx | no publication date (HTTP Last-Modified 2026-11-07) | **105** (57 public, 48 private) | counted `Province='Punjab'` items in the markup |
| HED Punjab | Public / private universities under HED | https://hed.punjab.gov.pk/public-universities , https://hed.punjab.gov.pk/private_universities | not stated | not counted | partial lists by city; use the HEC list as the denominator |
| UHS | Public and private medical/dental colleges in the 2026-27 prospectus | https://www.uhs.edu.pk/images/Prospectus26.pdf | Session 2026-2027 | not counted in this pass | batch 2 v4 has these rows; the PMDC national list (190) is the national denominator |

## Gaps

- PB-24: UHS list of private medical and dental colleges: in the prospectus, not counted in this pass.
- PB-25: Per-university admission rules for non-medical, non-UET universities: per university, batch 5; no Punjab-wide rule found.
- PB-26: Punjab domicile issuance rules: no official source read.
- UET's admission merit formula and its 2026 schedule PDF: the PDF at the batch 2 URL now holds a different (leftover-seats) schedule and is a scan in Urdu; not used.
- ECAT 2027 dates: not published on the page read.

## Check summary

- Lines: 26; cited: 23; gaps: 3.
- Check 2: correct 23, wrong 0, unclear 0, n/a 3 (run 2026-11-07T19:46:14.935780Z).
- Check 1: not done yet.
