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
| R-47 | Counsellor fixes C1, C2, C3, C5, C6, C7 | P0-T4 (§5) | Tests tagged R-47 per fix (§5.2); offline replay before and after (§5.1) |

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

## 5. Counsellor fixes (R-47)

Approved by the owner on 2026-11-03 (design in chat; decisions P0-D8 and P0-D9 below). Source of each problem:
`docs/local-test/live-run-issues-2026-11-02.md`.

### 5.1 Rules for every fix

- **Proof:** an offline replay (`python -m scripts.eval_counselor_deep --offline` from `backend/`, recorded personas,
  no model calls) before and after shows that nothing else changed. The replay does not run path analysis, research,
  onboarding or the frontend, and replays recorded model outputs, so each fix is proved by its own targeted tests
  (named per task in the plan). A live graded run is not part of
  P0 (master R-46: before real students, with the owner's approval and a cost cap).
- **Frozen files:** a fix that changes a frozen path (master §10) goes in its own PR with the `freeze-exception`
  label, R-47 in the title, the replay, and the Counsellor lead's approval. Only C2 and C6 need this.
- **No new chat messages from the OS, no change of tone or style** (master D-05, R-45). Notices added here are the
  Counsellor's own fixed sentences in non-frozen data files, in English like the existing fixed sentences (P0-D10).
- **Tests** carry `@pytest.mark.req("R-47")`; when all six land, `R-47` is set `built: true`.

### 5.2 The fixes

| # | Problem | Cause (where) | Fix | Frozen? |
|---|---|---|---|---|
| C1 | A field the student excluded keeps being suggested | Only the Dismiss button dismisses a path (`routers/counselor_possibilities.py`). The Vault already records a stated exclusion as an `option` item with status `ruled_out` (`memory/catalog/vault_catalog.json`), but nothing reads it. Since `87aa26f`, a path a newer run leaves out is kept, so it stays on Roadmaps | When the Vault holds `option` = `ruled_out` for a field, the matching path is dismissed with reason `student_excluded` and the student's words as evidence, and the path analyzer treats it as dismissed so it is never suggested again. A one-line notice tells the student what was removed and why. The match is by the field key the path analyzer already uses; an exclusion that matches no path changes nothing. Undoing it is the existing restore of a dismissed path | No (`pai_c/possibilities.py`, `pai_c/paths/analyzer.py`, a Vault-change hook) |
| C2 | One failed analysis blocks every later one | `deep/analysis.py`: a rejected planner patch raises `AnalysisPatchRejected` (not retryable, job `failed`); every later `counselor.analyze` finds a failed predecessor and raises `AnalysisPredecessorFailed` ("earlier analysis failed; replay required"), which also ends `failed`. Stage advance and path analysis only run on success, so the journey stays at stage D | A failed earlier analysis no longer blocks: it is recorded as `skipped` (kept for the operator's replay tool) and the next analysis runs, from the full conversation as it does today. Pending or running predecessors still make the job wait, so order is kept. The stage H gate (G4) needs no separate change: it opens once analyses run again | **Yes** (`deep/analysis.py`): exception PR |
| C3 | "I'll check official sources", then nothing | `pai_c/runtime.py` starts research only when the reply's action is `note_question` **and** recorded, or the decision is `answer_request`. A question the classifier already recorded makes the model's action a `duplicate`; other decisions and a busy research lock (`research/gateway.py`) end silently | Every recorded question that needs research starts a research job, whatever the turn's decision, and a failed start is retried once. A sweep finds questions still open with no job after 30 minutes and posts the existing "couldn't find an answer" notice (`information_unanswered`, already in policy). The student is never left with a silent promise | No (`pai_c/runtime.py`, `pai_c/myths.py`, `research/gateway.py`, a job for the sweep) |
| C5 | Chat cards show 1–2 paths, Roadmaps shows 5 | The chat card lists only the paths the latest run returned (`paths/analyzer.py`, `paths_found`); Roadmaps lists every non-dismissed path (`roadmap/engine.py`) | One reader for "the student's current paths", used by Roadmaps and by the newest paths card. Older cards keep the snapshot of what they said (from `87aa26f`), so past messages don't change | No (`pai_c/possibilities.py`, `roadmap/engine.py`, `frontend/components/counselor/possibilities.tsx`) |
| C6 | Roman Urdu reply to an English message; "Wa alaikum assalam" twice | The `<language_policy>` built in `deep/context.py` always names the replacement ("Roman Urdu") for the blocked Devanagari script, which nudges the model even when the student writes English. Nothing stops a second greeting (`voice/guards.py` only compares whole replies and questions) | **Rule (P0-D9): follow the student.** The reply uses the language of the student's latest message; the replacement language is named only when a reply has to be redone because it came out in a blocked script. A guard drops a second greeting in the same conversation | **Yes** (`deep/context.py`): exception PR; the greeting guard (`voice/guards.py`) is not frozen |
| C7 | Onboarding doesn't ask for marks | The onboarding form is built from the Vault catalog's `onboarding` blocks (`memory/onboarding.py`, `memory/catalog/vault_catalog.json`); marks have no block, though the Vault already stores them (`education.result`; entry tests as `test_attempt`) | **Scope (P0-D8):** onboarding asks for matric marks, intermediate marks (total so far, optional while studying) and an entry-test score (optional, e.g. MDCAT), saved as `stated` through the normal onboarding path. O/A-level students get grades instead of marks. Part-I and Part-II separately is P1 (R-16, R-80) | No (catalog JSON, `memory/onboarding.py`, `frontend/components/onboarding/`) |

### 5.3 Decisions

| # | Decision |
|---|---|
| P0-D8 | C7 in P0 asks for matric marks, intermediate marks (the total so far) and the entry-test score. Storing intermediate Part-I and Part-II separately stays in P1 (R-16, R-80). |
| P0-D10 | Fixed sentences stay English for now. The C1 notice reads "I've removed {titles} from your paths, since you said it isn't for you." (plural "…they aren't…"). C7: marks of a completed exam are required, current-study marks and the entry test optional. C2: replaying a skipped analysis after newer ones is acceptable. A dismissal keeps its reason and evidence in a new nullable `pai_possibilities.dismissal` column (migration). |
| P0-D9 | C6: the reply follows the language of the student's latest message. Roman Urdu is used only as the replacement when a reply came out in a blocked script (Devanagari). |

### 5.4 Order

C2 first (it unblocks analysis, which C1 and C5 rely on in the replay), then C1, C5, C3, C7, and C6 last (its replay
shows reply-language changes, easiest to read once the others are in).

## 6. Gate (master §12, P0)

1. P0-T1 and Task 0 merged into `pai-connect` with every CI job green.
2. `python scripts/check_traceability.py --gate P0` passes (needs R-47's tests).
3. The live-run student (fictional Ayesha Malik, `docs/local-test/live-run-issues-2026-11-02.md`) reaches stage H
   with only MBBS and BDS.
4. Counsellor evaluations pass; a replay shows only the fixed behaviour changed.
5. Handoff `docs/connect/handoff/p0-handoff.md` written; both owners sign off: the Counsellor lead (`@memsa771-hub`) and
   the integration owner (`@MusawirKtk`, master §15 Q5).
