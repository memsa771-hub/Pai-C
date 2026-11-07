# Counsellor offline replays

Offline replays of the Counsellor (recorded model outputs, no network, no API key) used to show what each R-47 fix changed.

## Folders

- `r47-before/default/` - replay on the base before any R-47 fix, default policy mode.
- `r47-before/guided/` - the same with `--policy-mode guided`.
- Each holds `counselor_deep_<date>.json` (compared by `compare.py`) and `.md` (readable).
- `compare.py` - `python docs/connect/replays/compare.py BEFORE.json AFTER.json` prints a markdown table of every persona turn whose `reply`, `action.type`, `action_status`, `decision` or `guard_violations` differ, plus persona `status`/`stop_reason` changes. Prints `No differences.` when none. If the two files' `policy_mode` (or `mode`) differ it prints a `Warning: comparing policy_mode X with Y` line before the table (a warning, not an error). Exit code is 0 whether or not there are differences, 2 on bad usage. One-sided rows read `only in BEFORE` / `only in AFTER`. Ids, timings, usage and cost are ignored.

## Commands (from `backend/`)

```
env -u PAI_API_KEY python -m scripts.eval_counselor_deep --offline --result-dir ../docs/connect/replays/r47-before/default
env -u PAI_API_KEY python -m scripts.eval_counselor_deep --offline --policy-mode guided --result-dir ../docs/connect/replays/r47-before/guided
```

Use another `--result-dir` (for example `r47-after/default`) for an AFTER run, then compare the two JSON files.

## P1 (T10)

- `p1/before/{default,guided}/` - replay on the P1 start (`bed47c8`), run from a temporary git worktree of that commit.
- `p1/after/{default,guided}/` - the same on the T10 branch. `p1/diff.md` holds the `compare.py` result (no differences).
- `p1/stage-a-i/{off,on}.json` and `p1/stage-a-i.md` - the stage A-I replay with the connection off and on. It records every
  model call's input, which the persona replay does not. Regenerate it from `backend/` (needs `OS_TEST_DATABASE_URL`):
  `env -u PAI_API_KEY python -m scripts.connect_stage_replay --out ../docs/connect/replays/p1/stage-a-i`.

```
git worktree add <scratch>/p1-before bed47c8
(cd <scratch>/p1-before/backend && env -u PAI_API_KEY python -m scripts.eval_counselor_deep --offline --result-dir <repo>/docs/connect/replays/p1/before/default)
(cd <scratch>/p1-before/backend && env -u PAI_API_KEY python -m scripts.eval_counselor_deep --offline --policy-mode guided --result-dir <repo>/docs/connect/replays/p1/before/guided)
git worktree remove <scratch>/p1-before
```

## What the replay cannot show

- It forces each analysis job to `succeeded`, so C2's cascade never appears.
- It runs no path analysis, research, onboarding or frontend, so C1, the C3 sweep, C5 and C7 show only "nothing else changed".
- It replays recorded model outputs, so a prompt-only change (C6 language policy) shows no reply difference.
- Offline, every guided turn carries `guard_violations: ['classifier_fallback']` (the classifier raises offline), so guided decisions come from the fallback path (for example `explore_area`), not a real classifier result. C3's runtime change is therefore NOT shown by this replay either; C3 is proved by its targeted tests.

Each fix is proved by its named tests, not by this replay.
