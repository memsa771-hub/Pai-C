# P1-T6: proposals, adoption, the OS builder via the decision service, escalations ×5 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a Counsellor plan, the OS never changes the choice (R-07). A choice change the student accepts goes to the Counsellor as a `choice_request.v1`. The decision service writes version n+1 only while the base choice is still current; otherwise the proposal becomes `expired`. A self-serve plan is adopted, not refused, when the student agrees (R-08). With the Counsellor on, the OS route builder writes through the decision service; with it off, the builder works standalone as today (R-09). Escalations carry all five reasons. The plan pauses, and the student is taken back to choosing with the reason (R-11).

**Architecture:**
- **OS side.**
  - A new port, `ports/choice_requests.py`, writes `choice_request` rows to the OS `counsellor` outbox channel. Each row is written in the same OS transaction as the proposal's new status `requested`.
  - The host configures two callables on that port. `enabled()` tells the OS whether the host part is on. `on_request(key)` is the post-commit hook.
  - A second port, `ports/choice_sink.py`, is a synchronous host callback for the builder's start.
  - A new kernel method `adopt_plan` and an adoption intent table support adoption.
  - The plan is paused through a port that the host calls.
- **Host side, in `backend/app/pai_os_bridge.py`.** The bridge delivers `choice_request` rows to `RouteDecisionService.apply_choice_request`, which it imports lazily. It marks each outcome back on the OS side. It sends all five escalation reasons when `CONNECT_HANDOFF` is on.
- **Counsellor side.**
  - The decision service gains `apply_choice_request`, `request_from_builder` and `adopt`.
  - The escalation endpoint takes all five reasons.
  - Student sentences live in Counsellor and OS data files marked `approved: false`.
- **Frontend.** Shows the new proposal states, the escalation reason on the roadmap plan banner, and the adoption offer on `plan-card.tsx`.

**Tech Stack:** Python 3.13, SQLAlchemy (app ORM, OS Core), Alembic (two trees), DBOS worker, Next.js, pytest/vitest.

**Spec:** `docs/superpowers/specs/2026-11-04-p1-connection-core-design.md` §3.7, P1-D3, P1-D9, P1-D11, P1-D12. Master: R-07, R-08, R-09, R-11 (R-22 touched); §6 rows 6.5, 6.6, 6.12, 6.13, 6.16, 6.17.
- **Code map:** the session scratchpad `p1-t6-explore.md`. All file:line references below come from it and were re-checked on `pc/p1-t6-proposals`.
- **Controller rulings:** `p1-t6-decisions.md` (Q1–Q12). Both files are carried into the SDD workspace.

## Global Constraints

- **Flags off means today, byte for byte.**
  - Every new backend path needs two things: the OS `counsellor` module, and `part_on("CONNECT_HANDOFF")` (ruling 5). The adoption offer in the UI also needs `part_on("CONNECT_MY_PLAN")`. No new flag is added.
  - The OS cannot read host flags. It learns the host part through the `enabled()` callable the host configures on the `choice_requests` and `choice_sink` ports.
    - An unconfigured port (the worker, the standalone tests, the OS without a host) reads as off.
    - So the code takes today's path whenever any part is missing.
  - Each task names the tests that prove the flags-off behaviour. Those tests already exist and must pass **unchanged**. Where a task extends `tests/test_connect_flags_off.py`, it compares against fixtures captured from the current code before any change.
- **Frozen.**
  - Contracts `choice_request.v1`, `decision_record.v2`, `escalation.v2`, `plan_view.v1` and `os_event.v1` are used as they are (hash tests in `tests/os/contracts/test_frozen_v2.py`).
  - Also frozen, and never touched:
    - `pai_c/policy/*.json`, `roadmap.json`, `pai_c/**/*.md`, `deep/**` and `docs/counselor/COUNSELOR_V3_PROMPTS.md`;
    - the model settings in `app/config.py`.
  - The chat never says anything new. "Back to choosing" is shown only by the stage, the roadmap and the bell (`deep/context.py` reads the stage only).
- **Imports, names and checks.**
  - `app/os` never imports Counsellor code (Tach). All glue lives in `backend/app/pai_os_bridge.py`.
  - The bridge imports `RouteDecisionService` and `routers.escalations` lazily, inside functions. `pai_c/roadmap/decisions.py:19` imports the bridge at module level.
  - No country, institution, exam or qualification names in `app/os` Python (R-58, `tests/os/test_invariants.py:15-19,72-80`). OS YAML stays generic too.
  - Only the kernel changes plans and tasks.
  - DB changes go only through Alembic:
    - OS tree `backend/alembic/versions_os/` (head `os_0020`, `os_0020_vault_events.py`);
    - Counsellor tree `backend/alembic/versions/` (head `126_vault_versions.py`);
    - one head each.
- **No free text crosses (P1-D12).**
  - `choice_request` carries IDs and codes only, with no reason field.
  - Proposal and Supervisor `reason` strings stay in the OS UI.
  - The Counsellor shows only reason codes and its own fixed sentences.
- **Every new student-facing sentence is marked "OWNER approval, stored approved:false".**
  - It lives in a data file with `approved: false`, never in code.
  - The P1-D3 pattern applies: while a file is not approved, its sentences are returned only in rehearsal and tests, otherwise `null`.
    - Counsellor side: approved, or the existing `CONNECT_CONSENT_DRAFT`.
    - OS side: approved, or `settings.rehearsal`.
- **Process.**
  - Run `tach check` and `pytest tests/os` before pushing OS code. Never run them alongside the legacy suite (shared Postgres).
  - Never weaken a test. A test whose expectation changes on purpose is named in the commit message with the reason.
  - Tag tests with `@pytest.mark.req("R-xx")` or `// req: R-xx`. Commit messages end with the session attribution lines.
  - Fictional students only. No live model calls.

## Decisions taken in this plan (within the rulings; flagged to the owner in the PR)

- **D-x1, where the proposal stores its base and its outcome.** OS migration `os_0021` makes these changes to `os_proposals`:
  - widens `ck_os_proposals_status` with `requested`;
  - widens `ck_os_proposals_source` with `student`, for the builder's swap and remove (ruling 2: `choice_request.v1` needs a `proposal_id`);
  - adds `base_decision_version INT NULL`, set at creation for Counsellor plans;
  - adds `requested_version INT NULL`, the n+1 the Counsellor wrote;
  - adds `request_outcome TEXT NULL`, constrained to `written`, `duplicate`, `stale` or `refused`.

  For a proposal made before the migration, `base_decision_version` is NULL. It falls back to the plan's newest applied version at accept time. The accept's contract-SHA check (`apply.py:360`) has already proven that the plan is unchanged since the proposal.
- **D-x2, mixed proposals.** On a Counsellor plan with the host part on, `swap_programme` and `cancel_programme` become one `choice_request`. The other ops of the same proposal (tasks, nudges, escalate, upgrade) still apply at accept time through today's `apply` path, with the choice ops filtered out.
  - The proposal becomes `requested`, with the revision of those other ops if there was one.
  - It becomes `accepted` when the OS intake applies n+1 (ruling 4).
  - A request that would leave zero places is not sent (`choice_request.py:2`, R-22). The proposal becomes `refused`, and a support case is opened through `Replanner.support`.
- **D-x3, settling.** A `requested` proposal becomes `accepted` in two places, whichever comes first. Both writes are idempotent `UPDATE … WHERE status='requested'`.
  - In `intake.process`, after it applies a version ≥ `requested_version` to the plan.
  - In `mark_delivery`, if that version is already applied.

  A withdrawal or a closed plan makes the request `expired` (`request_outcome` stays as delivered). A decision service `stale` or `refused` answer also makes it `expired` (ruling 3), with `request_outcome` saying which. The student sees `expired` either way.
- **D-x4, "chosen field" (rulings 6a and 8).** The student's chosen field is the field of the **active** `RouteDecision`. With no active decision, the builder answers 409 `choose_field_first` and adoption offers "choose your field in PAI first".
  - The new version copies these columns from the active row: `field_key`, `possibility_id`, `title`, `verdict`, `route`, `steps`, `steps_done`, `chosen_at`, and every consent column (`_COPIED`, `decisions.py:240-242`).
  - It takes `origin_country`, `destination_country`, `level`, `places` and `intake` from the request.
  - `path_ref` is kept when the destination and level are unchanged; otherwise it is `None`.
  - `os_supported` comes from `pai_os_bridge.route_supported`.
- **D-x5, the request key (ruling "repeat delivery never writes n+2").** Counsellor migration `127_route_decision_request_key.py` adds `pai_route_decisions.request_key TEXT NULL`, with a partial unique index `(workspace_id, request_key) WHERE request_key IS NOT NULL`.
  - The keys are `choice_request:{proposal_id}`, `builder:{sha256 of route, intake and places}` and `adopt:{plan_id}:{contract_sha256}`.
  - The idempotence lookup runs **before** the stale check. Otherwise a re-delivery after n+1 would read as stale.
  - `request_key` is not in `_COPIED`, so a consent copy never carries it.
- **D-x6, adoption without `adopts_plan_id` (ruling 6e cannot be built as worded; see "Ruling problems" below).** `decision_record.v2` is frozen with `extra="forbid"`, so a decision cannot carry `adopts_plan_id`. The student's agreement is recorded on the OS side instead.
  - Migration `os_0021` adds a table `os_plan_adoptions`: `tenant_id`, `student_ref`, `plan_id` (FK), `contract_sha256`, `requested_at`, `adopted_at` NULL, unique `(tenant_id, plan_id)`.
  - The intent row is written through `plan_source.request_adoption` **before** the app transaction commits the new version.
  - Intake adopts only when four things hold:
    1. an intent exists for the student's open self-serve plan;
    2. that plan's `contract_sha256` still equals the intent's;
    3. the decision's route, programmes in order and intake equal the plan contract's;
    4. no other plan holds `(tenant, "counsellor", external_ref)`.

    Otherwise intake refuses with `self_serve_plan_open`, as today (`intake.py:173-175`).
  - An orphan intent (the app transaction failed) is harmless. It adopts only a decision equal to what the student agreed to.
- **D-x7, the escalation pause is triggered by the host (ruling 9 under ruling 5).**
  - After `escalate()` succeeds with `CONNECT_HANDOFF` on, the bridge calls a new port, `plan_source.pause_for_escalation(student_ref, decision_version, reason)`.
  - The port calls `kernel.pause_plan(plan_id, reason)` (`kernel.py:191`) on the student's open Counsellor plan.
  - With the part off, nothing is paused, as today.
- **D-x8, lifting an escalation pause.**
  - Today intake resumes any paused plan on any revise (`intake.py:~183`). That would let a consent-only copy un-pause an escalation.
  - A plan paused with an escalation reason code (read from the newest `plan_paused` event) is resumed only by a decision whose contract choice differs from the stored contract: places, order, intake, destination or level. This follows rulings 3 and 9.
  - A `consent_missing` pause resumes as today.
- **D-x9, the journey after an escalation (ruling 9).** With the part on, the endpoint works whenever an active decision exists (`decisions.py:164`).
  - It moves `CHOSEN → PROPOSED` (`stages.py` TRANSITIONS allow it). Every other stage is left unchanged.
  - It always appends `{"kind":"route_escalation", reason_type, details, previous_stage, decision_version, at}`.
  - `follow_active` (`decisions.py:116`, called from `journey_sync.py:57`) does not move PROPOSED → CHOSEN while the newest route entry is a `route_escalation` whose `decision_version` ≥ the active row's version. Legacy entries have no `decision_version`, so legacy flows are unchanged.
  - The decision is not withdrawn.
  - **Correction (Task 4 review).** The literal "version ≥ the active row's version" assumed that versions advance only on a choice. A consent copy also writes a version, which would lift the guard and bounce the stage. The guard holds CHOSEN back while the newest route entry is an escalation with a non-null `decision_version` and either that version ≥ the active version, or the row at that version has the same choice (route, places in order, intake) as the active row. A written choice request with new places ends it. The endpoint also answers 409 for an escalation whose version is above the active one or whose choice differs from the active choice.
- **D-x10, the 202 answers.** These are new response shapes. With the module or the part off, the routes return exactly today's status codes and bodies.
  - `POST /v1/os/plans/self` on the connected path returns 202 `{state:"preparing", decision_version}`.
  - Builder swap and remove on a Counsellor plan return 202 `{state:"requested", proposal_id}`.
  - `POST /v1/os/proposals/{id}/accept` returns `{status:"requested", revision}`.

## Ruling problems found (reported to the controller)

1. **Ruling 6e ("the decision carries `adopts_plan_id`") is impossible.** `DecisionRecordV2` is frozen: `extra="forbid"`, and it is hash-pinned in `tests/os/contracts/test_frozen_v2.py:50`. A new field would need a `decision_record.v3`. This plan uses D-x6 instead: an OS adoption intent plus an equality check. The kernel method `adopt_plan(plan_id, external_ref, contract)` is kept as ruled.
2. **Ruling 2 (builder swap/remove → `choice_request`) needs two things the rulings do not mention.** `ChoiceRequestV1.proposal_id` is a required `int`, and `ck_os_proposals_source` (`os_0012:50`) allows only `rules` and `supervisor`. So this plan adds a proposal source `student` in `os_0021` (D-x1).
3. **Ruling 5 cannot be enforced inside the OS.** The OS cannot read host flags, and the worker has no host. The OS gate is therefore host-configured (`enabled()`), and the pause is host-triggered (D-x7).
   - Ruling 10 also replaces `EscalationV1` with `EscalationV2` on the channel whenever the module is on. With the module on and `CONNECT_HANDOFF` off, the stored outbox payload bytes therefore differ. The behaviour does not: the bridge sends today's `EscalationInput`.
   - "Byte-identical" is proven by two facts:
     - module off → no row;
     - part off → the same endpoint call and result.
4. **Ruling 9 conflicts with today's intake resume and with `follow_active`.**
   - Today intake resumes any paused plan on any revise, so a consent copy would undo the pause.
   - Stage sync would bounce PROPOSED → CHOSEN, because the decision stays active.

   D-x8 and D-x9 settle both. Please confirm.
5. **The spec and ruling 10 disagree on the student text.** §3.7 says to show the reason "with the existing fixed OS sentences (notes.yaml)". Ruling 10 replaces them with new student sentences. This plan follows ruling 10 and marks them OWNER.
6. **The text gate.** Ruling 5 forbids new flags, so unapproved T6 Counsellor sentences reuse `CONNECT_CONSENT_DRAFT` as the rehearsal switch. OS sentences use `settings.rehearsal`. Please confirm this reuse.

## Review Focus

1. **A choice_request is delivered twice, or the bridge crashes between the app commit and the OS mark.**
   - No n+2 is written. The second delivery answers `duplicate` with the same version, and the proposal ends `accepted` once.
   - → Task 3 test.
2. **A consent copy lands between the proposal and its delivery.**
   - The request still writes n+2 on the newest choice and is not expired, because the choice is unchanged (ruling 3).
   - A real choice change in between makes it `expired`.
   - → Task 3 test.
3. **The escalation flow.**
   - The plan stays paused after a consent copy and after an identical re-choice.
   - A changed choice resumes it (D-x8).
   - Stage sync does not bounce the journey back to CHOSEN (D-x9).
   - → Task 4 test.
4. **Adoption with a closed Counsellor plan of the same external_ref.**
   - `uq_os_plans_identity` holds. Intake refuses as today, and nothing half-adopts.
   - → Task 6 test.
5. **Module on and `CONNECT_HANDOFF` off.**
   - Accept, builder start, swap and remove, and escalations behave exactly as today.
   - → the flags-off tests named in every task.

---

### Task 1: OS migration, proposal store and EscalationV2 on the channel

**R-IDs:** R-07 (store), R-08 (intent table), R-11 (v2 payload).

**Files:**
- Create: `backend/alembic/versions_os/os_0021_choice_requests.py`. It is self-contained like `os_0020_vault_events.py`:
  - drop and recreate `ck_os_proposals_status` with `requested`, and `ck_os_proposals_source` with `student`;
  - add the columns `base_decision_version`, `requested_version` and `request_outcome`, with a check;
  - create table `os_plan_adoptions` (D-x6);
  - write a downgrade that reverses all of it.
- Modify:
  - `backend/app/os/models.py`: `PROPOSAL_STATUSES` (:538) gains `requested`; `proposals` (:545-572) gains the columns and the source `student`; new table `plan_adoptions`.
  - `backend/app/os/replan/store.py`:
    - `Proposal` and `_proposal` (:58) carry the new columns;
    - `create` (:72) takes `base_decision_version`;
    - new `request(conn, proposal_id, revision)` sets `requested` on the caller's connection;
    - new `settle_requested(plan_id, applied_version, revision)`;
    - new `expire_requested(proposal_id, outcome)`;
    - new `set_requested_version(proposal_id, version, outcome)`;
    - `set_status` (:109) stamps `answered_at` for `requested` too.
  - `backend/app/os/adapters/counsellor/escalation.py`:
    - `_payload` (:62) builds `EscalationV2`, with `decision_version` = the plan's max applied intake version (the same query as `ports/os_events.py:35`);
    - `intake_refused` (:105) uses the intake's own `decision_version`.
  - `backend/app/os/ports/escalation.py`: `pending_counsellor_escalations` (:21-30) validates v2, and an older stored v1 row is read as v2 with `decision_version=None`; the return type is `EscalationV2`.
- Tests:
  - new: `backend/tests/os/test_os_0021_migration.py`, `backend/tests/os/test_proposal_request_store.py`;
  - extend: `tests/os/test_counsellor_escalation.py` (payload schema, named in the commit), `tests/os/test_escalation_port.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_os_0021_upgrade_downgrade` (R-07): run `alembic upgrade os@head`, then `downgrade os_0020`, then `upgrade` again.
    - A `requested` and a `student` row insert after the upgrade.
    - The same insert raises `IntegrityError` at `os_0020`.
    - `backend/scripts/check_alembic_heads.py` reports one OS head.
  - `test_request_sets_status_on_callers_connection`: inside a rolled-back `engine.begin()`, the status is still `pending` afterwards.
  - `test_settle_requested_only_moves_requested`:
    - `requested`, with `requested_version=4` and applied 4 → `accepted`, with the revision stored;
    - applied 3 → unchanged;
    - `pending` → unchanged;
    - a second call → no change, rowcount 0.
  - `test_expire_requested_records_outcome`: `stale` → `status == "expired"`, `request_outcome == "stale"`, `answered_at` set.
  - `test_counsellor_payload_is_escalation_v2` (R-11): `schema == "pai.escalation.v2"`, and `decision_version` equals the plan's newest applied intake version. An intake refusal carries the intake's version.
  - `test_pending_reads_stored_v1_rows`: a v1 row already in `os_outbox` is returned as v2 with `decision_version is None`.
  - **Flags-off proof:** `tests/os/test_api_replan.py`, `tests/os/test_replan_store.py`, `tests/os/test_replan_run.py` and `tests/test_pai_os_bridge.py` pass unchanged. The bridge reads only `reason`, `note`, `journey_id` and `student_ref` while the part is off.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new files, then `tests/os -k "replan or escalation or migration"`, then `tach check`.
- [ ] **Step 5: Commit** `feat(os): proposal status requested, adoption intents, escalation v2 on the counsellor channel (R-07, R-08, R-11)`.

### Task 2: `choice_request` on accept and on the builder's swap/remove, plus the post-commit hook port

**R-IDs:** R-07; rows 6.5, 6.6 (the OS half).

**Files:**
- Create: `backend/app/os/ports/choice_requests.py`. It mirrors `ports/os_events.py`:
  - `configure(enabled: Callable[[], bool] | None, on_request: Callable[[str], None] | None)`;
  - `enabled() -> bool` (False when unconfigured or on any exception);
  - `applies(conn, tenant_id, plan_id) -> bool` (module enabled, `plan.source == "counsellor"`, and `enabled()`);
  - `emit(conn, tenant_id, plan_id, proposal_id, base_version, programmes, at) -> bool`. It writes the channel `counsellor`, template `choice_request`, key `choice_request:{proposal_id}`, payload `ChoiceRequestV1` (`journey_id` from `adapters.counsellor.escalation.journey_of` logic, re-implemented locally with no import across the adapter), with `on_conflict_do_nothing(uq_os_outbox_key)`;
  - `pending(limit=100) -> list[ChoiceRequestV1]`, filtered on the template;
  - `notify(key)`. It calls `on_request` and swallows any exception, logging the class name only. The sweep is the backup (ruling 12).
- Create: `backend/app/os/replan/choice_texts.yaml`. Keys `requested` and `expired`, plus `version`, `approved: false`. — **OWNER approval, stored approved:false.** Plus a loader `backend/app/os/replan/choice_texts.py` with `note(key, settings) -> str | None`. It returns `None` unless the file is approved or `settings.rehearsal`.
- Modify:
  - `backend/app/os/ports/__init__.py` `configure` (:23-32) and `backend/app/os/api/mount.py` `mount_os` (:32-72): new keyword args `choice_enabled=` and `on_choice_request=`. Both default to None, and a None leaves today's behaviour.
  - `backend/app/os/replan/apply.py`:
    - `_decide` (:243-246) passes `base_decision_version` for Counsellor plans;
    - `accept` (:350-372): after today's checks, if `choice_requests.applies(...)` and the ops hold a `SwapProgramme` or a `CancelProgramme`, it applies the other ops through `apply` with the choice ops filtered out (D-x2);
    - a new parameter on `apply` (:~260): `ops_filter`;
    - it computes the new place list from the current contract (swap in place, cancel then re-rank 1..n);
    - with zero places → `refused` plus `self.support(...)`;
    - otherwise, in one `engine.begin()`: `proposals.request(conn, …)` + `choice_requests.emit(conn, …)`;
    - it returns the revision. The direct `_swap` (:322-335) and the `cancel_programme` override (`ops.py:116`) are not reached on this path.
  - `backend/app/os/api/replan.py` `answer` (:98-110): returns `{"status": "requested", …}` when the proposal is `requested`, then calls `choice_requests.notify(key)` after the plan lock is released. `proposal_out` (:43) adds `status_note` (from `choice_texts`) and `request_outcome`. `student_proposals` (:48) also lists the student's `requested` proposals, and those `expired` with a `request_outcome` in the last 7 days.
  - `backend/app/os/routes/builder.py` `swap` (:122) and `remove` (:156): on a Counsellor plan where `applies(...)` holds, they run the same checks as today (`_not_started`, `_within_limit`, the last-place rule). Then they create a proposal: source `student`, `big=True`, ops `[SwapProgramme]` / `[CancelProgramme]`, `base_decision_version`, status `requested`. They emit in the same transaction and return `("requested", proposal_id)` instead of calling `plans.change_programmes`.
  - `backend/app/os/api/router.py` `_change` (:311-318) and the swap and remove routes (:320-328): for `("requested", id)` they return a `JSONResponse(202, {"state":"requested","proposal_id": id})`, then `notify`.
  - `backend/app/os/api/schemas.py`: the proposal out schema gains the optional `status_note` and `request_outcome`.
- Tests:
  - new: `backend/tests/os/test_choice_request_emit.py`. It is built on the `svc` fixture of `tests/os/test_counsellor_intake_v2.py:33-44`, with a Counsellor plan from `intake.process`, and `test_connect_t4_flow.py` `run_rules` for a real pending `CancelProgramme`.
  - extend: `tests/os/test_api_replan.py` (new cases only).

- [ ] **Step 1: Write the failing tests (R-07).**
  - `test_accept_on_counsellor_plan_writes_choice_request_not_contract`:
    - the plan's `contract_sha256` is unchanged;
    - the proposal is `requested`;
    - exactly one outbox row exists, with template `choice_request` and key `choice_request:{id}`;
    - the payload validates as `ChoiceRequestV1`;
    - `based_on_version` equals the proposal's `base_decision_version`;
    - `programmes` is the swapped list, with ranks 1..n.
  - `test_cancel_programme_request_drops_and_reranks`: after the drop, the ranks are `[1..n-1]`, and no row is written to `os_plan_overrides`.
  - `test_request_and_status_share_one_transaction`: kill `emit` with an exception → the proposal is still `pending`, and there is no outbox row.
  - `test_accept_twice_is_stale`: the second accept → 409 and no second row.
  - `test_mixed_proposal_applies_other_ops_now` (D-x2): an `add_task` op applies with a revision. Only the swap goes into the request.
  - `test_zero_places_is_refused_with_support_case` (R-22).
  - `test_builder_swap_on_counsellor_plan_is_a_request`: a 202 body, a proposal with source `student` and status `requested`, and the contract unchanged.
  - `test_builder_remove_last_place_still_refused`: 409, as today.
  - `test_notify_called_after_commit_and_errors_swallowed`: a hook that raises → the accept still returns 200.
  - `test_status_note_hidden_until_approved`: `status_note is None` with `approved: false` and rehearsal off. With rehearsal on, it is the YAML sentence.
  - **Flags-off proof:**
    - `test_self_serve_plan_accept_unchanged`, and `test_unconfigured_port_keeps_direct_edit` (module on, `enabled` unconfigured, Counsellor plan) → the contract is swapped as today, and the status is `accepted`.
    - `test_module_off_no_choice_request_rows`.
    - Existing files pass unchanged: `tests/os/test_api_replan.py`, `tests/os/test_route_builder.py`, `tests/os/test_api_self_serve.py`, `tests/os/test_replan_*.py`, `tests/os/test_connect_t4_flow.py`.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file, then `tests/os -k "replan or builder or self_serve or proposal"`, then `tach check`, then the R-58 test.
- [ ] **Step 5: Commit** `feat(os): an accepted choice change on a Counsellor plan becomes a choice_request (R-07)`.

### Task 3: Delivery to the decision service — stale check, idempotence, status back

**R-IDs:** R-07; row 6.6 ("same version both sides").

**Files:**
- Create: `backend/alembic/versions/127_route_decision_request_key.py`. It adds the column `request_key` and the partial unique index `uq_route_decision_request_key` (with `postgresql_where` and `sqlite_where`). The downgrade drops both.
- Modify:
  - `backend/app/models.py` `RouteDecision` (:779-805): gains `request_key`.
  - `backend/app/pai_c/roadmap/decisions.py`: new `apply_choice_request(workspace_id, request: dict) -> tuple[str, int | None]`.
    - It takes `_lock` (:168).
    - **First** the idempotence check: a row with `request_key == request["key"]` → `("duplicate", its version)`.
    - Then the stale check (ruling 3). It compares `newest()` (:179) with the row at `based_on_version` on places (refs and order), intake, destination, level and `field_key`. A missing base, a `withdrawn` newest row, or any difference → `("stale", None)`.
    - Otherwise it copies the active row like `update_consent` (:244-270), with `places` and/or `intake` replaced, `request_key` set and the version n+1, then calls `outbox.record(db, new)` (not `consent_only`) and returns `("written", n+1)`.
    - It makes no journey change, no possibility change and no check-in change (like `update_consent`).
    - Refusals return `("refused", code)`, with codes `no_decision` and `not_supported`.
  - `backend/app/os/ports/choice_requests.py`: new `mark_delivery(key, outcome, version=None)`.
    - `written` or `duplicate` → `set_requested_version`, then settles at once if the plan already applied that version (D-x3).
    - `stale` or `refused` → `expire_requested(outcome)`.
    - The outbox row is set to `sent`.
  - `backend/app/os/adapters/counsellor/intake.py` `process` (:181-191): after `_revise` or `start_plan` on a Counsellor plan, it calls `ProposalStore.settle_requested(plan_id, decision.decision_version, revision)`. `_withdraw` and the close in `others` expire the plan's `requested` proposals.
  - `backend/app/pai_os_bridge.py`:
    - new `deliver_choice_requests(db) -> dict`. For each `pending()` row it calls `RouteDecisionService(db).apply_choice_request(...)`, then `db.commit()`, then `deliver_pending(db, ws)` (:47), then `mark_delivery`. An exception rolls back and leaves the row pending.
    - new `deliver_choice_request_now(key)`, which opens its own session like `recipient_email` (:263).
    - new `choice_enabled() -> bool` = `part_on("CONNECT_HANDOFF")`.
    - `sweep_once` (:211-238): inside `if handoff`, it calls `deliver_choice_requests(db)` **before** `first = deliver_pending(db)`.
  - `backend/app/main.py` (:477-478): passes `choice_enabled=choice_enabled` and `on_choice_request=deliver_choice_request_now` to `mount_os`.
- Tests:
  - new: `backend/tests/test_choice_request_apply.py` (SQLite, the decision service alone), `backend/tests/os/test_choice_request_delivery.py` (Postgres OS plus the app session of `test_connect_t5_flow.py` `world` :34-53);
  - extend: `tests/test_connect_flags_off.py`, `tests/os/test_crash_counsellor_intake.py` (new kill points only).

- [ ] **Step 1: Write the failing tests (R-07).**
  - `test_written_when_base_current`: v3 plus a request based on v3 → v4. Places are replaced, consent and field are copied, `request_key` is set, and one outbox row `decision:{ws}:4` exists.
  - `test_consent_copy_does_not_make_stale` (Review Focus 2): v3 → `update_consent` v4 → a request based on v3 → v5 written.
  - `test_changed_places_make_stale`: v3 → a choose with other places → `("stale", None)`. No row and no outbox row are added.
  - `test_withdrawn_makes_stale`.
  - `test_repeat_is_duplicate_not_n_plus_2` (Review Focus 1): the second call → `("duplicate", 4)`, and the count of rows is unchanged.
  - `test_consent_copy_does_not_carry_request_key`.
  - `test_bridge_delivers_and_proposal_accepted_after_intake`:
    1. Accept, then `deliver_choice_request_now`.
    2. The decision is v n+1, and the proposal has `requested_version = n+1`.
    3. `run_os(svc)` → the intake revises the plan, the proposal is `accepted`, and the plan's contract equals the decision's places.
    4. `plan_view.decision_version == n+1` (row 6.6).
  - `test_stale_answer_expires_proposal`: `status == "expired"` and `request_outcome == "stale"`.
  - `test_mark_after_intake_settles_at_once` (D-x3 ordering).
  - Crash points: after the app commit and before the mark, and after the mark and before the intake → a re-sweep gives one version and an `accepted` proposal.
  - **Flags-off proof:**
    - `test_sweep_skips_choice_requests_when_handoff_off`: the rows stay pending, and no decision is written.
    - `tests/test_connect_flags_off.py` gains `test_t6_sweep_and_roadmap_unchanged`: the `/v1/roadmap` body and the sweep counts match the captured fixture.
    - `tests/test_pai_os_bridge.py`, `tests/test_roadmap_choice_api.py` and `tests/os/test_connect_t5_flow.py` pass unchanged.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new legacy file and the touched legacy files (`--ignore=tests/os`). Then, separately, `tests/os -k "choice or intake or crash"`. Then `tach check` and `backend/scripts/check_alembic_heads.py`.
- [ ] **Step 5: Commit** `feat(connect): the decision service writes accepted choice requests as n+1, once (R-07)`.

### Task 4: Escalations ×5 — endpoint, bridge, plan pause, back to choosing, student text

**R-IDs:** R-11 (R-22 mapping); row 6.12.

**Files:**
- Create: `backend/app/pai_c/connect/escalation_texts.yaml`. It holds `version` and `approved: false`, one student sentence per reason (`not_eligible`, `all_rejected`, `deadline_passed`, `blocking_gap`, `other`), and `action` (the label of the banner button). — **OWNER approval, stored approved:false.** Plain English, no country, institution or date. A loader `backend/app/pai_c/connect/escalation_texts.py` (`text(reason) -> str | None`, `action() -> str | None`) returns `None` unless approved or `config.CONNECT_CONSENT_DRAFT`, and fails at import on a missing reason.
- Modify:
  - `backend/app/routers/escalations.py`:
    - `EscalationInput` (:20-24): `reason_type` widens to the legacy three plus `not_eligible`, `deadline_passed` and `other`, and gains an optional `decision_version: int | None = None`.
    - With `part_on("CONNECT_HANDOFF")` off, the handler first re-checks the legacy three. A reason outside them raises `RequestValidationError` with `loc ["body","reason_type"]` and type `literal_error`, so the 422 matches today's. The rest of the path is unchanged: the stage check (:43-44), DIRECTION (:46-48), the response.
    - With the part on: 409 if `RouteDecisionService.active(ws)` is None. Otherwise `CHOSEN → PROPOSED`, or the stage is left as it is (D-x9). The entry gains `decision_version`, and `next_recommended_action` is unchanged. The response is `{journey_id, stage}`.
  - `backend/app/pai_os_bridge.py` `_deliver` (:141-165):
    - with the part on: `reason_type = e.reason` (identity), plus `decision_version=e.decision_version`; after success, `plan_source.pause_for_escalation(...)`;
    - with the part off: `_TODAY` (:41-43), exactly as today.
  - `backend/app/os/ports/plan_source.py`: new `pause_for_escalation(student_ref, decision_version, reason) -> bool`. It finds the open Counsellor plan of the student (whose newest applied version equals `decision_version` when that is given), then calls `kernel.pause_plan(plan_id, reason)`.
  - `backend/app/os/adapters/counsellor/escalation.py` `_BY_EVENT` (:31-32): adds `"student_fact_changed": "not_eligible"` (ruling 11).
  - `backend/app/os/adapters/counsellor/intake.py` (:~183): the resume rule of D-x8, through a helper `_pause_reason(svc, plan_id)` that reads the newest `plan_paused` event.
  - `backend/app/pai_c/roadmap/decisions.py` `follow_active` (:116): the guard of D-x9.
  - `backend/app/pai_c/roadmap/plan_adapter.py` (:~126): when `plan.state == "paused"` and `state_reason` is one of the five, it adds optional `plan.reason_text` and `plan.reason_action` from `escalation_texts` (additive keys only, R-44).
- Tests:
  - extend: `tests/test_counselor_escalations.py`, `tests/test_pai_os_bridge.py`, `tests/os/test_counsellor_escalation.py`, `tests/test_plan_adapter.py`;
  - new: `backend/tests/os/test_escalation_pause.py`, `backend/tests/test_escalation_texts.py`.

- [ ] **Step 1: Write the failing tests (R-11).**
  - `test_endpoint_accepts_five_reasons_when_on` (parametrised over five reasons): 200, the entry `reason_type` equals the input, and `decision_version` is stored.
  - `test_endpoint_needs_active_decision_when_on`: none → 409.
  - `test_endpoint_works_outside_proposed_chosen_when_on`: a journey in DIRECTION with an active decision → 200, the stage stays DIRECTION, and the entry is recorded.
  - `test_chosen_goes_to_proposed_decision_kept`: the active `RouteDecision` is unchanged, with no new version.
  - `test_follow_active_does_not_bounce_after_escalation` (Review Focus 3): `sync_counselor_stage` → still PROPOSED. A new choose → CHOSEN.
  - `test_bridge_sends_reason_unchanged_when_on` (parametrised): `not_eligible`, `deadline_passed` and `other` arrive as themselves, then `pause_for_escalation` is called once.
  - `test_plan_paused_with_reason_code`: the plan status is `paused`, and `plan_view.state_reason == "not_eligible"`.
  - `test_consent_copy_keeps_escalation_pause` and `test_same_rechoice_keeps_pause`. Then `test_changed_choice_resumes`: the plan is `active` and revised (D-x8).
  - `test_consent_pause_resumes_as_today`.
  - `test_student_fact_changed_reaches_counsellor`: an `Escalate(fact_all_below)` from `rules.py:134` → a pending escalation with reason `not_eligible`.
  - `test_reason_text_null_until_approved`, `test_every_reason_has_text`, `test_no_country_words_in_texts`.
  - `test_adapter_adds_reason_text_only_for_escalation_pause`: a `consent_missing` pause has no `reason_text`.
  - **Flags-off proof:**
    - `tests/test_pai_os_bridge.py:65-68` (the parametrised three-reason collapse) passes **unchanged** with the part off.
    - `tests/test_counselor_escalations.py` existing cases pass unchanged: the stage 409, DIRECTION, a 422 on an unknown reason with the same `detail[0].type` and `loc`.
    - `test_flags_off_no_pause_call`.
    - `tests/test_connect_flags_off.py` `test_t6_roadmap_paused_unchanged`: with the PLANVIEW flag on and HANDOFF off, the body carries no `reason_text`.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the legacy files touched (`--ignore=tests/os`), then `tests/os -k "escalation or intake or pause"`, then `tach check`.
- [ ] **Step 5: Commit** `feat(connect): escalations carry all five reasons; the plan pauses and the student goes back to choosing (R-11)`. Name the changed v2 expectation in the body.

### Task 5: `ChoiceSink` port and the OS builder via the decision service

**R-IDs:** R-09; rows 6.13, 6.17.

**Files:**
- Create: `backend/app/os/ports/choice_sink.py`, modelled on `ports/student_facts.py` (docstring :1-14):
  - `configure(request: Callable[..., dict] | None)`;
  - `request(student_ref, origin, destination, level, intake, choices) -> dict | None`. It returns `None` when unconfigured, or when the host answers `None` (part off, so standalone). Otherwise it returns `{"outcome": "written" | "unchanged" | "refused", "decision_version": int | None, "code": str | None}`.
- Modify:
  - `backend/app/os/ports/__init__.py` and `backend/app/os/api/mount.py`: new arg `choice_sink=`.
  - `backend/app/os/routes/builder.py` `start` (:56-83):
    - after `_route`, `_check_programmes` and the contract validation, while the module is enabled (`manifest.is_enabled`), it calls `choice_sink.request(...)` **before** `plans.start_plan`;
    - on `written` or `unchanged` it returns `Preparing(decision_version)`;
    - on `refused` it raises `ChoiceRefused(code)`;
    - on `None` the code is today's, unchanged.
    - The 10-programme limit (:59) stays for standalone.
  - `backend/app/os/api/router.py` `start_self` (:297-309): `Preparing` → `JSONResponse(202, {"state":"preparing","decision_version": v})`. `ChoiceRefused` → 409 `{"detail": code}`, with codes `choose_field_first` and `too_many_places`.
  - `backend/app/os/replan/choice_texts.yaml`: adds `preparing`, `choose_field_first` and `too_many_places`. — **OWNER approval, stored approved:false.** Served as `note` in the 202 and 409 bodies through `choice_texts.note` (`None` until approved or in rehearsal).
  - `backend/app/pai_c/roadmap/decisions.py`: new `request_from_builder(workspace_id, origin, destination, level, intake, places) -> tuple[str, int | None, str | None]`.
    - It takes `_lock`. No active decision → `refused`, `choose_field_first` (D-x4). More than 5 places → `refused`, `too_many_places`.
    - If the active row already has these route, places and intake → `unchanged`.
    - Otherwise a new version per D-x4, with `request_key = builder:{sha}`; a repeat → `unchanged`. Then `outbox.record` and `written`.
  - `backend/app/pai_os_bridge.py`: new `request_choice(student_ref, origin, destination, level, intake, choices) -> dict | None`. It returns `None` unless `part_on("CONNECT_HANDOFF")`. It opens its own session, calls the service, commits, then `deliver_pending(db, ws)`.
  - `backend/app/main.py` (:477-478): `choice_sink=request_choice`.
- Tests:
  - new: `backend/tests/os/test_choice_sink.py`, `backend/tests/test_builder_choice.py`.

- [ ] **Step 1: Write the failing tests (R-09).**
  - `test_builder_with_counsellor_on_writes_decision` (row 6.13): POST `/v1/os/plans/self` → 202 `{state:"preparing", decision_version: n+1}`.
    - No `self_serve` plan row is created.
    - After `deliver_pending` and `run_os`, a `counsellor` plan exists with the same places, and `plan_view.decision_version == n+1`.
  - `test_builder_no_field_is_409_choose_field_first`.
  - `test_builder_six_places_is_409_too_many_places`.
  - `test_builder_repeat_is_unchanged_not_new_version`.
  - `test_builder_note_null_until_approved`.
  - `test_request_from_builder_copies_field_and_consent` (D-x4).
  - **Flags-off proof (row 6.17, R-59):**
    - `test_module_off_builder_standalone`: 201, a `self_serve` plan, and `choose_task` completed, exactly as `tests/os/test_route_builder.py` expects.
    - `test_handoff_off_builder_standalone`: the host answers `None` → 201, as today.
    - `test_unconfigured_sink_standalone`.
    - `tests/os/test_route_builder.py`, `tests/os/test_api_self_serve.py` and `tests/os/test_slice4*.py` pass unchanged.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new files, then `tests/os -k "builder or self_serve or sink"`, then `tach check`.
- [ ] **Step 5: Commit** `feat(connect): with the Counsellor on, the route builder writes through the decision service (R-09)`.

### Task 6: Adoption — kernel `adopt_plan`, intake, decision service `adopt`, API and texts

**R-IDs:** R-08; row 6.16.

**Files:**
- Modify:
  - `backend/app/os/kernel/kernel.py`: new `adopt_plan(plan_id, external_ref, contract) -> bool`.
    - Under `_lock_plan` it updates `source="counsellor"`, `external_ref`, `contract`, `contract_sha256` and `updated_at` in one transaction.
    - It writes one `plan_adopted` event through `_event` (:344). It writes no revision and no task change (ruling 6e).
    - It returns False if the plan is not open or not `self_serve`.
    - An `IntegrityError` on `uq_os_plans_identity` (`models.py:70`) is re-raised as `PlanIdentityTaken`.
  - `backend/app/os/adapters/counsellor/intake.py` (:173-175): an adoption branch before `_consent_missing` (:158-160), so that adoption runs first and a missing consent then pauses the adopted plan (ruling 6c).
    - It applies when the open self-serve plan matches D-x6. It calls `kernel.adopt_plan` with the contract from `_v1_contract` (:98), then sets `os_plan_adoptions.adopted_at`.
    - The normal path then finds `same` and revises with no task change.
    - Any mismatch or `PlanIdentityTaken` → `_refuse(..., "self_serve_plan_open")`, as today.
  - `backend/app/os/ports/plan_query.py`: new `self_serve_plan(student_ref) -> dict | None`, returning `{plan_id, route_key, origin, destination, level, intake, programmes, contract_sha256}`.
  - `backend/app/os/ports/plan_source.py`: new `request_adoption(student_ref, plan_id) -> Literal["recorded", "not_found", "module_off"]`, an idempotent upsert of the intent.
  - `backend/app/pai_c/roadmap/decisions.py`: new `adopt(workspace_id, plan: dict) -> tuple[str, int | None]`.
    - No journey → `refused`, `no_journey`. No active decision → `refused`, `choose_field_first`. More than 5 places → `refused`, `too_many_places`.
    - Otherwise a version per D-x4 with `request_key = adopt:{plan_id}:{sha}`; a repeat → `duplicate`.
    - Consent is copied, never invented (ruling 6c).
  - `backend/app/pai_os_bridge.py`: new `self_serve_plan(ws)` and `request_adoption(ws, plan_id)`.
  - `backend/app/routers/roadmap.py`:
    - New `GET /v1/roadmap/adoption`. It returns `{offer: false}` unless `part_on("CONNECT_HANDOFF")` and `part_on("CONNECT_MY_PLAN")` are on, the student has a journey (6d) and the student has an open self-serve plan.
    - Otherwise it returns `{offer: true, state: "ready" | "choose_field_first" | "too_many_places", plan: {plan_id, route_key, places: n}, text: {...} | null}`.
    - New `POST /v1/roadmap/adoption` `{plan_id}`, gated by `_need_handoff` (:77). It runs in this order:
      1. it takes the lock and re-checks the state;
      2. it calls `request_adoption`;
      3. it calls `adopt`;
      4. it commits through `_write` (:121-135), which also delivers.
    - It returns 200 `{state:"linking", decision_version}`, or 409 with the code.
  - Create `backend/app/pai_c/connect/adoption_texts.yaml`. Keys `offer`, `agree`, `choose_field_first`, `too_many_places`, `linking`, plus `approved: false`. — **OWNER approval, stored approved:false.** Its loader uses the same gate as `escalation_texts`.
- Tests:
  - new: `backend/tests/os/test_adopt_plan.py`, `backend/tests/test_adoption_api.py`;
  - extend: `tests/os/test_counsellor_intake_v2.py` (new cases only; the existing `self_serve_plan_open` refusal test stays green unchanged).

- [ ] **Step 1: Write the failing tests (R-08).**
  - `test_adopt_plan_keeps_tasks_and_revision`: tasks, task states, `current_revision` and the done steps are identical before and after. `source == "counsellor"`, and `external_ref == decision.external_ref`.
  - `test_intake_adopts_with_intent_and_equal_choice` (row 6.16): the intake status is `revised` (or `planned`), it creates no new plan row, and `plan_view` shows the same plan id.
  - `test_intake_refuses_without_intent`: `self_serve_plan_open`, as today.
  - `test_intake_refuses_when_plan_changed_after_intent`: the SHA differs → refused.
  - `test_identity_taken_refuses_cleanly` (Review Focus 4): a closed Counsellor plan with the same `external_ref` → refused, the self-serve plan is untouched, and the intent `adopted_at` is NULL. `uq_os_plans_identity` holds, as the test asserts with a count query.
  - `test_adoption_without_consent_pauses_consent_missing` (6c).
  - `test_offer_states`:
    - no journey → `offer false`;
    - no active decision → `choose_field_first`;
    - 6 places → `too_many_places`;
    - otherwise → `ready`.
  - `test_post_adoption_writes_version_and_intent`; and a repeat POST → the same version.
  - `test_adoption_text_null_until_approved`.
  - **Flags-off proof:**
    - `test_offer_false_when_my_plan_off` and `test_post_404_when_handoff_off`, with the same body as `_need_handoff` today.
    - `tests/os/test_counsellor_intake_v2.py` and `tests/os/test_counsellor_intake.py` pass unchanged.
    - `tests/test_connect_flags_off.py` `test_t6_no_adoption_route_effect`.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the legacy files (`--ignore=tests/os`), then `tests/os -k "adopt or intake or kernel"`, then `tach check`.
- [ ] **Step 5: Commit** `feat(connect): a self-serve plan is adopted when the student agrees (R-08)`.

### Task 7: Frontend — proposal states, escalation reason, builder answers, adoption offer

**R-IDs:** R-07, R-08, R-09, R-11.

**Files:**
- Modify:
  - `frontend/lib/os-replan.ts`:
    - the status union (:22) gains `'requested'`;
    - the source union gains `'student'`;
    - it adds the optional `status_note: string | null` and `request_outcome`.
  - `frontend/components/os/proposal-card.tsx`:
    - `requested` shows no Accept/Decline and shows `status_note`;
    - `expired` with a `request_outcome` shows `status_note`;
    - with no note, it shows no extra line.
  - `frontend/app/[workspaceId]/(os)/os-inbox/page.tsx` (:8, :143): lists `requested` and recently `expired` proposals without buttons.
  - `frontend/lib/api.ts`:
    - `startOsPlan` (:345), `swapOsProgramme` and `removeOsProgramme` return a union typed with `{state:'preparing'|'requested', …}`;
    - `acceptOsProposal` (:514) types `status: 'accepted'|'requested'`;
    - new `getAdoption()` and `adoptPlan(planId)`.
  - `frontend/components/os/route-builder.tsx`: on 202 it shows the backend `note` (if any) and stops treating the body as `OsSelfPlan`. A 409 `choose_field_first` / `too_many_places` shows the backend note.
  - `frontend/lib/roadmap.ts` (:63): `RoutePlan` gains the optional `reason_text` and `reason_action`.
  - `frontend/components/counselor/workspace/roadmap-parts.tsx` `PlanBanner` (:297):
    - prefers `plan.reason_text`;
    - with `reason_action`, it renders one button that calls the existing change-route handler of `YourRoute`, which is passed in.
    - `copy.json` is not changed.
  - `frontend/components/os/plan-card.tsx`: when `getAdoption()` answers `offer: true`, it renders the offer with `text.*` from the backend. "Agree" (state `ready` only) calls `adoptPlan`. The other states show their text with no button. Nothing renders when `text` is null.
  - Fixtures: `frontend/tests/fixtures/counselor.ts` (:373), `frontend/tests/preview/fake-api.ts`.
- Tests:
  - extend: `components/os/replan.test.tsx`, `components/os/route-builder.test.tsx`, `components/counselor/workspace/roadmap.test.tsx`;
  - new: `components/os/plan-card.test.tsx`.

- [ ] **Step 1: Write the failing tests (`// req: R-07`, `R-08`, `R-09`, `R-11`).**
  - `ProposalCard requested hides buttons and shows note`.
  - `expired after request shows note`.
  - `route builder 202 shows preparing note and no plan`.
  - `409 choose_field_first shows note`.
  - `PlanBanner shows reason_text and one action that opens change route`.
  - `plan card shows adoption offer and agree calls adoptPlan`.
  - `no text means no offer`.
  - **Flags-off proof:**
    - every existing test in these files passes unchanged;
    - the fixtures without the new fields render exactly as before;
    - the `copy.json`/`roadmap.json` equality test passes.
- [ ] **Step 2: Fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test`, then `npm run build`.
- [ ] **Step 5: Commit** `feat(connect): screens for requested proposals, escalation reasons and plan adoption (R-07, R-08, R-09, R-11)`.

### Task 8: Scripted flow and traceability

**R-IDs:** R-07, R-08, R-09, R-11; rows 6.5, 6.6, 6.12, 6.13, 6.16, 6.17.

**Files:**
- Create: `backend/tests/os/test_connect_t6_flow.py`. It follows the pattern of `test_connect_t5_flow.py`: the `world` fixture (:34-53) with `CONNECT_HANDOFF` and `CONNECT_ROADMAP_FROM_PLANVIEW` on, `run_os` (:55) and `no_chat()`. It uses `test_connect_t4_flow.py` `run_rules` for the Vault-driven proposal.
- Modify: `docs/requirements/connection.yaml` (:35-39).

- [ ] **Step 1: Flow test (fictional students; Germany and the fake routes).**
  - **6.5 → 6.6, Germany.** In order:
    1. Choose with 3 places → planned (v1).
    2. A Vault write drops the marks → a pending `CancelProgramme` proposal; the roadmap shows `proposals_waiting`.
    3. Accept → `requested`.
    4. The hook delivers → v2 with 2 places.
    5. `run_os` → revised; the proposal is `accepted`; the plan contract and the decision both have 2 places; `plan_view.decision_version == 2` on both sides.
  - **Stale.** A proposal on v2, then the student changes places (v3), then accept → the request answers `stale`. The proposal is `expired` and no v4 exists.
  - **6.12.**
    1. An admission is rejected on every place → an escalation `all_rejected` reaches the endpoint.
    2. The journey is PROPOSED, the plan is `paused` with the reason, and the roadmap banner shows `reason_text` (with the draft flag on).
    3. A consent copy does not resume the plan.
    4. A new choice resumes it and revises.
  - **6.13.** The builder with the Counsellor on → 202, the decision is v n+1, and a Counsellor plan is created from the intake.
  - **6.16.** A self-serve plan exists. The module and both parts are switched on, and the student has a chosen field. Then the offer appears, the student agrees, the decision version is written, and the plan is adopted with the same plan id and the same tasks.
  - **6.17.** The module is switched off. The plans continue, the builder starts a `self_serve` plan (201), and an accept edits the contract directly.
  - Throughout, no chat message is created (`no_chat()`).
- [ ] **Step 2: Traceability.**
  - Set `built: true` for R-07, R-08, R-09 and R-11.
  - Run `python scripts/check_traceability.py`.
- [ ] **Step 3: Full checks, one after the other.**
  - The legacy suite (`env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider --ignore=tests/os`), then `tests/os`.
  - `npm test`, then `npm run build`.
  - `tach check`, `python scripts/check_freeze.py --base origin/pai-connect`, `backend/scripts/check_alembic_heads.py`.
  - Report the counts.
- [ ] **Step 4: Commit** `test(connect): T6 flow test; R-07, R-08, R-09, R-11 built`.
