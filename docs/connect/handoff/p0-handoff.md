# P0 handoff: setup and Counsellor fixes (DRAFT)

Status: draft, 2026-11-04. Phase spec: `docs/superpowers/specs/2026-11-03-p0-setup-design.md`. Master spec: `docs/superpowers/specs/2026-11-03-pai-connect-design.md` (§12 row P0, §13.5). The next phase (P1) starts by reading this file.

## 1. What was built

| Part | Result | Where |
|---|---|---|
| P0-T1 baseline green | `pai-merge` failures fixed at their cause (fastapi pin, OS inventory fates, tsc test errors) | `56a2035` |
| Task 0 setup | R-57 traceability check, R-58 country-name red-flag search, R-59 CI jobs and rulesets; freeze check and CODEOWNERS started (owned by P1) | `75a4b75`, `0900ff5` (PRs #177 and #178 were superseded by these squash commits) |
| Integration owner | Integration owner set to `@MusawirKtk` (master §15 Q5) | #179 |
| C2 | A failed analysis no longer blocks later ones (frozen file, freeze-exception) | #180 |
| C1, C3, C5, C7 | Excluded field not suggested again; recorded questions always get research or a notice; chat card and Roadmaps share one reader of current paths; onboarding asks for marks | #181 |
| C6 | Reply language follows the student's latest message; one greeting per conversation (frozen `deep/context.py`, freeze-exception) | #182 (also: PAI returns a student's salaam; removed greetings are not reliability failures) |
| R-47 | `built: true` in `docs/requirements/connection.yaml`; offline replay before and after in `docs/connect/replays/r47-diff.md` | #182 |
| Follow-ups from the final review | The newest paths card refreshes after a removal notice; a changed exclusion is re-stamped | #183 |
| CI health | An intermittent `tests/os` research test reads its task by base key | #185 |
| Round 2 (after live run 1) | R2-1 strengths count toward interests (P0-D15); R2-2 every "I'll check" opens research; R2-3 rejected patches say why; R2-4 an ignored question cools down; R2-5 quote check ignores dash/quote variants, no student data in drop logs | #187 |
| Round 2, R2-6 | PAI refers to itself as "hum" in Roman Urdu (frozen voice prompts, freeze-exception, P0-D16) | #186 |
| Live runs | Run 1: FAIL (stuck at stage D), $0.28. Run 2 after round 2: PASS, $0.31 | `docs/local-test/live-run-2026-11-04.md`, `live-run-2026-11-04b.md` |

## 2. Gate report (phase spec §6)

| # | Gate item | Status |
|---|---|---|
| 1 | P0-T1 and Task 0 merged into `pai-connect` with every CI job green | Merged. CI green on this branch: pending the C6 PR's CI run |
| 2 | `python scripts/check_traceability.py --gate P0` passes | Passes (exit 0) |
| 3 | Live-run student (Ayesha Malik) reaches stage H with only MBBS and BDS | PASS on 2026-11-04 (second live run, $0.31, 12 fixed messages, code = pai-connect + #186 + #187): stage H, MBBS exploring, BDS suggested, Pharm-D removed with her words. Caveat: the Explore action ran without a research Operator (see open items). First run failed at stage D; fixed by round 2 |
| 4 | Counsellor evaluations pass; a replay shows only the fixed behaviour changed | Offline replay only: no differences in default or guided mode (`docs/connect/replays/r47-diff.md`). Each fix is proved by its targeted tests |
| 5 | Handoff written; the owner signs off | Handoff drafted here. Sign-off pending from the owner, MSAQLAIN (`@memsa771-hub`) only (owner decision P0-D13; no sign-off from `@MusawirKtk` or `@10Faheem`) |

Output of `python scripts/check_traceability.py --report P0`:

| R-ID | Title | Built | Tests |
|---|---|---|---|
| R-47 | Counsellor fixes from the live run | yes | backend/tests/test_adaptive_counseling.py:339, backend/tests/test_adaptive_counseling.py:356, backend/tests/test_adaptive_counseling.py:371, backend/tests/test_adaptive_counseling.py:389, backend/tests/test_adaptive_counseling.py:401, backend/tests/test_adaptive_counseling.py:413, backend/tests/test_adaptive_counseling.py:424, backend/tests/test_adaptive_counseling.py:452, backend/tests/test_adaptive_counseling.py:474, backend/tests/test_adaptive_counseling.py:490, backend/tests/test_adaptive_counseling.py:505, backend/tests/test_adaptive_counseling.py:518, backend/tests/test_adaptive_counseling.py:529, backend/tests/test_adaptive_counseling.py:548, backend/tests/test_adaptive_counseling.py:561, backend/tests/test_adaptive_counseling.py:572, backend/tests/test_adaptive_counseling.py:581, backend/tests/test_adaptive_counseling.py:595, backend/tests/test_adaptive_counseling.py:618, backend/tests/test_adaptive_counseling.py:632, backend/tests/test_counselor_deep_pr3.py:92, backend/tests/test_counselor_deep_pr3.py:112, backend/tests/test_counselor_deep_pr4.py:131, backend/tests/test_counselor_deep_pr4.py:152, backend/tests/test_counselor_deep_pr4.py:168, backend/tests/test_counselor_deep_pr4.py:182, backend/tests/test_counselor_voice_v4.py:143, backend/tests/test_greeting_guard.py:9, backend/tests/test_greeting_guard.py:20, backend/tests/test_greeting_guard.py:29, backend/tests/test_greeting_guard.py:35, backend/tests/test_greeting_guard.py:42, backend/tests/test_path_exclusions.py:22, backend/tests/test_possibilities.py:195, backend/tests/test_possibilities.py:251, backend/tests/test_roadmap_engine.py:285, backend/tests/test_student_onboarding.py:772, backend/tests/test_student_onboarding.py:786, backend/tests/test_student_onboarding.py:804, backend/tests/test_student_onboarding.py:816, backend/tests/test_student_onboarding.py:825, backend/tests/test_student_onboarding.py:832, backend/tests/test_student_onboarding.py:854, backend/tests/test_student_onboarding.py:866, backend/tests/test_student_onboarding.py:874, backend/tests/test_student_onboarding.py:889, backend/tests/test_student_onboarding.py:904, backend/tests/test_student_onboarding.py:918, backend/tests/test_student_onboarding.py:932, backend/tests/test_student_onboarding.py:964, backend/tests/test_student_onboarding.py:978, backend/tests/test_student_onboarding.py:995, backend/tests/test_student_onboarding.py:1002, backend/tests/test_student_onboarding.py:1014, backend/tests/test_student_onboarding.py:1021, frontend/components/counselor/possibilities.test.tsx:52, frontend/components/onboarding/onboarding-view.test.tsx:142, frontend/components/onboarding/onboarding-view.test.tsx:169, frontend/components/onboarding/onboarding-view.test.tsx:197, frontend/components/onboarding/onboarding-view.test.tsx:210, frontend/components/onboarding/onboarding-view.test.tsx:241, frontend/components/onboarding/onboarding-view.test.tsx:252, frontend/components/onboarding/onboarding-view.test.tsx:262, frontend/components/onboarding/onboarding-view.test.tsx:278, frontend/lib/onboarding.test.ts:103, frontend/lib/possibilities.test.ts:1 |
| R-57 | Requirement traceability check in CI | yes | backend/tests/test_connect_traceability.py:9 |
| R-58 | Fake routes stay in tests; red-flag search for country names | yes | backend/tests/os/test_invariants.py:72, backend/tests/os/test_invariants.py:82, backend/tests/os/test_invariants.py:118 |
| R-59 | Every phase passes the full suite in CI | yes | backend/tests/test_connect_ci.py:10, backend/tests/test_connect_rulesets.py:8 |

## 3. Owner decisions

From the phase spec §2 and §5.3 (owner MSAQLAIN, 2026-11-03 unless stated):

| # | Decision |
|---|---|
| P0-D1 | Traceability uses a `built` flag per R-ID; a task sets `built: true` in the PR that adds its tests |
| P0-D2 | Branches as in master §13.4; task branches `pc/p0-t<M>-<name>` squash-merged into `pai-connect` |
| P0-D3 | Standalone suite is a pytest marker `standalone`; CI job `standalone` |
| P0-D4 | P0-T1 "baseline green" added and merged before Task 0 |
| P0-D5 | Freeze check is a script in its own workflow, not a path filter |
| P0-D6 | `backend/app/config.py` owned by the Counsellor lead alone |
| P0-D7 | Branch rulesets kept as files in `docs/connect/rulesets/`; a repository admin imports them |
| P0-D8 | C7 asks for matric marks, intermediate marks (total so far) and entry-test score; Part-I/Part-II separately stays in P1 |
| P0-D9 | C6: the reply follows the language of the student's latest message; Roman Urdu only as replacement for a blocked script |
| P0-D10 | Fixed sentences stay English; C1 notice wording; C7 required/optional marks; C2 replay of a skipped analysis acceptable; dismissal reason and evidence in a new nullable `pai_possibilities.dismissal` column |
| P0-D11 | Counsellor lead's approval of a freeze-exception PR is given in the Claude session chat and quoted in the PR |
| P0-D12 | Marks of a completed exam are required only on first onboarding (`onboarded_at` is None) |

Also recorded: the owner approved C6 in chat on 2026-11-04, and approved the wording "Enter a number from {min} to {max}." (C7 error text).

## 4. Deviations and reasons

- PRs #177 and #178 were not merged as opened; Task 0 and P0-T1 landed as the squash commits `75a4b75` and `56a2035`.
- Spec §5.4 order was C2, C1, C5, C3, C7, C6; C1, C3, C5 and C7 shipped together in #181 to share one branch, as they touch the same files (`possibilities.py`, `myths.py`).
- The replay cannot show any of the six fixes (no path analysis, research, onboarding or frontend offline; recorded outputs; guided turns fall back to `classifier_fallback`). Proof is by targeted tests, as spec §5.1 already states.
- Greeting guard never drops a leading sentence ending in `?` or `؟`, and the history check matches the greeting phrase prefix without a word limit (review ruling): a greeting phrased as a question stays.
- C3 sweep: skips questions from `clear_myth` turns, treats a cancelled research job like a failed one, considers only questions younger than 48 hours and posts at most one notice per workspace per tick (review rulings).
- Preview flow (`frontend/tests/preview`) step order differs from the real onboarding form (cosmetic, preview-only).

## 5. Open items

- Sign-off by the owner, MSAQLAIN (`@memsa771-hub`), only (P0-D13).
- No merge into `pai-merge` until the whole plan is complete (P0-D14); work stays on `pai-connect`.
- `paths/explain.py` still names the language replacement for the path page; follow-up task queued.
- `greeting_removed` may be logged twice on a retry (frozen `turn.py`).
- C1 matches only the field names in the path analyzer's field list; an exclusion naming another field changes nothing.
- From live run 2 (follow-ups, none blocks the gate):
  - Explore marks a path "exploring" even when starting research fails (`app/research/gateway.py` commits before the Operator call); pre-existing.
  - The Mirror shows "budget over 10 lakh" for a stated 15–20 lakh (catalog band `over_10_lakh` drops the ceiling).
  - "Local first, abroad only as a fallback" is not saved: no Vault item type for place preference (P1: R-13, R-78).
  - A Vault strength note says "he" for a female student.
  - The Mirror text can be built before the same turn's extraction lands ("family still unknown").
  - One Roman Urdu reply still used "karunga"; the same question was still asked twice (not three times).
  - The R2-3 rejection reason reaches the retry prompt but not the app log line (frozen `deep/analysis.py`).
  - Duplicate Vault entries (3 BDS options, 2 MDCAT records); MBBS stored as "considering" (the `option` status has no "chosen").
