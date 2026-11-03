# C6 replay diff (R-47 C6)

Before: `origin/pai-connect` at b7d1303. After: branch `pc/p0-t4-c6-language`. Offline, recorded model outputs, `PAI_API_KEY` unset.

## default

No differences.

## guided

No differences.

## Why

- None of the 21 recorded replies in either mode opens with a greeting (checked with `leading_greeting`), so the repeat-greeting guard never fires and no `greeting_removed` appears.
- The language-policy change (no `replacement` in `<language_policy>`; replacement named only in the blocked-script retry) changes only the prompt, and the replay uses recorded outputs, so it cannot change a reply (see README). Both changes are proved by the R-47 tests in `tests/test_counselor_deep_pr3.py`, `tests/test_greeting_guard.py` and `tests/test_counselor_voice_v4.py`.
