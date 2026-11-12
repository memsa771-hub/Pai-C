# P2 merge handoff: where the P2 task branches stand (2026-11-12)

**A new session reads this first, then `docs/connect/handoff/p1-handoff.md` and the P2 spec.** The spec is
`docs/superpowers/specs/2026-11-07-p2-national-data-design.md`; §5 has the rules for every P2 task and §6 lists the
task groups. This note covers only where the merges into `pai-connect` stand and how to finish them.

## 1. Branches and the rules that hold

- **`pai-connect`** is the P2 working base. Every P2 task merges into it by PR, squash-merged (spec §5).
- **`pai-merge`** carries the combined product. Nothing goes into it until the whole plan is done (P0-D14).
- **Never touch these:** `pai-c` (it is LIVE in production), `pai-os`, `dev`, `main`.
- **One task per PR.** Name the task's R-IDs in its PR. Tick `built: true` in `docs/requirements/connection.yaml`.
- **Data:** no data from memory; use fake domains and the fixture server.
- **AI calls:** no live model calls without the owner's approval and a cost cap.
- **Before pushing:** run `tach check` (from `backend/`) and `pytest tests/os`. Run the legacy suite too
  (`env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider --ignore=tests/os`).
- **Postgres** stops when the container sits idle: run `service postgresql start`. The test database is
  `OS_TEST_DATABASE_URL=postgresql://os_test:os_test@localhost:5432/os_test`.

## 2. What is merged into `pai-connect`

| Task | PR | Migration (as merged) |
|---|---|---|
| P2-T1 foundations | #203 | `os_0025_fact_intake_columns` |
| P2-T5 review queue | #206 | `os_0026_review_queue` |
| P2-T2 registry | #204 | `os_0027_registry` |
| P2-T3 sources | #205 | `os_0028_sources` |
| P2-T8 intakes | #207 (open; conflicts fixed 2026-11-12, see §3) | `os_0029_intakes` |

**Watch the migration order.** The branches that were built later (T7, T9, T11, T12 and `pc/p2-integration`)
assumed the order registry 0026, sources 0027, review 0028. What merged is review 0026, registry 0027, sources 0028.
From `os_0029` on, the numbering matches. So when one of those branches is merged, keep **`pai-connect`'s
`os_0026`–`os_0029` files** and drop the branch's copies. Then chain the branch's own new migration on the current
head, and check for one head.

## 3. T8 (#207): what was done on 2026-11-12

`pai-connect` was merged into `pc/p2-t8-intakes` after T3 landed.

- **Migration:** `os_0026_intakes` became **`os_0029_intakes`**, revising `os_0028`.
- **`models.py`:** keeps the T5, T2 and T3 tables and constants, plus T8's `os_intakes` and `os_fact_slots`.
  - `backfill` is a new **`FACT_REVISION_CAUSES`**, the fact-revision check only. The registry-revision check stays
    exactly as T2's migration made it.
  - `knowledge/store.py` validates against `FACT_REVISION_CAUSES`.
- **`knowledge/requests.py`:** `_has_facts` keeps both T2's `owner_ref == ""` filter and T8's `intake_term` filter.
- **`tests/os/test_models.py`:** both table lists.
- **Checks:** see the PR comment for the full-suite result.

## 4. What is next (in this order)

All of these branches exist and were reviewed in earlier sessions. Each is 5 commits behind `pai-connect`, so each
needs `pai-connect` merged in and its migration renumbered (§2) before its PR.

| Order | Branch | Its new migration after renumbering | Needs first |
|---|---|---|---|
| 1 | `pc/p2-t4-reading` (render fallback, OCR, Urdu, `not_readable`) | `os_0030_reading` | T3 ✓ |
| 2 | `pc/p2-t6-sheets` (spreadsheet format, import, undo) | `os_0031_imports` | T2 ✓, T3 ✓, T4, T5 ✓ |
| 3 | `pc/p2-t10-merit` (`ProgrammeFacts`, `MeritCheck`) | none new beyond T1/T8 copies (check) | T5 ✓, T8 |
| 4 | `pc/p2-t7-monitoring` (season monitoring, reports) | `os_0032_monitoring` | T3 ✓, T5 ✓ |
| 5 | `pc/p2-t9-coverage` (coverage screen, intake `current` gate) | none new (check) | T2 ✓, T5 ✓, T8 |
| 6 | `pc/p2-t11-calendars` (official calendars) | uses imports; check against T6 | T2 ✓, T6 |
| 7 | `pc/p2-t12-gate` (consistency rules 9–12, proofs, P2 handoff) | `os_0033_consistency_rules_9_12` | all |

**Use the integration branch as a cross-check.** `pc/p2-integration` ("P2 integration v2 of T4, T6, T7, T9, T11")
already combines T4, T6, T7, T9 and T11. Compare conflict resolutions against it, but merge task by task, with one
PR per task.

**Then the P2 gate (T12) and the people lane (spec §6.2: H4 registry batches, H5 verified sample per region, H7
one collected source).** The data work is on `pc/p2-research-batches` (10 behind `pai-connect`). It is the
critical path the spec warns about: people, not code.

## 5. Starting the next session on your own PC (T4 onward)

T4 onward runs in a **local** Claude Code session on your PC, not in the cloud. Set up once:

1. **Tools:** Git, Docker Desktop, Python 3.12 (the version CI uses), Node 22, and Claude Code. On Windows, use
   PowerShell. Keep line endings as LF: run `git config --global core.autocrlf input` before cloning.
2. **Code:**
   ```powershell
   git clone https://github.com/memsa771-hub/Pai-C.git pai-connect-work
   cd pai-connect-work
   git checkout pai-connect
   git fetch origin "refs/heads/pc/p2-*:refs/remotes/origin/pc/p2-*"
   ```
3. **Python:**
   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r backend/requirements.txt -r backend/requirements-dev.txt
   ```
4. **Test database (Docker):** this is the same database CI uses.
   ```powershell
   docker run -d --name os-test-pg -e POSTGRES_USER=os_test -e POSTGRES_PASSWORD=os_test -e POSTGRES_DB=os_test -p 5432:5432 postgres:16
   $env:OS_TEST_DATABASE_URL = "postgresql://os_test:os_test@localhost:5432/os_test"
   ```
   - If port 5432 is already taken (for example by a local `pai-merge` stack), use `-p 5433:5432` and port 5433 in
     the URL.
   - Next time, start it again with `docker start os-test-pg`.
5. **Check that the setup works** (from `backend/`):
   - `tach check`;
   - `python ../scripts/check_alembic_heads.py` (from the repo root: `python scripts/check_alembic_heads.py`);
   - `python -m pytest tests/os -q -p no:cacheprovider`. This takes about 20–25 minutes and should pass on
     `pai-connect`;
   - the legacy suite: `python -m pytest -q -p no:cacheprovider --ignore=tests/os`. In PowerShell, clear
     `PAI_API_KEY` first if it is set: `Remove-Item Env:PAI_API_KEY -ErrorAction SilentlyContinue`.
6. **Never** put API keys or real student data into the chat. Keys live only in your environment.

**First message for the local session** (paste it as is):

> Read `docs/connect/handoff/p2-merge-handoff.md` in full, then the P2 spec §5 and §6. Work only on `pc/p2-*`
> branches and PRs into `pai-connect`; never touch `pai-c`, `pai-os`, `dev`, `main` or `pai-merge`. Start with T4:
> merge `pai-connect` into `pc/p2-t4-reading`, renumber its migration as the handoff says, run `tach check` and
> both test suites, push, and open its PR. Ask me before anything outside that.

## 6. Earlier work this session (for context)

- **Slice 9a** is closed, and the owners accepted its gate. The billed run cost $0.49 per student.
- **The 9b entry conditions are merged into `pai-os`:**
  - #172: visa apply-by is 15 weeks before the semester start.
  - #173: real research of `semester_start`, plus an admin script.
  - #174 and #175: usable email, with the address from the student's PAI account.
  - #176: the CI timeout is 30 minutes.
- **`pai-merge`** (pai-c + pai-os) runs locally on Windows. The guide is `docs/local-test/WINDOWS-GUIDE.md`; the
  owners have since added live-run fixes and `docs/local-test/live-run-issues-2026-11-02.md`.
- **Email setup and the pilot server** are still open owner items.
