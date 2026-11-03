# Branch rulesets for the connection work

Without these rulesets the CI checks and CODEOWNERS on `pai-connect` and `pai-merge` are advisory: nothing stops a
merge that fails them (master spec §10, R-59). A repository admin imports them once.

| File | Branch | Merge method (master §13.4) | Required checks |
|---|---|---|---|
| `pai-connect.json` | `pai-connect` | squash (task branches) | `os`, `legacy`, `frontend`, `standalone`, `traceability`, `freeze` |
| `pai-merge.json` | `pai-merge` | merge commit (phase gates) | `os`, `legacy`, `frontend`, `standalone`, `traceability` |

`freeze` is not required on `pai-merge`: the Freeze workflow runs only on pull requests into `pai-connect`, where every
exception is approved; a required check that never runs would block every gate merge.

Both rulesets require one approving review, a Code Owner review (so the Counsellor lead approves every PR touching
Counsellor files, the frozen settings in `backend/app/config.py` and the freeze tooling), dismiss stale approvals on
push, and forbid force pushes and deletion.

## Import (repository admin)

1. GitHub → the repository → **Settings** → **Rules** → **Rulesets**.
2. **New ruleset** → **Import a ruleset** → choose `pai-connect.json`. Check the summary, then **Create**.
3. Repeat for `pai-merge.json`.
4. Check: open any pull request into `pai-connect`; its merge box lists the six required checks and "Review required
   from Code Owners".

Add a bypass actor (for example the integration owner, master §15 Q5) only if the owners agree to it.

`backend/tests/test_connect_rulesets.py` fails when a required check here no longer matches a CI job that runs for
pull requests into that branch.
