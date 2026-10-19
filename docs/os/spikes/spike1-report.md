# Spike 1 report: research of the 30 shortlist programmes

**Verdict: PASS (3 of 3 final runs), with a thin margin on the confirmed rate.** Pending the
developers' sign-off and their check of the 3 key questions in §5.

Design: `docs/os/spikes/spike1-design.md`. Code: `backend/spikes/spike1/` (how to run: its
`README.md`). Answer key: `backend/tests/os/quality/spike1_answer_key.yaml`. Full results of the final
runs (every fact's verdict, quote, URL and reasons; `wrong`, `extras_for_review`,
`unsettled_for_review`): `docs/os/spikes/spike1-results/run9.json`, `run10.json`, `run11.json`.

## Pass bar (parent §5, row 1)

- **Correct rate** (agent-confirmed scored facts that match the key) ≥ 0.95.
- **Confirmed rate** (agent-confirmed scored facts ÷ scored facts) ≥ 0.70.

Scored facts: 184 (non-null key fields in the 25 settled rows, excluding `open_fields`; 197 before the
key corrections in §4). All runs: `--min-cycle 2026` (SP1-D1, option A), model `gpt-5.4-mini`, the same
page cache (175 pages), 2026-10-19, run on the user's Windows machine.

## Final runs (three readings, SP1-D6 ruling)

| Run | Confirmed | Correct | Correct rate | Confirmed rate | Fabricated quotes | Programmes needing reading C | Cost (printed) | Time | Bar |
|---|---|---|---|---|---|---|---|---|---|
| 9 | 136 | 130 | **0.956** | **0.739** | 15 | 22 | $1.01 | 54 s | PASS |
| 10 | 129 | 125 | **0.969** | **0.701** | 30 | 25 | $1.05 | 60 s | PASS |
| 11 | 130 | 125 | **0.962** | **0.707** | 22 | 22 | $1.04 | 60 s | PASS |

Tokens over the three runs: 3.12M input, 0.17M output. No reading errors. The printed cost uses the
parent §9 prices; check the OpenAI usage page for the billed figure.

**Per field** (sum over the 3 runs; each field is scored 3 times):

| Field | Scored ×3 | Confirmed | Correct |
|---|---|---|---|
| language_of_instruction | 75 | 72 | 69 |
| tuition_fee_non_eu_eur | 75 | 40 | 40 |
| semester_contribution_eur | 57 | 39 | 39 |
| deadline_open | 39 | 27 | 27 |
| deadline_close | 75 | 44 | 44 |
| application_route | 75 | 65 | 63 |
| english_requirement | 72 | 37 | 31 |
| german_requirement | 15 | 11 | 10 |
| grade_requirement | 24 | 19 | 19 |
| admission_test | 12 | 9 | 9 |
| intakes | 33 | 32 | 29 |

Dates and amounts confirm least often: a page that gives "15 July" with no year cannot pass the
cycle rule (`cycle_unknown`, 20–24 facts per run). That is the rule working, not a reading failure.

**Why facts stay unconfirmed** (per run, runs 9 / 10 / 11): quote not on the page 27 / 43 / 36,
readings disagree 20 / 27 / 23, cycle unknown 20 / 20 / 24, single reading 18 / 26 / 22, URL not read
2 / 2 / 0, not official 1 / 2 / 0, cycle older than 2026 1 / 2 / 1. (A fact can have several reasons.)

## Every run, in order (nothing hidden)

| Run | Change before it | Correct rate | Confirmed rate | Bar |
|---|---|---|---|---|
| 1 | first billed run (two readings) | 0.862 | 0.700 | FAIL |
| 1 rescored | answer key corrected (§4), same outputs | 0.937 | 0.685 | FAIL |
| 2 | prompt rules: no menu labels as quotes, all English scores, language definitions, intakes | 0.940 | 0.630 | FAIL |
| 3 | quote check accepts a table label and value, or a cut passage, in order within 400 characters; prompts: copy quotes exactly | 0.954 | 0.701 | PASS |
| 4 | none (repeat) | 0.952 | 0.674 | FAIL |
| 5 | none (repeat) | 0.954 | 0.701 | PASS |
| 6 | reading A also asked for "not required" answers and opening dates | 0.959 | 0.658 | FAIL |
| 7 | none (repeat) | 0.959 | 0.669 | FAIL |
| 8 | none (repeat) | 0.939 | 0.712 | FAIL |
| 9–11 | reading A's prompt back to run 3; **reading C** when A or B gave no valid reading for some field | 0.956–0.969 | 0.701–0.739 | PASS ×3 |

Runs 3–8 show that a single run moves by about ±0.03 on the same input, more than the prompt changes
gained. Prompt tuning was stopped there to avoid fitting the prompts to the key. The change that held
(reading C) is structural, not a prompt tweak. Total printed cost of all 11 runs: about $9.

## The answer key corrections (after run 1)

Each comes from an official quote that the run verified on the page. They are also recorded in the
key's header.

| Programme(s) | Field | Was | Now | Why |
|---|---|---|---|---|
| 17 rows | intakes | `[winter]` | null (not scored) | The developers' notes do not mention intakes there; the transcription had defaulted to winter only. DAAD and OVGU pages say "Winter and summer semester" for several of them. |
| OVGU EEIT, Data and Knowledge Engineering, Digital Engineering | semester contribution | ~277.90 | ~311.30 | DAAD: "Currently, the semester fee is 311.30 EUR." (the note itself called 277.90 a 2024/25 figure) |
| Saarland Embedded Systems | semester contribution | ~280 | 394.30 | DAAD: "an administrative fee of 394.30 EUR per semester" |
| TU Chemnitz Automotive Software Engineering, Web Engineering | German | none / A2 later | A1 with the application | TU Chemnitz application page: "Applicants applying for a degree programme offered in English language need to show a German language proof at minimum level A1 … at the time of application." **Developers to confirm**: the notes said no German was needed to apply. |

## Wrong facts in the final runs

| Programme / field | Runs | Agent's value and source | Likely cause |
|---|---|---|---|
| OVGU EEIT / English | 9, 10, 11 | B2, IELTS 6.5, TOEFL iBT 85, PTE 70 (DAAD 6091, current list) | **Key question:** the key has IELTS 6.0 / TOEFL 80 from an older DAAD reading. Developers check. |
| HSRW Mechanical Engineering / English | 9, 10, 11 | B2 (HSRW's master's application table: "Mechanical Engineering, M.Sc. / 2.5 / B2") | **Key question:** the key has C1 from DAAD. The university's own table says B2. |
| Paderborn Computer Science / language | 9, 10, 11 | english (DAAD: "All courses are held in English.") | **Key question:** the developers' note says "mostly English" (department page). Two official pages differ. |
| Anhalt ECE / intakes | 9, 10, 11 | winter only ("Intake winter semester 2026") | Agent: the page names one intake; the developers found a summer window too. |
| Koblenz / route | 9 | direct (a German page: route "depends on your previous education") | Agent: it read a conditional sentence as a route. |
| TU Chemnitz ASE / route | 9 | uni-assist (TU Chemnitz's list of who applies via uni-assist) | Agent: a university-wide rule applied to a programme that is direct. |
| TU Chemnitz ASE / German | 11 | level "none", with a quote that says A1 | **Agent: the value contradicts its own quote.** The quote check cannot catch this (§7, lesson 1). |

If the developers confirm the 3 key questions as key errors, the correct rate of every final run is at
or above 0.978.

## Lessons for the Slice 2 spec

1. **A verified quote does not verify the value.** Add a rule check that the numbers, dates and levels
   in a value appear in its quote (for example A1/B2, 15 July, 311.30), and send mismatches to
   unconfirmed.
2. **Two readings are not enough for a 0.70 confirmed rate; three are.** Keep the rule "every valid
   reading agrees, and at least two are valid": a third reading only fills a gap and never outvotes.
   It costs about 40% more (about $1.04 a run for 30 programmes, still far under the parent §9
   estimate of $190 a year).
3. **The cycle rule is the main limit on dates and amounts.** Re-run with `--min-cycle 2027` once
   WS 2027/28 is published (Feb–Mar 2027). That run gates real pilot data. The freshness sweeper
   should drive these re-checks.
4. **University-wide pages cause programme mix-ups** (TU Chemnitz lists rules for many programmes).
   Prefer the programme's own page and mark general pages as such in the prompt.
5. **Fabricated or reworded quotes are common** (15–43 per run) and the quote check catches them. It
   must stay deterministic and must allow table rows (label and value on separate lines).
6. **Score over three runs, not one:** a single run moves by about ±0.03.
7. **Reading pages:** DAAD detail pages were readable (contrary to Spike 5 §4); HISinOne portals are
   refused by robots.txt (fine: they are forms); several answer-key links are dead (HSRW, the TU
   Freiberg brochure). The standard-library HTML parser and `pypdf` were enough for these pages; the
   Slice 2 spec decides on Docling.
8. **`conflict` status (Spike 5 open point 4):** source conflicts showed up (Paderborn, OVGU EEIT,
   HSRW ME). `unconfirmed` with a `conflict_note` (S1-D6) carried them; a separate status is not needed
   for the trust flow. The Slice 2 spec decides whether the student screen needs one.
9. **The `language_of_instruction` values overlap** ("english" vs "mostly_english" vs
   "english_or_german"). For planning, the question is "can the student study fully in English"; the
   Slice 2 field list should say that.

## Sign-off

| Developer | Verdict | Date |
|---|---|---|
| @10Faheem | | |
| @MusawirKtk | | |
