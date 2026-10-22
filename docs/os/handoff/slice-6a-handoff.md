# PAI OS handoff: Slice 6a (the application pack) built; Slice 6b (the visa file) next (2026-10-22)

**A new session reads this file first, all of it.** It continues `slice-5-handoff.md` (in #110), which still holds the
environment, people, rules and earlier history. Where they disagree, this file is newer.

Authority order: parent spec > Slice 6a spec > Slice 6a plan > the rulings in the PRs > this handoff.
- **Slice 6a spec and plan:** `docs/superpowers/specs/2026-10-22-pai-os-slice-6a-design.md`,
  `docs/superpowers/plans/2026-10-22-pai-os-slice-6a.md` (both in #111).

## 1. Where things stand

Slice 6a is built, reviewed and fixed, in **ten stacked PRs: #112 → #121** (each PR's base is the previous one). Merge
**#111** (spec and plan) first, then **#112 … #121 in order**. After each squash merge, rebase the next branch with
`git rebase --onto origin/pai-os <old base> <branch>` and push with `--force-with-lease`.
- #112 (`requirements.txt`) and #120 (`frontend/lib/api.ts`) touch shared files: they need a Counsellor review.
- **Never open or prepare a `pai-os` → `dev` PR.** The owners merge once, at the very end of all slices.

On the final tip `os/s6a-t10-gate`:
- `pytest tests/os`: **933 passed, 0 skipped**. The 5 failures on native Windows are the `SIGKILL` crash tests
  (including the new `test_crash_during_pack_build`) and `test_worker_enqueues_by_itself`; Linux CI runs them.
- Legacy suite: **1006 passed**, 3 pre-existing skips.
- Frontend: Vitest **98 passed**, `tsc` clean, OS-enabled build passes.
- Alembic head **`os_0010`**.

### What Slice 6a built (no AI)
- **Pack config per route:** `app/os/packs/<route>.yaml` (data sheet, checklist, formats, instructions per
  `application_route` value, fees), validated at startup. Fake Ireland and Pakistan BS configs are in
  `tests/os/fixtures/packs/`.
- **Rules:** `checklist.py` (research `required_documents` > route default > student additions), `datasheet.py`
  (gaps, never guesses), `instructions.py` (templates filled from facts, each step sourced).
- **Renderer:** `render.py`. ReportLab in invariant mode gives byte-identical PDFs, with WinAnsi text. Documents are
  converted within `max_mb`, bounded to 3,000 px per page, kept encoded, with a 1,600 px legibility floor and 40
  pages at most. The original upload is never changed.
- **The `os.pack` workflow:** one step per file, no bytes in step outputs, `failed` never stuck. The workflow ID is
  `pack:{tenant}:{student}:{programme}:{inputs16}:v{version}[:r{attempt}]`.
- **Manifest and approval:**
  - The manifest is canonical JSON, including `inputs_sha256`. `GET` shows `building` while it is stale.
  - Approval binds the manifest's SHA-256, refuses a stale or incomplete pack, and completes `review_pack` through
    the kernel.
- **Tables:** `os_0009` adds `os_pack_files` (once per SHA-256 per student), `os_pack_items` and
  `os_profile_values.source`. `os_0010` adds the pack kind, statuses and the `system` author.
- **API:** `/v1/os/packs` (list, build, details, items, per-student download, approve).
- **Screens:** `/<workspace>/os-pack`.
- **Plan:** a `review_pack` task on Germany (after `application_documents`, before applying), a cited
  `uni_assist_fee_eur` constant, and the research field `required_documents`.

## 2. Rulings (binding unless the owners change them; each is in its PR)
The full list with costs is in each PR's "Rulings" section. The ones that matter most:
- **There is no Pack generator agent in 6a** (S6a-D5, owners). Add it back only to read unstructured,
  programme-specific instructions, through the Slice 5 facts check and student approval.
- **The pack step is route data.** The fake Ireland and Pakistan BS playbooks are shared Slice 1 fixtures and stay
  unchanged. Their packs build and approve completely; only Germany has `review_pack`.
- **A document is ready only when `confirmed`.** A format note such as "attested copy" is settled by the student's
  tick.
- **Approval depends on the checklist, not the data sheet.** Gaps are shown but don't block approval (spec S6a-D7);
  see deferred minor 5.

## 3. Deferred minors (from the final review)
1. `inputs_sha256` covers all of the student's material, so an unrelated change makes a new version and drops an
   approval.
2. Approve and a concurrent `store` step are not in one locked transaction.
3. `Item.note` is not shown on the screen.
4. Fees show no currency: put it in the YAML label.
5. Required `entered` fields don't block approval: add `kind: entered` checklist items (YAML only).
6. `URL.revokeObjectURL` runs right after `click()`, which can cancel a download in some browsers.
7. `added:{n}` can collide when two adds happen at once, and added items can't be removed.
8. The `os_0009` downgrade leaves the `entered.*` profile rows behind.
9. An image over Pillow's decompression-bomb limit says "upload a clearer copy" instead of "page too large".

## 4. Open items for the owners
- **Slice 6a spec §11:**
  - Q1: confirm dropping the Pack generator agent.
  - Q2: whether the application fee is a playbook constant (75, cited) or a research fact.
  - Q3: how long rendered pack files are kept.
- Everything still open from `slice-5-handoff.md` §7: the Spike 4 role-play run, the deferred minors, and the
  Slice 4 items.

## 5. Next: Slice 6b, the visa file
Spec → plan → build, as in 6a. Start with superpowers brainstorming, and **ask the owners first whether 6b needs
the Compliance agent at all** (the same question as for the Pack generator in 6a).
- 6b reuses 6a's renderer and checklist validator.
- It needs:
  - the funds calculator (a rule-based worker);
  - a route-level funds fact or a cited playbook constant;
  - the visa checklist;
  - the Phase C tasks (`blocked_account`, `travel_insurance`, `visa_apply`).

## 6. Environment notes (native Windows, this machine)
- **Docker Desktop crashes and won't restart** when it leaves broken socket files behind. Fix it while Docker is
  not running:
  - rename `%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` (each gets a `.broken-…` suffix);
  - start Docker Desktop, then wait without force-quitting it.
  - Free memory is tight (about 4 GB of 16 GB).
- **Two throwaway databases on port 5433.** `os_test` is for full-suite runs (in a separate worktree, pinned to a
  commit). `os_dev` is for quick per-task runs, so the two never collide.
- **Run each stacked branch's full suite, not just the tip's.** A fixture change in Task 4 broke 13 Slice 1 tests
  that only the tip's full run caught.
