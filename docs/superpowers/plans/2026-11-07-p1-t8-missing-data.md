# P1-T8: missing and wrong data — playbook `needs`, provide / result expected / which is right steps, one request per fact, the unanswered ladder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A plan is built even when the student's data is missing. Each missing fact or document becomes a **provide** step, dated backwards from the step that needs it. The steps that need it are blocked with the reason, and eligibility never says "not eligible" for a missing value (R-17). Each playbook step declares the evidence level it needs, and a request closes only when that level is met (R-18). There is one open request per fact per student. The OS owns it. It is shown in the plan, the inbox, email and the app notification, and answering anywhere closes it everywhere (R-19). A result that is not out yet becomes a **result expected** step dated from a calendar fact, then a provide step; P1 proves this with a test calendar fact (R-20). Conflicting data becomes one **which is right** step showing both values and their sources. The steps that use the fact pause, and the answer goes to the Vault through the reconciler (R-21). An unanswered request goes through reminders, then deadline at risk, then a proposal (drop or swap the place), then an escalation when every place is affected. The plan never fails silently (R-22). With the flags off, the app is today's, byte for byte.

**Architecture:**
- **OS side.**
  - The playbook schema gains two optional parts: `needs:` on a step (`[{fact | document, evidence}]`) and a top-level `asks:` block (the route's words for each request, plus an optional calendar fact for "result expected").
  - Germany master and the three fake routes get a **new playbook version** (v2) that declares them. Running v1 plans stay pinned. They move to v2 only through today's upgrade proposal, which the student accepts.
  - `select_playbook` picks a playbook that declares `needs` only when the caller asks for it. The caller asks only while the student's needs gate is on.
  - The pure compiler takes a new input, `StudentState`: the evidence level held for each fact and document, plus the facts in question. From it the compiler adds generated `provide@…`, `result_expected@…` and `which_is_right@…` steps, the hard edges to the steps that need them, and the blocked reasons `awaiting_fact` and `which_is_right`.
  - The kernel closes an answered request step as `done` (not `cancelled`), and blocks a waiting student step that gains a T8 block code.
  - A new table, `os_student_requests`, mirrors the open request steps. The kernel syncs it in the same transaction. A unique open row per student and fact makes R-19 and §9.3 rule 7 a database rule.
  - `plan_view.v1` fills its existing `requests` and `steps[].needs`.
  - A new port, `ports/fact_questions.py`, reads the student's open Vault conflicts from the host (a new contract, `fact_conflicts.v1`) and sends the student's answer back to the host.
  - New endpoints: `GET /v1/os/requests` and `POST /v1/os/requests/{id}/answer`.
  - The replan rules gain the R-22 ladder's last two rungs. Reminders already exist; the deadline-at-risk rung exists too.
- **Host side, in `backend/app/pai_os_bridge.py`.**
  - `fact_conflicts(student_ref)` is the read adapter. It runs in the API through `mount_os` and in the worker through `OS_FACT_CONFLICTS`.
  - `answer_fact_question(...)` is the answer adapter (API only).
- **Counsellor side.**
  - `app/pai_c/connect/fact_conflicts.py` builds the conflict list from the open `ProfileIssue` cards on education and test records, and applies an answer through `ProfileIssueService.resolve`.
  - `ProfileIssueService` gains a close hook. The T8 hook raises the Vault version and writes a `vault_event` for the card's keys, so an answer on the Vault page also reaches the OS. That includes "keep current", which writes nothing to the Vault.
  - `app/pai_c/roadmap/plan_adapter.py` marks a step with an open request as not tickable and adds an additive `request` key.
- **Frontend.**
  - The OS inbox shows how to answer a request. A **which is right** item shows the two values, their sources and the answers.
  - The roadmap shows the request line on a step.
  - All of this applies only while `GET /v1/os/requests` answers. A 404 renders today's UI.

**Tech Stack:** Python 3.13, SQLAlchemy Core (OS) and ORM (app), Alembic (OS tree), Pydantic v2, FastAPI, DBOS worker, Next.js, pytest/vitest.

**Spec:** `docs/superpowers/specs/2026-11-04-p1-connection-core-design.md` §3.5, §1 (R-20 note), P1-D9, P1-D12, P1-D14, P1-D16, §5 T8 (needs T4, T5, T7), §6 (risk "plan hash churns"), §7 rows 6.19, 6.21, 6.22. Master: R-17–R-22, §4 (who owns requests, conflicts and student facts), §6 rows 6.19–6.22 (6.20 is P2), §7, §9.3 rules 5, 6 and 7.
- **Code map:** the session scratchpad `p1-t8-explore.md`. All file:line references below come from it, checked on `pc/p1-t7-one-upload` at `aa95cb6` (T1–T7, T6 included) and, for T9's sidecar loader, on `pc/p1-t9-my-plan` at `79b2dd9`.
- **Controller decisions:** D-w1…D-w20 below. This plan's controller took them within the spec. There is no separate rulings file.

**Test database for implementers.** The controller assigns one of two databases. In the T7 worktree (`/home/user/Pai-C-t7`), use `postgresql://os_test:os_test@localhost:5432/os_test_b`. In the main tree (`/home/user/Pai-C`), use `…/os_test`. Never point one tree at the other's database. Export it in your shell only, as `OS_TEST_DATABASE_URL`, before `pytest tests/os`. Never print it, never write it to a file, and never commit it.

## Global Constraints

- **Flags off means today, byte for byte.**
  - Every new behaviour needs the student's **needs gate** (D-w1): the OS `counsellor` module, a configured StudentFacts host adapter, and that adapter answering for this student. It answers only while `CONNECT_STUDENT_FACTS` is on (`pai_os_bridge.student_facts`, `pai_os_bridge.py:489-505`).
    - The gate reads the same way in the API and the worker, because the worker loads the same adapter from `OS_STUDENT_FACTS`.
    - No new flag is added (P1-D9).
    - The answer endpoint also checks `part_on("CONNECT_STUDENT_FACTS")` on the host side.
  - While the gate is off:
    - `select_playbook` never returns a playbook that declares `needs` (D-w3), so new plans keep v1 and no upgrade proposal appears;
    - `compile_plan` gets `student=None` and compiles exactly as today;
    - no row is written to `os_student_requests`;
    - `plan_view` keeps `needs=[]` and `requests=[]`;
    - `GET /v1/os/requests` answers 404 `{"detail":"Not Found"}`;
    - the replan rules, reminders and the inbox behave as today.
  - **No existing response model gains a field.** FastAPI would print a new field as `null` with the flags off. New data travels only in `GET /v1/os/requests`, in `plan_view` (existing fields), and in the roadmap's additive `request` key. That key is present only on a step with an open request (R-44).
  - Each task names the tests that prove the flags-off behaviour. Those tests already exist and must pass **unchanged**. Where a task extends `tests/test_connect_flags_off.py`, it compares against fixtures captured from the current code **before any change**.
- **Frozen.**
  - Contracts `plan_view.v1`, `student_facts.v1`, `vault_event.v1`, `os_event.v1`, `escalation.v2`, `choice_request.v1` and `fact_proposal.v1` are used as they are (hash tests in `tests/os/contracts/test_frozen.py` and `test_frozen_v2.py`). The new `fact_conflicts.v1` (D-w12) gets its own hash-pinned schema in this PR.
  - The playbook files a running plan pins are **never edited**: `app/os/playbooks/germany_master.v1.yaml`, and `tests/os/playbooks/*.v1.yaml` (OS invariant 10). Their golden and compiler tests stay byte-for-byte unchanged.
  - Also never touched:
    - `backend/app/pai_c/**/*.md`, `pai_c/deep/**`, the planner/policy/voice prompt directories, `pai_c/playbooks/`, `pai_c/policy/actions/` and `pai_c/policy/*.json`;
    - `docs/counselor/COUNSELOR_V3_PROMPTS.md`;
    - the Counsellor model settings in `app/config.py`;
    - `app/memory/catalog/vault_catalog.json` (P1-D16).
  - `python scripts/check_freeze.py --base origin/pai-connect` must pass. If an implementer finds a frozen file that would have to change, **stop and report**; do not plan around it.
  - The chat never says anything new. The Counsellor chat request card is not used for OS requests (R-45).
- **Imports, names and checks.**
  - `app/os` never imports Counsellor code (Tach, `backend/tach.toml`). All glue lives in `backend/app/pai_os_bridge.py`. `app/main.py` only passes bridge callables to `mount_os`. `main.py` is a shared file, so it needs a reviewer from each team.
  - The bridge imports `app.memory.*` and `app.pai_c.connect.*` lazily, inside functions, as T4–T7 do.
  - No country, institution, exam or qualification names in `app/os` Python (R-58, `tests/os/test_invariants.py:15-19,72-80`). Fact keys, document types and calendar fact names live only in YAML (playbooks, doc types, `limits.yaml`) and test data.
  - Only the kernel changes plans and tasks (invariant 1, `tests/os/test_invariants.py:9-35`). `os_student_requests` is not a plan table. It is still written only by `app/os/requests/store.py`, and that module is called by the kernel inside its transaction.
  - Generated steps use task types that already have an owner module (invariant 2): `student.provide`, `student.choose` (module `inbox`) and `system.milestone` (module `milestone`) (`runner/modules.py:9-10,34-35`).
  - DB changes go only through Alembic.
    - **OS tree:** `os_0023_student_requests.py`, `down_revision` T7's `os_0022_document_file_ref.py`.
    - **Counsellor tree:** no migration.
    - One head each: `backend/scripts/check_alembic_heads.py`. Re-check both heads after every rebase (T9 adds none; a later task might).
- **Clock.** OS code takes the time from `app.os.clock.now()` / `clock.today()` (`tests/os/test_invariants.py` `direct_clock_calls`). The compiler gets `today` as an argument, as it does now. Counsellor code uses `datetime.now(timezone.utc)` as its neighbours do.
- **Privacy and ownership.**
  - The OS never stores a Vault value (R-01, master §4). `os_student_requests` holds codes, keys and IDs only. The two values of a **which is right** step are read live from the host on every `GET /v1/os/requests`.
  - Conflicts and answers cross only for the StudentFacts allow-list keys (`student_facts_keys.yaml`: education and test scores). Never a name, a date of birth or a document number.
  - A document-vs-document finding on identity fields stays OS document data (D-w12, "Ruling problems" 4).
  - Logs carry IDs and class names, never values.
- **Student copy.**
  - Every new student-facing sentence is marked **"approved by the owner"** and stored with `approved: true` in a data file, never in code. The owner approved the T-series student sentences in chat: "you dont need to open PRs for such silly student sentences just update it directly".
  - OS sentences go in `backend/app/os/requests/texts.yaml`. Counsellor sentences go in `backend/app/pai_c/connect/request_texts.yaml`. Route words (step titles) go in the v2 playbooks' `asks:` (route data, P1-D12/R-52).
  - Loaders fail at import when a listed key is missing. The full list is D-w16.
  - Frontend labels with no backend text use `copy.json` under `connect.requests`. The `copy.json`/`roadmap.json` equality test stays green.
- **Process.**
  - Run `tach check` and `pytest tests/os` before pushing OS code. Never run them alongside the legacy suite: run the legacy suite and `tests/os` one after the other (shared Postgres).
  - Never weaken a test. A test whose expectation changes on purpose is named in the commit message with the reason.
  - Tag tests with `@pytest.mark.req("R-xx")` or `// req: R-xx`. Commit messages end with the session attribution lines.
  - Fictional students only. No live model calls (`OS_MODEL_MODE=offline`; the Counsellor extractor is stubbed).
  - CODEOWNERS: the Counsellor lead (`memsa771-hub`) reviews the PR. It touches `app/memory/profile_issues.py`, `app/pai_c/connect/**`, `app/pai_c/roadmap/plan_adapter.py`, `frontend/components/counselor/**`, `copy.json` and `pai_os_bridge.py`.

## Decisions taken in this plan (controller; flagged to the owner in the PR)

- **D-w1, the needs gate (no new flag).** `app/os/requests/gate.py` `on(student_ref, *, engine, tenant_id) -> StudentFactsV1 | None` returns `student_facts.host_facts(...)` (`ports/student_facts.py:83-97`).
  - **Gate on** means it returns facts: the module is on, a host adapter is configured, and `CONNECT_STUDENT_FACTS` is on in that process.
  - The worker reads the same flag through `OS_STUDENT_FACTS`, so the API and the worker agree. If they disagreed, the hourly recompile (`workers/deadline_engine.py:16-40`) would add and remove request steps every hour.
  - **Worker startup check:** when `OS_STUDENT_FACTS` is set and `OS_FACT_CONFLICTS` is not, the worker exits with code 2. It names the setting, never a value. It is the same pattern as `runner/worker.py:274-281`.
  - A plan already pinned to v2, read with the gate off, compiles with `student=None`. Its `needs` are ignored, and its open request steps are removed (cancelled, requests `cancelled`). The plan keeps running (row 6.17).
- **D-w2, a new playbook version, not a sidecar (task question).** `needs` change the compiled plan: they add steps, edges and blocked reasons. A sidecar joined onto v1 (as T9 does for `pages`) would change the structure of plans already pinned to v1, without an explicit revision. That breaks invariant 10 ("upgrades are explicit plan revisions"). T9's sidecar is display-only, so it does not.
  - So T8 adds new files: `app/os/playbooks/germany_master.v2.yaml`, and `tests/os/playbooks/needs/{pakistan_inter,pakistan_bs,ireland_master}.v2.yaml`.
    - The fake v2 files go in a new fixture directory. `tests/os/test_playbooks.py:23-25` pins the exact set of fake playbooks in `tests/os/playbooks/`, and T9's label test renders that directory.
    - T8 tests load `{**load_playbook_dir(FAKE_DIR), **load_playbook_dir(FAKE_DIR / "needs")}`.
  - **The explicit upgrade.** With the gate on, `PlanService.check_newer` (`service.py:160-174`, run by `replan/run.py:142` every 5 minutes) sees v2 as newer for a v1 plan. It records `playbook_newer`. The rules turn that into today's `UpgradePlaybook` proposal (`rules.py:124-125`), which `is_big` makes a student decision (`ops.py:98-99`). Accepting it runs `PlanService.upgrade(plan_id, 2)` → `kernel.upgrade_playbook` (a revision, and the pin moves). Nothing is new here except the gate.
- **D-w3, gated selection.**
  - `Playbook.declares_needs` is a computed property: any step has `needs`.
  - `select_playbook(books, origin, destination, level, *, with_needs: bool = False)`:
    - by default it skips books that declare needs;
    - with `with_needs=True` it picks the newest of all.
  - **Callers that pass the gate:** `PlanService.start_plan`, `check_newer` and `upgrade(version=None)` (`service.py:101-183`). Each passes `with_needs=gate.on(contract.student_ref) is not None`.
  - **Every other reader stays on plain books:**
    - `select_playbook` callers `plan_view.py:156`, `ports/plan_source.py:60`, `adapters/counsellor/intake.py:231,301`. These use only `book.key`, which is the same in v1 and v2.
    - The "newest" helpers `api/self_serve.py:21-31` (`routes_out` prints `version`), `ports/plan_query.py:35,51` and `routes/builder.py:76-80`. These move to one helper, `playbooks.newest_plain(books)`, so `/v1/os/routes` and the route builder keep their bytes in every state.
  - `apply.check` (`replan/apply.py:161-164`) and `_pinned` (`service.py:36-46`) look playbooks up by `(key, version)`. They find v2 because the mapping holds every book.
- **D-w4, the schema (`app/os/playbooks/models.py`, additive, optional).**
  - `Need`: exactly one of `fact: str` (the `FACT_KEY` pattern of `student_facts.py`) or `document: str` (a doc-type key), plus `evidence: Literal["stated","shown","confirmed"]`.
  - `TaskTemplate.needs: list[Need] = []`.
  - `Ask`:
    - `stated`, `shown` and `confirmed`: the provide titles per level, each optional;
    - `which_is_right`: the conflict step title;
    - `duration_days: int = 1`: the provide step's own duration;
    - `expected`: an optional `Expected{fact: str, title: str}`, where `fact` names a **route** Knowledge fact holding a date (the calendar).
  - `Playbook.asks: dict[str, Ask] = {}`, keyed by the fact key or the doc type.
  - **Validation**, in `_references_resolve`:
    1. every need has an `asks` entry with the title for its evidence level;
    2. a fact need's entry has `which_is_right`;
    3. a document need's evidence is `shown` (see "Ruling problems" 8);
    4. `expected` only on a fact entry;
    5. no playbook step uses a reserved `template_key` (`provide`, `which_is_right`, `result_expected`);
    6. a need on a step with `fan_out: programme` is allowed.
  - `needed_fields` (`compiler/compile.py:79-89`) adds each `expected.fact` to the route fields. Only v2 books have one.
- **D-w5, generated steps (pure, `app/os/compiler/needs.py`).** Instance keys are `<template>@<kind>:<ref>:<level>`, plus `result_expected@fact:<ref>`, parsed by one function, `requests/keys.py parse`.
  - **Meeting a need.**
    - The levels rank `stated < shown < confirmed`. A fact is met when `StudentState.facts[key]` ranks ≥ the need. Vault `unknown` (inferred) counts as missing.
    - A document is met when the student has a non-deleted OS document of that type with status `confirmed`.
  - **One request step per ref.** For each ref that a live step (one kept after conditions and overrides) needs and that is unmet:
    - If the ref is **in question** (in `StudentState.questions`), the step is `which_is_right@<kind>:<ref>:<highest level needed>`. It is `student.choose`, `inbox_kind: choose`, titled from `asks[ref].which_is_right`. No provide step is added for that ref while it is in question (R-19).
    - Otherwise it is `provide@<kind>:<ref>:<L>`, where L is the **lowest unmet level** a live step needs. It is `student.provide`, `inbox_kind: provide`, titled from `asks[ref].<L>`, with `asks[ref].duration_days`.
      - For the master §7 example: "type your marks" closes when the student types them, then "upload the mark sheet" opens as a new step and request. There is one open request per fact at any time.
    - **Result expected (R-20).** If the fact ref is missing (not merely too weak), `asks[ref].expected` is set, and the route fact `expected.fact` for the intake year holds a date **after `today`**, then `result_expected@fact:<ref>` is added before the provide step.
      - It is a `system.milestone` work step with `blocked_reason: result_expected:<ref>`, so it never runs. Its deadline is the end of that date in the fact's or the playbook's time zone, and its citation comes from the fact URL.
      - The provide step hard-depends on it with `pull: false`, so the provide date does not pull it earlier.
      - When the date passes or the fact arrives, it drops out of the draft.
  - **Edges and blocks.**
    - Every live step with an unmet need, or a need in question, on a ref hard-depends on that ref's request step. The backward pass then dates the request step from the step that needs it (R-17).
    - Such a step gets `blocked_reason` `which_is_right:<ref>` (in question) or `awaiting_fact:<ref>` (missing or too weak; also used for documents, as the spec words it). With several refs, the first in sort order is used. `plan_view` shows only the code before the colon (`plan_view.py:28-31`).
  - **The answered set.** `PlanDraft.answered: tuple[str, ...]` lists the request keys this draft considers answered:
    - `provide@…:<L>` for each live need met at level L;
    - `which_is_right@…` for each needed ref that is no longer in question.
    - It defaults to `()`, so every existing draft is unchanged.
- **D-w6, `StudentState` and where it comes from (`app/os/requests/state.py`).** A frozen dataclass with:
  - `facts: {key: level}`;
  - `documents: {doc_type: "confirmed" | "uploaded"}`;
  - `questions: {ref: QuestionRef}`. A `QuestionRef` has `origin` (`vault` | `impossible` | `documents`) and an ID: the Vault card ref, the limit pair, or the finding ID.

  `build(svc, student_ref)` returns None while the gate is off. Otherwise it reads four sources:
  1. the facts from the gate's StudentFacts (levels only, never values);
  2. the documents from `DocumentStore.list_for`;
  3. the open Vault conflicts from `fact_questions.conflicts(student_ref)` (D-w12);
  4. impossible values: for each `(value_key, total_key)` pair it checks value > total on the StudentFacts values. The pairs are the doc types' `scale_of` mapped to `fact:` keys (`documents/types/*.v1.yaml`) plus `app/os/requests/limits.yaml` (the `part1` / `part2` pairs, R-80). The check reads values in memory and stores nothing.

  It also reads open `mismatch` findings (`os_document_findings`), keyed `document:<doc_type>.<field>` for each doc type in the finding.

  `PlanService.compile` (`service.py:50-66`) passes `student=state.build(self, contract.student_ref)` when the pinned book declares needs. Otherwise it passes None.
- **D-w7, kernel changes (`kernel/kernel.py`).**
  - In `_revise` (:502-559), a key in `d.removed` that is also in `draft.answered`, with stored state `waiting_student`, becomes `done` with cause `request_answered`. `WAITING_STUDENT → DONE` is allowed (`states.py:24`). Every other removed key is cancelled, as today.
  - A changed, unstarted **student** step that gains a blocked reason starting with `awaiting_fact:`, `which_is_right:` or `result_expected:` moves `WAITING_STUDENT → READY → BLOCKED` (both allowed, `states.py:21,24`). Today only `READY` is moved (:537-539). Other codes keep today's behaviour, which keeps flags-off byte for byte.
  - A started step (running, waiting for review, done) is never re-blocked (revisions change only unstarted tasks, `revisions.py`). This is reported in "Ruling problems" 1.
  - `create_plan`, `_revise` and `close_plan` call `requests.store.sync(conn, tenant_id, plan_id, answered=draft.answered or ())` before they return, in their own transaction (D-w9).
- **D-w8, what triggers a recompile.**
  - **Vault changes.** `replan/student_facts.py` `used_keys` (:20-25) also returns the fact refs of the pinned book's `needs` and `asks`. `record_changes` (:31-48) still records `student_fact_changed` once per Vault version. For a plan whose pinned book declares needs, it then calls `plans.recompile(plan_id, "student_fact_changed")`.
    - Errors are logged by class and swallowed. The hourly deadline engine is the backup.
    - The rules' own answer to the event (`rules.py:127-135`) is unchanged.
  - **OS document changes.** `POST /documents/{id}/confirm` (`router.py:420`), `DELETE /documents/{id}` (:454) and `POST /documents/findings/{id}/resolve` (:438) call `requests.refresh(svc, student_ref, "document_changed")` after they succeed, while the gate is on. `refresh` recompiles each open plan of the student whose pinned book declares needs.
  - **Answers.** The answer endpoint calls `refresh` with cause `request_answered` after the host answers.
- **D-w9, `os_student_requests` (migration `os_0023_student_requests.py`).**
  - Columns:
    - `id` BIGSERIAL, `tenant_id`, `student_ref`;
    - `plan_id` FK `os_plans`, `task_id` FK `os_tasks` `ON DELETE SET NULL`;
    - `kind` (`provide` | `which_is_right`), `need_kind` (`fact` | `document`), `need_ref`, `evidence` (`stated` | `shown` | `confirmed`);
    - `status` (`open` | `answered` | `cancelled`), `closed_cause` TEXT NULL;
    - `created_at`, `closed_at`.
  - Check constraints on every coded column.
  - **The unique partial index `uq_os_student_requests_open (tenant_id, student_ref, need_kind, need_ref) WHERE status = 'open'`** is R-19 and §9.3 rule 7.
  - Index `(tenant_id, plan_id)`.
  - `sync` closes before it opens, so a level change (the stated step done, the shown step new) never collides:
    1. **Close.** Each open row of the plan whose step is gone or terminal is closed: `answered` when the step is `done`, or when its key is in `answered`; otherwise `cancelled`.
    2. **Open.** Each non-terminal request step gets an open row: inserted with `on_conflict_do_nothing`, or reused when another plan of the same student already holds the open row for that fact.
  - `result_expected` steps get no row. The request is the provide step after them; it is open, pending, and shown in the plan with its due date.
  - The table holds no value.
- **D-w10, the four surfaces of R-19 come from the one step.**
  - **Plan:** `plan_view.requests` and `steps[].needs`.
  - **Inbox:** the step itself (`api/queries.py:109-121` lists waiting student steps).
  - **Email:** today's reminder cadence (`workers/reminders.py:30-58`). The first slot of a newly waiting step fires on the next hourly run, because the key is `reminder:{task}:{slot}`. No new email template.
  - **App notification:** the kernel's `student_needed` os_event when the step starts waiting (`kernel.py:407-432`).
  - Answered anywhere means the step leaves `waiting_student` and the row is closed. Inbox, reminders and notifications stop together.
- **D-w11, a request is never ticked.**
  - `inbox_actions.complete` (`inbox_actions.py:22-40`) raises `StepActionError("answer_required", text("answer_required"))` for a step whose template is `provide`, `which_is_right` or `result_expected`. The inbox route and the roadmap's PlanActions port both go through it.
  - `plan_adapter.steps_of` (`plan_adapter.py:100-114`): `tickable` is false when the step has an open request. That is a step whose need equals an open request's need. Playbook steps whose needs are met stay tickable.
- **D-w12, conflicts.**
  - **Vault conflicts are Vault data.** After T7, a document value that differs from a Vault record always opens a `ProfileIssue` (`domain_stewards.py:73-86`, `student_records.py:290-305`). So does a chat correction against a document-backed record. The OS reads the open cards through `ports/fact_questions.py` `conflicts(student_ref) -> FactConflictsV1 | None`. A new contract, `app/os/contracts/fact_conflicts.py` plus `fact_conflicts.v1.schema.json`, has these fields:
    - `schema` (`pai.fact_conflicts.v1`), `student_ref`, `vault_version`, `built_at`;
    - `conflicts: [{ref, key, values, answers}]`, where:
      - `ref` matches `^profile_issue:[A-Za-z0-9-]+$`;
      - `key` matches `FACT_KEY`;
      - `values` is exactly two items `{side: current | proposed, value, evidence: stated | shown | confirmed | unknown, document_ref, as_of}`;
      - `answers` is a subset of `keep_current`, `accept_proposed`, `provide_new`, taken from the card's own answers (`vault_view.py:595-617`).
    - `extra="forbid"`, `frozen=True`. One entry per differing allow-listed key.
  - **Impossible values** are found by the OS (D-w6) with ref `impossible:<value_key>`.
  - **Document vs document** uses the existing open `mismatch` findings (`os_document_findings`, `documents/checks.py:88-102`). These are identity fields, so the answer is the existing `resolve_finding` (`confirm.py:89-96`, OS profile values). It never goes to the Vault ("Ruling problems" 4).
  - A **profile-page edit** by the student is not a conflict. The Vault rule is that the student's explicit edit wins, with the document reading kept as a disagreement (`student_records.py:306-317`) ("Ruling problems" 5).
- **D-w13, answering.**
  - `POST /v1/os/requests/{id}/answer` takes `{choice: "current" | "proposed" | "new", value?}`. It checks the student and the tenant (404 otherwise), that the row is `open` (409 `already_answered` otherwise), and that the kind is `which_is_right` (409 `answer_elsewhere` for provide: that is answered by giving the information).
  - The `QuestionRef` origin decides the route:
    - **`vault`:** the OS calls `fact_questions.answer(student_ref, ref, key, choice, value)`. This is a synchronous host callback, like `ports/choice_sink.py`. The host runs `ProfileIssueService(db).resolve(ws, issue_id, {current: keep_current, proposed: accept_proposed, new: provide_new}[choice], value=…, capture="os_which_is_right")` and commits.
      - The answer must be one of the card's `answers`.
      - For `provide_new`, the value is placed at the field's path in the card's record value (`_candidate_spec`, `profile_issues.py:179-200`).
      - An issue already closed answers `gone`, which is also success.
    - **`impossible`:** only `new` is allowed. The host proposes a `user_explicit` / `profile` `student_record` candidate for the family's record, mapped as in `document_facts._split` / `_record_id`, and reconciles it inline.
    - **`documents`:** the OS calls `resolve_finding` with the chosen document's value.
  - Then `refresh(...)` runs, and the response is `{status: "answered"}`. The step is `done` before the response returns.
  - With the part off, or the host not answering (`None`), the response is 404.
- **D-w14, an answer on the Vault page reaches the OS.**
  - `app/memory/profile_issues.py` gains `register_close_hook(hook)`, with `hook(db, issue)` called after every `_close` (:222) in `resolve` and `_resolve_document_owner`.
  - T8 registers `vault_version.after_issue_closed` in `app/capabilities/system.py`, next to `after_accept` (:14-23). For a `conflicting_record` card on `education` or `test_attempt` with `CONNECT_STUDENT_FACTS` on, the hook:
    1. maps the card's record to keys (`keys_for`-style, `vault_version.py:68-105`);
    2. calls `bump(db, ws, keys)` (:108-121);
    3. calls `outbox.record_vault_event(...)` (as `after_accept` does, :124-138).
  - This covers `keep_current`, which reconciles nothing and so fires no accept hook. The OS gets `student_fact_changed`, recompiles (D-w8), and closes the step and the request.
  - A repeat delivery is harmless, because events are deduped by Vault version.
- **D-w15, the unanswered ladder (R-22).**
  1. **Reminders**, on today's cadence. `workers/reminders.py:39-42` records `document_missing` when a provide inbox item is past due. T8 extends that condition to `which_is_right` request steps (template check), so they reach the same ladder.
  2. **Deadline at risk.** This is today's `detect_at_risk` plus `os_event` (`events.py:64-80`), and `_at_risk` (`rules.py:82-100`). The request step is the unstarted student dependency of the blocked step, so the rule reprioritises it and nudges the student.
  3. **Proposal.** In `rules_for`, a `document_missing` event on a **request step** (template `provide` or `which_is_right`) works out the affected places: the `programme_ref` of every open step that hard-depends on the request step. A route-level needing step affects every place.
     - If fewer than `min_programmes` places would be left, go to step 4.
     - Otherwise, for each affected place: a `SwapProgramme` to the first close match (the `suggestions` of `_rejected`, `rules.py:59-72`), or else a `CancelProgramme`. Both are big, so the student accepts. On a Counsellor plan this becomes a T6 `choice_request`.
     - The reasons are `unanswered_swap` and `unanswered_drop` from `texts.yaml`.
  4. **Escalation.** When every live place is affected: `Escalate(reason=text("unanswered_all"))` → support case → `CounsellorSink` maps `document_missing` to `blocking_gap` (`escalation.py:31-33`) → T6 pauses the plan, and the journey goes back to choosing.
  - A `document_missing` on a non-request provide step keeps today's nudge (`rules.py:113-117`).
  - **Never silent.** Every open request step whose due date has passed has, within one sweep, either a pending or applied proposal, or a support case naming its event.
- **D-w16, student sentences (approved by the owner, `approved: true`).**
  - `backend/app/os/requests/texts.yaml`, version 1, `approved: true`:
    - `how_stated`: "Tell PAI in the chat or on your profile page. This step closes by itself when PAI has it."
    - `how_shown`: "Upload it on the Documents page and check what PAI read. This step closes by itself when you confirm it."
    - `how_confirmed`: "Check it on your profile page. This step closes by itself when you confirm it."
    - `how_document`: "Upload it on the Documents page and check what PAI read. This step closes by itself when you confirm it."
    - `how_which_is_right`: "Two places say different things. Choose the one that is right, or type the right value."
    - `how_impossible`: "This value is higher than its total. Type the right value."
    - `answer_required`: "This step closes by itself when PAI has what it needs."
    - `current_label`: "Saved in PAI"
    - `proposed_label`: "From your document"
    - `new_label`: "Neither: I will type the right value"
    - `unanswered_swap`: "A step of this place is still waiting for information from you: a close match is suggested instead."
    - `unanswered_drop`: "A step of this place is still waiting for information from you: removing this place is suggested."
    - `unanswered_all`: "Information your plan needs has not arrived and every place depends on it; the Counsellor decides with the student."
  - `backend/app/pai_c/connect/request_texts.yaml`, version 1, `approved: true`, for the roadmap request line:
    - `provide_stated`: "PAI needs this from you. Tell PAI in the chat or on your profile page."
    - `provide_shown`: "PAI needs to see this. Upload it on the Documents page."
    - `provide_confirmed`: "Check this on your profile page."
    - `which_is_right`: "Two places say different things. Choose the right one on your Vault page or in your PAI inbox."
    - `result_expected`: "Your result is not out yet. PAI will ask for it when it is."
  - Germany v2 `asks:` titles, which are route data:
    - `ssc_certificate.shown`: "Upload your SSC certificate with subjects and grades"
    - `hssc_certificate.shown`: "Upload your HSSC certificate with subjects and grades"
    - `transcript.shown`: "Upload your final transcript"

    The wording comes from v1's `school_certificates` and `grading_system_doc` titles (`germany_master.v1.yaml:108-134`).
  - The fake v2 titles are test data (Task 1).
- **D-w17, v2 content: no new institution data.** The only changes from v1 are the ones listed here.
  - **Germany v2** (`germany_master.v2.yaml`):
    - It is `version: 2`.
    - The manual `school_certificates` step is removed. Its two documents become `needs` of `uni_assist_apply` and `direct_apply`: `ssc_certificate` and `hssc_certificate` at `shown`, plus `transcript` at `shown`.
    - The `depends_on` entries that pointed at `school_certificates` are dropped.
    - No date, fee, rule or citation is added. The same S-sources are cited.
  - **`pakistan_inter.v2`:**
    - `admission_form` needs `education.matric.marks_obtained` and `education.matric.marks_total` at `stated`;
    - `merit_list` needs `education.matric.marks_obtained` at `shown`, which demonstrates "type" versus "upload" (R-18);
    - `asks['education.matric.marks_obtained'].expected = {fact: matric_result_date, title: "Matric result expected"}`.
    - The test seed has a `matric_result_date` route fact (the test calendar, R-20).
  - **`pakistan_bs.v2`:** `entry_test` needs `education.intermediate.marks_obtained` at `stated`, and `merit_list` needs `hssc_certificate` at `shown`.
  - **`ireland_master.v2`:** `apply` needs `transcript` at `shown`. A new programme fan-out step, `english_proof`, has `condition: {fact: english_requirement, present: true}` and needs `test.ielts.score` at `shown`. A need on only some places is what lets the drop/swap rung fire (D-w15).
- **D-w18, R-20 is built in P1 as the mechanism with a test calendar fact.** `connection.yaml` gives R-20 `phases: [P1]`, so the P1 gate requires it built. The row 6.20 proof with official calendars stays P2, as the P1 spec note says.
- **D-w19, `GET /v1/os/requests` (new, student-owned).** It answers `{"requests": [...]}`. Each item has:
  - `id`, `task_id`, `kind`, `need {kind, ref, evidence}`, `status`, `due_at`, `due_tz`, `title` (the step title);
  - `how`: the texts key for its kind and level, resolved to a sentence;
  - for `which_is_right` only, `choices: [{choice, label, value, source: {kind: vault | document | chat, evidence, document_ref, as_of}}]` and `allow_new`.

  The values are read live (D-w12) and never stored. It lists open requests and those answered in the last 7 days. It answers 404 while the gate is off.
- **D-w20, T9 coordination.** T9 (`pc/p1-t9-my-plan`) is not merged in the T7 tree. Its loader joins `pages/<key>.v<n>.yaml` (`/home/user/Pai-C/backend/app/os/playbooks/loader.py:18-48`).
  - Whichever merges second rebases.
  - If T9 is on `pai-connect` when Task 1 runs, Task 1 adds `app/os/playbooks/pages/germany_master.v2.yaml` (a byte copy of the v1 sidecar). It also checks that T9's `GET /v1/os/plan` reads route pages through the pin, which it does through `plan_view`.
  - The fake v2 files live in `needs/`, which has no `pages/` subdir, so T9's label test is unaffected.

## Ruling problems found (reported to the controller)

1. **"Dependent steps are blocked" cannot reach a step that has started.** Revisions change only unstarted tasks (`kernel/revisions.py` `diff`). A step already running or waiting for review keeps going when a conflict appears later.
   - A waiting student step is unstarted, but `WAITING_STUDENT → BLOCKED` is not an allowed transition (`states.py:24`). D-w7 goes through `READY`, for the T8 codes only.
   - Please confirm that "pause" means `blocked` with reason `which_is_right` (a step state), not a plan pause. A plan pause (P1-D11) would stop every other step too.
2. **R-19 ("one open request per fact") against master §7 ("typing marks closes 'tell us your marks' but not 'upload the mark sheet'").** Literally, that is two requests for one fact. D-w5 settles it in sequence: one open request per fact, at the lowest unmet level. The stated one is answered, then the shown one opens. Please confirm.
3. **The OS cannot see Vault conflicts through the frozen contracts.** `student_facts.v1` has no "in question" state, and `vault_event.v1` carries keys only. So T8 needs:
   - a new contract, `fact_conflicts.v1`, which needs both teams' sign-off in this PR, as T7's `fact_proposal.v1` did;
   - a close hook in `app/memory/profile_issues.py` (Counsellor code, not frozen; the Counsellor lead reviews), because "keep current" writes nothing, so without a hook the OS would not hear of it until the hourly recompile.
4. **"The answer goes to the Vault" cannot hold for document-vs-document conflicts.** Today's findings compare identity fields only (`full_name`, `father_name`, `date_of_birth`, `checks.py:83-102`). The StudentFacts allow-list and T7's privacy rule keep those out of the Vault. The answer stays in the OS profile values (`resolve_finding`). If the owner wants identity facts Vault-owned, that is a new catalog type and a freeze decision (P1-D16), not T8.
5. **"A student correction" as a conflict.** A chat correction against a document-backed record already opens a Vault card, and T8 shows it. A profile-page edit is the student's explicit answer by the Vault's own rule ("the student's edit wins", `student_records.py:306-317`), so T8 does not ask again. Please confirm.
6. **R-20 "dated from the official exam calendar".** P1 has only a test calendar fact, and StudentFacts v1 carries no "still studying" status. So "not out yet" is decided by the calendar date alone: the fact is missing and the calendar date is after today. A student whose result is out but who has not told PAI sees "result expected" until that date. They can still give it at any time, and the request then closes. P2 brings the official calendars, and can add the student's status if the owner wants it.
7. **"Reminders on the playbook's schedule" (master §7).** The cadence is OS-wide (`reminders.py:14-27`), and no playbook declares a schedule. T8 keeps the OS cadence. A per-route cadence would be new route data for a later phase.
8. **Evidence levels for documents.** `confirmed` for a document has no meaning in P1: no reviewer confirms documents. `stated` for a paper is not evidence. So document needs accept `shown` only (validated). A document counts as `shown` when the student confirmed it on the OS screen (T7's rule).
9. **No T8 flag exists in P1-D9.** T8 is gated by `CONNECT_STUDENT_FACTS`, because needs read Vault facts. A new flag would go beyond P1-D9, as T6 ruling 5 found. Please confirm.
10. **The Germany v2 content removes the manual `school_certificates` step.** Its documents become needs instead (D-w17); otherwise there would be two "upload your certificates" steps. This is a route-content change for the owner to approve in the PR.
11. **The escalation rung ends in "back to choosing" (T6 D-x9), even for a missing document.** That follows the spec (R-22 → R-11). It is harsh for a document the student can still get, so the owner may want to look at it.
12. **Running v1 plans do not get needs until the student accepts the upgrade proposal** (invariant 10). A student who declines keeps the v1 plan without provide steps. R-17 holds for new plans and upgraded ones.

## Review Focus

1. **No churn.**
   - The same `StudentState` gives the same draft. The hourly recompile makes no revision while nothing changed (spec §6 risk).
   - The API and the worker compute the same gate. The worker refuses to start without `OS_FACT_CONFLICTS` when `OS_STUDENT_FACTS` is set.
   - → Task 2 and Task 4 tests.
2. **One open request per fact.**
   - The unique index holds under two concurrent revisions.
   - A level change (stated, then shown) closes one row and opens the next in one transaction.
   - A second plan of the same student reuses the open row.
   - → Task 3.
3. **Answered anywhere closes everywhere.** The answer may arrive by:
   - chat (Vault extraction);
   - the Vault page, including `keep_current`;
   - the OS answer endpoint;
   - an upload and confirm.

   Each time, the step is `done`, the row is `answered`, the inbox no longer lists it, no further reminder is written, and `plan_view` shows `answered`. → Task 4 and Task 7.
4. **Flags off.**
   - v1 is selected and no upgrade proposal appears.
   - No request row is written, and `plan_view` has `needs=[]` and `requests=[]`.
   - `/v1/os/routes`, the inbox, the replan rules and the reminders are byte-identical.
   - → the flags-off tests named in every task.
5. **The ladder order, and never silent.** Reminders come first, then at risk, then a proposal, then the escalation. A request past its date always ends in a proposal or a support case. → Task 5.

---

### Task 1: Playbook `needs` and `asks`, the v2 playbooks, gated selection

**R-IDs:** R-17 (data), R-18 (evidence per step), R-20 (calendar fact declared).

**Files:**
- Modify: `backend/app/os/playbooks/models.py`.
  - New models `Need`, `Expected` and `Ask` (D-w4).
  - `TaskTemplate.needs` (:84-117).
  - `Playbook.asks` and the `declares_needs` property (:134-200).
  - New validation in `_references_resolve`.
  - The reserved names `REQUEST_TEMPLATES = ("provide", "which_is_right", "result_expected")`.
- Modify: `backend/app/os/playbooks/loader.py`: `select_playbook(..., with_needs=False)` (:40-48), and new `newest_plain(books)`. `backend/app/os/playbooks/__init__.py` exports both.
- Modify the callers per D-w3:
  - `backend/app/os/service.py` (:101-116, :160-183) takes the gate (Task 2 supplies `gate.on`; this task adds the keyword with a default of False);
  - `backend/app/os/api/self_serve.py:21-31`, `backend/app/os/ports/plan_query.py:35,51` and `backend/app/os/routes/builder.py:76-80` use `newest_plain`.
- Modify: `backend/app/os/compiler/compile.py` `needed_fields` (:79-89) adds `expected.fact`.
- Create: `backend/app/os/playbooks/germany_master.v2.yaml` (D-w17); `backend/tests/os/playbooks/needs/pakistan_inter.v2.yaml`, `pakistan_bs.v2.yaml` and `ireland_master.v2.yaml`; the `matric_result_date` and `english_requirement` facts in the T8 test seed `backend/tests/os/fixtures/needs_seed.yaml`, loaded with `load_seed` like `SEED_DIR / "germany_ws2027.yaml"` (`tests/os/test_golden.py:58`).
- Tests:
  - new: `backend/tests/os/test_playbook_needs.py`;
  - extend: `tests/os/test_playbooks.py` (new cases only).

- [ ] **Step 1: Write the failing tests.**
  - `test_need_needs_one_of_fact_or_document` (R-18).
  - `test_every_need_has_an_ask_title_for_its_level`.
  - `test_fact_need_needs_a_which_is_right_title`.
  - `test_document_need_accepts_shown_only` (Ruling problems 8).
  - `test_expected_only_on_a_fact_ask`.
  - `test_reserved_template_keys_refused`.
  - `test_germany_v2_loads_and_differs_from_v1_only_in_needs` (D-w17). Loading both files: remove `needs` and `asks`, put `school_certificates` and its edges back, set the version to 1, and the model dumps are equal. The task-type registry validates v2 (`default_registry().validate`).
  - `test_fake_v2_playbooks_load_from_needs_dir`.
  - `test_select_skips_needs_books_by_default` and `test_select_with_needs_picks_v2`.
  - `test_newest_plain_ignores_needs_books`: `routes_out` gives version 1 for germany with v2 loaded.
  - `test_needed_fields_adds_expected_fact` (R-20).
  - **Flags-off proof:**
    - `tests/os/test_playbooks.py` (incl. `test_fake_playbooks_load` :23-25 and `test_select_playbook_highest_version` :53-63), `tests/os/test_golden.py` (both golden tests on `load_playbook_dir()`), `tests/os/test_compiler.py`, `tests/os/test_eligibility_rules.py`, `tests/os/test_builder_choice_flow.py`, `tests/os/test_plan_view.py` and `tests/test_connect_flags_off.py` pass unchanged;
    - `GET /v1/os/routes` is byte-identical with v2 loaded (new `test_routes_bytes_unchanged_with_v2_loaded`, compared with a fixture captured before the change).
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/os -k "playbook or golden or compiler or routes or builder"`, then `tach check` and the R-58 test.
- [ ] **Step 5: Commit** `feat(os): playbook needs and asks; Germany and fake routes v2; needs playbooks chosen only through the gate (R-17, R-18, R-20)`.

### Task 2: The compiler, the gate and the kernel — provide, result expected and which is right steps

**R-IDs:** R-17, R-18, R-20, R-21 (the compile half).

**Files:**
- Create:
  - `backend/app/os/compiler/needs.py` (pure, D-w5): `expand(insts, playbook, student, route_facts, today, tz) -> answered`, called from `compile_plan` after the playbook is expanded and the overrides are applied (`compile.py:336`), before the confirm tasks are added.
  - `backend/app/os/requests/__init__.py`, `gate.py` (D-w1), `state.py` (D-w6), `keys.py` (`parse`, `make`), `limits.yaml` and `refresh.py` (`refresh(svc, student_ref, cause) -> int`).
  - `backend/app/os/ports/fact_questions.py`. It mirrors `ports/student_facts.py`:
    - `configure(conflicts=None, answer=None)`;
    - `load` / `from_settings`, raising `FactQuestionsSourceError` that names `OS_FACT_CONFLICTS`;
    - `conflicts(student_ref)`, which returns `{}` while unconfigured. This task reads only `key → ref`; Task 4 adds the contract validation.
- Modify:
  - `backend/app/os/compiler/compile.py`: `compile_plan(..., student: StudentState | None = None)` (:164-176). `PlanDraft.answered: tuple[str, ...] = ()` (:57-62). With `student=None`, nothing changes.
  - `backend/app/os/service.py` `compile` (:50-66) passes `student=state.build(...)` when the book declares needs. `start_plan`, `check_newer` and `upgrade` pass `with_needs=gate.on(...) is not None`.
  - `backend/app/os/kernel/kernel.py` `_revise` (:502-559), for D-w7: the answered keys become `done`, and the T8 codes block a waiting student step.
  - `backend/app/os/replan/student_facts.py` `used_keys` and `record_changes` (:20-48), for D-w8.
  - `backend/app/os/api/router.py`: confirm (:420), delete (:454) and finding resolve (:438) call `refresh` after success.
  - `backend/app/os/settings.py` (:22-23, :105-106) gains `fact_conflicts`. `backend/app/os/runner/worker.py` (:274-281) loads it, with the D-w1 startup check.
- Tests:
  - new: `backend/tests/os/test_compile_needs.py` (pure, no DB), `backend/tests/os/test_needs_kernel.py`, `backend/tests/os/test_needs_gate.py`;
  - extend: `tests/os/test_student_fact_replan.py` (new cases only), `tests/os/test_workers.py` (the worker startup case).

- [ ] **Step 1: Write the failing tests.**
  - `test_missing_fact_adds_one_provide_step_dated_from_the_needing_step` (R-17): the provide step's `latest_finish` equals the needing step's `latest_start`. The needing step has `blocked_reason` `awaiting_fact:<ref>` and a hard edge to the provide step.
  - `test_two_steps_needing_one_fact_share_one_provide_step` (R-19 at compile).
  - `test_stated_met_moves_the_ask_to_shown` (R-18): with marks stated, `provide@fact:…:stated` is in `answered` and `provide@fact:…:shown` is added. `admission_form` is unblocked and `merit_list` stays blocked.
  - `test_inferred_counts_as_missing` (R-18).
  - `test_document_need_met_only_by_a_confirmed_document`: uploaded and unconfirmed → still provide.
  - `test_result_expected_before_provide_when_calendar_date_is_ahead` (R-20): the step is a blocked `result_expected` milestone due on the calendar date, cited from the fact URL. The provide step depends on it with no pull. After the date (today moved), the step is gone and the provide step stays. With the fact given, both are gone.
  - `test_fact_in_question_gets_which_is_right_not_provide` (R-21): the needing steps are blocked with `which_is_right`.
  - `test_impossible_value_is_a_question`: obtained 1200 of total 1100 → `which_is_right@fact:education.matric.marks_obtained:…`.
  - `test_mismatch_finding_blocks_steps_needing_those_documents`.
  - `test_same_state_same_draft`: two compiles give equal drafts, and the second `kernel.revise` returns None (Review Focus 1).
  - `test_needs_ignored_without_student_state`: the v2 plan with `student=None` equals the v1 plan without `school_certificates`.
  - `test_answered_waiting_step_closes_as_done` (D-w7): a provide step answered → `done`, cause `request_answered`; one removed for another reason → `cancelled`.
  - `test_waiting_step_gaining_a_t8_block_is_blocked`; `test_other_block_codes_keep_todays_rule` (flags-off guard).
  - `test_vault_event_for_a_need_key_recompiles_the_plan` (D-w8): a T4 delivery with `education.matric.marks_obtained` → a revision with cause `student_fact_changed`.
  - `test_document_confirm_refreshes_the_plan`.
  - `test_gate_off_selects_v1_and_records_no_playbook_newer` (D-w3).
  - `test_gate_on_records_playbook_newer_and_upgrade_is_a_proposal` (D-w2).
  - `test_worker_refuses_student_facts_without_fact_conflicts` (D-w1).
  - `test_eligibility_never_below_for_a_missing_value` (R-17): a v2 plan with no marks → programme cards say `needs_input` / `unknown`, never `likely_below`; a `student_fact_changed` without the value proposes no `CancelProgramme`.
  - **Flags-off proof:**
    - `tests/os/test_compiler.py`, `tests/os/test_golden.py`, `tests/os/test_kernel.py`, `tests/os/test_replan_rules.py`, `tests/os/test_student_fact_replan.py`, `tests/os/test_connect_t4_flow.py`, `tests/os/test_connect_t5_flow.py` and `tests/os/test_workers.py` pass unchanged;
    - `test_compile_without_student_is_todays_compile`: every golden input compiled with `student=None` gives exactly today's draft, field for field, with `answered == ()`.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/os -k "compile or needs or kernel or golden or replan or student_fact or workers"`, then `tach check`, the R-58 test and the kernel-write test.
- [ ] **Step 5: Commit** `feat(os): missing data becomes provide, result expected and which is right steps; dependent steps blocked (R-17, R-18, R-20, R-21)`.

### Task 3: One request per fact — the table, the kernel sync, the plan view, no ticking

**R-IDs:** R-19, R-18 ("closes only when that level is met"); §9.3 rule 7.

**Files:**
- Create:
  - `backend/alembic/versions_os/os_0023_student_requests.py` (D-w9). It is self-contained like `os_0020_vault_events.py`, and its downgrade drops the table.
  - `backend/app/os/requests/store.py`: `sync(conn, tenant_id, plan_id, answered=())`, `open_for(engine, tenant, student_ref)`, `for_plan(conn, tenant, plan_id)`, `get(engine, tenant, request_id)`, `duplicates(engine, tenant) -> list` (rule 7 check for T10).
  - `backend/app/os/requests/texts.py` and `texts.yaml` (D-w16). The loader requires every key and `approved: true`.
- Modify:
  - `backend/app/os/models.py`: the table `student_requests`.
  - `backend/app/os/kernel/kernel.py`: `create_plan` (:89-126), `_revise` (:502-559) and `close_plan` (:199-223) call `store.sync` (D-w7).
  - `backend/app/os/plan_view.py`:
    - `_steps` (:60-73) fills `needs` from the pinned playbook's template `needs` (the pin's key **and version**, :124-125) and, for generated steps, from `keys.parse`;
    - `build_plan_view` (:111-166) fills `requests` from `store.for_plan`, with the due date and time zone from the step.
  - `backend/app/os/inbox_actions.py` (:22-40): the `answer_required` refusal (D-w11).
  - `backend/app/os/api/router.py`: new `GET /requests` (D-w19, without `choices` until Task 4). `backend/app/os/api/schemas.py`: new `RequestsOut` (new model only).
- Tests:
  - new: `backend/tests/os/test_os_0023_migration.py`, `backend/tests/os/test_student_requests.py`;
  - extend: `tests/os/test_plan_view.py` (new cases; the T5 and T7 cases stay as they are), `tests/os/test_plan_actions.py` and `tests/os/test_api.py` (inbox cases; new cases only).

- [ ] **Step 1: Write the failing tests (`@pytest.mark.req("R-19")` unless noted).**
  - `test_os_0023_upgrade_downgrade`, and one OS head.
  - `test_unique_open_request_per_student_and_fact`: a second open insert raises `IntegrityError`; an answered row plus a new open row is fine.
  - `test_sync_opens_a_row_for_each_request_step`.
  - `test_level_change_closes_then_opens_in_one_transaction` (R-18): the stated row is `answered` and the shown row is `open`.
  - `test_plan_closed_cancels_its_requests`.
  - `test_second_plan_reuses_the_open_row`.
  - `test_concurrent_revisions_keep_one_open_row` (two threads, Review Focus 2).
  - `test_result_expected_has_no_row_and_its_provide_step_has_one` (R-20).
  - `test_plan_view_lists_requests_and_step_needs` (R-17): open and answered, with `need.evidence`; `steps[].needs` for the playbook steps and the generated steps; `blocked_reason == "awaiting_fact"`.
  - `test_request_step_cannot_be_ticked` (R-18): `inbox_actions.complete` raises `answer_required`, and so does the PlanActions port.
  - `test_get_requests_404_while_gate_off`.
  - `test_get_requests_lists_own_only` (tenant and student isolation).
  - `test_rows_hold_no_value`: no column holds a fact value.
  - `test_texts_all_approved_and_complete`.
  - **Flags-off proof:**
    - `tests/os/test_plan_view.py` (every T5 and T7 case), `tests/os/test_connect_t5_flow.py`, `tests/os/test_kernel.py` and `tests/os/test_plan_actions.py` and `tests/os/test_api.py` pass unchanged;
    - `test_flags_off_no_request_rows`: a full T5 flow with the gate off leaves `os_student_requests` empty, and the plan view has `needs == []` and `requests == []` on every step.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/os -k "request or plan_view or inbox or kernel or migration"`, then `tach check` and `check_alembic_heads.py`.
- [ ] **Step 5: Commit** `feat(os): one open request per fact, synced with the plan; shown in the plan view; never ticked by hand (R-19, R-18)`.

### Task 4: Conflicts from the Vault, the answer path, and the close hook

**R-IDs:** R-21, R-19 ("answering anywhere closes it everywhere"); row 6.21.

**Files:**
- Create:
  - `backend/app/os/contracts/fact_conflicts.py` and `fact_conflicts.v1.schema.json` (D-w12). Extend `tests/os/contracts/test_frozen_v2.py` with its hash, and `test_contracts_v2.py` with the samples.
  - `backend/app/pai_c/connect/fact_conflicts.py`:
    - `build(db, workspace_id) -> dict` (FactConflictsV1-valid). It covers open `ProfileIssue` with `issue_type == "conflicting_record"` and `affected_type` in (`education`, `test_attempt`), keys through `student_facts_keys.yaml` and `chosen_education` (`student_facts.py:85-99`), one entry per differing allow-listed key, and `answers` from the card (`VaultView`).
    - `answer(db, workspace_id, ref, key, choice, value) -> dict` (D-w13).
    - It does not import `app.os`.
  - `backend/app/pai_c/connect/request_texts.yaml` (D-w16), with a loader in `request_texts.py`.
- Modify:
  - `backend/app/os/ports/fact_questions.py` validates `FactConflictsV1`. A wrong `student_ref` → logged by class, `{}`. It adds `answer(...)` (sync, None when unconfigured).
  - `backend/app/os/requests/state.py` uses it.
  - `backend/app/os/api/router.py`: `GET /requests` gains `choices`; new `POST /requests/{id}/answer` (D-w13), with `AnswerIn` and `AnswerOut` in `schemas.py`.
  - `backend/app/os/api/mount.py` and `ports/__init__.py`: the keyword args `fact_conflicts=` and `fact_answer=`.
  - `backend/app/pai_os_bridge.py`:
    - `fact_conflicts(student_ref)` reads the plain `CONNECT_STUDENT_FACTS` flag in its own session, like `student_facts` (:489-505);
    - `answer_fact_question(student_ref, ref, key, choice, value)` checks `part_on("CONNECT_STUDENT_FACTS")` in its own session and commits.
  - `backend/app/main.py` (:479-484) passes both. `docker-compose.yml` (:186-188) sets `OS_FACT_CONFLICTS: app.pai_os_bridge:fact_conflicts` on the os-worker.
  - `backend/app/memory/profile_issues.py`: `register_close_hook` and the calls after `_close` (:222) (D-w14).
  - `backend/app/pai_c/connect/vault_version.py` gains `after_issue_closed`. `backend/app/capabilities/system.py` (:14-23) registers it.
- Tests:
  - new: `backend/tests/test_fact_conflicts.py` (SQLite, the Vault side alone), `backend/tests/os/test_which_is_right.py` (Postgres OS plus the app session);
  - extend: `tests/test_vault_reconcile.py` or `tests/test_vault_api.py` (the close hook only, new cases).

- [ ] **Step 1: Write the failing tests (`@pytest.mark.req("R-21")` unless noted).**
  - `test_contract_rejects_extra_and_needs_two_values`.
  - `test_document_vs_vault_card_becomes_one_conflict_per_key`: a T7 fact proposal of CGPA 3.2 against a stated 3.4 → one entry for `education.bachelor.gpa`, with the current value stated from chat and the proposed value shown with the `document_ref`.
  - `test_chat_correction_against_a_shown_record_is_a_conflict` (Ruling problems 5).
  - `test_profile_page_edit_is_not_a_conflict`.
  - `test_name_cards_never_cross`: a document-owner or identity card gives no entry.
  - `test_get_requests_shows_both_values_and_sources_live`.
  - `test_answer_proposed_resolves_the_card_and_closes_the_step`: the Vault holds 3.2 `user_explicit` with the evidence naming the request; the step is `done` and the row is `answered` before the response returns.
  - `test_answer_current_keeps_the_vault_value_and_closes_the_step`.
  - `test_answer_new_writes_the_typed_value`.
  - `test_impossible_value_answer_writes_through_the_reconciler`.
  - `test_finding_answer_uses_resolve_finding_and_never_the_vault` (Ruling problems 4).
  - `test_vault_page_keep_current_reaches_the_os` (R-19): resolve on `/v1/vault/conflicts/{id}/resolve` → the close hook bumps the version → a `vault_event` → the OS recompiles → the step is `done`.
  - `test_answer_twice_is_already_answered`, and `test_answer_for_a_closed_card_is_gone_and_closes`.
  - `test_answer_404_for_another_student_or_tenant`.
  - `test_answer_404_while_part_off`.
  - `test_close_hook_off_without_connect_student_facts` (flags-off guard).
  - **Flags-off proof:**
    - `tests/test_vault_reconcile.py`, `tests/test_vault_api.py`, `tests/test_vault_view.py`, `tests/test_pai_os_bridge.py`, `tests/test_document_facts.py`, `tests/os/test_fact_proposals.py` and `tests/os/test_vault_check.py` pass unchanged;
    - `test_flags_off_profile_issue_resolve_writes_no_vault_event`.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run:**
  1. the legacy files (`--ignore=tests/os`);
  2. then, separately, `tests/os -k "which_is_right or contracts or request or vault_check or fact_proposal"`;
  3. then `tach check` and `python scripts/check_freeze.py --base origin/pai-connect`.
- [ ] **Step 5: Commit** `feat(connect): Vault conflicts become which is right steps; the answer goes to the Vault from any screen (R-21, R-19)`.

### Task 5: The unanswered ladder

**R-IDs:** R-22; row 6.22.

**Files:**
- Modify:
  - `backend/app/os/workers/reminders.py` (:39-42): `document_missing` also for `which_is_right` request steps (D-w15 step 1).
  - `backend/app/os/replan/rules.py`:
    - `rules_for` `document_missing` (:113-117): the request-step branch of D-w15 steps 3 and 4;
    - `PlanState` gets `suggestions` for this event too (`replan/run.py:102-103` passes `with_suggestions` for `document_missing` on a request step);
    - the reasons come from `requests/texts.py`.
  - `backend/app/os/replan/run.py` (:102-103), as above.
- Tests:
  - extend: `tests/os/test_replan_rules.py` (new cases only), `tests/os/test_workers.py` (new cases only);
  - new: `backend/tests/os/test_unanswered_ladder.py` (Postgres, the rehearsal clock moved through the dates).

- [ ] **Step 1: Write the failing tests (`@pytest.mark.req("R-22")`).**
  - `test_request_step_gets_reminders_on_the_cadence` (rung 1): weekly, then every 3 days, then daily, one per slot.
  - `test_blocked_step_at_risk_nudges_the_request_first` (rung 2): `deadline_at_risk` on the needing step → `Reprioritise` and `RequestFromStudent` on the provide step, and an `os_event` `deadline_at_risk`.
  - `test_overdue_request_on_some_places_proposes_swap_or_drop` (rung 3, the ireland v2 `english_proof`): one place has a close match → `SwapProgramme`; the other has none → `CancelProgramme`; both are pending big proposals.
  - `test_overdue_request_on_every_place_escalates_blocking_gap` (rung 4): a route-level need → `Escalate` → a support case → the `CounsellorSink` outbox row has reason `blocking_gap`.
  - `test_ladder_never_leaves_fewer_than_min_programmes`.
  - `test_counsellor_plan_drop_becomes_a_choice_request` (T6 D-x2).
  - `test_overdue_which_is_right_enters_the_ladder`.
  - `test_plan_never_fails_silently`: for every open request step past its due date, after one `run_reminders` and one `run_replan_job`, there is a proposal or a support case naming its event.
  - `test_answer_after_proposal_leaves_the_proposal_to_the_student`: the request is answered, the needing steps unblock, and the pending proposal stays until the student answers it or it expires.
  - **Flags-off proof:**
    - `tests/os/test_replan_rules.py` (incl. `test_document_missing_requests_it` :86-91 and `test_document_missing_but_done_does_nothing` :92-95), `tests/os/test_workers.py` (`test_reminders_rerun_same_slot_no_new_rows` :116, `test_overdue_reminder_escalates` :133), `tests/os/test_replan_run.py` and `tests/os/test_counsellor_escalation.py` pass unchanged;
    - `replan_cases.yaml` replays give the same answers.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/os -k "replan or workers or ladder or escalation"`, then `tach check` and the R-58 test (no route terms in the rules: `test_no_route_terms_in_replan`).
- [ ] **Step 5: Commit** `feat(os): unanswered requests go reminders, at risk, a proposal, then an escalation (R-22)`.

### Task 6: Screens — the inbox, which is right, and the roadmap request line

**R-IDs:** R-19 (shown in the plan and the inbox), R-21 (both values with their sources), R-18 (how to answer at each level).

**Files:**
- Modify (backend, Counsellor side):
  - `backend/app/pai_c/roadmap/plan_adapter.py`:
    - `steps_of` (:100-114): `tickable` is false for a step with an open request (D-w11);
    - an additive `request: {kind, evidence, text}` on such a step, with `text` from `request_texts.yaml`, `provide_<level>` or `which_is_right`;
    - `result_expected` steps get `request: {kind: "result_expected", text}`.
    - Steps without a request are unchanged (R-44).
- Modify (frontend):
  - `frontend/lib/api.ts`: `getOsRequests()` (404 → `null`) and `answerOsRequest(id, choice, value?)`.
  - `frontend/lib/os-inbox.ts` (:186-204): `completeActions` returns `[]` for an item that has a request; `actionHint` returns the request's `how`.
  - `frontend/components/os/inbox-list.tsx` (:76-190): a request item shows `how`. A which-is-right item renders `choices` as buttons (label, value, source line: kind, level, date) and, with `allow_new`, a value field. An answer calls `answerOsRequest`, then reloads the inbox.
  - `frontend/app/[workspaceId]/(os)/os-inbox/page.tsx` fetches the requests once with the inbox.
  - `frontend/components/counselor/workspace/roadmap-steps.tsx` shows `step.request.text` under the step. `frontend/lib/roadmap.ts` types `request?`.
  - `copy.json` gets only `connect.requests.*` labels that have no backend text (for example the answer button "Use this value").
  - Fixtures: `frontend/tests/fixtures/counselor.ts`, `frontend/tests/preview/fake-api.ts`.
- Tests:
  - extend: `components/os/inbox-list.test.tsx`, `components/counselor/workspace/roadmap.test.tsx`, `tests/test_connect_flags_off.py` (new case);
  - new: `backend/tests/test_plan_adapter_requests.py`.

- [ ] **Step 1: Write the failing tests (`// req: R-19`, `R-21`, `R-18`; Python `@pytest.mark.req`).**
  - `request item shows how and no Mark as done`.
  - `which is right shows both values with sources and answers`.
  - `typing a new value sends choice new`.
  - `no requests endpoint means today's inbox` (404).
  - `roadmap shows the request line and no tick`.
  - Python `test_adapter_step_with_open_request_not_tickable`, and `test_adapter_adds_request_key_only_on_request_steps`.
  - **Flags-off proof:**
    - every existing test in these files passes unchanged;
    - `tests/test_connect_flags_off.py` `test_roadmap_and_steps_are_byte_identical_to_the_pre_adapter_answers` (:135) and `test_t6_roadmap_paused_unchanged` (:222) pass unchanged;
    - new `test_t8_roadmap_and_inbox_unchanged`, compared with fixtures captured before the change;
    - the `copy.json`/`roadmap.json` equality test passes.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the legacy files, then `npm test`, then `npm run build`.
- [ ] **Step 5: Commit** `feat(connect): requests on the inbox and the roadmap; which is right shows both values (R-19, R-21, R-18)`.

### Task 7: Scripted flow and traceability

**R-IDs:** R-17, R-18, R-19, R-20, R-21, R-22; rows 6.19, 6.21, 6.22 (6.20: the mechanism, with a test calendar).

**Files:**
- Create: `backend/tests/os/test_connect_t8_flow.py`. It follows `test_connect_t5_flow.py`:
  - the `world` fixture (:34-53), with `CONNECT_STUDENT_FACTS`, `CONNECT_ONE_UPLOAD`, `CONNECT_HANDOFF` and `CONNECT_ROADMAP_FROM_PLANVIEW` on;
  - `run_os` (:55) and `no_chat()`;
  - `test_connect_t4_flow.py` `run_rules` for the replan;
  - the T7 flow's offline reader and sample documents;
  - the reconcile job run inline;
  - the playbooks `{FAKE_DIR, FAKE_DIR/needs, PLAYBOOK_DIR}`;
  - the seed `needs_seed.yaml`.
- Modify: `docs/requirements/connection.yaml` (:45-50).

- [ ] **Step 1: Flow test (fictional students; Germany master's and the fake routes).** In order:
  1. **6.19, Germany v2.**
     1. Choose with 2 places → planned on v2.
     2. `provide@document:transcript:shown`, `…ssc_certificate…` and `…hssc_certificate…` are waiting. Both apply steps are blocked with `awaiting_fact`, and the provide steps are dated from them.
     3. Three request rows are open. `plan_view.requests` has 3 open. The roadmap shows the request lines, not tickable. The inbox lists them. One reminder is written per step. A `student_needed` os_event exists.
  2. **R-18 and R-19, fake PK intermediate v2.**
     1. Before the calendar date → `result_expected@fact:education.matric.marks_obtained` (due on the test calendar date), then a pending provide step with an open row (R-20).
     2. Move the clock past the date → the provide step waits.
     3. The student types the marks in chat (the Vault, stated) → `vault_event` → recompile → the stated step is `done`, its row is `answered`, and `admission_form` is unblocked. A `…:shown` step and row are open, and `merit_list` stays blocked. There is still exactly one open row for the fact.
     4. Upload and confirm the SSC certificate (T7) → the Vault holds the fact as shown → the shown step is `done`, and `merit_list` is ready.
  3. **6.21, Germany.**
     1. The student said CGPA 3.4 in chat.
     2. The transcript confirm proposes 3.2 → a Vault card → a `which_is_right` step. The apply steps are paused (blocked `which_is_right`). `GET /v1/os/requests` shows 3.4 (chat, stated) and 3.2 (document, shown).
     3. Answer `proposed` → the Vault holds 3.2 (explicit, with the request in the evidence), the step is `done`, the row is `answered`, and the steps resume.
     4. **Second student:** answer `current` on the Vault page instead → the close hook → the OS step is `done` within the same delivery.
  4. **Impossible value.** Fake PK BS: intermediate marks 1200 of 1100 → `which_is_right`. Answer `new` 1000 → the Vault is updated, the step is `done`.
  5. **6.22, the fake Ireland v2.**
     1. No IELTS → the clock moves through the cadence: reminders, then `deadline_at_risk`.
     2. At the due date, the one place with `english_proof` gets a proposal (swap, or drop when there is no close match). Accept → T6 `choice_request` → v n+1 without that place → revised.
     3. Then a route-level `transcript` request goes unanswered → `Escalate` with `blocking_gap` → the plan is paused → the journey is back to choosing (T6). The test also checks that `test_plan_never_fails_silently`'s rule holds.
  6. **Upgrade.** A v1 Germany plan started with the gate off. Turn the gate on → one `UpgradePlaybook` proposal. Accept → pinned v2, and the provide steps appear.
  7. **Gate off (standalone and flags off).** The same Germany choice → v1, no request rows, `plan_view` `needs == []` and `requests == []`, `GET /v1/os/requests` 404, and the inbox and roadmap are byte-identical to the T5 flow.
  8. Throughout:
     - no chat message is created (`no_chat()`);
     - `store.duplicates()` is empty (§9.3 rule 7);
     - every `os_student_requests` row has no value column.
- [ ] **Step 2: Traceability.**
  - Set `built: true` for R-17, R-18, R-19, R-20 (the mechanism; D-w18), R-21 and R-22.
  - Run `python scripts/check_traceability.py`.
- [ ] **Step 3: Full checks, one after the other.**
  - The legacy suite (`env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider --ignore=tests/os`), then `tests/os` (with `OS_TEST_DATABASE_URL` exported in the shell only).
  - `npm test`, then `npm run build`.
  - `tach check`, `python scripts/check_freeze.py --base origin/pai-connect`, `backend/scripts/check_alembic_heads.py`.
  - Report the counts.
- [ ] **Step 4: Commit** `test(connect): T8 flow test; R-17, R-18, R-19, R-20, R-21, R-22 built`.

## Owner rulings (2026-11-06, in chat)
- **Ruling problem 10:** approved. The Germany v2 playbook replaces the manual `school_certificates` step with document needs, so there is no duplicate upload step.
- **Ruling problem 11:** for a missing document, the unanswered ladder ends at a proposal plus a support case for a person: reminders → at risk → proposal → support case. It does NOT escalate the student back to choosing. Other missing facts follow the same rule unless the plan says otherwise. Task 5 must implement and test this.
- **Ruling problem 12:** approved. Running v1 plans get the needs only through the explicit upgrade proposal, never silently.
