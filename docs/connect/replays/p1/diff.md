# P1 replay: before and after the whole phase

Offline replay (recorded model outputs, no network, no API key, no model call), 18 personas, 21 recorded turns.
Before = `p1/before/` (the P1 start, `bed47c8`, #190, run in a temporary git worktree of that commit, since removed),
after = `p1/after/` (the T10 branch `pc/p1-t10-lane-c`, whose tree holds T1 to T9 as merged, 2026-11-07). Compared with
`docs/connect/replays/compare.py`. Cost $0.000183 per run (the recorded usage figures, not a charge).

## compare.py output

Default policy mode:

```
No differences.
```

Guided policy mode (`--policy-mode guided`):

```
No differences.
```

All 18 personas are `complete` in all four runs, with the same 21 turns. No reply, action type, action status, decision
or guard violation changed in either mode.

## Cross-checks

- `python scripts/check_freeze.py --base bed47c8`: no frozen Counsellor file and no model setting changed since the P1 start (Task D3).
- The stage A-I replay (`p1/stage-a-i.md`) goes further than this one: it compares the model inputs, not only the replies.

## What the replay cannot show

- Each persona runs only 1 to 3 turns (18 personas, 21 turns), so none reaches stage H or I.
- It replays recorded model outputs and ignores the model input (`counselor(**_kwargs)`), so a change in what the Counsellor
  reads shows nothing here. That is why the stage A-I replay records the inputs.
- It forces each analysis job to `succeeded` and runs no path analysis, research, onboarding or frontend.
- Offline, every guided turn carries `guard_violations: ['classifier_fallback']`, so guided decisions come from the fallback path.
- A prompt-only change shows no reply difference.
