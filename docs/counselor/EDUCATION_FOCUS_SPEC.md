# Education focus spec (25 Oct 2026)

Founder decision after the end-to-end audit: PAI C is an educational counselor. Its job is to help a student
choose a professional field of study and then a place to study it. Hobbies, side work and personal stories are
supporting evidence only, never the goal of the conversation.

## 1. Onboarding captures current education exactly
Step 2 of onboarding asks, with taps only:
1. **Where are you now?** Matric · O-level · Intermediate · A-level · DAE (diploma) · Bachelor's · Master's ·
   Other.
2. **Which group?** Shown only for the first answer that has one:
   - Matric: Science (Biology) · Science (Computer) · Arts
   - Intermediate: FSc Pre-Engineering · FSc Pre-Medical · ICS · I.Com · FA
   - O-level / A-level: subject chips (multi-select)
   - DAE: technology (Electrical, Mechanical, Civil, Electronics, Computer, …)
   - Bachelor's / Master's: the field, from the study-fields list
3. **Status:** studying (1st or 2nd year) or completed (year).
Marks stay optional (later, by chat card or result card).
All answers become ONE education record, Stated, through the existing propose → reconcile door. Intermediate
keeps today's codes: Pre-Engineering and Pre-Medical are qualification `fsc` with `field_of_study`
`pre_engineering` or `pre_medical`; ICS, I.Com and FA keep `ics`, `icom`, `fa`. Lists live in the Vault catalog.
Date of birth, gender, country and city stay as they are.

## 2. Study fields, and which fields a group opens
A data file (`pai_c/policy/study_fields.json`) lists the fields of study students in Pakistan and abroad
actually choose (Electrical Engineering, Computer Engineering, Software Engineering, Computer Science, MBBS,
Pharm-D, BBA, Architecture, …). Each entry has: `key`, `title`, `family`, `levels` (e.g. bachelor, diploma),
its ISCED-F code (kept for PAI OS, never shown), `open_to` (the groups that qualify) and `check` (groups that may
qualify with conditions, e.g. ICS for some engineering; decided by research, never by memory).

## 3. Paths are fields, never forced
- The path analyzer picks only from study fields open to (or `check` for) the student's group.
- Titles are the field titles ("Electrical Engineering"). No generic ISCED labels.
- Between 0 and 5 paths, only those with real fit (subjects, stated interest, marks, budget, city and
  mobility). If the education or enough signal is missing, no paths, and PAI says what it still needs.
- A `check` field carries "needs checking for your group" until research confirms it.
- Existing paths with the old generic titles are replaced on the next analysis.

## 4. PAI stays on education
- PAI asks only what helps choose a field: subjects liked and strong, marks, the field they lean toward and
  why, entrance test plans (ECAT, MDCAT, NAT, SAT…), budget range, city and willingness to move, family's wish
  about the field.
- Hobbies, side work and stories are saved if the student mentions them, as supporting evidence, but PAI does
  not ask about them unless they help decide between two fields.
- One question per reply when an education basic is missing; no praise; no repeating the student's words back.
- Unchanged: one counselor voice, safety first, places only after a field, no fees or merit from memory.
