# PAI OS handoff: Slice 3 (Documents), after Task 6 (2026-10-21)

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
2. Check whether **#74 (Task 5)** is merged into `pai-os` (§1). If it is not, stop and tell the developer.
   Task 7 needs it.
3. Continue with **Task 7**, then Tasks 8, 9 and 10, then the final review (§6). Read each task's brief in the plan
   before starting it. The exact names and values are there, not here.

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
| 5 | The reader agent (`documents.v1.yaml`, `reader.py`) | **#74** | **open**, CI green when pushed (579 OS tests passed, 0 skipped) |
| 7 | The `os.document` workflow | — | **next** |
| 8 | The API | — | to do |
| 9 | Screens | — | to do (shared file `frontend/lib/api.ts`) |
| 10 | Sample set, Spike 2 runner, crash test, billed gate | — | to do |
| — | Final whole-slice review and one fix pass | — | to do |

Task 6 was done before Task 5 because Task 5 had to wait for #67, the shared reading loop.

**Branches:** `os/s3-t5-reader` (#74) is the only open task branch. These are merged and can be deleted:
`os/s3-spec`, `os/s3-t1-types`, `os/s3-t2-store`, `os/s3-t3-intake`, `os/s3-t4-validators`, `os/s3-t6-checks` and
`os/s2-gate-followup`. This handoff is on `chore/s3-handoff`.

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

On `pai-os` with #74 merged: `tach check` ✅, one alembic head ✅, and `pytest tests/os` **579 passed, 0 skipped**.
Without #74, 572 passed.

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

## 6. What is left, in order

### Task 7: the `os.document` workflow (needs #74)

Follow the plan's brief and model it on `app/os/knowledge/research/run.py`.

What's already there for you:
- `DocumentStore` / `FindingStore` / `ProfileStore` (`app/os/documents/store.py`);
- `check_upload` / `prepare` / `tiles` (`intake.py`);
- `build_readers` / `read_document` (`reader.py`; shared loop `run_in_reading_loop`);
- `validate` (`validators.py`);
- `cross_check`, `load_name_variants`, `NAME_VARIANTS` (`checks.py`);
- `load_document_types` (`types.py`);
- `AgentRuns` and `cost` (`knowledge/research/readings.py`).

Two known gaps to close in Task 7:
- **`AgentRuns` can't record a document reading yet:** `record()` takes a `research_run_id`, and `ON CONFLICT`
  names `uq_os_agent_runs_reading`. Add a document path (`document_id`, constraint `uq_os_agent_runs_document`).
- **`AgentRuns.month_spend()` sums all agents.** Filter it by agent, so document spend doesn't use up the research
  budget, and the reverse. The documents budget is `OS_DOCUMENTS_MONTHLY_USD`, default 10.

Run the legacy suite too, because the runner and worker are touched.

### Task 8: the API

Spec §4 exactly. Remember Review Focus #4: the same file from two students is allowed; the same file twice from one
student is `409`. Run the legacy suite.

### Task 9: screens

Spec §5, mobile-first at 360 px. `frontend/lib/api.ts` is shared, so the PR needs a Counsellor reviewer. The upload
uses `FormData`: a bare `fetch` with the same auth headers, **no** `Content-Type: application/json`.

### Task 10: sample set, Spike 2 runner, crash test, gate

- Build everything offline first: the generator, the scoring, the runner with the test model, and the crash test.
- **The billed gate needs:**
  1. the owner's go-ahead;
  2. a **verified** answer key. @MusawirKtk must check its 3 `check:` items and set `verified: true`;
  3. the real set, on @MusawirKtk's machine.
- The gate: the chosen mode reaches ≥ 0.90 of fields correct in both runs, every planted mismatch is caught, and
  each consistent bundle gets at most 1 variant flag.
- The runner prints only rates and counts, never values. If the gate fails: stop and report.

### Final review

Run one fresh reviewer, on the most capable model, over the whole Slice 3 diff (`git diff 29394d2..origin/pai-os`).
Give it:
- the spec, the plan, and the plan's Review Focus list verbatim;
- §5 of this file.

Then one fix pass: each Critical or Important finding gets a RED→GREEN test. Minors go to a "Deferred minors" list.
Then the slice gate PR `pai-os` → `dev`, **only when the owners say so**.

## 7. Open items for the owners

- [ ] Merge #74.
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
> (or `git show origin/chore/s3-handoff:docs/os/handoff/slice-3-handoff.md` if it isn't merged yet), all of it.
> Then read the Slice 3 spec and plan it names. Follow its working rules exactly, including the secrets and
> personal-data rules. Check the §3 environment without printing any secret, and run the §4 checks. Check whether
> PR #74 is merged into `pai-os`. Then tell me in a few lines where Slice 3 stands and what you'll do next, and
> wait for my go. After my go, do Task 7 natively with TDD, one branch and PR from `pai-os`, and carry on through
> Tasks 8–10 and the final review without check-ins. Stop only for a merge, a billed run, a key, real data, or
> anything going into `dev`.
