# PAI OS handoff: Slice 3 (Documents), after Tasks 7–10 and the final review (2026-10-21)

**A new session reads this file first, all of it.** It continues `slice-1-handoff.md` and `README.md` in this
folder, which still hold the general rules, people and earlier history. Where they disagree, this file is newer.

Authority order: parent spec > Slice 3 spec > Slice 3 plan > the rulings in §5 > this handoff.

- Parent spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (invariants §3.1)
- **Slice 3 spec:** `docs/superpowers/specs/2026-10-20-pai-os-slice-3-design.md` (S3-D1…D12; API §4, screens §5,
  gate §9)
- **Slice 3 plan:** `docs/superpowers/plans/2026-10-20-pai-os-slice-3.md` (Tasks 1–10, Global Constraints,
  Review Focus)
- OS rules: `backend/app/os/CLAUDE.md` (invariants) and the root `CLAUDE.md`

## 0. Start here

1. Set up the environment (§3) and run the checks (§4). Everything must be green with **0 skipped**.
2. Check which of **#76–#79** are merged into `pai-os` (§1). Merge order: #76 first, then #78, #79 and #77.
3. All Slice 3 code is written and reviewed. What is left is the **billed Spike 2 gate** (§6) and the slice gate
   PR into `dev`. Both need the owners.

## 1. Where things stand

**Slices 0–2:** built and merged into `pai-os`.
- The Slice 2 quality gate passed at the owners' pilot bar: confirmed ≥ 0.45, correct ≥ 0.95. See
  `docs/os/slice-2-quality-report.md`.
- The Slice 2 gate PR into `dev` (#66) is **closed on purpose**. Reopen it only when the owners say so.
- **Nothing goes into `dev` without the owners' explicit go.**

**Slice 3:**

| Task | What | PR | State |
|---|---|---|---|
| spec + plan | | #68 | merged |
| 1 | Document types as YAML config, loader, `reading_model()` | #69 | merged |
| 2 | Tables `os_0004` and the store | #70 | merged |
| 3 | Intake: upload checks, page preparation, tiles | #71 | merged |
| 4 | Validators, including MRZ | #72 | merged |
| 6 | Cross-checks and name variants | #73 | merged |
| 5 | The reader agent (`documents.v1.yaml`, `reader.py`) | #74 | merged |
| 7 | The `os.document` workflow (+ migration `os_0005`) | **#76** | open; merge first |
| 8 | The API | **#78** | open; stacked on #76 |
| 9 | Screens (shared `frontend/lib/api.ts`; Counsellor reviewer @memsa771-hub) | **#77** | open; merge after #78 |
| 10 | Sample set, Spike 2 runner, crash test (offline) | **#79** | open; stacked on #76. **Billed gate not run** |
| — | Final whole-slice review and one fix pass | in #76, #78, #77 | done (§6) |

Task 6 was done before Task 5 because Task 5 had to wait for #67, the shared reading loop.

**Branches:** the open task branches are `os/s3-t7-workflow` (#76), `os/s3-t8-api` (#78), `os/s3-t9-screens`
(#77) and `os/s3-t10-gate` (#79). #78 and #79 are stacked on #76. Once #76 is squash-merged, rebase them on `pai-os`
(`git rebase --onto origin/pai-os os/s3-t7-workflow <branch>`), so each shows only its own commits.
- Merged and can be deleted: `os/s3-spec`, `os/s3-t1-types` … `os/s3-t6-checks`, `os/s3-t5-reader`,
  `chore/s3-handoff` and `os/s2-gate-followup`.
- This handoff is on `chore/s3-handoff-final`.

## 2. Working rules

- **Native (inline) execution**, which the owner chose: implement every task yourself, with TDD. Write the plan's
  failing tests first, watch them fail, implement, then watch them pass. No subagent per task. **One fresh
  reviewer** checks the whole slice at the end (§6).
- **One branch and PR per task:** `os/s3-t<N>-<name>`, cut from the latest `origin/pai-os`, touching only that
  task's files. Squash-merged.
  - Stack a branch on another only when it needs unmerged code. Say so in the PR text, and tell the developer to
    merge the base first.
- **Before every push**, from `backend/`, all of the following must pass, with 0 skipped:
  `tach check`, `python scripts/check_alembic_heads.py`, `python -m pytest tests/os -v -rs`.
  - Also run the **legacy suite** when a task touches `app/os/runner`, a shared file, or `main.py`. That means Tasks
    7 and 8, and Task 9's `api.ts`. Run it without the OS DB URL, as CI does:
    `python -m pytest tests -q -p no:tach --ignore=tests/os`. It takes about 15 minutes.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. PR bodies follow
  `.github/pull_request_template.md`: What changed, Rulings, Tests with the test count, Rules touched. They end with
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Record every decision the plan does not settle** as a ruling: in the PR's "Rulings" section, with why and what
  it costs if wrong. Add it to §5 of this file when you next update it.
- **Shared files need a reviewer from each team.** For Slice 3, that is `frontend/lib/api.ts` (Task 9); name a
  Counsellor reviewer (@memsa771-hub) on that PR.
- **The owners want speed.** Keep messages short. Don't check in between tasks. Ask only when a decision is
  theirs: merges into `dev`, gates, money, keys, real data.
- **If a step fails in a way the plan does not explain, stop and say so.** Don't improvise around it.

### Secrets and personal data (hard rules)

- Never print, echo, log or commit `OS_OPENAI_API_KEY`. Check it only with
  `[ -n "$OS_OPENAI_API_KEY" ] && echo set || echo MISSING`. Never run `env` or `printenv` unfiltered.
- The test database is a throwaway (port 5433). Never point anything at another database.
- **No billed OpenAI run without the owner's explicit OK.** Don't re-run one either without that OK.
- **The real Spike 2 documents stay outside the repo.** They are real people's passports, transcripts, degrees and
  IELTS forms, given with consent to @MusawirKtk only.
  - They live on @MusawirKtk's machine in `~/spike2-docs/` (`docs/` and `answer_key.yaml`), not in the repo.
  - No value from them may appear in code, tests, fixtures, logs, commits, PR text or chat.
  - Tests use only synthetic files and the generated sample set (Task 10).
  - The real-set run in Task 10 happens on @MusawirKtk's machine, or wherever they decide.

## 3. Environment (a fresh local machine)

Linux, macOS, or WSL2 (Ubuntu) on Windows. The crash tests need POSIX signals, so native Windows Python won't work.

1. **Repo:** `git clone https://github.com/memsa771-hub/Pai-C.git`, or `git fetch origin` in an existing clone.
   Then `git checkout -B os/<branch> origin/pai-os` for each task.
2. **Python 3.12** (CI's version). In `backend/`:
   `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt`.
   Slice 3 needs no new packages: `pypdf`, `pypdfium2` and Pillow are already in `requirements.txt`.
3. **Postgres 16** in Docker:
   `docker run -d --name os-pg -p 5433:5432 -e POSTGRES_PASSWORD=os -e POSTGRES_DB=os_test postgres:16`.
   Start it again later with `docker start os-pg`.
4. **Test env**, in the shell before `claude`, or in a small `env.sh` you source:
   ```bash
   export OS_TEST_DATABASE_URL=postgresql://postgres:os@127.0.0.1:5433/os_test
   export OS_DATABASE_URL=$OS_TEST_DATABASE_URL
   ```
   The pre-push `pytest tests/os` run should run like CI: unset `OS_DATABASE_URL` and `OS_OPENAI_API_KEY` for that
   command.
5. **Key:** needed only for Task 10's billed run, and only with the owner's OK. Set `OS_OPENAI_API_KEY` in the
   shell before starting `claude`. Never paste it into chat.
6. **PRs:** `gh pr create --base pai-os --head <branch> --title ... --body-file ...` (GitHub CLI, signed in as you).

## 4. Checks (expected now)

On `pai-os` before #76–#79: `tach check` ✅, one alembic head ✅, and `pytest tests/os` **579 passed, 0 skipped**.
Each branch's count includes its base; see the PRs. The legacy suite gives 1006 passed (3 skips are pre-existing and
need `APP_ENV=production`).

**Native Windows (no WSL):**
- Four `test_crash.py` tests fail there: `test_worker_enqueues_by_itself`, `test_crash_no_lost_or_duplicated`,
  `test_crash_during_research` and the new `test_crash_during_document_read`. There is no `SIGKILL`, and the worker
  subprocess doesn't start. That is expected; Linux CI runs them.
- Set `PYTHONUTF8=1`: the research replay fixture is UTF-8.
- Put `.venv/Scripts` on `PATH`: the Tach tests call `tach`.
- In PowerShell, the GitHub CLI is `& "C:\Program Files\GitHub CLI\gh.exe"`.

## 5. Rulings so far (Slice 3)

These are binding unless the owners change them. Each is also in its PR.

- **T2:** the field-check column is `check_result`, because `check` is a SQL keyword. The store still returns it as
  `check`.
- **T2:** duplicate uploads count only live documents (a partial unique index skips `deleted`), so a student can
  re-upload a file they deleted.
- **T2:** document readings reuse `os_agent_runs`, with a new `document_id` (unique with `reading`) and a nullable
  `research_run_id`. Spend stays in one table.
- **T3:** a PDF page with under 200 characters of text is rendered as an image, because a few stray words from a
  stamp don't make a readable page. Tiles overlap by 10% of a band.
- **T4:** the expiry check hangs on the `mrz` rule's expiry field, not a field name, so Python knows no
  document-specific names.
- **T4:** a rule runs only on values that passed their own check. An MRZ birth year in the future means the 1900s.
- **T4:** the plan's MRZ specimen was one character short. The tests use the real ICAO specimen,
  `L898902C36UTO7408122F1204159ZE184226B<<<<<10`.
- **T6:** the passport's `father_or_husband_name` is not cross-checked, because it may hold a husband's name.
- **T6:** a missing or extra name token is a mismatch, not a variant. Dates of birth must be identical ISO strings.
  "Abdul Rehman" / "Abdulrehman" is a variant.
- **T5:** the agent limits take `spend_usd_per_document` beside `spend_usd_per_programme`, and at least one is
  required. `mode` (`whole | tiles`) defaults to `whole` until Spike 2 decides it.
- **T5:** `detected_type` is free text. Task 7 compares it with the expected type.
- **T7:** over the monthly documents budget, the workflow **ends**. It does not sleep, because a sleeping workflow
  holds one of the 4 slots on the shared `os` queue. The document stays `uploaded` with a `budget_exceeded` event. A
  daily `documents_retry` job (00:10 UTC) re-enqueues `uploaded` documents, with `:YYYY-MM-DD` added to the workflow
  ID.
- **T7:** `start` claims a document in one statement (`uploaded` → `reading`) and records the workflow in
  `os_documents.claimed_by` (migration `os_0005`). A replay after a crash inside `start` carries on, and any other
  workflow is refused.
- **T7:** file bytes and page images never go into a DBOS step output. `prepare` only checks the file; the pages are
  prepared again, deterministically, at workflow level just before the reading.
- **T7:** `detected_type` matches when it names the chosen type's key or label as whole words, either way round. An
  empty answer is a match. A failed reading stores only the error's kind, never its message.
- **T7:** the cross-check runs **after** `finish`, one student at a time (advisory lock), over `read`,
  `needs_student` and `confirmed` documents, preferring confirmed values. `AgentRuns.month_spend(now, agent)` is per
  agent. The $0.05 per-document cap is recorded, not enforced up front (one reading, request limit 3).
- **T8:** profile keys:
  - `full_name`, `father_name` and `date_of_birth` stay as they are. Each is held back while an open finding covers
    it, and never overwrites a value the student chose when resolving a finding.
  - Every other confirmed, non-empty field becomes `<doc_type>.<field>`.
- **T8:** findings:
  - Confirming re-runs the cross-checks.
  - A resolved finding (same kind, field, documents and values) is not reopened.
  - Resolve accepts only one of the values found, sourced from the document that showed it.
- **T8:** delete:
  - It removes the file, the fields, the profile values sourced from them, and the document's **DBOS workflows**,
    whose step outputs hold the values read. The row stays as `deleted`.
  - A failed document can be deleted and the same file uploaded again; this is the spec §6 "retry".
- **T8:** a lost enqueue is picked up by the daily retry. `GET /documents` also returns `doc_types` (key and label
  from the YAML).
- **T9:**
  - Type labels come from the API.
  - Resolve is one button per value found.
  - Rows that can't be opened (failed, waiting, reading) show Delete.
  - An empty box confirms `null`.
- **T10:**
  - The sample mark is drawn with a hyphen, because the built-in font has no en dash.
  - Determinism is tested by generating the set twice, because Pillow is not pinned.
  - The real answer key uses the sample key's format: `verified`, `documents: {file: {type, person?, fields,
    check?}}`.
  - A planted variant counts as caught by any finding on its field. A consistent bundle fails on any mismatch, or on
    more than one variant flag.
  - The runner prints and writes only rates and counts, not even file names.

## 6. What is left, in order

### Final review: done

One fresh reviewer (Opus) read the whole Slice 3 diff, with the spec, the plan, the Review Focus list and §5. Its
findings and the fix pass, each fixed with a RED→GREEN test:

| # | Finding | Fix | PR |
|---|---|---|---|
| C1 | After a delete, the values read stayed in DBOS step outputs (the model request's output) | Delete cancels and deletes the document's workflows (`forget_document`) | #78 |
| I1 | Documents read at the same time skipped each other's cross-check, so no finding was written | Cross-check after `finish`, with a per-student advisory lock | #76 |
| I2 | Confirming a document overwrote a value the student chose when resolving a finding | Resolved fields are held back | #78 |
| I3 | A failed or stuck document was a dead end on the screens | Delete on rows that can't be opened, so the file can be uploaded again | #77, #78 |

Review Focus coverage:
- Items 1, 2, 4 and 5 are covered by tests.
- Item 3 is covered at 6000×4500 rather than 8000×6000. "Stored as uploaded" is checked by the store's round-trip
  test.

**Deferred minors** (not fixed in Slice 3):
1. `finish` and `store` check for `deleted` and then write in a second statement, so a delete in between can turn the
   row back to `read` with no bytes. Fix: `UPDATE … WHERE status <> 'deleted'`.
2. If `enqueue_document` raises after the upload is stored, the student gets a 500. The daily retry still reads the
   document. Fix: catch the error and still return 201.
3. PDFs have no cap on pages or render size, which risks memory and cost. Fix: cap pages and pixels, and fail with a
   reason.
4. `enum` and number fields are typed in the reading model, so an off-list value fails output validation instead of
   being stored as `check_failed`.
5. A number field that was read as null and then typed by the student is confirmed as a string.
6. The Spike 2 runner passes on whatever subset of real files exists (`missing_files` is only counted), and it
   accepts `--runs 1`. Until that is enforced, run the real set with `--runs 2` and check that `missing_files` is 0.
7. `validators._yymmdd` uses `date.today()` instead of the `today` passed to `validate`.

### The billed Spike 2 gate (Task 10 step 6): waiting for the owners

It needs three things:
1. the owner's go-ahead (about $1–3 a run);
2. @MusawirKtk verifying the answer key's 3 `check:` items and setting `verified: true`, in the format above;
3. the run on @MusawirKtk's machine:

```bash
python -m tests.os.quality.run_document_quality --model openai --set real --mode whole --runs 2 --out real-whole.json
python -m tests.os.quality.run_document_quality --model openai --set real --mode tiles --runs 2 --out real-tiles.json
python -m tests.os.quality.run_document_quality --model openai --set sample --mode whole --runs 1 --out sample.json
```

The gate:
- the chosen mode reaches ≥ 0.90 of fields correct in both runs;
- every planted finding is caught;
- no consistent bundle gets a mismatch or more than one variant flag.

If it passes, set the chosen mode in `agents/documents.v1.yaml` and write `docs/os/slice-3-quality-report.md` (rates
and per-type rates only). If it fails, stop and report.

After that comes the slice gate PR `pai-os` → `dev`, **only when the owners say so**.

## 7. Open items for the owners

- [x] Merge #74.
- [ ] Merge #76 (Task 7) first. Then rebase #78 (Task 8) and #79 (Task 10) on `pai-os` and merge them. Then merge
  #77 (Task 9), which needs a Counsellor review of `frontend/lib/api.ts`.
- [ ] Give the go-ahead for the billed Spike 2 gate (§6).
- [ ] The `pai-os` rule: the owners chose to drop the required review on `pai-os` and keep CI required. Every
  change is still reviewed at the `pai-os` → `dev` gate. @memsa771-hub (admin) makes the change. `dev` stays as it is.
- [ ] @MusawirKtk: verify the Spike 2 answer key (3 `check:` items) and set `verified: true`.
- [ ] An admin hand-confirms TU Chemnitz Automotive `application_route` = `direct` (Slice 2 report condition).
- [ ] Spec §11 questions Q1–Q3: file retention, admin file access, and who maintains the name variants.
- [ ] Rotate the keys pasted into chat in earlier sessions. Use a budgeted PAI OS OpenAI project key for billed runs.
- [ ] Reopen the Slice 2 gate PR (#66) into `dev` when the owners decide.

## 8. Prompt for the next session

Do the §3 setup first. Then start `claude` in the repo root and paste:

> Continue PAI OS Slice 3. Run `git fetch origin`, then read `docs/os/handoff/slice-3-handoff.md` from `pai-os`
> (or `git show origin/chore/s3-handoff-final:docs/os/handoff/slice-3-handoff.md` if it isn't merged yet), all of
> it. Then read the Slice 3 spec and plan it names. Follow its working rules exactly, including the secrets and
> personal-data rules. Check the §3 environment without printing any secret, and run the §4 checks. Check which of
> PRs #76-#79 are merged into `pai-os`, and rebase any stacked branch that needs it. Then tell me in a few lines where
> Slice 3 stands and what is next, and wait for my go. Stop for a merge, a billed run, a key, real data, or anything
> going into `dev`.
