# Slice 2 quality gate report

**Result: GATE FAILED (0 of 3 runs passed).** Correct rate passes every run; confirmed rate fails every run.
Per spec §9 and plan Task 10 step 4, work stops here: the owners decide (spec Q1). The key and the thresholds
were not changed.

| | |
|---|---|
| Date | 2026-10-20, 09:41–09:49 UTC |
| Code | `os/s2-t10-gate` at `23cb019` (PR #65), on `pai-os` with Slice 2 Tasks 1–9 |
| Command | `python -m tests.os.quality.run_research_quality --model openai --runs 3 --min-cycle 2026` |
| Model | `gpt-5.4-mini` (cheap tier), readings A and B, C when a field has one valid reading |
| Pages | live, through the production page gateway (139 fetched, 128 readable; robots.txt respected) |
| Answer key | `backend/tests/os/quality/spike1_answer_key.yaml`, version 3 (unchanged) |
| Bars (every run) | correct ≥ 0.95 and confirmed ≥ 0.70 |
| Full results | `docs/os/quality/slice2-gate-20261020T094059Z.json.gz` (every verdict, its evidence and reasons) |

## Runs

| Run | Correct (of confirmed) | Confirmed (of scored) | Cost | Time | Reading errors | Result |
|---|---|---|---|---|---|---|
| 1 | 91 / 92 = **0.989** | 92 / 184 = **0.500** | $0.71 | 237 s | 11 | FAIL (confirmed) |
| 2 | 86 / 87 = **0.989** | 87 / 184 = **0.473** | $0.39 | 132 s | 4 | FAIL (confirmed) |
| 3 | 96 / 96 = **1.000** | 96 / 184 = **0.522** | $0.37 | 93 s | 2 | FAIL (confirmed) |
| All | 273 / 275 = 0.993 | 275 / 552 = 0.498 | **$1.46** | | 17 | |

For comparison, Spike 1 (the same key, `min_cycle 2026`, the Spike 1 rules) reached correct 0.969–0.992 and
confirmed 0.690–0.739. The production rules trade confirmed facts for correctness, as the replay of the Spike 1
readings predicted (#59, #65: correct 0.99–1.00, confirmed 0.54–0.57).

## Wrong facts (2 of 275 confirmed)

1. **TU Chemnitz Automotive Software Engineering, `application_route`** (run 1): confirmed `uni_assist`, key
   `direct`. The quote is the university-wide uni-assist rule. Readings A and B gave a real scope quote that names
   the programme ("Note on the application procedure for the following Master's degree programmes: … Automotive
   Software Engineering …"), but that note is the **exception** (the direct-application pilot), not the rule
   quoted. **Cause:** the scope check (rule 6) tests that the scope quote is near the quote and names the
   programme, not that it belongs to the same rule. This is the D3 defect again, now through a scope quote.
2. **TU Freiberg Computational Materials Science, `grade_requirement`** (run 2): confirmed `german_max 2.0`, key
   `percent_min 75`. The page (DAAD) says "at least 75% … equivalent to 2.0 (German grading system)". **Cause:** the
   page states both forms, and the key and matcher accept only the percentage. Arguably not wrong; it needs a ruling
   on the key (both forms) rather than a code change.

## Why facts stayed unconfirmed (277 of 552)

The main reason per unconfirmed fact, summed over the three runs (a fact can fail several rules; the first
matching row counts):

| Reason | Facts | What it means |
|---|---|---|
| `single_reading` | 45 | Only one reading was valid, and C did not add a second (or a reading had errored). |
| `not_found` | 45 | No reading reported the field: the pages read do not state it, or a needed page was not collected. |
| `scope_unclear` (alone) | 44 | The fact came from a page that does not name the programme, with no scope quote that does. |
| `cycle_unknown` | 29 | An amount or date with no year on the page (mostly fee pages). |
| `value_not_in_quote` (alone) | 24 | The quote does not state the value (paraphrase, or the value is in another sentence). |
| combinations with `scope_unclear` / `quote_not_on_page` | 51 | Several checks failed at once. |
| `readings_disagree` | 13 | Two valid readings gave different values. |
| `list_not_complete` | 11 | One intake or test without "only" (D1 rule). |
| `cycle_old` | 6 | The page shows an older cycle than 2026. |
| `scores_on_other_page` | (in combinations) | A CEFR level alone while a handout lists test scores (D2 rule). |

By field, confirmed out of scored across the three runs: language 54/75, application route 46/75, tuition
33/75, semester contribution 30/57, deadline close 27/75, English 25/72, deadline open 17/39, grade 14/24,
intakes 13/33, German 12/15, admission test 4/12. Deadlines and English requirements are the weakest.

## A bug found by the gate (affects production too)

16 of the 17 reading errors are `RuntimeError: … is bound to a different event loop` (the 17th is a model
timeout). The runner reads programmes on 4 threads. Each `run_sync` uses its thread's event loop, but all
readers share one `AsyncOpenAI` client, whose connection pool is bound to the first loop. **The worker has the
same pattern:** the DBOS queue runs up to 4 research workflows at once on threads, sharing the readers. In
production a failed reading is recorded as an error and the facts stay unconfirmed (nothing is wrong, but less
is confirmed). This bug explains part of runs 1 and 2. It does not explain the gate failure: run 3 had only 2
errors and reached 0.522.

## What the owners need to decide (spec Q1)

The parent spec's fallbacks are to show more facts as unconfirmed (labelled, with the "Ask the university" draft)
or to use fewer programmes. The options:

1. **Ship with the current rules and accept a ~0.50 confirmed rate.** Correctness is 0.99. Unconfirmed facts are
   already labelled for students, re-researched daily, and sit in the admin queue with their evidence. The cost is
   more admin confirmations: about half of the facts.
2. **Improve and re-run the gate (about $1.50).** The changes most likely to raise the confirmed rate, in order of
   expected effect:
   - fix the shared-client bug (one client per event loop): recovers the errored readings;
   - read the programme's own start pages as programme-specific (most `scope_unclear` cases are the programme's
     official page or its FAQ, whose title does not repeat the name);
   - let a fee with no year count when it is not cycle-bound in practice, or have the reader copy the year from the
     page header (the `cycle_unknown` cases);
   - tighten the scope rule so a scope quote must not come from a different rule's exception list (wrong fact 1).
3. **Lower the bar** (for example confirmed ≥ 0.50 per run), with the correct-rate bar kept at 0.95.

My recommendation: option 2 for the bug fix and the start-page scope change (both are small), then one re-run.
If it still falls short, choose between options 1 and 3.

## Sign-off

- Developer review: ☐ (not yet signed)
- Owners' decision on Q1: ☐
