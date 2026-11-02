# Live run issues: PAI counsellor + PAI OS (2 Nov 2026)

Branch `pai-merge`, local stack in live demo mode (real OpenAI for the counsellor and PAI OS; pretend sign-in,
logged email, rehearsal clock). One fictional student, five chat messages.

**Student:** Ayesha Malik (made up), Faisalabad, Punjab domicile. FSc Pre-Medical 970/1100, Matric 950/1100,
MDCAT 140/180. Wants MBBS first, BDS second, nothing else. Abroad only if local is not possible. Budget 15–20 lakh
rupees a year.

## Counsellor

| # | Severity | Issue | What happened |
|---|---|---|---|
| C1 | High | Excluded fields keep being suggested | Roadmaps lists Pharm-D, Medical Lab Technology and Biotechnology next to MBBS and BDS. They stay after the student asks to remove them; PAI says it "can't confirm" removing them. Partly caused by the pai-merge change that keeps paths a newer run leaves out (`87aa26f`): a field the student excludes must be dismissed. |
| C2 | High | One failed analysis blocks all later ones | On message 2 the planner's patch was rejected twice (`AnalysisPatchRejected`). Every later `counselor.analyze` then fails with "earlier analysis failed; replay required". The journey stays at Stage D. |
| C3 | High | Promised checks never happen | PAI says "I'll check official sources" for Punjab colleges and MBBS abroad. No research job starts (C2 blocks it) and the student is never told. |
| C4 | High | No merit answer | For "my UHS aggregate and last year's closing merit", research read Facebook posts and mdcatprep.com, then answered "I couldn't verify a reliable answer yet". The aggregate is a published formula; the Pakistan eligibility data layer is missing. |
| C5 | Medium | Chat and Roadmaps disagree | Chat cards show 1, then 2 paths (MBBS, BDS); Roadmaps shows 5. |
| C6 | Low | Language and greeting | A reply in Roman Urdu to an English message, then English again; "Wa alaikum assalam" twice. |
| C7 | Low | No marks in onboarding | Matric, FSc marks and MDCAT can only be given in chat. |

## Gaps between the counsellor and PAI OS

| # | Severity | Gap | What happened |
|---|---|---|---|
| G1 | High | No route for this student | PAI OS has one route: Pakistan → Germany, master's. Searching "MBBS" finds no programmes. Medical students, the counsellor's main audience, cannot plan abroad. |
| G2 | High | No hand-off | When the counsellor considers MBBS abroad, nothing reaches PAI OS: the decision export (`app/pai_c/os_export.py`) is not built. |
| G3 | High | OS ignores what the student said | It does not know she has FSc, offers master's programmes, and lists Biomedical Engineering first, a field she excluded. Budget, domicile and exclusions never reach it. |
| G4 | High | Stage H gate plus C2 | Outside the rehearsal, the plan opens at stage H. With C2 the journey stops at D, so a real student never reaches it. |
| G5 | Medium | Two sources for marks | Marks said in chat and mark sheets uploaded to PAI OS are kept apart; only the degree is compared. |

## What worked

- Onboarding offers Intermediate → FSc Pre-Medical; PAI greets the student by name.
- MBBS first and BDS second are kept in chat; marks, budget and domicile are noted.
- No merit numbers or admission chances are invented.
- The MBBS path page shows evidence in the student's own words.

## Suggested order

1. Counsellor, on pai-merge: C1 (a stated exclusion dismisses the field), C2 (one failure must not block every later
   analysis), C3 (every "I'll check" runs or tells the student it could not).
2. Product work: the Pakistan merit data (C4), an undergraduate/MBBS route in PAI OS (G1), the counsellor hand-off
   (G2, G3).
