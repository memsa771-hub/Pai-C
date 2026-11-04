# P0 Counsellor Fixes Implementation Plan (R-47: C1, C2, C3, C5, C6, C7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the six Counsellor problems from the 2 Nov live run (`docs/local-test/live-run-issues-2026-11-02.md`) so that an excluded field stays dismissed (C1), one failed analysis never blocks later ones (C2), every "I'll check" either runs or ends with the existing "couldn't find an answer" notice (C3), the newest chat paths card and Roadmaps read one list (C5), the reply follows the student's language and greets once (C6), and onboarding asks for marks (C7). When all six are in, R-47 is `built` and `--gate P0` passes.

**Architecture:** Small changes at each cause, reusing what exists: the reconciler accept hook (`app/memory/reconciler.py` `register_accept_hook`, already used by `paths.after_accept`), the possibility transition table, the durable job queue (`app/runtime/task_runtime.enqueue`) and the worker's existing `session.sweep` tick, the research gateway and `myths._deliver_information`, the Vault catalog's `onboarding` blocks, and the Voice guards. New fixed sentences and thresholds live in non-frozen data files. Two fixes (C2, C6) change frozen files and go in their own freeze-exception PRs; the other four share one branch.

**Tech Stack:** Python 3.12/3.13, FastAPI, SQLAlchemy, Alembic, pytest; Next.js, TypeScript 5.9, vitest.

**Spec:** docs/superpowers/specs/2026-11-03-p0-setup-design.md §5 (master: docs/superpowers/specs/2026-11-03-pai-connect-design.md §10)

## Global Constraints

- Frozen paths (master §10, `scripts/check_freeze.py`): `backend/app/pai_c/**/*.md`, `backend/app/pai_c/deep/`, `backend/app/pai_c/{planner,policy,voice}/prompts/`, `backend/app/pai_c/playbooks/`, `backend/app/pai_c/policy/actions/`, `backend/app/pai_c/policy/*.json`, `docs/counselor/COUNSELOR_V3_PROMPTS.md`, Counsellor model settings in `backend/app/config.py`.
- Only C2 and C6 touch frozen paths. Each is its own branch and PR into `pai-connect`: label `freeze-exception`, "R-47" in the title, the offline replay before/after and its diff summary, Counsellor lead (`@memsa771-hub`) approval.
- The non-frozen branch must pass `python scripts/check_freeze.py --base origin/pai-connect` with no label (exit 0). If a step there needs a frozen file, stop and ask.
- Read frozen data (e.g. `policy/myths.json`, `policy/possibilities.json`, `policy/study_fields.json`) but never edit it outside the C2/C6 PRs.
- No new chat behaviour beyond the fixes (master D-05, R-45). The only new sentence is the C1 notice (owner approves its wording, see Ruling needed). No change of tone or style.
- No change to `backend/app/config.py` model settings; no new config settings at all (thresholds go in data files).
- DB change only by Alembic migration (C1 adds a column, see Ruling needed); never drop a table; never edit `.env`; no live model calls.
- Every new backend test carries `@pytest.mark.req("R-47")` (or module `pytestmark`); every new frontend test file or block has `// req: R-47`.
- Backend tests, from `backend/`: `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider -p no:tach <files>`.
- Frontend, from `frontend/`: `npx tsc --noEmit`, `npm test`.
- Never weaken a test. Where a test asserted the old behaviour that a fix removes (C2's `test_failed_prior_turn_requires_replay_and_preserves_order`), it is rewritten to the new behaviour and the PR says why.
- Commit messages end with exactly these two lines (no model names in commits or files):
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```
- Branches, all cut from `origin/pai-connect`, squash-merged: `pc/p0-t4-c2-analysis` (C2), `pc/p0-t4-counsellor-fixes` (Task R0, C1, C5, C3, C7), `pc/p0-t4-c6-language` (C6 and the final task). Merge order follows spec §5.4: C2 PR, then the shared branch, then the C6 PR; rebase each on `pai-connect` before its PR.
- Offline replay command (the script imports `app` and `scripts.`, so it runs as a module from `backend/`, not as a file path): `env -u PAI_API_KEY python -m scripts.eval_counselor_deep --offline [--policy-mode guided] --result-dir <dir>`. It writes `counselor_deep_<YYYYMMDD>.json` and `.md` into `<dir>`.

## Review Focus

1. **A failed attempt that is retrying still blocks.** A predecessor in `pending` after a retryable failure (`attempts=1`, `last_error` set) must still make the later job wait; only `failed` is skipped (C2 test `test_pending_retry_of_a_failed_attempt_still_blocks`).
2. **Restore must stick.** A path dismissed by an exclusion and then restored by the student must not be dismissed again by the next analyzer run or the next unrelated Vault write while the same Vault item stands (C1 test `test_restored_path_is_not_dismissed_again`).
3. **The classifier already recorded the question.** Voice's `note_question` returns `duplicate`, the decision is not `answer_request`, and research must still start, exactly once (C3 test `test_classifier_recorded_question_starts_research_when_voice_note_is_duplicate`).
4. **Old cards don't change.** Only the newest paths card reads the current list; an older card keeps its snapshot even when the current list has five paths (C5 test `an older paths card keeps its snapshot and does not read the current list`).
5. **The prior record must not hijack the form.** After onboarding saves a separate completed Matric record for an Intermediate student, reopening onboarding still prefills Intermediate, and a second submission corrects that Matric record in place instead of adding another (C7 tests `test_prefill_after_prior_matric_record_keeps_intermediate`, `test_reonboarding_corrects_existing_matric_record_in_place`).

## Decisions (owner answers 2026-11-03; every other line below is built as its default)

- Owner approved: the C1 notice wording as proposed; fixed sentences stay English for now (translations later, as data);
  C7 marks of a completed exam are required, current-study marks and the entry test optional; C2 out-of-order replay
  of a skipped analysis is acceptable.

- **Decided (C1 match):** a Vault `option` item has only free `text` and `status`; it carries no field key. Default: the text is read through the catalog's `study_fields` choice list (`vault_catalog().choice_code("study_fields", text)`: code, label or synonym), which is the key family the path analyzer uses (`PaiPossibility.study_field["key"]`). "Pharm-D", "MBBS", "Medical Lab Technology", "Biotechnology" match today; "Pharmacy" or "MLT" do not unless synonyms are added to `vault_catalog.json`. Adding synonyms is a separate data change, not in this plan.
- **Decided (C1 storage):** `pai_possibilities` has no place for a dismissal reason and evidence. Default: Alembic migration `123_possibility_dismissal.py` adds a nullable JSONB column `dismissal` (`{"reason", "item_id", "quote", "at", "restored_at"?}`); downgrade drops the column only.
- **Decided (C1 notice wording and home):** `policy/*.json` is frozen, so the notice lives in a new non-frozen `backend/app/pai_c/paths/exclusion.json`. Proposed wording: one `"I've removed {titles} from your paths, since you said it isn't for you."`, other `"I've removed {titles} from your paths, since you said they aren't for you."` A new Counsellor sentence needs the owner's approval (master §10, escalations row).
- **Decided (C1/C3 notice language):** every existing fixed sentence (`information_unanswered`, `paths_found_message`) is English only; the C6 rule "follow the student" cannot apply to fixed sentences without translations. Default: English, like the existing fixed sentences.
- **Decided (C1 notice channel):** the reconciler hook has no chat channel. Default: a new durable job `counselor.paths_excluded` posts the notice into the channel of the source student event (`candidate.source_event_ids[0]`), else the channel of the student's latest message, else posts nothing (`{"status": "no_channel"}`); it waits for care like information delivery.
- **Decided (C1 no row yet):** "an exclusion that matches no path changes nothing" is read as "text that maps to no study field changes nothing". An exclusion that maps to a field with no path row yet changes no row and posts no notice, but the analyzer hides that field from the model so it is never suggested. Confirm.
- **Decided (C1 chosen path):** the frozen transition table has no `chosen -> dismissed`; default: a `chosen` path is left alone (the route decision owns it).
- **Decided (C2 "skipped"):** default without a migration or new status value: the failed predecessor keeps status `failed` (so `replay_failed_analyses` and its CLI work unchanged) and gets `result = {"skipped_by": <job id>}`; the later job's result lists `skipped_predecessors`. Consequence: a later operator replay applies the older turn after newer ones, so strict turn order is no longer preserved across a replay.
- **Decided (C3 wellbeing turns):** today research never starts on a wellbeing action. "Whatever the turn's decision" is built literally: research starts, and delivery already waits while care is active (`myths._deliver_information` defers). Confirm.
- **Decided (C3 failed jobs):** a research job that ends `failed` also leaves a silent promise; the spec names only "no job". Default: the sweep also covers a question whose job ended `failed`.
- **Decided (C3 scope):** only `kind == "information"` questions with `needs_research` are researched (`myths.enqueue_information`); `task`/`decision_help`/`other` rows with `needs_research` are not swept. Confirm.
- **Decided (C6 "same conversation"):** default: the Voice history the turn already loads (`PAI_COUNSELOR_HISTORY_SIZE` recent messages), so a student returning after that window may be greeted again.
- **Decided (C7 required marks):** the spec says intermediate marks are optional while studying and the entry test optional. Default: marks/grades of a completed record are required (Matric completed, Intermediate completed, the prior Matric of an Intermediate or DAE student, the prior O-level of an A-level student); marks of a current record and the entry test are optional.
- **Decided (C7 entry test with no score):** default: a chosen test with no score is saved with `details.status: "planned"` (as chat extraction does); with a score, no status.
- **Decided (R-47 built):** P0-D1 sets `built: true` in the PR that adds the tests; R-47's tests land in three PRs. Default: the final task is the last commit of the C6 PR (the last to merge), kept as a separate commit so the reviewer can tell it from the C6 change.

---

### Task R0: BEFORE replay on the base

**Branch:** `pc/p0-t4-counsellor-fixes` (now identical to `origin/pai-connect` in `backend/` and `frontend/`).

**Files:**
- Create: `docs/connect/replays/r47-before/default/counselor_deep_<date>.{json,md}`, `docs/connect/replays/r47-before/guided/counselor_deep_<date>.{json,md}`, `docs/connect/replays/README.md`, `docs/connect/replays/compare.py`

**Interfaces:**
- Produces: `docs/connect/replays/compare.py` — `python docs/connect/replays/compare.py BEFORE.json AFTER.json` prints a markdown table of every persona turn whose `reply`, `action.type`, `action_status`, `decision` or `guard_violations` differ, plus persona `status`/`stop_reason` changes, and `No differences.` when none. It ignores ids, timings, usage and cost (they differ every run).

- [ ] **Step 1: Confirm the base.** `git diff --stat origin/pai-connect -- backend frontend` → empty. If not, run Step 2 in a worktree of `origin/pai-connect` instead.
- [ ] **Step 2: Run both modes.** From `backend/`: `env -u PAI_API_KEY python -m scripts.eval_counselor_deep --offline --result-dir ../docs/connect/replays/r47-before/default` and the same with `--policy-mode guided --result-dir ../docs/connect/replays/r47-before/guided`. Expected: both exit 0; every persona `status: complete`.
- [ ] **Step 3: Self-check `compare.py`.** Comparing a before file with itself → `No differences.`; run it twice on the same base → `No differences.` (the replay is deterministic in the compared fields).
- [ ] **Step 4: `README.md`.** What each folder holds, the commands above, and what the replay cannot show: it forces each analysis job to `succeeded` (C2's cascade never appears), runs no path analysis, research, onboarding or frontend (C1, C3 sweep, C5, C7 show only "nothing else changed"), and replays recorded model outputs, so a prompt-only change (C6 language policy) shows no reply difference; C3's runtime start is exercised only in `--policy-mode guided`. Each fix is proved by its named tests.
- [ ] **Step 5: Commit.**
  ```
  test(counsellor): offline replay before the R-47 fixes

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task C2: A failed analysis no longer blocks later ones

**Branch:** `pc/p0-t4-c2-analysis` (frozen: exception PR).

**Files:**
- Modify: `backend/app/pai_c/deep/analysis.py` (`_prior_job_pending`, `analyze_job`; remove `AnalysisPredecessorFailed`)
- Test: `backend/tests/test_counselor_deep_pr4.py` (rewrite `test_failed_prior_turn_requires_replay_and_preserves_order`, add three tests; drop the `AnalysisPredecessorFailed` import)
- Create: `docs/connect/replays/c2/{before,after}/…`, `docs/connect/replays/c2/diff.md`

**Interfaces:**
- Consumes: `BackgroundJob` (`status` pending|running|succeeded|failed|cancelled, `result` JSONB), `replay_failed_analyses(db, workspace_id) -> int` (unchanged).
- Produces:
  - `_prior_job_pending(db, job) -> bool`: True only when an earlier (`(source_timestamp, user_event_id)` smaller) `counselor.analyze` job of the workspace is `pending` or `running`; earlier `failed` jobs never raise and never block.
  - `_skip_failed_predecessors(db, job) -> list[str]`: ids of earlier `failed` analyze jobs, in order; sets `other.result = {**(other.result or {}), "skipped_by": job.id}` only where `skipped_by` is not already set, commits, logs `counselor_analysis_predecessor_skipped workspace_id=%s job_id=%s skipped=%d` (counts and ids only).
  - `analyze_job(job, db) -> dict`: called inside the workspace lock after the second `_prior_job_pending` check; its success results (`applied`, `duplicate`, `patch_rejected`) gain `"skipped_predecessors": [ids]` when non-empty.

- [ ] **Step 1: Write the failing tests** (`@pytest.mark.req("R-47")` each), in `tests/test_counselor_deep_pr4.py` using `_turn_job` and `_model_notebook`:
  ```python
  async def test_failed_prior_turn_is_skipped_and_kept_for_replay():
      # first.status = "failed", attempts = max_attempts
      result = await analyze_job(second, db)            # model returns _model_notebook()
      assert result["status"] == "applied" and result["version"] == 1
      assert result["skipped_predecessors"] == [first.id]
      db.refresh(first)
      assert first.status == "failed" and first.result == {"skipped_by": second.id}
      assert replay_failed_analyses(db, student.workspace_id) == 1
      assert first.status == "pending" and first.attempts == 0

  async def test_pending_retry_of_a_failed_attempt_still_blocks():
      # first.status = "pending", attempts = 1, last_error = "AnalysisPatchRejected: x"
      with pytest.raises(AnalysisOrderPending):
          await analyze_job(second, db)
      model.assert_not_awaited()

  async def test_running_predecessor_still_blocks():          # first.status = "running"
      with pytest.raises(AnalysisOrderPending): await analyze_job(second, db)

  async def test_later_turn_advances_stage_after_patch_rejection():
      # first: model returns "not json" twice -> AnalysisPatchRejected; JobService(db).fail(first, "x", retry=False)
      assert first.status == "failed"
      with patch("app.pai_c.deep.analysis._advance_stage") as advance:
          assert (await analyze_job(second, db))["status"] == "applied"
      advance.assert_called_once()
  ```
  `test_analysis_waits_for_earlier_workspace_turn` stays as it is.
- [ ] **Step 2: Run** `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider -p no:tach tests/test_counselor_deep_pr4.py` → the new tests FAIL with `AnalysisPredecessorFailed: earlier analysis failed; replay required`; the running/pending tests pass already.
- [ ] **Step 3: Implement** the interfaces in `deep/analysis.py`: drop `"failed"` from the `status.in_(...)` filter of `_prior_job_pending`; delete `AnalysisPredecessorFailed` and its raise; add `_skip_failed_predecessors` and call it inside `async with _workspace_lock(...)` right after the second `_prior_job_pending` check (before `_candidate`, which rolls back). Add `"skipped_predecessors"` to each returned dict when non-empty. Update the `replay_failed_analyses` docstring: "failed turns, including ones a later analysis skipped".
- [ ] **Step 4: Run** the same file plus `tests/test_counselor_planner.py tests/test_planner_rejection_log.py tests/test_truth_map_v2.py tests/test_counselor_sessions*.py` → pass.
- [ ] **Step 5: Replay.** On this branch: `--result-dir ../docs/connect/replays/c2/after/{default,guided}`; before = `r47-before` from Task R0 (same base code; copy it into `c2/before/` on this branch). `python docs/connect/replays/compare.py …` for both modes into `c2/diff.md` → expected `No differences.` (the replay forces each analysis to succeed, README). The proof of C2 is the four tests above.
- [ ] **Step 6: Freeze check.** `python scripts/check_freeze.py --base origin/pai-connect` with no label → exit 1 listing only `backend/app/pai_c/deep/analysis.py`.
- [ ] **Step 7: Commit, push, PR** titled `R-47 C2: a failed analysis no longer blocks later ones`, label `freeze-exception`, body: cause, fix, the rewritten test and why, replay diff, the "Ruling needed (C2)" default, request `@memsa771-hub`.
  ```
  fix(counsellor): a failed analysis no longer blocks later ones (R-47 C2)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task C1: A field the student excluded stays dismissed

**Branch:** `pc/p0-t4-counsellor-fixes`.

**Files:**
- Create: `backend/app/pai_c/paths/exclusions.py`, `backend/app/pai_c/paths/exclusion.json`, `backend/alembic/versions/123_possibility_dismissal.py`
- Modify: `backend/app/models.py` (`PaiPossibility.dismissal`), `backend/app/pai_c/possibilities.py` (`transition`), `backend/app/pai_c/memory.py` (`ruled_out_options`), `backend/app/pai_c/paths/analyzer.py` (`after_accept`, `path_analysis_job`), `backend/app/pai_c/myths.py` (`care_active`), `backend/app/capabilities/system.py` (register the job), `frontend/lib/possibilities.ts` (optional `dismissal` on `Possibility`)
- Test: `backend/tests/test_path_exclusions.py` (new), `backend/tests/test_possibilities.py` (migration test)

**Interfaces:**
- Consumes: `VaultItemService(db).active(ws, ["option"])` via `app.pai_c.memory.MemoryService`; `vault_catalog().choice_code("study_fields", text)`; `PossibilityService.transition(ws, id, "dismiss")` (frozen table allows suggested/saved/exploring → dismissed); `register_accept_hook` (already calls `paths.after_accept`; `option` is already a `vault_trigger_types` entry, so a path run is queued too); `send_to_student`.
- Produces:
  - `PaiPossibility.dismissal = Column(JSONB, nullable=True)`; migration `123` (down_revision `122`) adds/drops only that column.
  - `MemoryService.ruled_out_options(self, workspace_id) -> list[dict]`: active `option` items with `value["status"] == "ruled_out"` and `level != "inferred"`, as `{"item_id", "text", "quote", "level"}` (`quote` from `evidence["quote"]`, else the last corroboration's quote, else `text`).
  - `exclusions.excluded_fields(db, workspace_id) -> dict[str, dict]`: study field key → that option dict; texts that map to no field are left out.
  - `exclusions.apply_exclusions(db, workspace_id) -> list[PaiPossibility]`: for each row with status in `{"suggested", "saved", "exploring"}` and `study_field["key"]` in `excluded_fields`, unless `row.dismissal` has the same `item_id` and a `restored_at`: transition `dismiss`, set `row.dismissal = {"reason": "student_excluded", "item_id", "quote", "at": iso}`; flush; return the changed rows.
  - `exclusions.hidden_field_keys(db, workspace_id, rows) -> set[str]`: `excluded_fields` keys minus keys of rows that are not `dismissed` (a restored path stays visible to the analyzer).
  - `exclusions.enqueue_exclusion_notice(db, workspace_id, rows, *, source_event_id: str | None) -> str | None`: job `JOB_PATHS_EXCLUDED = "counselor.paths_excluded"`, payload `{"possibility_ids": [...], "source_event_id"}`, idempotency key `paths-excluded:{workspace_id}:{",".join(sorted(ids))}`.
  - `exclusions.paths_excluded_job(job, db) -> dict`: defers (`JobDeferred`, `delay_seconds = load_data("myths.json")["care_retry_seconds"]`) while `care_active`; posts `notice["one"|"other"].format(titles=…)` (titles joined with `list_separator`/`list_last`) once (metadata `{"paths_excluded_job_id": job.id}`, checked before posting); `{"status": "posted", "message_id"}` or `{"status": "no_channel"}`.
  - `myths.care_active(db, workspace_id) -> bool`: the existing check in `_deliver_information` (latest `CounselorTurnDecision` is `wellbeing` or action `care`), moved into a function that `_deliver_information` now calls.
  - `PossibilityService.transition`: on `save`/`explore` from `dismissed` with `dismissal.reason == "student_excluded"`, sets `dismissal["restored_at"] = iso` (the existing restore is the undo).
  - `exclusion.json`: `{"_note": "...", "notice": {"one": "...", "other": "..."}, "list_separator": ", ", "list_last": " and "}` (wording: Ruling needed).
  - `analyzer.after_accept`: when `candidate.candidate_type == "vault_item" and candidate.key == "option"`, in a savepoint: `rows = apply_exclusions(...)`; if rows, `enqueue_exclusion_notice(..., source_event_id=(candidate.source_event_ids or [None])[0])`; then the existing enqueue. Errors are logged and never undo the Vault write (as today).
  - `path_analysis_job`: inside the workspace lock, before reading `existing`: `rows = apply_exclusions(...)`, notice enqueued as above with `payload.get("source_event_id")`; the `fields` sent to the model and the `candidates` passed to `sanitize` exclude `hidden_field_keys(...)`; `_prune` still gets the full `candidates`.

- [ ] **Step 1: Write the failing tests** (`pytestmark = pytest.mark.req("R-47")`) in `tests/test_path_exclusions.py`, using `StudentSession`, `add_education` (FSc Pre-Medical) and `item` from `tests.truth_map_fixtures`:
  - `test_ruled_out_option_dismisses_matching_path_with_student_words`: suggested row `pharm_d`; option `{"text": "Pharm-D", "status": "ruled_out"}` stated, quote `"Pharm-D nahi karni"` → `apply_exclusions` returns `[row]`; `row.status == "dismissed"`; `row.dismissal["reason"] == "student_excluded"`, `["item_id"] == item.id`, `["quote"] == "Pharm-D nahi karni"`.
  - `test_saved_and_exploring_paths_are_dismissed_too` (parametrize `saved`, `exploring`).
  - `test_chosen_path_is_left_alone`.
  - `test_exclusion_matching_no_field_changes_nothing`: text `"Something else entirely"` → `[]`, statuses unchanged, no `counselor.paths_excluded` job.
  - `test_inferred_or_considering_option_changes_nothing` (parametrize level `inferred` with `ruled_out`; level `stated` with `considering`).
  - `test_restored_path_is_not_dismissed_again`: exclude → `transition(..., "save")` → `status == "saved"` and `dismissal["restored_at"]`; `apply_exclusions` → `[]`; a path run whose model returns `pharm_d` keeps it `saved`.
  - `test_new_exclusion_after_restore_dismisses_again`: a later `ruled_out` option item (new id) for the same field → dismissed again.
  - `test_analyzer_never_suggests_an_excluded_field`: no row; option `Biotechnology` ruled out; model returns paths `biotechnology` and `mbbs` → only MBBS stored; the analyst input's `<fields>` has no `"biotechnology"`.
  - `test_reconciler_hook_dismisses_and_queues_one_notice`: accept a `vault_item` `option` candidate through `MemoryReconciler.reconcile` → row dismissed; exactly one `counselor.paths_excluded` job; reconciling the same statement again leaves one job.
  - `test_exclusion_notice_posts_the_fixed_sentence_once`: run `paths_excluded_job` twice → one PAI message, content `notice["one"].format(titles="Pharm-D (Pharmacy)")`; two rows → `notice["other"]` with `"Pharm-D (Pharmacy) and Medical Laboratory Technology"`.
  - `test_exclusion_notice_waits_for_care`: latest decision `move="wellbeing"` → raises `JobDeferred`, no message.
  - In `tests/test_possibilities.py`: `test_migration_123_adds_and_drops_dismissal_column` (pattern of `test_migration_111_upgrade_constraints_and_downgrade`).
- [ ] **Step 2: Run** `… tests/test_path_exclusions.py tests/test_possibilities.py` → FAIL (`ModuleNotFoundError: app.pai_c.paths.exclusions`).
- [ ] **Step 3: Implement** the interfaces: model column + migration, `ruled_out_options`, `exclusions.py`, `exclusion.json`, `care_active` refactor, transition restore stamp, the two analyzer call sites, the job registration in `capabilities/system.py` (`(exclusions.JOB_PATHS_EXCLUDED, exclusions.paths_excluded_job, {"possibility_ids": array, "source_event_id": string})`), `dismissal?: { reason: string; item_id: string; quote?: string; at: string; restored_at?: string } | null` on the frontend type.
- [ ] **Step 4: Run** `… tests/test_path_exclusions.py tests/test_possibilities.py tests/test_path_analyzer.py tests/test_path_fields.py tests/test_roadmap_engine.py tests/test_vault_consumers.py tests/test_adaptive_counseling.py` → pass; `python scripts/check_alembic_heads.py` → exit 0; `npx tsc --noEmit` → 0 errors.
- [ ] **Step 5: Commit.**
  ```
  fix(counsellor): a field the student excluded stays dismissed (R-47 C1)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task C5: Newest paths card and Roadmaps read one list

**Branch:** `pc/p0-t4-counsellor-fixes`.

**Files:**
- Modify: `backend/app/pai_c/possibilities.py` (`current`), `backend/app/pai_c/roadmap/engine.py` (`build`), `backend/app/pai_c/journey_sync.py` (`_live_paths`), `backend/app/routers/counselor_possibilities.py` (`GET /current`), `frontend/lib/api.ts` (`getCurrentPaths`), `frontend/lib/possibilities.ts` (`newestPathsMessageId`), `frontend/components/counselor/possibilities.tsx` (`PathsFound`), `frontend/components/chat/chat-message.tsx`, `frontend/components/chat/chat-messages.tsx`
- Test: `backend/tests/test_roadmap_engine.py`, `backend/tests/test_possibilities.py`, `frontend/components/counselor/possibilities.test.tsx`, `frontend/lib/possibilities.test.ts` (new)

**Interfaces:**
- Produces:
  - `PossibilityService.current(self, workspace_id) -> list[PaiPossibility]`: rows with `status != "dismissed"`, in `list` order. The one reader of "the student's current paths".
  - `RoadmapEngine.build` iterates `PossibilityService(self.db).current(workspace_id)`; `journey_sync._live_paths` returns `bool(PossibilityService(db).current(workspace_id))`. (`deep/context.py` keeps its own query: frozen, same set.)
  - `GET /v1/counselor/possibilities/current?network=…` → `{"possibilities": [serialize(row) for row in current(...)]}`, same auth as the list route.
  - `workspaceApi.getCurrentPaths(): Promise<Possibility[]>`.
  - `newestPathsMessageId(messages: Pick<WorkspaceMessage, 'id' | 'metadata'>[]): string | null`: id of the last message whose `metadata.paths_found` is a non-empty array.
  - `PathsFound({ ids, snapshot, newest }: { ids: string[]; snapshot?: PathSnapshot[]; newest?: boolean })`: `newest` → shows `getCurrentPaths()` rows, no "changed" note; otherwise unchanged (snapshot, else legacy ids filter over `getPossibilities()`).
  - `ChatMessage` prop `newestPaths?: boolean` passed to `PathsFound newest`; `chat-messages.tsx` computes `newestPathsMessageId` over the chat groups' messages with `useMemo` and passes `newestPaths={group.message.id === newestId}`.

- [ ] **Step 1: Write the failing tests.**
  - Backend (`@pytest.mark.req("R-47")`): `test_roadmap_and_current_paths_read_one_list` in `test_roadmap_engine.py`: five non-dismissed rows (two from the latest run, three kept from earlier runs) and one dismissed → `sorted(c["possibility_id"] for c in RoadmapEngine(db).build(ws)["fields"]) == sorted(r.id for r in PossibilityService(db).current(ws))` and `len(...) == 5`. `test_current_paths_endpoint_matches_roadmap` in `test_possibilities.py` with `client_for`: `GET /v1/counselor/possibilities/current` ids == `GET /v1/roadmap` `fields[*].possibility_id` (as sets), dismissed id absent; another workspace's token → 401/403 as the list route.
  - Frontend (`// req: R-47`), mock gains `getCurrentPaths: vi.fn()`:
    - `it('the newest paths card shows the current paths, as Roadmaps does')`: `getCurrentPaths` resolves 5 rows; `<PathsFound newest ids={['a','b']} snapshot={[a, b]} />` → all 5 titles; `pathsFoundChanged` copy absent.
    - `it('an older paths card keeps its snapshot and does not read the current list')`: same props without `newest` → only `a`, `b` titles; `expect(workspaceApi.getCurrentPaths).not.toHaveBeenCalled()`.
    - `lib/possibilities.test.ts`: `newestPathsMessageId([{id:'1',metadata:{paths_found:['a']}},{id:'2',metadata:{paths_found:[]}},{id:'3',metadata:{}}]) === '1'`; `newestPathsMessageId([]) === null`.
- [ ] **Step 2: Run** backend `… tests/test_roadmap_engine.py tests/test_possibilities.py` → FAIL (`AttributeError: current`; 404/405 on `/current`); frontend `npm test -- possibilities` → FAIL.
- [ ] **Step 3: Implement** the interfaces.
- [ ] **Step 4: Run** backend `… tests/test_roadmap_engine.py tests/test_possibilities.py tests/test_roadmap_api.py tests/test_path_analyzer.py` → pass; frontend `npx tsc --noEmit`, `npm test` → pass (incl. `paths.test.tsx`, `roadmap.test.tsx`, `path-card.test.tsx`).
- [ ] **Step 5: Commit.**
  ```
  fix(counsellor): the newest paths card and Roadmaps read one path list (R-47 C5)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task C3: Every "I'll check" runs, or the student is told it couldn't

**Branch:** `pc/p0-t4-counsellor-fixes`. Frozen and untouched: `deep/noted_questions.py`, `deep/actions.py`, `deep/request_policy.json`, `policy/myths.json`, the Voice prompts.

**Files:**
- Modify: `backend/app/pai_c/runtime.py` (research start after the reply), `backend/app/pai_c/myths.py` (`open_research_question`, `check_job`, `sweep_unstarted_information`), `backend/app/pai_c/sessions.py` (`sweep_job`), `backend/app/pai_c/reliability.json` (`unstarted_question_minutes: 30`)
- Test: `backend/tests/test_adaptive_counseling.py`

**Interfaces:**
- Consumes: `request_research("information", …)` (returns `{"ok": False, "error": {"code": "research_busy"}}` when the advisory lock is held, `{"ok": bool, "data": {"job_id"}}` otherwise); `JOB_CHECK = "research.claim"`, idempotency key `information:{ws}:{request.id}`; `_deliver_information` (care deferral, idempotent post, sets `unanswered`); the worker's `session.sweep` every `PAI_SESSION_SWEEP_SECONDS` (300 s).
- Produces:
  - `myths.open_research_question(db, workspace_id, source_event_id) -> CounselorNotedQuestion | None`: the filter `enqueue_information` uses today (kind `information`, `needs_research`, status `open|unanswered`); `enqueue_information` calls it.
  - `runtime._start_information_research(db, workspace_id: str, source_event_id: str) -> dict | None`: one `request_research` call; when the result is `research_busy` or the call raised (after `db.rollback()`), exactly one more call; logs `information_enqueue_failed error_type=%s attempt=%d`. A result `{"ok": False}` without an error (no row) is not retried.
  - In `_run_deep_turn`, the `voice_noted`/`policy_asked` condition and the `action.get("type") != "wellbeing"` exclusion are replaced by: `if open_research_question(db, workspace_id, turn.source_event_id) is not None: await _start_information_research(...)` (Ruling needed C3 wellbeing). The comment above it is updated.
  - `myths.check_job`: a job with `payload["not_started"] is True` skips `_check_job`, sets `result = {"status": "not_started"}`, and delivers (no fact → `information_unanswered`).
  - `myths.sweep_unstarted_information(db, *, now: datetime | None = None) -> int`: for questions with `status == "open"`, kind `information`, `needs_research`, `created_at <= now - unstarted_question_minutes` (from `app/pai_c/reliability.json`), whose job under key `information:{ws}:{id}` is missing or `failed` (Ruling needed C3 failed jobs): enqueue `JOB_CHECK` with payload `{"request_id", "source_event_id", "not_started": True}`, key `information-unanswered:{ws}:{id}`; returns the count enqueued; commits.
  - `sessions.sweep_job` calls it and adds `"information_notices": n` to its result.

- [ ] **Step 1: Write the failing tests** (`@pytest.mark.req("R-47")`) in `tests/test_adaptive_counseling.py` (patterns of `test_voice_promise_to_check_always_starts_research`):
  - `test_classifier_recorded_question_starts_research_when_voice_note_is_duplicate`: classifier signals with `request={"text": q, "kind": "information", "needs_research": True}`, controller decision patched to a non-`answer_request` action, Voice returns `note_question` with `q` → exactly one `research.claim` job, `payload["request_id"] == noted.id`.
  - `test_recorded_question_starts_research_whatever_the_decision` (parametrize Voice action `none`, `note_question`; decision `answer_request`, `explore`) → one job each.
  - `test_research_starts_on_a_wellbeing_turn_and_delivery_waits_for_care` → job exists; running `check_job` with a stubbed `_check_job` raises `JobDeferred`.
  - `test_busy_research_start_is_retried_once`: patch `app.research.gateway.request_research` with `AsyncMock(side_effect=[{"ok": False, "error": {"code": "research_busy"}}, {"ok": True, "data": {"job_id": "j"}}])` → `await_count == 2`.
  - `test_busy_research_start_gives_up_after_one_retry`: always busy → `await_count == 2`, the reply is still posted.
  - `test_question_without_research_need_starts_nothing`: `needs_research=False` → `request_research` not awaited.
  - `test_sweep_tells_the_student_after_30_minutes_without_a_job`: open question, `created_at = now - 31 min`, no job → `sweep_unstarted_information(db, now=now) == 1`; running that job posts `load_data("myths.json")["information_unanswered"]` once; row `status == "unanswered"`.
  - `test_sweep_leaves_recent_or_started_questions`: 29 min → 0; 31 min with a `pending` job under `information:{ws}:{id}` → 0.
  - `test_sweep_covers_a_failed_research_job`: job `failed` → 1.
  - `test_sweep_is_idempotent`: two sweeps → one job; second returns 0.
  - `test_session_sweep_runs_the_information_sweep`: `sweep_job` result has `information_notices == 1`.
- [ ] **Step 2: Run** `… tests/test_adaptive_counseling.py` → the new tests FAIL (no job on duplicate; `sweep_unstarted_information` missing).
- [ ] **Step 3: Implement** the interfaces.
- [ ] **Step 4: Run** `… tests/test_adaptive_counseling.py tests/test_counselor_research.py tests/test_counselor_deep_research_contracts.py tests/test_counselor_light_research.py tests/test_counselor_deep_lean.py tests/test_request_intake.py tests/test_voice_v5.py tests/test_web_research.py` → pass.
- [ ] **Step 5: Commit.**
  ```
  fix(counsellor): every promised check runs or the student is told it could not (R-47 C3)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task C7: Onboarding asks for marks

**Branch:** `pc/p0-t4-counsellor-fixes`. Scope P0-D8: no Part-I/Part-II split (P1, R-16, R-80).

**Files:**
- Modify: `backend/app/memory/catalog/vault_catalog.json` (education `follow_ups`; a new `onboarding` block on `test_attempt`), `backend/app/memory/onboarding.py`, `frontend/lib/onboarding.ts`, `frontend/components/onboarding/onboarding-view.tsx`, `frontend/lib/i18n/messages/en-US.ts`, `frontend/tests/preview/main.tsx` (spec list)
- Test: `backend/tests/test_student_onboarding.py`, `frontend/components/onboarding/onboarding-view.test.tsx`, `frontend/lib/onboarding.test.ts`

**Interfaces:**
- Catalog (follow-up format as today: `name`, `label`, `prompt`, `input`, `record_field`, `depends_on {field, values?, and?}`, `required`); new keys `input: "number" | "text"`, `minimum`, `maximum`, `max_length`, and `record` (the fixed values of a separate record of the same type):
  - Education, current record: `marksObtained` / `marksTotal` (`number`, 0–9999, `result.marks_obtained` / `result.marks_total`) for level `matric` or `intermediate`, one pair with `depends_on status completed` (`required: true`) and one with `status current` (`required: false`, label `marksSoFar`); `grades` (`text`, max 120, `result.grade`) for `o_level`/`a_level`, required when completed, optional when current.
  - Prior record: `matricMarksObtained` / `matricMarksTotal` (`number`, `record: {"qualification_name": "matric", "academic_status": "completed"}`) for level `intermediate` or `dae`; `oLevelGrades` (`text`, `record: {"qualification_name": "o_level", "academic_status": "completed"}`) for `a_level`; required per Ruling needed C7.
  - `test_attempt.onboarding`: `{"order": 7, "step": 3, "name": "entryTest", "input": "choice", "choices": "tests", "shown": ["mdcat", "ecat", "nat", "net", "sat"], "record_field": "test_type", "required": false, "follow_ups": [{"name": "entryTestScore", "label": "entryTestScore", "input": "number", "minimum": 0, "maximum": 9999, "record_field": "overall_score", "required": false, "depends_on": {"field": "entryTest"}}]}`.
- `OnboardingField` gains `is_number: bool = False`, `is_text: bool = False`, `minimum: int | None = None`, `maximum: int | None = None`, `record: dict | None = None`; `_catalog_fields` reads them; `_field_state` adds `"isNumber"`, `"isText"`.
- `_clean_follow_up`: `is_number` → digits only, within `minimum..maximum`, returned as `str`; `is_text` → trimmed, ≤ `max_length`; `_stored` keeps converting to the schema type (`marks_*` are numbers → `int`; `overall_score` is a string → `"140"`).
- `apply`: records are keyed `(field_key, json.dumps(record, sort_keys=True) or "")`, so prior-record answers form their own record with the `record` values merged in; a prior record corrects in place the existing row of the same type whose `read_education` level equals `record["qualification_name"]` (`entities.record_id`), else is new. Cross-check before any write: `marksObtained <= marksTotal` (and the matric pair) or `MemoryDataError("marksObtained cannot be more than marksTotal")`. A `test_attempt` with no score gets `details.status = "planned"` (Ruling needed C7). Every write still goes `MemoryCandidateService.propose(source_type="user_explicit", capture onboarding)` → `MemoryReconciler.reconcile`, so the level is `stated`.
- `_latest(rows)`: most recent `current`, else the highest `level_ranks` rank (ties: most recent), so a prior Matric written later never becomes the form's main record. `_record_prefill` fills prior-record follow-ups from the matching row.
- Frontend `OnboardingFieldSpec` gains `isNumber?: boolean; isText?: boolean`; `onboarding-view.tsx` renders `isNumber` as `<Input inputMode="numeric" maxLength={4}>` stripping non-digits (like `isYear`) and `isText` as a plain `Input`; copy keys `onboarding.field.{marksObtained, marksTotal, marksSoFar, grades, matricMarksObtained, matricMarksTotal, oLevelGrades, entryTest, entryTestScore}` in `en-US.ts`.

- [ ] **Step 1: Write the failing tests** (`@pytest.mark.req("R-47")`) in `tests/test_student_onboarding.py`:
  - `test_onboarding_state_lists_the_marks_questions`: `state()["fields"]` names include all nine above; `marksObtained` has `isNumber is True`; `grades` has `isText is True`; `entryTest` `required is False`.
  - `test_intermediate_marks_and_matric_marks_are_saved_stated`: answers `level="intermediate"`, `group="pre_medical"`, `status="current"`, `year="year_2"`, `marksObtained="480"`, `marksTotal="550"`, `matricMarksObtained="950"`, `matricMarksTotal="1100"`, `entryTest="mdcat"`, `entryTestScore="140"` (plus name/city) → `rejected == {}`; education records: `fsc` current with `result == {"marks_obtained": 480, "marks_total": 550}`, `matric` completed with `{"marks_obtained": 950, "marks_total": 1100}`; `test_attempt` `mdcat` with `overall_score == "140"`; each card's `evidence_level == "stated"`.
  - `test_marks_are_optional_while_studying`: current Intermediate without marks → saved, no "Missing required answer".
  - `test_completed_intermediate_requires_its_marks`: completed without marks → `MemoryDataError` matching `Missing required answer: .*marksObtained`.
  - `test_o_and_a_level_get_grades_not_marks`: `a_level` → `grades`, `oLevelGrades` visible; `marksObtained` and `matricMarksObtained` answers are dropped; `result.grade` saved.
  - `test_marks_obtained_cannot_exceed_total`: `"600"` / `"550"` → `MemoryDataError("marksObtained cannot be more than marksTotal")`, nothing written.
  - `test_entry_test_without_score_is_planned`: `entryTest="mdcat"` only → `details.status == "planned"`, no `overall_score`.
  - `test_prefill_after_prior_matric_record_keeps_intermediate`: after the save above, `state()["prefill"]["level"] == "intermediate"`, `["matricMarksObtained"] == "950"`.
  - `test_reonboarding_corrects_existing_matric_record_in_place`: submit twice with `matricMarksObtained` `"950"` then `"960"` → one matric record, `marks_obtained == 960`.
  - Frontend (`// req: R-47`): `onboarding-view.test.tsx` `it('asks marks as numbers and lets a current student skip them')` (typing `"9a5"` gives `"95"`; Continue enabled with marks empty when `status=current`); `it('asks grades as text for A-level')`; `lib/onboarding.test.ts` a `required` follow-up hidden by its condition is not required.
- [ ] **Step 2: Run** `… tests/test_student_onboarding.py` → FAIL (`Unknown onboarding field: marksObtained`); `npm test -- onboarding` → FAIL.
- [ ] **Step 3: Implement** the catalog blocks, `onboarding.py`, and the frontend pieces above.
- [ ] **Step 4: Run** `… tests/test_student_onboarding.py tests/test_vault_completeness.py tests/test_path_analyzer.py tests/test_education_focus.py tests/test_vault_catalog*.py` → pass; frontend `npx tsc --noEmit`, `npm test` → pass.
- [ ] **Step 5: Commit.**
  ```
  feat(counsellor): onboarding asks for matric, intermediate and entry-test marks (R-47 C7)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task S: Shared-branch replay and PR

**Branch:** `pc/p0-t4-counsellor-fixes`.

- [ ] **Step 1: Rebase** on `origin/pai-connect` (with C2 merged). Full legacy suite from `backend/`: `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider` → 0 failed; `python scripts/check_alembic_heads.py` → 0; frontend `npx tsc --noEmit`, `npm test`, `npm run build` → pass.
- [ ] **Step 2: Replay after** both modes into `docs/connect/replays/shared/after/{default,guided}`; before = the base after C2 (rerun on `origin/pai-connect` into `shared/before/`); `compare.py` → `shared/diff.md`. Expected: `No differences.` in both modes (C3 starts research after the reply and decision are logged, and the replay creates no path rows for C1/C5 to touch); C3's new research starts show only as extra `research.claim` jobs, which the report does not compare. Any difference: stop and explain it before opening the PR.
- [ ] **Step 3: Freeze check** `python scripts/check_freeze.py --base origin/pai-connect` with no label → exit 0.
- [ ] **Step 4: Commit replay files, push, PR** titled `R-47 C1, C3, C5, C7: Counsellor fixes (non-frozen)`, no `freeze-exception` label, `@memsa771-hub` review (CODEOWNERS), body lists each fix, its tests, the Ruling-needed defaults, and the replay diff.
  ```
  test(counsellor): offline replay after C1, C3, C5, C7 (R-47)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task C6: Reply follows the student; one greeting

**Branch:** `pc/p0-t4-c6-language` (frozen: exception PR), cut after the shared branch merged.

**Files:**
- Modify (frozen): `backend/app/pai_c/deep/context.py` (`language_policy` without `replacement`), `backend/app/pai_c/deep/turn.py` (retry names the replacement; greeting guard call), `backend/app/pai_c/deep/prompts/language_retry.md`, `docs/counselor/COUNSELOR_V3_PROMPTS.md` (§5 `<language_policy>` line)
- Modify (not frozen): `backend/app/pai_c/voice/guards.py`
- Create (not frozen): `backend/app/pai_c/voice/greetings.json`
- Test: `backend/tests/test_counselor_deep_pr3.py`, `backend/tests/test_greeting_guard.py` (new), `backend/tests/test_counselor_voice_v4.py`

**Interfaces:**
- `deep/context.py`: `"language_policy": _json({"blocked_scripts": [...], "fallback_reply": config.PAI_COUNSELOR_FALLBACK_REPLY})` (no `replacement`). Settings in `config.py` unchanged.
- `deep/turn.py`, blocked-script branch on attempt 0: `retry_line = load_prompt("language_retry") + "\n<language_replacement>" + _json({"replacement": config.PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT}) + "</language_replacement>"` (so the existing assertion `'"replacement":"configured replacement"' in retry_prompt` still holds, and only there).
- `language_retry.md`: "Rewrite your previous reply without any script listed in <language_policy> blocked_scripts. Write it in the language named in <language_replacement>. Return the same JSON structure and no other text."
- `voice/greetings.json`: `{"_note": "...", "phrases": ["assalam o alaikum", "assalamu alaikum", "asalam o alaikum", "assalam alaikum", "salam", "wa alaikum assalam", "walaikum assalam", "wa alaikum salam", "hello", "hi", "hey", "good morning", "good afternoon", "good evening"], "max_extra_words": 2}`.
- `voice/guards.py`:
  - `leading_greeting(text: str) -> int`: end offset of the leading sentence (up to and including the first `!`, `.`, `?`, `؟` or newline; commas stay inside it) whose casefolded, punctuation-stripped tokens start with a phrase's tokens and have at most `max_extra_words` more (a name); 0 when none.
  - `drop_repeat_greeting(reply: str, history: list[dict]) -> str`: when any earlier `assistant` row in `history` has `leading_greeting(content) > 0` and the reply has one, returns the reply without that sentence and its following whitespace, first letter upper-cased; returns `reply` unchanged when the rest would be empty.
- `deep/turn.py`: after `reply = polish_reply(reply)`: `greeted = drop_repeat_greeting(reply, history)`; if changed, `reply = greeted` and `violations.append("greeting_removed")`.

- [ ] **Step 1: Write the failing tests** (`@pytest.mark.req("R-47")`):
  - `test_counselor_deep_pr3.py`: `test_language_policy_names_no_replacement_before_a_blocked_reply`: English reply, `PAI_LANGUAGE_BLOCKED_SCRIPTS="Greek"`, replacement `"configured replacement"` → one call; its `system_prompt` contains `'"blocked_scripts":["Greek"]'` and not `"configured replacement"` and not `'"replacement"'`. Extend `test_configured_blocked_script_retries_once_then_uses_configured_fallback`: `"configured replacement" not in model.call_args_list[0].kwargs["system_prompt"]` (the retry assertion stays).
  - `test_greeting_guard.py`:
    ```python
    EARLIER = [{"role": "assistant", "content": "Assalam o alaikum Ayesha! Main PAI hoon."}]
    assert drop_repeat_greeting("Wa alaikum assalam, Ayesha! MBBS ke liye marks batao.", EARLIER) == "MBBS ke liye marks batao."
    assert drop_repeat_greeting("Hello Ayesha. Let's look at BDS.", EARLIER) == "Let's look at BDS."
    assert drop_repeat_greeting("Wa alaikum assalam, Ayesha! MBBS ke liye marks batao.", []) == "Wa alaikum assalam, Ayesha! MBBS ke liye marks batao."
    assert drop_repeat_greeting("Wa alaikum assalam!", EARLIER) == "Wa alaikum assalam!"
    assert drop_repeat_greeting("MBBS is a good fit. Hello to your family too.", EARLIER) == "MBBS is a good fit. Hello to your family too."
    assert drop_repeat_greeting("Hi there! the high merit list is out.", [{"role": "assistant", "content": "Hi Ayesha!"}]) == "The high merit list is out."
    assert drop_repeat_greeting("Highlights first, then fees.", EARLIER) == "Highlights first, then fees."
    ```
  - `test_counselor_voice_v4.py`: `test_second_greeting_in_a_conversation_is_dropped`: `run_deep_turn` with `history` holding an earlier greeting reply and the model returning `"Wa alaikum assalam, Ayesha! Kya aap MBBS ke baare mein sochti hain?"` → `result.reply == "Kya aap MBBS ke baare mein sochti hain?"`, `"greeting_removed" in result.guard_violations`, one model call.
- [ ] **Step 2: Run** `… tests/test_counselor_deep_pr3.py tests/test_greeting_guard.py tests/test_counselor_voice_v4.py` → FAIL (`replacement` present; `ImportError: drop_repeat_greeting`).
- [ ] **Step 3: Implement** the interfaces; update `COUNSELOR_V3_PROMPTS.md` §5 to `<language_policy> configured blocked scripts and fallback; the replacement is named only when a reply is redone for a blocked script </language_policy>`.
- [ ] **Step 4: Run** `… tests/test_counselor_deep_pr1.py tests/test_counselor_deep_pr3.py tests/test_greeting_guard.py tests/test_workspace_language.py tests/test_counselor_opening.py tests/test_counselor_voice.py tests/test_counselor_voice_v4.py tests/test_voice_v5.py tests/test_voice_guided.py` → pass.
- [ ] **Step 5: Replay** before = `origin/pai-connect` (with the shared branch merged) into `docs/connect/replays/c6/before/`, after into `c6/after/`, both modes; `compare.py` → `c6/diff.md`. Expected: replies differ only where a recorded reply opens with a second greeting (now dropped, `greeting_removed`); the language-policy change cannot change a recorded reply (README) and is proved by the tests above. Any other difference: stop.
- [ ] **Step 6: Freeze check** with no label → exit 1 listing exactly `backend/app/pai_c/deep/context.py`, `backend/app/pai_c/deep/prompts/language_retry.md`, `backend/app/pai_c/deep/turn.py`, `docs/counselor/COUNSELOR_V3_PROMPTS.md`.
- [ ] **Step 7: Commit.**
  ```
  fix(counsellor): reply follows the student's language and greets once (R-47 C6)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Task G: R-47 built, replay proof and gate

**Branch:** `pc/p0-t4-c6-language` (last commit of the C6 PR; Ruling needed R-47 built).

**Files:**
- Modify: `docs/requirements/connection.yaml` (`R-47: {…, built: true}`)
- Create: `docs/connect/replays/r47-after/{default,guided}/counselor_deep_<date>.{json,md}`, `docs/connect/replays/r47-diff.md`

- [ ] **Step 1: Set** `R-47` `built: true`.
- [ ] **Step 2: Traceability.** From the repo root: `python scripts/check_traceability.py` → exit 0; `python scripts/check_traceability.py --gate P0` → exit 0; `python scripts/check_traceability.py --report P0` lists R-47 with the C1, C2, C3, C5, C6, C7 tests (paste into the PR).
- [ ] **Step 3: Replay after all six.** From `backend/`: `env -u PAI_API_KEY python -m scripts.eval_counselor_deep --offline --result-dir ../docs/connect/replays/r47-after/default` and `--policy-mode guided --result-dir ../docs/connect/replays/r47-after/guided`.
- [ ] **Step 4: Diff summary.** `python docs/connect/replays/compare.py docs/connect/replays/r47-before/<mode>/counselor_deep_<date>.json docs/connect/replays/r47-after/<mode>/counselor_deep_<date>.json` for both modes into `r47-diff.md`, with one line per fix: what the replay shows and which tests prove it (C1 `test_path_exclusions.py`; C2 `test_counselor_deep_pr4.py`; C3 `test_adaptive_counseling.py` sweep/start tests; C5 `test_roadmap_engine.py`, `possibilities.test.tsx`; C6 `test_counselor_deep_pr3.py`, `test_greeting_guard.py`; C7 `test_student_onboarding.py`, `onboarding-view.test.tsx`).
- [ ] **Step 5: Full checks.** Legacy suite (`env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider`) → 0 failed; `tach check`; `pytest tests/os` against Postgres; `python scripts/check_alembic_heads.py`; frontend `npx tsc --noEmit`, `npm test`, `npm run build` → green.
- [ ] **Step 6: Commit, push, PR** titled `R-47 C6: reply language follows the student; one greeting (completes R-47)`, label `freeze-exception`, body: C6 cause and fix, `c6/diff.md`, `r47-diff.md`, the traceability report, the Ruling-needed defaults, request `@memsa771-hub`.
  ```
  chore(connect): R-47 built; replay before and after the Counsellor fixes

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_011MZq2VfXhy4jZ6n3YZMYQj
  ```

### Next (not in this plan)

Gate item 3 (the live-run student reaches stage H with only MBBS and BDS) needs a live run with the owner's approval and a cost cap (master R-46); gate item 5 is the handoff `docs/connect/handoff/p0-handoff.md`.
