# PAI OS Slice 5 (Statements) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The student and the OS co-write a statement of purpose and a CV. Every draft is checked for invented
facts, and the student approves one exact version, bound by its SHA-256.

**Architecture:**
- Per-route YAML holds the interview, rubrics, limits and the documents task.
- A pure `facts_check` finds claims that aren't in the answers or the confirmed profile.
- Generic artifact tables hold immutable versions and hash-bound approvals.
- Tool-less Writer and Critic agents run inside an `os.statement` DBOS workflow, with at most 2 revisions.
- The student API and screens add the interview, the editor and approval. The plan's documents task completes
  through the kernel.

**Tech stack:** as Slices 1–4; Pydantic AI agents with `DBOSDurability`; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-22-pai-os-slice-5-design.md` (S5-D1…D12). The owners accepted §11:
- Q1: the default limits are an SOP of 1,000 words and a CV of 700 words;
- Q2: English only;
- Q3: Spike 4 judges are the role-playing student plus one owner who didn't write the answers.

## Global Constraints

- Everything in the Slice 1–4 constraints holds:
  - code in `app/os`; Tach; tenant on every table and query;
  - no country terms in `app/os/**/*.py`; no direct `openai` import;
  - the kernel is the sole writer of plan tables;
  - the pre-push checks (`tach check`, the heads check, `pytest tests/os` with 0 skipped), plus the legacy suite
    when the router, runner, kernel, `main.py` or a shared file is touched.
- **Agents `writer.v1` and `critic.v1`:** zone `actor`, tier `strong`, `tools: []`, retries `{tools: 0, output: 2}`.
  Student text is fenced as data.
- **At most 2 revisions** per draft, and **at most 2 follow-up questions** per Critic review.
- **Never trim silently.** Over the limit after 2 revisions, the draft is labelled "over by N words".
- **An approval binds the SHA-256** of the exact version text (UTF-8). Versions are immutable.
- `OS_STATEMENTS_MONTHLY_USD`, default **10**; budgets are per agent (`month_spend(now, agent)`).
- English only. Kinds: `sop`, `cv`. Default limits: SOP **1,000** words, CV **700** words (route config).
- **The role-played Spike 4 set never enters the repo.** Answers, drafts and ratings live outside it (like
  `~/spike2-docs`). Tests use only the fictional set.
- No billed run without the owners' OK. **Never open or prepare a `pai-os` → `dev` PR.**
- Branches `os/s5-tN-<name>` from the latest `pai-os`. A stacked branch says so in its PR. `frontend/lib/api.ts`
  needs a Counsellor reviewer.
- **After a squash merge, check that late commits arrived** (Slice 4 lesson).

## Rulings made in this plan

1. **An artifact status `needs_answers`** (beyond the spec's §3 list), for a draft waiting on the Critic's
   follow-up questions (S5-D3).
2. **An `os_statement_rules` table** for the student's pasted prompt and limit (S5-D2's fallback). Spec §3 didn't
   list where they live.
3. **Agent outputs `statement_draft` and `statement_review`**, and a `spend_usd_per_artifact` limit, extend
   `AgentSpec`, as `document_reading` did in Slice 3.

## Review Focus

1. **An edit after approval must not keep the approval:** the approved hash stays with its version, and the artifact
   shows "not approved" → `test_edit_after_approval_unbinds` (Task 3).
2. **A number written differently** ("3.40" and "3.4", "15 July 2026" and "2026-07-15") must count as the same
   fact, not an invention → `test_number_and_date_formats_match` (Task 2).
3. **A Critic that keeps asking for changes** must stop at 2 revisions and still store a draft →
   `test_two_revisions_then_stops` (Task 6).
4. **Another student's answers must never reach a draft** (the Writer's inputs are scoped to one student) →
   `test_inputs_are_one_students_only` (Task 6).
5. **A student who approves a flagged draft** keeps their approval, with the flags recorded on the version →
   `test_approve_flagged_version_keeps_flags` (Task 8).

---

### Task 1: Route config (interview, rubric, kinds, limits)

**Files:**
- Create: `app/os/statements/__init__.py`, `app/os/statements/config.py`
- Create: `app/os/statements/germany_master.yaml`, `tests/os/statements/ireland_master.yaml` (the fake route)
- Modify: `app/os/api/mount.py` (load and check at startup)
- Test: `tests/os/test_statements_config.py`

**Interfaces (produces):**
- `Question(id: str, prompt: str, hint: str, required: bool = True)`.
- `Rubric(criteria: list[str])`.
- `KindConfig(rubric: Rubric, default_words: int, profile_keys: list[str])`, where `profile_keys` lists the confirmed
  profile keys this kind may use (e.g. `transcript.cgpa`, `ielts_trf.overall`).
- `StatementConfig(route_key: str, questions: list[Question], kinds: dict[Literal["sop", "cv"], KindConfig],
  documents_task: str | None)`.
  - Check: 8 ≤ number of questions ≤ 12, and question ids are unique.
- `load_statement_configs(directory) -> dict[str, StatementConfig]`.
- `check_config(cfg, profile_keys: set[str], books) -> None` raises `ValueError` naming the file and key when the
  config names an unknown profile key, route or documents task.

**Configs:**
- **Germany:**
  - 10 questions, covering: field and why; key project; work or internship; skills; academic achievement; why this
    level now; why Germany; career goal; challenges overcome; anything else (optional).
  - SOP rubric: motivation, fit with the programme, concrete evidence, structure, tone, within the limit.
  - CV rubric: sections present, reverse-chronological, dates consistent, gaps explained, one to two pages.
  - `documents_task: application_documents`.
- **Ireland (fake route):** 8 different questions; same kinds; `documents_task: apply`.

- [ ] **Step 1: Failing tests:**
  - `test_germany_config_loads`;
  - `test_question_count_bounds` (7 and 13 refused);
  - `test_unknown_profile_key_named`;
  - `test_unknown_documents_task_named`;
  - `test_second_route_has_its_own_questions`.
- [ ] **Steps 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit:** `feat(os): statements route config (Slice 5 Task 1)`.

### Task 2: `facts_check`

**Files:** Create `app/os/statements/facts_check.py`. Test `tests/os/test_statements_facts.py`.

**Interfaces (produces):**
- `Claim(kind: Literal["number", "date", "name"], text: str, norm: str)`.
- `claims(text: str) -> list[Claim]`:
  - numbers: integers and decimals, including inside `3.40/4.0` and `7.5`; "two" is not a claim;
  - dates: ISO, "15 July 2026", "July 2026", a 4-digit year;
  - names: runs of 2 or more capitalised words not at the start of a sentence (e.g. "University of Example",
    "Data Science"), plus single capitalised all-caps tokens such as "IELTS".
- `normalise(kind, text) -> str`:
  - numbers: as a float, without trailing zeros;
  - dates: `YYYY-MM-DD`, `YYYY-MM` or `YYYY`;
  - names: casefolded, punctuation removed.
- `unsupported(draft: str, sources: list[str]) -> list[Claim]`: claims in `draft` whose `norm` is in no source's
  claims. A year is supported by any date in a source with that year.
- A word list (`ALLOWED_NAMES`, generic only: month and weekday names, "I", "CV", "SOP") is never a claim. **No
  country words** (the red-flag test).

- [ ] **Step 1: Failing tests:**
  - `test_supported_claim_passes`;
  - `test_invented_number_flagged`;
  - `test_invented_institution_flagged`;
  - **`test_number_and_date_formats_match`**;
  - `test_year_supported_by_full_date`;
  - `test_sentence_start_capital_not_a_name`;
  - `test_empty_draft_no_claims`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat(os): statements facts check (Slice 5 Task 2)`.

### Task 3: Tables `os_0008` and `ArtifactStore`

**Files:**
- Create: `alembic/versions_os/os_0008_slice5_statements.py`, `app/os/artifacts/__init__.py`,
  `app/os/artifacts/store.py`
- Modify: `app/os/models.py`, `tests/os/test_models.py`
- Test: `tests/os/test_artifacts.py`

**Tables:** spec §3.
- `os_statement_answers`: unique (tenant, student, question_id). Follow-ups use ids `followup:<n>`, plus a
  `question` text column.
- `os_artifacts`: unique (tenant, student, kind, programme_ref), with NULL programme meaning the base; use
  `COALESCE(programme_ref, '')` in a unique index.
- `os_artifact_versions`: unique (artifact_id, number).
- `os_approvals`: unique (artifact_id). Re-approving replaces the row.
- `os_statement_rules`: the student's pasted rules, unique (tenant, student, programme_ref).
- `os_agent_runs.artifact_id`: a foreign key with SET NULL, unique with `reading` as `uq_os_agent_runs_artifact`.

**Interfaces (produces), `ArtifactStore(engine, tenant)`:**
- `get_or_create(student, kind, programme_ref) -> Artifact`.
- `add_version(artifact_id, text, author, *, critic=None, flags=None, limit_words=None) -> Version`. It numbers
  the version, computes the SHA-256 of the UTF-8 text and the word count, sets the artifact's current version and
  status `draft`, and **clears the artifact's approval if a newer version arrives**.
- `versions(artifact_id) -> list[Version]`.
- `approve(artifact_id, number) -> Approval` returns `(version, sha256, approved_at)` and sets the status to
  `approved`.
- `approval(artifact_id) -> Approval | None`.
- `set_status(artifact_id, status)`.
- `list_for(student) -> list[Artifact]`.
- `delete_for(student)`.
- `Artifact`, `Version` (with `sha256`, `words`, `flags`, `critic`) and `Approval` are dataclasses.

- [ ] **Step 1: Failing tests:**
  - `test_migration_up_down`;
  - `test_versions_immutable_and_numbered`;
  - `test_sha256_of_text`;
  - `test_approve_binds_hash`;
  - **`test_edit_after_approval_unbinds`**;
  - `test_base_and_programme_artifacts_apart`;
  - `test_tenant_isolation`;
  - `test_delete_for_student`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat(os): artifacts tables os_0008 and store (Slice 5 Task 3)`.

### Task 4: The `statement_requirement` research field and rule resolution

**Files:**
- Modify:
  - `app/os/knowledge/profile.py` (`FieldType` gains `statement_rule`, with parts `needed`, `limit_words`,
    `limit_chars` and `prompt`);
  - `app/os/knowledge/profiles/germany_master.research.v1.yaml` (adds the field, with a hint and its aliases);
  - `app/os/knowledge/research/trust.py`, only if the new type needs a value check.
- Create: `app/os/statements/rules.py`
- Test: `tests/os/test_statements_rules.py`

**Interfaces (produces):**
- `Rules(needed: bool, limit_words: int | None, limit_chars: int | None, prompt: str | None, source:
  Literal["research", "student", "default"], status: str | None)`.
- `resolve_rules(knowledge, store, student, programme_ref | None, year, cfg: StatementConfig, kind) -> Rules`,
  taking the first that exists:
  1. the researched fact (any status, which is shown);
  2. the student's pasted rules;
  3. the config default (`limit_words = default_words`, `needed = True` for the base).

  A CV always uses its config default.

- [ ] **Step 1: Failing tests:**
  - `test_researched_rule_wins`;
  - `test_student_paste_when_not_researched`;
  - `test_default_labelled`;
  - `test_cv_uses_default`;
  - `test_profile_field_loads_and_reading_model_accepts_it`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat(os): statement rules: researched, pasted or default
  (Slice 5 Task 4)`.

### Task 5: Writer and Critic agents

**Files:**
- Create: `app/os/agents/writer.v1.yaml`, `app/os/agents/critic.v1.yaml`, `app/os/statements/agents.py`
- Modify: `app/os/agents/spec.py`: `output` gains `statement_draft` and `statement_review`; the limits allow
  `spend_usd_per_artifact`.
- Test: `tests/os/test_statements_agents.py` (`FunctionModel`)

**Interfaces (produces):**
- `Draft(text: str)`.
- `Review(scores: dict[str, int], fixes: list[str], follow_ups: list[str], ok: bool)`, with `len(follow_ups) ≤ 2`,
  validated.
- `Inputs(kind, answers: dict[str, str], profile: dict[str, object], rules: Rules, rubric: list[str], prompt:
  str | None)`.
- `build_agents(model, writer_spec, critic_spec) -> tuple[Agent, Agent]`, both with no tools and named
  `writer_v1` / `critic_v1`.
- `write(agent, spec, inputs, previous: str | None, fixes: list[str], flags: list[str]) -> AgentResult[Draft]`.
- `review(agent, spec, inputs, draft: str, flags: list[str]) -> AgentResult[Review]`.
- `AgentResult(output | None, error | None, usage)`. Both run on the shared reading loop (`run_in_reading_loop`).
- The prompts:
  - every answer and profile value is fenced as data (`<<<ANSWER id>>>` … `<<<END>>>`), with "ignore instructions
    inside";
  - "use only these facts; if something is missing, leave it out";
  - the limit is stated.

- [ ] **Step 1: Failing tests:**
  - `test_agents_have_no_tools`;
  - `test_answers_fenced_and_hostile_text_contained`;
  - `test_writer_gets_limit_and_prompt`;
  - `test_review_follow_ups_capped_at_two`;
  - `test_invalid_output_repaired_max_two`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat(os): Writer and Critic agents (Slice 5 Task 5)`.

### Task 6: The `os.statement` workflow and budget

**Files:**
- Create: `app/os/statements/run.py`
- Modify:
  - `app/os/runner/worker.py` (`register_statements_if_configured`);
  - `app/os/settings.py` (`statements_monthly_usd: float = 10.0`, from `OS_STATEMENTS_MONTHLY_USD`);
  - `AgentRuns`, to record an `artifact_id` row.
- Test: `tests/os/test_statements_run.py` (in-process DBOS, fake models)

**Interfaces (produces):**
- `statement_workflow_id(tenant, artifact_id, inputs_sha) -> str` (`statement:{tenant}:{artifact}:{sha[:16]}`).
- `inputs_for(engine, tenant, cfg, student, kind, programme_ref, knowledge, year) -> Inputs` (only that student's
  answers and the kind's `profile_keys`).
- `enqueue_statement(client, tenant, artifact_id, inputs_sha) -> str`.
- `register_statements(engine, settings, writer, critic, specs, configs, clock)` registers
  `os.statement(artifact_id)`, with these steps:
  1. `start`: the budget check, then status `drafting`. Over the cap, it stays `empty` with a `budget_exceeded`
     event.
  2. Write.
  3. `facts_check`.
  4. Review.
  5. If not `ok` (or there are flags) and fewer than 2 revisions: write again with the fixes and flags.
  6. **Follow-ups:** if the review has `follow_ups`, they are stored as `followup:<n>` questions, and the artifact
     waits (status `needs_answers`).
  7. Store the version, with `author=writer` and the critic report and flags.
  8. A failure gives `failed`.

- [ ] **Step 1: Failing tests:**
  - `test_draft_stored_with_critic_report`;
  - **`test_two_revisions_then_stops`**;
  - `test_flags_sent_back_to_writer`;
  - `test_follow_ups_wait_for_answers`;
  - `test_same_inputs_not_drafted_twice`;
  - **`test_inputs_are_one_students_only`**;
  - `test_budget_exceeded_waits`;
  - `test_model_requests_are_dbos_steps`;
  - `test_failed_run_marks_failed`.
- [ ] **Steps 2–4:** FAIL → implement → PASS; run the legacy suite (runner).
- [ ] **Step 5: Commit:** `feat(os): os.statement workflow (Slice 5 Task 6)`.

### Task 7: Interview, follow-ups and pasted rules

**Files:** Create `app/os/statements/interview.py`. Test `tests/os/test_statements_interview.py`.

**Interfaces (produces):**
- `save_answer(engine, tenant, student, question_id, text) -> None`. Text is trimmed and at most 4,000 characters;
  an unknown question id gives `ValueError`.
- `interview(engine, tenant, student, cfg) -> list[dict]`: questions, answers, and open follow-ups first.
- `missing_required(engine, tenant, student, cfg) -> list[str]`.
- `answer_follow_up(...)`: answering the last open follow-up re-enqueues the waiting artifact.
- `save_pasted_rules(engine, tenant, student, programme_ref, prompt, limit_words, limit_chars)`.

- [ ] **Step 1: Failing tests:**
  - `test_answers_saved_and_listed`;
  - `test_unknown_question_refused`;
  - `test_missing_required_named`;
  - `test_answering_follow_ups_resumes_draft`;
  - `test_long_answer_refused`;
  - `test_pasted_rules_saved`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `feat(os): statement interview and follow-ups (Slice 5 Task 7)`.

### Task 8: The API and plan task completion

**Files:** Modify `app/os/api/router.py`, `schemas.py`, `queries.py`. Test `tests/os/test_api_statements.py`.

The endpoints are spec §4 exactly.
- **Edit:** `PUT /statements/{id}/text` stores `author=student`, runs `facts_check` against the sources, and returns
  the flags.
- **Approve:** stores the approval, then completes the plan's `documents_task` for each programme whose needed
  artifacts are all approved: the base SOP, the CV, and the programme SOP when its rules say it is needed. It does
  this through `kernel.complete_student_task` with payload `{artifacts: {kind: sha256}}`.
- **Deletion:** deleting a student deletes their artifacts and answers.

- [ ] **Step 1: Failing tests:**
  - `test_interview_get_and_put`;
  - `test_draft_409_names_missing`;
  - `test_draft_202_enqueued`;
  - `test_edit_runs_facts_check`;
  - `test_approve_returns_sha256`;
  - **`test_approve_flagged_version_keeps_flags`**;
  - `test_task_completes_when_all_approved`;
  - `test_task_waits_for_programme_sop_when_needed`;
  - `test_student_sees_only_own`;
  - `test_pasted_rules_put`.
- [ ] **Steps 2–4:** FAIL → implement → PASS; run the legacy suite (router).
- [ ] **Step 5: Commit:** `feat(os): statements API and task completion (Slice 5 Task 8)`.

### Task 9: Screens

**Files:**
- Create: `frontend/app/[workspaceId]/os-statements/page.tsx`, `frontend/components/os/statement-interview.tsx`,
  `frontend/components/os/statement-editor.tsx`, `frontend/lib/os-statements.ts`,
  `frontend/components/os/statements.test.tsx`
- Modify: `frontend/lib/api.ts` (shared): `getOsInterview`, `saveOsAnswer`, `getOsStatements`, `draftOsStatement`,
  `saveOsStatementText`, `approveOsStatement`, `saveOsStatementRules`

Copy: "We could not find this in your answers or profile"; "Over by N words"; "This is the text that goes in your
application".

- [ ] **Step 1: Failing Vitest tests:**
  - one question per card with its hint;
  - the progress count;
  - follow-ups first;
  - the editor count and limit;
  - flagged phrases highlighted;
  - the Critic's notes;
  - Approve shows the version and short hash;
  - 360 px.
- [ ] **Steps 2–4:** Vitest, `tsc` and the OS-enabled build pass (in the Windows copy, per the Slice 4 handoff).
- [ ] **Step 5: Commit:** `feat(os): statements screens (Slice 5 Task 9)`. The PR names a Counsellor reviewer.

### Task 10: The fictional set, the Spike 4 runner and the gate test

**Files:**
- Create:
  - `tests/os/fixtures/statements/personas.yaml`: 10 fictional personas, each with answers, a profile and planted
    traps (a missing grade, an empty project answer, a tempting invented award);
  - `tests/os/quality/run_statement_quality.py`;
  - `tests/os/test_statement_quality.py`;
  - `tests/os/test_slice5_gate.py`.
- After the role-played run: `docs/os/slice-5-quality-report.md` (rates and counts only).

**Runner:** `--model test|openai --set fictional|roleplay --dir PATH --runs N --out FILE`.
- The role-played set defaults to `~/spike5-roleplay/`. It prints only rates and counts.
- **Fictional set checks (automatic):**
  - every planted invention is flagged;
  - limits are kept or labelled;
  - no persona's distinctive facts appear in another's draft.
- **Role-played set:** the runner writes the drafts to that folder, and the judges' ratings file is read back
  (`usable_after_one_edit`, `invented_facts`).

- [ ] **Step 1: Failing tests:**
  - `test_fictional_set_shape`;
  - `test_runner_offline_fictional_set` (test model);
  - `test_planted_inventions_flagged`;
  - `test_no_cross_persona_leak`;
  - **gate:** `test_slice5_gate` (interview → draft → edit → approve → task done, on Germany and Ireland).
- [ ] **Steps 2–4:** FAIL → implement → PASS; the full OS and legacy suites are green.
- [ ] **Step 5: Commit:** `test(os): Spike 4 runner, fictional set and gate (Slice 5 Task 10)`.
- [ ] **Step 6:** With the owners' OK: the billed role-played run, judged by the student and one owner (Q3), then
  the quality report. The gate is at least 8/10 usable after one edit for each kind, and 0 invented facts.

### Final review

One fresh reviewer, on the most capable model, over the whole Slice 5 diff. Give it the spec, this plan with its
Review Focus, and the PRs' rulings. Then one fix pass (RED→GREEN). **No `dev` PR.**
