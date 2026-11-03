# P0: setup and Counsellor fixes (phase spec)

Status: **draft for owner review** · 2026-11-03 · Owner: MSAQLAIN
Master spec: `docs/superpowers/specs/2026-11-03-pai-connect-design.md` (§12 row P0, §10, §13).
Visual overview: https://www.figma.com/board/X25QOs43qaDABBYEmzUPxk

## 1. Requirements this phase covers

| R-ID | Requirement (short) | Built in | Proved by |
|---|---|---|---|
| R-57 | Requirement traceability check in CI | Task 0 | `backend/tests/test_connect_traceability.py`; CI job `traceability` |
| R-58 | Red-flag search on country-specific names in `app/os` Python code | Task 0 | `backend/tests/os/test_invariants.py::test_no_country_terms_in_python`, `::test_country_terms_cover_pakistani_names` |
| R-59 | Every phase passes the full suite; missing CI jobs added | Task 0, P0-T1 | `backend/tests/test_connect_ci.py`; CI jobs `os`, `legacy`, `frontend`, `standalone`, `traceability`, `freeze` green |
| R-47 | Counsellor fixes C1, C2, C3, C5, C6, C7 | P0-T2 onward | Designed in a second round of this spec (§5), after reading the Counsellor code they touch |

Also started here, owned by P1: the freeze CI check and CODEOWNERS entries for R-43
(`backend/tests/test_connect_freeze.py`, `backend/tests/test_connect_codeowners.py`).

## 2. Decisions taken for this phase (owner, 2026-11-03)

| # | Decision |
|---|---|
| P0-D1 | **Traceability uses a `built` flag.** Each R-ID in `docs/requirements/connection.yaml` has `built: true/false`. CI requires a tagged test for every R-ID that is `built` or whose phase is `done`. `--gate P<N>` requires every R-ID of that phase. A task sets `built: true` in the same PR that adds its tests. |
| P0-D2 | **Branches as in master §13.4.** `pai-connect` is cut from `pai-merge` (done, `c3360b1`). Task branches `pc/p0-t<M>-<name>` are cut from `pai-connect` and squash-merged into it. |
| P0-D3 | **Standalone suite = a marker.** A `standalone` pytest marker on the tests that prove PAI OS works with the Counsellor module off (the Slice 4–7 gates and the module-off tests). CI job `standalone` runs `pytest tests/os -m standalone` against Postgres. |
| P0-D4 | **P0-T1 "baseline green" is added.** `pai-merge` has 7 failing tests today; they are fixed at their cause, never by weakening a test. P0-T1 merges into `pai-connect` before Task 0, so Task 0's CI can be green. |
| P0-D5 | **Freeze check is a script, not a path filter.** Path rules for the frozen files, and for `backend/app/config.py` a comparison of the Counsellor model settings only, so other settings stay editable. It runs in its own workflow so a label change doesn't rerun the 18-minute OS job. |
| P0-D6 | **`backend/app/config.py` is owned by the Counsellor lead alone** (CODEOWNERS), so a change to the frozen Counsellor model settings needs the lead's approval. PAI OS keeps its own settings in `backend/app/os/settings.py`, so this costs the OS developers little. |
| P0-D7 | **Branch rulesets are kept as files** in `docs/connect/rulesets/` (`pai-connect`: squash, six required checks including `freeze`; `pai-merge`: merge commit, five checks), with Code Owner review required on both. A repository admin imports them; `backend/tests/test_connect_rulesets.py` keeps them in step with the CI jobs. Until imported, CI and CODEOWNERS are advisory. |

## 3. Baseline found on `pai-merge` (`c3360b1`)

Legacy suite: 7 failed, 2699 passed, 620 skipped (no OS database). Frontend: vitest 326 passed, build passes,
`tsc --noEmit` fails with 3 errors.

| Failure | Cause | Fix (P0-T1) |
|---|---|---|
| `tests/test_mirror_gate_removed.py::test_no_route_or_job_references_mirror_confirmed`, `tests/test_os_route_detachment.py::test_counselor_and_os_contract_routes_stay_mounted` | `fastapi>=0.115.0` is unpinned; the latest release (0.162.0) keeps included routers as `_IncludedRouter` objects, so `app.routes` no longer lists their paths | Pin `fastapi>=0.115.0,<0.137`: bisection shows 0.136.3 lists included routes in `app.routes` and 0.137.0 is the first release that doesn't. A later unpin is its own task, with the tests moved to a version-independent route listing |
| 5 tests in `tests/os/test_inventory.py` | The old-OS inventory (`backend/scripts/os_inventory.py`, `docs/os/old-os-inventory.md`) predates the merge: 24 fate keys name modules `pai-c` deleted; 4 merged modules have no fate; `app.plugins.gap_assessment` is a `retire` now used by the Counsellor | Remove the 24 stale keys and the 3 stale touching-retire keys; propose fates (§3.1); regenerate the document |
| `tsc`: `frontend/components/counselor/workspace/inline-card.test.tsx` lines 17, 24, 25 | `exact` is not a `ByRoleOptions` property (role `name` strings already match exactly) | Remove `exact:true`; the test keeps its meaning |

### 3.1 Proposed fates (need the OS developers' and the owner's sign-off in the P0-T1 PR)

| Module | Proposed fate | Reason |
|---|---|---|
| `app.documents.owner` | keep | The Vault's "is this the student's own document" check; nothing replaces it |
| `app.plugins.path_explainer` | keep | Stage G owner workflow; the Counsellor's, not the old OS's |
| `app.plugins.program_search` | keep (until P2) | Stage H research; replaced for OS-run routes by `ProgrammeList` / `ProgrammeFacts` (R-49, master §4) |
| `app.research.seasons` | keep (until P2) | Season bounds for research freshness; replaced by Knowledge season monitoring (R-27) |
| `app.plugins.gap_assessment` | keep (until P2), was retire | Now imported by `app/pai_c/paths/programs.py`; retired with stage H research in P2 |

## 4. Task 0 design

| Piece | Design |
|---|---|
| Master spec | Committed at `docs/superpowers/specs/2026-11-03-pai-connect-design.md` with the FigJam link |
| `docs/requirements/connection.yaml` | `phases:` P0–P6 with `name` and `status` (`planned` / `current` / `done`; P0 `current`). `requirements:` R-01…R-81, each with `title`, `phases` (from master §12; R-10 also P5 for the legal review) and `built`. Task 0 sets `built: true` for R-57, R-58, R-59 |
| `scripts/check_traceability.py` | Scans `backend/tests/**/*.py` for `mark.req("R-xx", …)` (decorators and `pytestmark`) and `frontend/**/*.test.ts(x)` (not `node_modules`) for `// req: R-xx`. Fails on: invalid yaml (unknown phase, bad status, more than one `current`, bad R-ID); a tag naming an R-ID not in the yaml; a required R-ID (P0-D1) with no tag. `--gate P<N>` adds every R-ID of that phase; `--report` prints a markdown table R-ID → tests for the gate report |
| `scripts/check_freeze.py` | Frozen paths (master §10): `backend/app/pai_c/**/*.md`, `backend/app/pai_c/deep/`, `backend/app/pai_c/{planner,policy,voice}/prompts/`, `backend/app/pai_c/playbooks/`, `backend/app/pai_c/policy/actions/`, `backend/app/pai_c/policy/*.json`, `docs/counselor/COUNSELOR_V3_PROMPTS.md`. Counsellor model settings in `backend/app/config.py`: class attributes named `PAI_MODEL`, `PAI_COUNSELOR_*`, `PAI_*_MODEL`, `PAI_*_REASONING_EFFORT`, `PAI_*_MAX_TOKENS`, compared by parsed value between the base and the PR. A frozen change passes only with the `freeze-exception` label **and** an R-ID in the PR title or body |
| `.github/workflows/freeze.yml` | `pull_request` types opened, synchronize, reopened, edited, labeled, unlabeled; full history; labels and PR text passed through `env` (never interpolated into the script) |
| `.github/workflows/ci.yml` | Push triggers add `pai-merge` and `pai-connect`. New jobs: `frontend` (Node and build command as the production Dockerfile (Node 20, `npx next build --webpack`): `npm ci`, `npx tsc --noEmit`, `npm test`, build), `standalone` (Postgres 16 service, `pytest tests/os -m standalone`), `traceability` (`pip install pyyaml==6.0.3`, `python scripts/check_traceability.py`). Existing `os` and `legacy` jobs unchanged |
| `backend/pytest.ini` | Registers `req(*ids)` and `standalone` markers |
| R-58 | `COUNTRY_TERMS` gains Punjab, Sindh, Khyber, Pakhtunkhwa, Balochistan, Kashmir, Gilgit, Baltistan, MDCAT, ECAT, PMDC, UHS, Lahore, Peshawar, Quetta, Rawalpindi |
| `.github/CODEOWNERS` | `/backend/app/pai_c/`, `/backend/app/pai_os_bridge.py`, `/frontend/components/counselor/` → `@memsa771-hub` only (the last matching rule wins, so the lead's review is required) |
| `CLAUDE.md` (root) | Replaces "Branch pai-c only… PAI OS is another developer's work", "This repo is PAI C only", "Freeze new modules" and "Task branches start from and rebase on `pai-os`" with: master §13.2 rules, the `pai-connect` branch model (§13.4), D-16 (OS developers build the connection, Counsellor lead reviews), and the new check commands. Keeps: who and what, product rules, Roman Urdu or English, commands, no live calls without approval |
| `backend/app/os/CLAUDE.md` | Keeps invariants 1–13; adds a "Connection work" section: read master §2–§3 and the phase spec first and name the R-IDs, never invent data, invariant 12 is enforced by R-58, frozen Counsellor files (R-43), ownership per master §4, stop and ask when unclear |

## 5. Counsellor fixes (R-47): second design round

C1, C2, C3, C5, C6 and C7 each change Counsellor behaviour and go through the freeze exception process (master §10):
the `freeze-exception` label, the R-ID, a replay showing only the intended answers changed, and the Counsellor
lead's approval. They are designed after Task 0, once the freeze check exists, in an addendum to this spec. That
round reads `deep/analysis.py`, the planner patch path (`AnalysisPatchRejected`), `possibilities.py` and the
onboarding view, and settles C6 from the live-run finding. C7 depends on R-80 (P1) for the Vault write; P0 adds only
the onboarding questions if the addendum shows that can be done without the P1 Vault projection.

## 6. Gate (master §12, P0)

1. P0-T1 and Task 0 merged into `pai-connect` with every CI job green.
2. `python scripts/check_traceability.py --gate P0` passes (needs R-47's tests).
3. The live-run student (fictional Ayesha Malik, `docs/local-test/live-run-issues-2026-11-02.md`) reaches stage H
   with only MBBS and BDS.
4. Counsellor evaluations pass; a replay shows only the fixed behaviour changed.
5. Handoff `docs/connect/handoff/p0-handoff.md` written; both owners sign off. **Blocked on master §15 Q5** (which OS
   developer owns integration).
