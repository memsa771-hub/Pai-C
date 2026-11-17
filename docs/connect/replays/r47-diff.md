# R-47 replay: before and after the six Counsellor fixes

Offline replay (recorded model outputs, no network, no API key), 18 personas, before = `r47-before/` (base before any fix, 2026-11-03), after = `r47-after/` (this branch with C1, C2, C3, C5, C6, C7, 2026-11-04). Compared with `docs/connect/replays/compare.py`.

## compare.py output

Default policy mode:

```
No differences.
```

Guided policy mode (`--policy-mode guided`):

```
No differences.
```

No persona turn changed in either mode, so there is no difference to explain. This is expected: the replay cannot show these fixes (see `README.md`, "What the replay cannot show"). Each fix is proved by its named tests.

## One line per fix

| Fix | What the replay shows | Tests that prove it |
|---|---|---|
| C1 excluded field is not suggested again | Nothing: the replay runs no path analysis or Vault hook | `backend/tests/test_path_exclusions.py` |
| C2 a failed analysis no longer blocks later ones | Nothing: the replay forces each analysis job to `succeeded`, so the cascade never appears | `backend/tests/test_counselor_deep_pr4.py` |
| C3 recorded questions always get research or a notice | Nothing: no research runs offline, and offline every guided turn carries `classifier_fallback`, so the C3 runtime change is not exercised | `backend/tests/test_adaptive_counseling.py` (sweep and start tests) |
| C5 chat card and Roadmaps show the same current paths | Nothing: no path analysis and no frontend in the replay | `backend/tests/test_roadmap_engine.py`, `frontend/components/counselor/possibilities.test.tsx` |
| C6 reply follows the student's language; one greeting | Nothing: recorded model outputs are replayed, so a prompt-only change shows no reply difference | `backend/tests/test_counselor_deep_pr3.py`, `backend/tests/test_greeting_guard.py` |
| C7 onboarding asks for marks | Nothing: the replay runs no onboarding or frontend | `backend/tests/test_student_onboarding.py`, `frontend/components/onboarding/onboarding-view.test.tsx` |
