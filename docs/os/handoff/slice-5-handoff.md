# PAI OS handoff: Slice 5 (Statements) done; Slice 6 (Pack + visa file) ready to start (2026-10-22)

**A new session reads this file first, all of it.** It continues `slice-4-handoff.md`, `slice-3-handoff.md`,
`slice-1-handoff.md` and `README.md` in this folder. Those still hold the general rules, people, environment set-up
and earlier history. Where they disagree, this file is newer.

Authority order: parent spec > slice spec > slice plan > the rulings in §4 > this handoff.

- Parent spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (invariants §3.1, components §3, slices §6)
- **Slice 5 spec:** `docs/superpowers/specs/2026-10-22-pai-os-slice-5-design.md` (S5-D1…D12; API §4; screens §5)
- **Slice 5 plan:** `docs/superpowers/plans/2026-10-22-pai-os-slice-5.md`
- OS rules: `backend/app/os/CLAUDE.md` (invariants) and the root `CLAUDE.md`

## 0. Start here

1. Set up as in `slice-3-handoff.md` §3 (WSL, the throwaway Postgres on port 5433, the backend venv), then run the
   checks in §3 below. Everything must be green, with **0 skipped** in `tests/os`.
2. Slice 5 is built, reviewed and merged. **Next is Slice 6, scope B: Slice 6a (the application pack) first, then
   Slice 6b (the visa file).** Start 6a with superpowers brainstorming (§6). Nothing for Slice 6 is written yet:
   no spec, no plan, no code.
3. **Never open or prepare a `pai-os` → `dev` PR.** The owners merge `pai-os` into `dev` once, at the very end of
   all slices.
4. One item is still open from Slice 5: **the billed Spike 4 role-played run** (§7). It needs the owners' OK and
   people. It does not block Slice 6.

## 1. Where things stand

- **Slices 0–5:** built and merged into `pai-os`. All Slice 5 PRs are merged: #99 (spec and plan) and #100–#109
  (Tasks 1–10 plus the final-review fixes, which went in with #109).
- On `pai-os` at `1d11a69`:
  - `pytest tests/os`: **858 passed, 0 skipped**;
  - the legacy (Counsellor) suite: **1006 passed, 3 skipped** (pre-existing skips);
  - frontend Vitest: **84 passed**; `tsc` and the OS-enabled build pass;
  - `tach check` passes, and there is one alembic head (`os_0008`).

### What Slice 5 built

- **Route config** (`app/os/statements/`):
  - `config.py`, plus one YAML file per route (`germany_master.yaml`; a fake `ireland_master.yaml` in tests);
  - each route has 8–12 interview questions, and each kind (`sop`, `cv`) has a rubric, a default limit (SOP 1,000
    words, CV 700) and the profile keys it may use;
  - `documents_task` is the plan task that approval completes, and `allowed_names` are names a draft may use
    without the student writing them (countries, agencies);
  - startup fails on an unknown route, profile key or task (`mount.py`).
- **Tables (`os_0008`):** `os_statement_answers`, `os_artifacts`, `os_artifact_versions`, `os_approvals`,
  `os_statement_rules`, plus `os_agent_runs.artifact_id`. **They are generic: Slice 6 reuses `os_artifacts`,
  versions and approvals** (S5-D7). A version never changes in place, and an approval stores the version's
  SHA-256.
- **`ArtifactStore`** (`app/os/artifacts/store.py`): adding a version drops the approval, because a newer text is
  not the approved one.
- **Statement rules** (`rules.py`): research's `statement_requirement` (`needed`, `limit_words`, `limit_chars`; a
  `needed: true` must be stated in the quote) wins over the student's pasted prompt and limit, which wins over the
  route default (labelled as a default).
- **Writer and Critic** (`agents.py`; `agents/writer.v1.yaml`, `critic.v1.yaml`):
  - tool-less actors on the strong tier;
  - all student data is fenced, and `<<<` is defused;
  - the Critic returns scores, fixes, at most 2 follow-up questions, and `ok`.
- **Facts check** (`facts_check.py`, no AI): every name, number and date in a draft must appear in the answers, the
  profile, the programme prompt or the allowed names. A single capitalised word inside a sentence counts as a
  name. Generic application vocabulary (headings, salutations, degree words) is never a name.
- **The `os.statement` DBOS workflow** (`run.py`):
  - write → check → review → at most 2 revisions → store;
  - follow-ups make the artifact wait as `needs_answers`;
  - the workflow ID is `statement:{tenant}:{artifact}:{inputs_sha16}:{attempt}`, where `attempt` grows only after
    a `failed` or `budget` run;
  - there is a monthly budget (`OS_STATEMENTS_MONTHLY_USD`, default $10), and the status `budget` is visible;
  - the worker registers it in `runner/worker.py`.
- **Interview and approval:**
  - `interview.py`: answers, follow-ups, pasted rules, `start_draft`;
  - `approval.py`: approval completes the plan's documents task through the kernel, with
    `{artifacts: {sop, cv, programme_sop?: sha256}}`; a task that becomes ready later completes on the next
    `GET /statements` or `GET /inbox`; `delete_statements` is ready for a student-deletion path.
- **API** under `/v1/os/statements`:
  - `GET /interview`, `PUT /answers/{id}`;
  - `GET /` (artifacts plus each programme's rules), `POST /{kind}/draft`;
  - `PUT /{id}/text` and `POST /{id}/approve`, both `409` while drafting;
  - `PUT /rules/{programme_ref}`.
- **Screens:** `/<workspace>/os-statements`: the interview cards, the drafts list, the programme rows (write the
  programme's own SOP, or paste its question), and the editor (count and limit, flagged phrases, the reviewer's
  notes, Save / Write again / Approve).
- **Spike 4 tools:**
  - `tests/os/fixtures/statements/personas.yaml` (10 fictional personas with planted traps);
  - `tests/os/quality/run_statement_quality.py` (prints rates and counts only);
  - `tests/os/test_slice5_gate.py` (interview → draft → edit → approve → task done, on Germany and the fake
    Ireland route).

## 2. Lessons from this slice (process)

- **Stacked PRs and squash merges, again.** After #100–#102 were squash-merged, every PR stacked on them conflicted.
  The fix each time was to replay only the branch's own commits onto the new `pai-os`
  (`git rebase --onto origin/pai-os <old base> <branch>`), check that `git diff <old tip> <new tip>` is empty for
  code, and push with `--force-with-lease`. Better: **after Tasks 1–3, stack PRs on each other (base = the previous
  branch) or merge in order and rebase as you go.**
- **Each stacked PR must pass CI on its own.** A test broken in Task 4 and fixed only in the final commit made
  #103–#108 red while #109 was green. Run the full suite on every branch, not just the tip.
- **Don't commit with a task branch checked out and then `git branch -f` the others.** Every commit landed on the
  checked-out branch (`os/s5-t4-rules` briefly held Tasks 4–10). Commit on a detached HEAD, or check out each
  branch in turn.
- **Don't edit files while a full suite runs in the same worktree.** A mid-run YAML edit produced a false legacy
  failure. Use a second worktree for edits.
- **Pushing from WSL needs the Windows credential helper**, or `git push` hangs on a prompt:
  `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c "credential.helper=/mnt/c/Program\ Files/Git/mingw64/bin/git-credential-manager.exe" push ...`
- **Scripts beat inline commands.** PowerShell mangles quotes in `wsl bash -c`, and heredocs from Git Bash lose
  escapes such as `\n` and `\'`. Write `.sh` or `.py` files and run them through WSL, and check any escapes in
  what they write.
- **The fresh final reviewer found 6 Important issues** that per-task tests missed (stuck retries, overwritten
  edits, stuck tasks, an unusable programme SOP, facts-check gaps, no polling). Budget a full fix pass.

## 3. Checks (expected now)

On `pai-os` at `1d11a69`:
- `tach check` ✅; `python scripts/check_alembic_heads.py` ✅ (head `os_0008`);
- `OS_TEST_DATABASE_URL=postgresql://postgres:os@127.0.0.1:5433/os_test pytest tests/os -v -rs`: **858 passed,
  0 skipped**;
- the legacy suite (no `OS_TEST_DATABASE_URL`, `--ignore=tests/os`): **1006 passed, 3 skipped**;
- frontend (in a Windows copy, see `slice-4-handoff.md` §2): Vitest **84 passed**, `tsc --noEmit` clean, and
  `NEXT_PUBLIC_OS_ENABLED=true npm run build` passes.

## 4. Rulings (Slice 5)

These are binding unless the owners change them; each is also in its PR.

**Owners' answers:**
- Scope: SOP and CV only.
- Rules come from research first, then the student's paste, then a labelled default.
- Interview: 8–12 fixed questions per route, plus at most 2 Critic follow-ups.
- §11 Q1: the default limits are SOP 1,000 words and CV 700.
- §11 Q2: English only.
- §11 Q3: the Spike 4 judges are the role-playing student plus one owner who didn't write the answers.

**Plan rulings:**
- New statuses `needs_answers` and `budget`.
- `os_statement_rules` holds pasted rules.
- `AgentSpec` gained the outputs `statement_draft` / `statement_review` and `spend_usd_per_artifact`.
- `save_answer` takes the route config (to refuse unknown questions).
- `answer_follow_up` re-enqueues waiting drafts.

**Routes:** a student's route is their newest open plan, matched to a playbook by origin, destination and level.

**Approval:** a programme's documents task needs the base SOP, the CV, and the programme's own SOP only when its
rules say `needed`.

**The facts check's scope** is names, numbers and dates. Vaguer inventions are for the Critic and the Spike 4
judges.

**`test_profile`:** the Germany research profile may hold fields the Spike 1 answer key doesn't score (Slice 5:
`statement_requirement`). The scorer skips them.

## 5. Deferred minors (from the Slice 5 final review)

1. Follow-up numbering (`followup:<n>`) can collide when the SOP's and the CV's Critics ask at the same moment
   (one set is dropped), or repeat if a step re-runs after it commits.
2. No cap on follow-up rounds, and `spend_usd_per_artifact` (0.30) is not enforced per artifact. Open follow-ups
   block every draft (409), and answered follow-ups can't be revised.
3. A stale tab can approve an old version (`approve` accepts any version number).
4. A workflow that errors in `load` or `record` leaves the artifact `drafting`, so the page polls for ever. If no
   worker has a model key, enqueued drafts never run and nothing tells the student.
5. Character limits are not shown in the editor (versions store only `limit_words`).
6. A number in a Critic follow-up question counts as a source even if the student's answer is "no".
7. `Draft.used_sources` (spec §2) and "missing profile values … listed" (§6) are not built.
8. There is no student-deletion path in the OS yet; `delete_statements` waits for it.

## 6. What comes next: Slice 6, Pack + visa file (scope B, chosen 2026-10-22)

Parent spec §3 and §6: **"6 Pack + visa file | pack generator, Compliance, checklists, renderer | test student's
pack and visa file complete"**. The owners chose to **split it into two slices, each with its own spec → plan →
build cycle:**

- **Slice 6a: the application pack (first).** Per programme:
  - a **data sheet** with every commonly asked field, filled from the confirmed profile;
  - the student's **documents in the required format and size**;
  - the **approved SOP and CV** (Slice 5, bound by SHA-256);
  - a **checklist**, checked by a rule-based validator;
  - the programme's **application route and fees**;
  - the **renderer** (PDF/DOCX), which must be deterministic so a rendered file is traceable to the approved
    version.

  The parent spec's agent is the **Pack generator** (actor, cheap tier, writes a draft pack, guarded by the
  checklist validator and student approval). **The student submits and pays themselves**; the OS never submits.
- **Slice 6b: the visa file (second).** It reuses 6a's renderer and checklist validator:
  - the **funds calculator** (a rule-based worker; Slice 4 S4-D1 left it for this slice);
  - the **Compliance** agent (actor, cheap tier) that assembles the visa and funds file;
  - the visa checklist;
  - the playbook's Phase C tasks (`blocked_account`, `travel_insurance`, `visa_apply`).

### What already exists for Slice 6 to build on
- **Artifacts, versions and approvals:** the generic tables from Slice 5. A rendered pack can be one more artifact
  kind.
- **Confirmed profile values:** `ProfileStore` (Slice 3), keys `<doc_type>.<field>`.
- **Document types:** passport, transcript, degree certificate, IELTS TRF, SSC, HSSC, min passing grade letter.
- **Research fields** in the Germany research profile: `language_of_instruction`, `tuition_fee_non_eu_eur`,
  `semester_contribution_eur`, `deadline_open`, `deadline_close`, `application_route`, `english_requirement`,
  `german_requirement`, `grade_requirement`, `statement_requirement`, `admission_test`, `intakes`.
- **Germany playbook tasks:** `application_documents` (completed by Slice 5 approval), `uni_assist_apply`,
  `direct_apply`, and Phase C `blocked_account`, `travel_insurance`, `visa_apply`.
- **Eligibility cards** (Slice 4) and the grade converter.

### Gaps to settle in brainstorming (found while preparing this handoff)
- The playbook's `application_documents` task cites `citation_from_fact: required_documents`, but **there is no
  `required_documents` research field**. The pack checklist needs one, or a route-level list.
- **No research field holds format and size rules** for uploads (PDF only, max MB, certified copies,
  translations).
- **The funds amount (blocked account per year) is not a fact yet.** It is a route-level (country) fact, not a
  programme one. Slice 6b needs a route-scope fact or playbook constant with a citation.
- There is no renderer and no PDF/DOCX library in the backend yet. It must work in the worker container, be
  deterministic, and keep the output traceable.
- What a "data sheet" holds is not defined. It may be route data (YAML), like the interview questions.

### How to run it
superpowers brainstorming (architectural path) → the Slice 6a spec → its plan → native execution with TDD → one
fresh reviewer on the most capable model → one fix pass. Keep everything **route-agnostic (invariant 12)**: field
lists, checklists, formats and amounts are YAML or research facts, never Python, and the fake Ireland and Pakistan
BS routes must run unchanged.

## 7. Open items for the owners

- [ ] **Spike 4, the billed role-played run** (it needs your OK):
  - Owners and colleagues play 10 students. Their personas go in `~/spike5-roleplay/personas.yaml` (outside the
    repo; never in chat or logs).
  - Run `python -m tests.os.quality.run_statement_quality --model openai --set roleplay --runs 1 --out roleplay.json`.
  - The judges (the role-playing student and one owner who didn't write the answers) rate each draft in
    `~/spike5-roleplay/ratings.yaml`; then run `--score`.
  - The gate is at least 8 of 10 usable after one edit for each kind, and 0 invented facts. Then write
    `docs/os/slice-5-quality-report.md` (rates and counts only).
- [ ] Decide the 8 deferred minors (§5): one small PR, or later.
- [ ] Still open from Slice 4:
  - verify Germany's grade rounding (`truncate`);
  - review student-requested programmes;
  - the Slice 4 deferred minors;
  - the earlier items (Slice 3 spec §11 Q1–Q3, the TU Chemnitz `application_route` hand-confirm, rotating the keys
    pasted into chat in earlier sessions).

## 8. Prompt for the next session

Set up first (`slice-3-handoff.md` §3). Then start `claude` in the repo root and paste:

> Continue PAI OS. Run `git fetch origin`, then read `docs/os/handoff/slice-5-handoff.md` from `pai-os`, all of it,
> and the files it names when you need them. Follow its working rules, including the secrets and personal-data
> rules, and never open or prepare a `pai-os` → `dev` PR. Run the §3 checks. Then tell me in a few lines where
> things stand, and start Slice 6a (the application pack) with superpowers brainstorming: the owners chose to split
> Slice 6 into 6a (pack) then 6b (visa file). Classify it, read the parent spec's Slice 6 parts and this handoff's
> §6 gaps, and ask me one question at a time. Do not write code until the 6a spec and plan are approved.
