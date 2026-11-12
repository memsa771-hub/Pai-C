# P2 local handoff: finishing P2 on your own PC (2026-11-12)

**This file replaces `p2-merge-handoff.md` for everything after T8.** The rest of the plan (the rest of P2, then
P3 to P6) runs in a **local** Claude Code session, not in the cloud.

Read in this order:
1. This file.
2. The P2 spec `docs/superpowers/specs/2026-11-07-p2-national-data-design.md`: §5 (rules for every task), §6 (task
   groups), §9 (gate), §11 (owner rulings). **§11.3 is not on `pai-connect` yet**: see §5 step 1 below.
3. The draft P2 handoff on branch `pc/p2-t12-gate`: `docs/connect/handoff/p2-handoff.md`. It holds the full gate
   report, open gaps, flags and the student sentences. It lands with T12.
4. `docs/connect/handoff/p1-handoff.md` and master spec §2–3 (`docs/superpowers/specs/2026-11-03-pai-connect-design.md`).

## 1. Rules that hold (unchanged)

- **`pai-connect`** is the working base. Every task merges into it by PR, **squash-merged**, one task per PR, with the
  task's R-IDs named in the PR.
- **`pai-merge`**: nothing goes in until the whole plan (P0–P6) is done (P0-D14); then a merge commit.
- **Never touch** `pai-c` (live), `pai-os`, `dev`, `main`.
- **Phase sign-off is the owner's alone** (P0-D13), in chat; the sign-off is recorded in a small separate PR.
- **Never** force-push or rebase a shared branch. When the base was squash-merged, merge the base **into** the task
  branch.
- **No invented data** (institution, date, fee, merit figure, rule). Data enters only through the registry, research
  and the review queue. Tests use fictional students and `.test` domains (the fixture server).
- **No live model calls** without the owner's approval and a cost cap. **P2 cap: US$20 in total.**
- **No country names in `backend/app/os`** (R-58 red-flag search). Frozen Counsellor files only through the freeze
  exception (master §10: `freeze-exception` label, the R-ID, a replay, the Counsellor lead `@memsa771-hub` approves).
- **Never weaken a test.** Never paste API keys or real student data into Claude. Never edit `.env`.
- **Student sentences:** standing approval. Add them in the data files (yaml or `copy.json`) with `approved: true`,
  list them in the PR body. No separate PR is needed for the wording.
- Talk to the owner in English or Roman Urdu, never Hindi or Devanagari.

## 2. What is on `pai-connect` now (head `65f8cde`)

| Task | PR | Migration |
|---|---|---|
| P2-T1 foundations | #203 | `os_0025_fact_intake_columns` |
| P2-T5 review queue | #206 | `os_0026_review_queue` |
| P2-T2 registry | #204 | `os_0027_registry` |
| P2-T3 sources | #205 | `os_0028_sources` |
| P2 merge handoff | #208 | none |
| P2-T8 intakes | #207 | `os_0029_intakes` (the head) |

## 3. What is left, in this order

Each branch below is built, reviewed and fixed, green on its own and together on `pc/p2-integration`. Each is about
7 merges behind `pai-connect` (25 to 134 commits ahead), so each needs `pai-connect` merged in, its migration
renumbered, and the full checks (§4) before its PR.

| # | Branch (tip) | What | Migration on the branch → **rename to** | Notes |
|---|---|---|---|---|
| 1 | `pc/p2-t4-reading` (`0b9881a`) | headless render, OCR port, Urdu normalisation, `not_readable` | `os_0027_reading` → **`os_0030_reading`** (down `os_0029`) | drop the branch's `os_0026_sources`; keep `pai-connect`'s `os_0028_sources` |
| 2 | `pc/p2-t6-sheets` (`046f529`) | one spreadsheet format, import, undo | `os_0027_imports` → **`os_0031_imports`** (down `os_0030`) | drop its `os_0026_registry` copy |
| 3 | `pc/p2-t10-merit` (`ca40492`) | `ProgrammeFacts`, `MeritCheck` ports | none new | drop its `os_0026_intakes` copy (T8 is merged as `os_0029`) |
| 4 | `pc/p2-t7-monitoring` (`7413d3a`) | season monitoring, student reports | `os_0030_monitoring` → **`os_0032_monitoring`** (down `os_0031`) | drop its copies of 0026–0029 |
| 5 | `pc/p2-t9-coverage` (`0bb5bc3`) | coverage screen, intake `current` gate | none new | drop its copies of 0026–0029 |
| 6 | `pc/p2-t11-calendars` (`6b94c6c`) | official calendars | its `os_0030_imports` is T6's: after T6 is merged, keep `pai-connect`'s `os_0031_imports` and drop this copy | **T11 contains T6.** Merge only after T6; the PR must show only T11's changes |
| 7 | `pc/p2-t12-gate` (`99c6854`) | consistency rules 9–12, gate proofs, R-69 export, Spike 1 harness, the P2 handoff draft | `os_0033_consistency_rules_9_12` (down `os_0032`) | drop its copies of 0026–0032 |

**The migration trap.** The older branches (T7, T9, T11, T12, integration) assumed registry 0026, sources 0027,
review 0028. What merged is review 0026, registry 0027, sources 0028. From `os_0029` on the numbers match. On every
merge: keep `pai-connect`'s `os_0025`–`os_00NN` files exactly, delete the branch's copies, chain the branch's own new
migration on the current head, and run `python scripts/check_alembic_heads.py` (one head per tree).

**Use `pc/p2-integration` (`79ada0b`) as the cross-check** for conflict resolutions (it combines T4, T6, T7, T9 and
T11 on one chain), but merge task by task, one PR each.

**How to bring a branch up to date** (example T4):
```powershell
git checkout pc/p2-t4-reading
git fetch origin
git merge origin/pai-connect      # resolve: keep both sides' intent, never drop code from either side
git mv backend/alembic/versions_os/os_0027_reading.py backend/alembic/versions_os/os_0030_reading.py
# edit: revision = "os_0030", down_revision = "os_0029"; fix any test that names the old id
git push -u origin HEAD
```
If a merge with history problems is needed (`-s ours`), use it only after `git diff --quiet` proves the trees are
identical.

## 4. Checks before every push

From `backend/`:
- `tach check`
- `python -m pytest tests/os -q -p no:cacheprovider` (Postgres; about 25–35 minutes now)
- legacy: clear `PAI_API_KEY`, then `python -m pytest -q -p no:cacheprovider --ignore=tests/os`
  (do not run it in parallel with `tests/os`)
- frontend (in `frontend/`) when it is touched: `npm test` and `npm run build`

From the repo root:
- `python scripts/check_freeze.py --base origin/pai-connect` (must say unchanged)
- `python scripts/check_traceability.py` (and `--gate P2` on T12)
- `python scripts/check_alembic_heads.py`

CI's `os` job has a 60-minute limit. If CI fails, reproduce the failure locally first, fix only what failed.

## 5. After the code tasks: the rest of P2

1. **Land the spec rulings §11.3.** They are on `pc/p2-spec` (`a389b3c`) only (16 lines). Open a small docs PR that
   adds just those lines to the spec on `pai-connect`. Do not merge `pc/p2-spec` as it is: its tree is old and would
   delete the task plans.
2. **Research data:** `pc/p2-research-batches` (`e7fab44`) holds the walkthroughs, the official lists and the
   batches (v4 batches 1–5, the Sindh seat rows with check 1 and check 2: 84 re-entered, 74 accepted by both checks;
   the PMDC name matches: 59 accepted, the 043 disagreement held back). Merge `pai-connect` into it and open its PR.
   Then import with the T6 CLI: the v4 files with `--owner-accepted` (ruling §11.3, by file hash), everything else in
   the normal mode. Load the allow-lists. Undo is by import id.
3. **Answer keys and the live Spike 1 rerun (gate item 7).** One key per region,
   `backend/tests/os/quality/<region>_answer_key.yaml`, made by a checker who did not verify those rows. Then
   `python -m scripts.os_spike1_rerun plan` shows the cost; ask the owner before the billed run; stay inside US$20.
4. **Gate items 3, 5, 6** need the people lane: walkthrough checks (two AI checks count, ruling §11.2), one real
   not-readable source collected through the queue (H7), the registry percentage measured after the H4 import.
5. **Two freeze-exception PRs (gate item 12):** the Counsellor's merit answers (`CONNECT_MERIT_ANSWERS`, R-48) and the
   calendar and admission-rule move (`CONNECT_CALENDAR_FROM_KNOWLEDGE`). Each needs the label, the R-ID, a replay that
   shows only the intended answers changed, and the Counsellor lead's approval.
6. **The P2 handoff** (`p2-handoff.md`, from T12) is updated with the PR numbers and the real gate results, then the
   owner signs off. Then P3.

## 6. Owner decisions still open

- **R-15**, OS side (an excluded field disappears from the OS programme list): moved from P1 to P2 but not in the P2
  scope; not built. Where does it go?
- **Germany CGPA:** Germany v2 asks only for the SSC and HSSC certificates. A CGPA ask needs an official source and the
  owner's wording.
- **OCR engine:** Tesseract scored 6/10 on the bake-off (below the bar); Docling could not be installed and was not
  compared.
- **R-46** stays `built: false` as recorded in the P1 handoff.
- **R-48** is `built: false` until freeze exception 1 lands (the OS side is built).
- The T2 parent-kind table was chosen by the agent; the final review should confirm it.

## 7. Known limits to remember (details in the T12 draft handoff §4)

- Rules 9 and 12 report "not run" until an allow-list is loaded and `OS_SOURCE_GUARD=1`.
- Imported dates not in ISO format stay text and do not move plans.
- The render memory cap is tested on cgroup v1 only.
- All new P2 flags (`OS_SOURCE_GUARD`, `OS_MONITOR`, `OS_REPORTS`) default to off; with them off the app behaves as
  before P2.

## 8. Setting up the local session

Follow `p2-merge-handoff.md` §5 (Git with `core.autocrlf input`, Docker Desktop, Python 3.12, Node 22, the
`os-test-pg` Postgres container, the venv, the first checks). Fetch every P2 branch:
```powershell
git fetch origin "refs/heads/pc/p2-*:refs/remotes/origin/pc/p2-*"
```

**First message for the local session** (paste it as is):

> Read `docs/connect/handoff/p2-local-handoff.md` in full, then the P2 spec §5, §6, §9 and §11 (and §11.3 on
> `pc/p2-spec`). Work only on `pc/p2-*` branches and PRs into `pai-connect`; never touch `pai-c`, `pai-os`, `dev`,
> `main` or `pai-merge`. Start with row 1 of §3 (T4): merge `pai-connect` into `pc/p2-t4-reading`, renumber its
> migration to `os_0030_reading`, run every check in §4, push, and open its PR. Ask me before anything outside that.
