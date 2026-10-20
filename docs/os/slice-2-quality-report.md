# Slice 2 quality gate report

**Result: GATE PASSED under the owners' pilot bar (3 of 3 runs, in both gates).**

## Owners' decision (spec Q1), 2026-10-20

At the original bar (correct ≥ 0.95, confirmed ≥ 0.70 in every run), both gates failed on the confirmed rate
(about 0.50) while the correct rate held at 0.99. After the fix-and-re-run (option 2), the owners chose to
**lower the confirmed-rate bar to 0.45 per run for the pilot**, and to **keep the correct-rate bar at 0.95**.

- 0.45 was chosen because a 0.50 bar would still fail: the lowest runs were 0.473 (first gate) and 0.467
  (re-run).
- **Re-scored** against the new bars, with no new model calls:

  | Gate | Runs (correct / confirmed) | Result |
  |---|---|---|
  | First, `23cb019` | 0.989 / 0.500, 0.989 / 0.473, 1.000 / 0.522 | 3 / 3, **PASS** |
  | Re-run, `ee41481` | 0.990 / 0.538, 0.988 / 0.467, 0.989 / 0.489 | 3 / 3, **PASS** |

- **What it means for students:** "✓ checked" facts are right about 99% of the time. About half of the facts
  show as "⚠ unconfirmed", with an "Ask the university" draft. They are re-researched daily and queued for an
  admin with their evidence.
- **Conditions:**
  1. Before the pilot, an admin confirms TU Chemnitz Automotive Software Engineering's route by hand (`direct`).
     It is the one fact research gets wrong, in every run of the re-run.
  2. Improve the programme start URLs in the seed (the admission, deadline and fee pages). This is the main lever
     on `not_found`, then the bar should go back up.
  3. Re-gate with `min_cycle 2027` once WS 2027/28 is published (spec §9).
- **Where the bar lives:** `PASS_CONFIRMED` in `backend/tests/os/quality/scoring.py`, with this decision cited.
  The answer key was not changed.

The rest of this report is the record of the two gates as run, against the original 0.70 bar.

## Re-run after the fixes (2026-10-20, 10:31–10:45 UTC, `ee41481`)

The fixes, on PR #65:
- **One event loop for all readings.** The first gate lost 16 readings to "bound to a different event loop".
  `test_readings_from_several_threads_share_one_loop` reproduces it. The test that checks each model request is
  still a DBOS step was extended.
- **A programme's own start pages are programme-specific**, together with the pages in their folder. These are
  the start URLs no other programme in the registry uses. A shared university-wide start page stays general, so
  the D1–D5 regressions still pass.

| Run | Correct | Confirmed | Cost | Reading errors | Result |
|---|---|---|---|---|---|
| 1 | 98 / 99 = **0.990** | 99 / 184 = **0.538** | $0.45 | 0 | FAIL (confirmed) |
| 2 | 85 / 86 = **0.988** | 86 / 184 = **0.467** | $0.37 | 2 (OpenAI timeouts) | FAIL (confirmed) |
| 3 | 89 / 90 = **0.989** | 90 / 184 = **0.489** | $0.34 | 0 | FAIL (confirmed) |
| All | 272 / 275 = 0.989 | 275 / 552 = 0.498 | **$1.16** | 2 | |

Full results: `docs/os/quality/slice2-gate-20261020T103154Z.json.gz`.

**What changed:**
- **The bug is gone:** no event-loop errors.
- **The scope fix worked:** facts blocked only by `scope_unclear` fell from about 15 per run to about 8.
- **The confirmed rate did not move.** The largest reason is now **`not_found`** (23–29 facts per run, up from
  13–18): no reading reported the field, because the pages collected (the seed's start URLs plus up to 5 ranked
  links) do not state it. Next come `single_reading` (11–17), `cycle_unknown` (6–11) and `readings_disagree`
  (4–9).
- **The ceiling of these fixes:** even if every `not_found` fact were found *and* confirmed, a run would reach
  about 0.64, still under 0.70.

**The wrong fact** (all three runs): TU Chemnitz Automotive Software Engineering, `application_route`. It is
confirmed `uni_assist`, but the key says `direct`. This is the same scope-quote case as in the first gate: the
scope sentence names the programme in the direct-application pilot's exception list. It is the only wrong fact in
the re-run.

**What would raise the rate further** (each is larger than a fix):
1. **Better start URLs per programme.** This is data work by a developer: add each programme's admission,
   deadline and fee pages to the seed. It is the main lever on `not_found`.
2. **Relax rules:** accept a fee with no year when the page has no year at all (`cycle_unknown`), or confirm on
   one valid reading for low-risk fields (`single_reading`). Either trades correctness for confirmations.
3. **Lower the bar** (option 3 below).

My recommendation: **accept the current rules for the pilot (option 1), with the correct-rate bar kept at 0.95**,
and do the start-URL work as a data task in parallel. Students see only facts that are right 99% of the time.
About half are labelled "unconfirmed" with an "Ask the university" draft, re-researched daily, and queued for an
admin with their evidence. Before the pilot, an admin should confirm the TU Chemnitz Automotive route by hand
(`direct`).

---

# The first gate (2026-10-20, 09:41–09:49 UTC, `23cb019`)

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
- Owners' decision on Q1: ☑ 2026-10-20: confirmed bar 0.45 per run for the pilot, correct bar 0.95 kept (see the
  top of this report)
