# Spike 5 part 1: Germany master's playbook walkthrough

**Route:** Pakistani bachelor's graduate → English-taught master's at a German public university,
winter semester 2027/28 (spec D3). **Status:** draft for the reviewer's citation check.
**Checked:** 2026-10-17 by Claude for @MusawirKtk. **Reviewer:** @10Faheem (see §6).

Spec §5, row 5: "before Slice 1: every step cites an official page, checked by the reviewer".
This is research only. It records what the official pages say, step by step. The playbook format
(YAML, fields, `task_type` names) is decided in the Slice 1 spec, not here.

## 1. How the facts are recorded

Every fact follows the Knowledge rules of spec §3.2: an official source, the URL, an exact quote,
the date checked, the intake year, and a status.

- **Official source** means a German or Pakistani public body or the body that runs the procedure:
  a university, uni-assist, DAAD, the Federal Foreign Office and German missions in Pakistan, and
  HEC for Pakistani degree attestation. No agency, forum or listing site is cited.
- **Quote** is copied word for word from the page, including its typos. Quotes marked *(via fetch
  tool)* come from pages that block direct download (DAAD). The reviewer must re-read those first.
- **Intake year.** Every fact is checked against WS 2027/28.
  - A **procedural rule** on a current page with no year attached (for example "upload once") counts
    as applying to WS 2027/28.
  - **Amounts of money, dates and processing times** count only if the page names WS 2027/28 or
    2027. Otherwise they stay `unconfirmed` and are re-checked before use: the freshness sweeper
    re-checks 30 and 7 days before a deadline (spec §3.2).
- **Status** is one of three values:
  - `confirmed`: an exact quote from an official page that applies to WS 2027/28 under the rule above.
  - `unconfirmed`: the page is old or undated, the fact is not tied to 2027/28, it is only a lead,
    or no official page was found.
  - `conflict`: two official pages disagree. In Knowledge this is stored as `unconfirmed`, which is
    the spec's term. The spec has no `conflict` value, so the Slice 1 spec should decide whether to
    add it.
- **Second reading.** The spec's "two independent readings agree" is met by the reviewer re-reading
  every cited page (§6). My reading is the first.
- **Dates.** Each source line gives the page's own date where it shows one. "Undated" means the page
  shows none.

Citation IDs (`S1`…) refer to the source list in §5.

## 2. Route-level steps (the same for every programme)

The steps are grouped by phase. "Depends on" names earlier steps. "Lead time" is what the official
pages say about how long a step takes. When a step needs a per-programme fact, it names the field
from §3 in `[brackets]`.

### Phase A: documents

**A1. HEC attestation of the bachelor's degree and transcripts.**
Who: student (online), after the degree or transcript is issued. Depends on: none.
- uni-assist requires HEC attestation for Pakistani degrees: "your Degree certificate including an
  overview of subjects and grades (if available) with the Higher Education Commission (HEC)
  attestation stamps" (S1). **confirmed**
- HEC attestation is now fully online: "The Higher Education Commission (HEC) has introduced a fully
  online, paperless Degree Attestation System, replacing the previous process of attestation." (S8).
  **confirmed**
- The outcome is an e-certificate, not a stamp: "Applicants are notified via SMS and email for
  issuance of e-Attestation Certificate." and "Attestation of photocopies is no longer offered." (S8).
  **conflict** with S1's "attestation stamps". It is not clear whether uni-assist accepts the HEC
  e-Attestation Certificate in place of stamps. Resolve this by asking uni-assist or a uni-assist
  university before the playbook is final.
  - Update 2026-10-17: the developers report that uni-assist now accepts the HEC e-Attestation
    Certificate. No official page saying so was found (search of uni-assist.de, pakistan.diplo.de
    and hec.gov.pk). This stays **unconfirmed** until the source is attached here, for example the
    uni-assist reply or page.
- Transcripts can be attested before the degree: "Transcripts (complete or incomplete) can be
  attested even if the final degree has not been issued." (S8). **confirmed**
- Data must match: "their personal details on the CNIC and all educational documents are identical"
  (S8). **confirmed**
- Fee: "The attestation fee is Rs. 3,000 per document (degree, transcript, provisional certificate,
  or HEC equivalence letter)." (S8). **unconfirmed** for 2027, because it is an amount.
- Lead time: no official processing time was found on S8. **unconfirmed**: this needs a research
  task.

**A2. School certificates (SSC and HSSC).**
Who: student. Depends on: none.
- "your school leaving certificate including an overview of subjects and grades (X and X+II)" (S1).
  **confirmed**
- IBCC attestation or equivalence: no German official page checked asks for it (S1, S2, S10–S14).
  The old-OS lead (§4) is **unconfirmed**, so this is not a step unless a programme asks for it
  `[required_documents]`.

**A3. Statement of the minimum passing grade.**
Who: student, from their university. Depends on: none.
- "the minimum passing grade for your degree to be awarded." and "The minimum grade for passing a
  single course or semester is not sufficient" (S1). **confirmed**

**A4. The university's grading system.**
Who: student. Depends on: none.
- "In order to calculate your grade, we need the grading system used by your university in the award
  your degree." (S2). **confirmed**. Grade conversion inputs `[grade_requirement]` follow from this.

**A5. Translations: normally none.**
- "If your country issues your education certificates (additionally) in German or English, we do not
  need a translation (exceptions are listed under Info country by country)." (S2). **confirmed**. S1
  lists no translation exception for Pakistan.
- If a document is in Urdu: "There are no sworn translators in Paksitan." (S10). **confirmed**. The
  translation must then come from a translator in Germany, or from the issuing institution's
  authorised department (S2).

**A6. Certified paper copies, only if a programme asks for them.**
Condition: `[certified_copies_required]`. uni-assist itself is digital (S6).
- "If you need certified copies of your school/university/education documents in order to apply at
  German University, you can get this done at our embassy in Islamabad and our consulate general in
  Karachi." (S10). **confirmed**
- "Please submit your original certificates along with corresponding copies (no cross attestation by
  the HEC Pakistan required) and your passport in the same order." and "Only a maximum of 4 sets of
  copies can be attested per person and day." (S10, dated 14.04.2026). **confirmed**

**A7. English test.**
Who: student. Depends on: none. The minimum score is per programme `[english_requirement]`.
- For the visa: "Sufficient language skills for the intended degree programme, unless a preparatory
  language course precedes the degree programme" (S13). **confirmed**
- The leaflet lists "Confirmation of sufficient language skills in the language of instruction"
  (S15, dated 10/2023). **unconfirmed**: the leaflet is old.
- Whether a medium-of-instruction letter is accepted varies by programme `[english_requirement]`.

**A8. Admission test (GRE, GATE or TestAS), only if a programme asks for one.**
Condition: `[admission_test]`. No route-level rule exists. The shortlist shows that some programmes
require one for non-EHEA degrees. Each such requirement is a per-programme fact.

**A9. CV, motivation letter and references.**
- The visa needs a CV, "Curriculum Vitae" (S15, 10/2023), and a "Motivation letter" (S16, undated).
  **unconfirmed**: the Consular Services Portal now generates the document list (S11).
- For admission these are per-programme documents `[required_documents]`.

**A10. APS: not a step for Pakistan.**
- "It exists in China, Vietnam and India." and "For these countries, the APS certificate is a
  requirement for applying to a German university." (S3). **confirmed**: Pakistan is not listed.
  Re-check before each intake.

### Phase B: application

**B1. Pick the application route for each programme.**
The routes are uni-assist standard, uni-assist VPD then a direct application, or direct only
`[application_route]`.
- "You can find out if your chosen university has instructed uni-assist to use the special VPD
  procedure by checking our database: uni-assist universities." (S4). **confirmed**
- For VPD: "Please allow sufficient time for your application because you still need to apply to the
  university directly, using the VPD." (S4). **confirmed**
- "You can apply for a VPD at any time. It is valid for one year from the date of issue" (S7).
  **confirmed**

**B2. uni-assist application: upload, pay, submit.**
Depends on: A1–A5, A7. Condition: the route uses uni-assist.
- "Yes. The application via uni-assist is fully digital." (S6). **confirmed**
- Documents are uploaded once: "You need to upload each document only once, even if you wish to apply
  to multiple universities." (S2). **confirmed**
- Fees: "Cost for the first chosen course of study: EUR 75.00", "For each additional chosen course of
  study: EUR 30.00" and "The costs are the same for all forms of application, whether standard or
  VPD procedure." (S5). **unconfirmed** for 2027, because these are amounts. Some universities pay the
  fee for their applicants `[uni_assist_fee_paid_by_university]`.
- Payment time: "International bank transfers can take up to two weeks." (S6). **unconfirmed**: this
  is a processing time.
- **Lead time:** "Tip: Apply as early as possible, at least 8 weeks before the application deadline
  expires if possible." and "You will usually receive your evaluation result within 4 to 6 weeks –
  counting from the day on which we received your online application form." (S6). **unconfirmed** as
  numbers for 2027. These are the best official lead times available: submit at least 8 weeks before
  `[deadline_close]`.
- Hard rule: "We can only forward applications to the universities that were submitted complete
  within the application deadline." (S6). **confirmed**

**B3. Direct application in the university portal.**
Condition: the route is direct, or VPD then direct. The portal and the documents are per programme
`[portal_url]`, `[required_documents]`, `[deadline_close]`. There is no route-level source beyond B1.

**B4. Admission letter received; accept and enrol.**
The decision date, the acceptance deadline and the enrolment rules are per programme
`[decision_date]`, `[enrolment_deadline]`, `[late_arrival_policy]`. For the visa, the portal requires
a "Letter of admission for a course of study at a state or state-recognised university" (S13).
**confirmed**

### Phase C: visa (Islamabad or Karachi)

**C1. A visa is required.**
- In the Federal Foreign Office list, the row for Pakistan reads "yes" under "Entry visa required
  no/yes" (S12, dated 03.06.2026). **confirmed**
- "Visas for study purposes are usually issued for a period of up to one year." (S13). **confirmed**

**C2. Open a blocked account, or use another proof of funds.**
Depends on: none stated on S9. Who: student and bank.
- Amount: "From 1 January 2025 the presumed annual requirement that must be paid into the blocked
  account when applying for a visa will increase to 992,00 Euros monthly or 11.904,00 Euros yearly."
  (S9, dated 27.11.2025). The portal also says "To commence studying, you must prove that you have at
  your disposal at least 992 euros per month" (S13). **conflict** with two older embassy documents:
  "blocked account (11,208 EUR for one year)" (S15, dated 10/2023) and "Confirmation letter for the
  blocked account with an amount of 10,236 €" (S16, undated).
  - Resolution: the newest dated page (S9) wins today.
  - For WS 2027/28 the amount stays **unconfirmed**, because it is set per year. Re-check in 2027.
- Provider: "However, please ensure that the provider offers a login code for authorities which
  allows us to verify the blocked account or provides a contact in order to do so." (S9).
  **confirmed**
- Signature attestation: "Your signature on the documents to open a blocked account has to be
  attested by the Embassy in Islamabad, the Consulate General in Karachi or the Honorary Consul in
  Lahore." (S9). **confirmed**
  - It is a separate appointment: "Please note that you have to book the online appointment for
    submission of your visa application seperately." (S9). **confirmed**
  - Fee: "The fee to be paid directly at the Embassy is 25,- € (about 5400 PKR), but may change due to
    exchange rate." (S9). **unconfirmed**: this is an amount.
- Alternatives: a deed of obligation from a sponsor in Germany, or a scholarship. "Please note that a
  scholarship awarded by a Pakistani University is not sufficient, only a scholarship awarded by HEC
  can be accepted." (S9). **confirmed**

**C3. Travel health insurance for the visa.**
- "Travel health insurance" and "valid from intended date of travel" (S15, 10/2023).
  **unconfirmed**: the leaflet is old, and the portal's questionnaire is the current list (S11).

**C4. Apply on the Consular Services Portal.**
Depends on: B4, C2, C3.
- "The Consular Service Portal provides a full digital solution to the application process." and
  "All required documents will appear after the interactive questionnaire" (S11, dated 27.11.2025).
  **confirmed**
- Which mission:
  - "The Embassy Islamabad is open for applicants from the Islamabad Capital Territory,
    Gilgit-Baltistan, Khyber Pakthtunkwa, Azad Jammu & Kashmir and the Punjab." (S11). **confirmed**
  - "Applicants from Sindh and Baluchistan can submit their applications for Student Visa at this
    link:" (S11, Karachi). **confirmed**
- Mandatory from the start: "Past degree certificates (school, bachelor or past master degrees)",
  "Degree transcripts" and "Proof of payment of tuition fees (if applicable to the course of study)"
  "are mandatory documents and must be submitted from the outset." (S11). **confirmed**
- Passport: "validity of passport: at least one year plus three months" (S15, 10/2023).
  **unconfirmed**: the leaflet is old.
- Visa fee: "in the amount of 75 EUR, to be paid in PKR" (S15, 10/2023). **unconfirmed**: this is an
  amount from an old leaflet.

**C5. Visa lead time: the biggest open risk.**
- "While the Consular Services Portal has led to an overall increase in finalized applications, we
  are aware that ongoing demand still exceeds our capacity." (S11). **confirmed** as a statement.
  The page gives no waiting time, so the lead time is **unconfirmed** and needs a research task.
- Mitigation from the same page: "However, every student can actively assist the process by
  submitting either proof of acceptance of late arrival at your university or an enrollment letter
  for next semester." (S11). **confirmed**. This makes `[late_arrival_policy]` a planning field.

### Phase D: after arrival

**D1. Register the address.**
- "you have to go to the Einwohnermeldeamt (residents' registration office) within two weeks." (S17,
  *via fetch tool*). **unconfirmed** until the reviewer reads the page directly.

**D2. Health insurance for enrolment.**
- "International students have to prove equivalent health insurance coverage that meets German
  health insurance standards" (S18, *via fetch tool*). **unconfirmed** until re-read.

**D3. Enrol at the university.** The documents and the deadline are per programme
`[enrolment_deadline]`, `[required_documents]`.

**D4. Residence permit before the visa expires.**
- "you must report to the Ausländerbehörde (foreigners' office) and apply for a residence permit."
  (S17, *via fetch tool*). **unconfirmed** until re-read.
- The legal basis on the embassy leaflet is "§ 16b Residence Act" (S15). **unconfirmed**: the
  leaflet is old.

## 3. Per-programme facts: fields to research (Spike 1, not researched here)

Each programme in the shortlist (`PAI-OS-Programme-Shortlist-WS2027.xlsx`, 30 rows, kept by the
developers) gets these fields from its own official page, under the same rules as §1. The shortlist's
values are leads, all marked unconfirmed for WS 2027/28 by its author. Row 18 (BTU Power Engineering)
already shows a deadline conflict, and rows 7, 8 and 13–15 cite only third-party listings.

- `programme_page_url`, `daad_listing_url`: official programme page, plus the DAAD entry as a lead.
- `degree`, `language_of_instruction`, `intake` (winter only?), `start_date`.
- `deadline_open`, `deadline_close`: the application window for non-EU applicants for WS 2027/28.
  Also any earlier date for visa applicants (the shortlist notes one for TU Ilmenau). Stored with the
  institution's timezone; end of day unless the page says otherwise (invariant 13).
- `application_route`: uni-assist standard / uni-assist VPD then direct / direct (B1). `portal_url`.
- `uni_assist_fee_paid_by_university` (B2).
- `tuition_fee_non_eu`: amount per semester, and the rule it comes from. `semester_contribution`:
  amount, and when it is paid.
- `english_requirement`: accepted tests and minimum scores, and whether a medium-of-instruction letter
  is accepted. `german_requirement`.
- `grade_requirement`: the minimum grade and how it is converted. Inputs: the university's grading
  system (A4) and the minimum passing grade (A3). The OS result is always labelled *estimated* (spec
  §3.2 grade converter).
- `degree_requirements`: ECTS or credit minimum, degree length, subject background, required modules.
- `admission_test`: GRE / GATE / TestAS and minimum scores, if any (A8).
- `required_documents`: CV, motivation letter, number of references, module descriptions, work
  experience, school certificates, IBCC documents if asked (A2).
- `certified_copies_required` (A6).
- `decision_date`, `enrolment_deadline`, `late_arrival_policy` (B4, C5).

## 4. Old-OS leads re-checked

These are the sourced packs named in handoff §6. They were used as leads only.

- **`de.json`, DAAD requirements overview** (`daad.de/en/studying-in-germany/requirements/overview/`):
  not re-read. DAAD pages refuse automated download (HTTP 403) and the browser was refused too, so
  this lead is not cited. The Slice 2 research agent will meet the same block.
- **`de.json`, uni-assist educational certificates:** the old URL now redirects to S2. The content was
  re-read and is used in A4, A5 and B2.
- **`de.json`, uni-assist Pakistan page:** re-read (S1). It is the main source for A1–A3.
- **`de.json`, APS ("do not presume it for Pakistan"):** re-read (S3). Correct: APS covers China,
  Vietnam and India only (A10).
- **`pk.json`, HEC degree attestation:** re-read (S8). The process has changed to a fully online
  e-Attestation, which creates the A1 conflict.
- **`pk.json`, IBCC equivalence:** the page is reachable. IBCC equivalence is a Pakistani procedure,
  and no German page checked requires it for Pakistani SSC/HSSC (A2). **unconfirmed**; it is kept
  only as a per-programme document.
- **`pk.json`, MOFA attestation** (`apostille.mofa.gov.pk/sops`): the page could not be fetched. No
  German page checked asks for MOFA attestation. The embassy says certified copies need "no cross
  attestation by the HEC Pakistan" (S10). Not a step; **unconfirmed**.
- **`pk.json`, CGPA has no universal percentage conversion:** consistent with uni-assist asking for
  the university's own grading system (A4).
- **`gap_assessment` logic:** a rule is compared only when it has an https source URL, a check date
  and a machine-comparable threshold. The results are `met`, `fixable` (a cited remediation exists),
  `blocking` or `unknown`. A missing student fact becomes an upload request. This matches the trust
  rules above and is a reference for the Slice 1 eligibility check; it is not copied as code.

## 5. Sources

Checked 2026-10-17. "Undated" means the page shows no date.

- S1. uni-assist, Info country by country: Pakistan. https://www.uni-assist.de/en/tools/info-country-by-country/details-country/country/pk/ (undated)
- S2. uni-assist, Educational certificates & translations. https://www.uni-assist.de/en/how-to-apply/plan-your-application/educational-certificates-translations/ (undated)
- S3. uni-assist, Glossary: Akademische Prüfstelle (APS). https://www.uni-assist.de/en/tools/glossary-of-terms/description/term/akademische-pruefstelle-aps/ (undated)
- S4. uni-assist, FAQs: Plan your application. https://www.uni-assist.de/en/faqs/plan-your-application/ (undated)
- S5. uni-assist, Pay & submit. https://www.uni-assist.de/en/how-to-apply/apply-online/pay-submit/ (undated)
- S6. uni-assist, FAQs: Apply online. https://www.uni-assist.de/en/faqs/apply-online/ (undated)
- S7. uni-assist, Checklist: VPD in 3+1 steps (PDF). https://www.uni-assist.de/fileadmin/Downloads/Tools/Checklisten/EN/UA-Checkliste-VPD-Verfahren-EN.pdf (undated)
- S8. Higher Education Commission Pakistan, Degree Attestation. https://www.hec.gov.pk/english/services/students/das/Pages/Degree-Attestation.aspx (undated)
- S9. German Missions in Pakistan, How to finance your stay. https://pakistan.diplo.de/pk-en/service/1995528-1995528 (27.11.2025)
- S10. German Missions in Pakistan, Legal (certified copies, translations). https://pakistan.diplo.de/pk-en/service/legal-uess-1680522 (14.04.2026)
- S11. German Missions in Pakistan, Visa: Students. https://pakistan.diplo.de/pk-en/service/2-study-visa-seite-1676104 (27.11.2025)
- S12. Federal Foreign Office, Overview of visa requirements/exemptions. https://www.auswaertiges-amt.de/en/visa-service/-/231148 (03.06.2026)
- S13. Federal Foreign Office, Consular Services Portal: Studying and seeking a university place. https://digital.diplo.de/studium (undated; the page renders with JavaScript)
- S14. IBCC, Equivalence application process. https://ibcc.edu.pk/equivalence-application-process/ (undated; used only in §4)
- S15. German Missions in Pakistan, Student § 16b Residence Act checklist leaflet (PDF). https://pakistan.diplo.de/resource/blob/2208710/4a44b499964d27c04ecb6e5770fdb824/study-visa---leaflet-data.pdf ("Stand 10/2023")
- S16. German Consulate General Karachi, Checklist of required documents for student and language course visas (PDF). https://pakistan.diplo.de/resource/blob/2290888/dbca85b1c7f634f1a1290ec15a71ac76/checklist---student---language-course-visas-data.pdf (undated)
- S17. DAAD, Residence permit & address registration. https://www.daad.de/en/studying-in-germany/living-in-germany/registering/ (undated; via fetch tool)
- S18. DAAD, Healthcare and health insurance. https://www.daad.de/deutschland/nach-deutschland/bewerbung/en/58221-health-insurance/ (undated; via fetch tool)

## 6. Open points for the reviewer and the Slice 1 spec

1. **A1 conflict:** does uni-assist accept the HEC e-Attestation Certificate in place of "attestation
   stamps"? The developers report yes (2026-10-17). Attach the source (the uni-assist reply or page)
   to close it.
2. **Unknown lead times:** HEC attestation (A1) and the visa (C5). The visa backlog is the largest
   planning risk, because a winter start with June–July deadlines leaves little time.
3. **Amounts for 2027** (blocked account, fees) are unconfirmed until 2027 pages exist. The freshness
   sweeper must re-check them.
4. The **`conflict` status** is not in spec §3.2. The Slice 1 spec should decide whether to add it.
5. **Blocked automated reading:** DAAD and Make it in Germany refused automated access. The
   Slice 2 research agent needs a compliant way to read them (spec §3.2: robots.txt respected).
6. **Old visa checklists** (S15, S16) describe the paper process. The portal (S11, S13) is now the
   source of truth for the document list. Facts that come only from S15/S16 stay unconfirmed.

### Automated pre-check (2026-10-17)

An independent Claude reviewer agent re-fetched every source itself, without reusing the author's
files, and matched the quotes.
- **Result:** 64 quotes checked, every real quote matched.
- **Weaker checks:**
  - S13 needs JavaScript, so the reviewer read it in a browser.
  - S17 and S18 (DAAD) were readable only through a summarising fetch tool. D1, D2 and D4 therefore
    stay `unconfirmed`.
- **Control test:** to prove the check is not a rubber stamp, the reviewer was given a copy with two
  planted errors and was not told about them: the HEC fee changed to Rs. 2,500, and "Pakistan" added
  to the APS country list. It flagged both, quoting the real page text.

This pre-check does not replace the human reviewer below.

### Reviewer check (second reading)

For each source, open the URL, find the quoted text, and confirm it is the official body named. Tick
it, or write what differs.

- [ ] S1 · [ ] S2 · [ ] S3 · [ ] S4 · [ ] S5 · [ ] S6 · [ ] S7 · [ ] S8 · [ ] S9
- [ ] S10 · [ ] S11 · [ ] S12 · [ ] S13 · [ ] S14 · [ ] S15 · [ ] S16 · [ ] S17 · [ ] S18
- Reviewer: ______ · Date: ______ · Verdict (every step cites an official page): ______
