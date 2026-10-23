# PAI OS handoff: Slice 7 (replanning) built (2026-10-23)

**A new session reads this file first, all of it.** It continues `slice-6b-handoff.md` (and through it 6a and 5),
which still hold the environment, people, rules and earlier history. Where they disagree, this file is newer.

Authority order: parent spec > Slice 7 spec > Slice 7 plan > the rulings in the PRs > this handoff.
- **Slice 7 spec and plan:** `docs/superpowers/specs/2026-10-23-pai-os-slice-7-design.md`,
  `docs/superpowers/plans/2026-10-23-pai-os-slice-7.md` (both in #131).

## 1. Where things stand

Slice 7 is built, reviewed and fixed, in **PRs that each target `pai-os`**, merged in order (spec PR #131 first). After
each squash merge, rebase the next branch onto `pai-os` with `git rebase --onto origin/pai-os <old base> <branch>` and
push with `--force-with-lease`.

| Order | Branch | What |
|---|---|---|
| 0 | `os/s7-spec` | Spec and plan (#131) |
| 1 | `os/s7-t1-tables` | `os_0012`: proposals, plan overrides, support cases, `changes_paused`, Supervisor readings per plan |
| 2 | `os/s7-t2-ops` | The operation union; the compiler applies plan overrides on every compile |
| 3 | `os/s7-t3-checks` | Kernel checks on operations; `apply_replan`, the pause flag, the daily count |
| 4 | `os/s7-t4-events` | Events and detectors (kernel, deadline engine, reminders, service) |
| 5 | `os/s7-t5-rules` | The rules, and per-route replan config |
| 6 | `os/s7-t6-supervisor` | The Supervisor agent (tool-less actor, structured input only) |
| 7 | `os/s7-t7-run` | The `os.replan` workflow, proposals, limits, support cases, the worker job |
| 8 | `os/s7-t8-api` | `/v1/os/changes`, `/plans/{id}/changes`, proposal accept/decline, admin support inbox |
| 9 | `os/s7-t9-screens` | Suggestion cards, the paused banner, "What changed" on the inbox; `/os-admin/support`. **`frontend/lib/api.ts` is shared: Counsellor review.** |
| 10 | `os/s7-t10-gate` | The gate, the replan crash test, the evaluation harness, this handoff |

- **Never open or prepare a `pai-os` → `dev` PR.** The owners merge once, at the very end of all slices.

On the tip `os/s7-t10-gate`: Full suites on the stack tip `os/s7-t10-gate` (contains every branch before it): `pytest tests/os` **1082 passed**, 7 failed (the native-Windows SIGKILL crash tests incl. the new `test_crash_during_replan`, and `test_worker_enqueues_by_itself`; Linux CI runs them); legacy **1006 passed**, 3 pre-existing skips; tach and the single-alembic-head check clean; frontend Vitest **120 passed**, `tsc` clean, OS-enabled build passes. Alembic head `os_0012`.

### What Slice 7 built
- **Events** (`replan/events.py`), recorded once each with a dedupe key: `admission_rejected` (the inbox's
  "Not admitted"), `deadline_at_risk` and `route_invalid` (deadline engine), `document_missing` (reminders),
  `task_failed` (kernel), `playbook_newer` and `approved_changed` (the replan job's sweep), `escalate` (reminders).
- **Rules first** (`replan/rules.py`, pure): rejection → remove the programme (or swap below `min_programmes`);
  deadline at risk → move the blocking student step ahead and ask for it; document missing → ask; failed → one
  retry, then escalate; newer guide → propose the upgrade; changed approved file → re-add its review step.
- **The Supervisor** (`replan/supervisor.py`, `agents/supervisor.v1.yaml`): strong tier, no tools, sees only
  structured plan state (no titles, no free text), at most 10 typed operations, 2 output repairs, its own monthly cap
  (`OS_REPLAN_MONTHLY_USD`, default 5). No key → hand-overs go to the support inbox.
- **Kernel checks** (`replan/checks.py`): unknown step, missing/started/protected target, a dependent losing its only
  input of that kind, a step pushed past its deadline, an unconfirmed swapped-in programme. A refused operation is
  dropped; the rest still apply.
- **Applying** (`replan/apply.py`): skips, cancels, adds and reorders are plan overrides the compiler applies on every
  compile; each change is a kernel revision `replan:<proposal id>`. Small changes apply at once; big ones (swap or
  remove a programme, skip/cancel a critical step, add more than a day of new student work, a guide upgrade) wait for
  the student (7 days, or 1 day before the deadline). Accepting re-checks against the plan as it is now.
- **Limits:** 10 operations per wake; 3 automatic replan revisions per plan per UTC day; the 4th pauses changes and
  opens a support case. Resolving the case can resume them (held events then run, by a pause generation in the
  workflow ID).
- **Screens:** suggestion cards (Accept / Decline, answer-by date), the paused banner and "What changed" on the
  inbox; `/<workspace>/os-admin/support` (the admin types the token per visit; memory only, own header).

## 2. Rulings (binding unless the owners change them; each is in its PR)
- proposals are listed in the inbox beside items and notes (like Slice 4 notes), not as os_tasks rows - the kernel's tasks are plan steps and only the kernel writes them - cost if wrong: one inbox query.
- an UpgradePlaybook op (rules only, always big) joins the union - the spec makes a playbook upgrade a big proposal but S7-D4's union has no op for it - cost if wrong: one op type.
- is_big takes the playbook (is_big(op, tasks, playbook)) - "add student work over 1 day" needs the template's duration - cost if wrong: none.
- compile_plan takes overrides duck-typed (op, target, payload) so the compiler imports nothing from replan.
- check_operations takes compile_with(ops) instead of one precomputed candidate - each op is checked against the plan with only the ops kept so far (the fixed point the plan asks for) - cost if wrong: none.
- "a dependent loses its input" means it loses every hard dependency of that step kind - a route-level step fed by several programmes keeps the others when one programme is cancelled - cost if wrong: a check too lax for multi-programme joins.
- "pushed past its deadline" = a step with slack >= 0 now gets negative slack (DraftTask has no deadline field; negative slack is exactly a missed deadline).
- approved_changed and playbook_newer are detected by functions the replan job calls for each active plan (detect_approved_changed, PlanService.check_newer), not inside packs/approval.py - an approval drops when a new version is added anywhere, so a sweep finds every case in one place - cost if wrong: up to 5 minutes' delay.
- a plan that no longer compiles (CompileError) records route_invalid instead of only recompute_failed; other exceptions keep recompute_failed.
- a rejection that leaves enough programmes is a CancelProgramme proposal, which is big (S7-D7: a whole programme's tasks) - the student confirms even an obvious removal - cost if wrong: one extra Accept tap.
- below min_programmes the rule proposes a Swap (which itself drops the rejected programme's steps) instead of Cancel + Swap; no suggestion -> Supervisor.
- deadline_at_risk asks for the step that blocks the late one (an unstarted student predecessor, else the step itself) and moves it ahead of the most deferrable non-critical student step; with no student step: a programme's deadline -> Supervisor, a route step -> escalate.
- task_failed retries once (Retry, through Kernel.retry) when its attempt < 2, else escalates.
- event payloads reach the Supervisor only through a whitelist of structured fields (instance_key, programme_ref, template_key, attempt, version, slack_days); titles, failure reasons and errors never do (invariant 9).
- the Supervisor may not propose upgrade_playbook (output validation refuses it) - an upgrade is an explicit, rules-made, accepted revision (invariant 10).
- re-adding a step the plan already has (AddTask whose base instance exists) is small - S7-D11 says the re-review is small, but review_visa_file lasts 2 days so the size rule alone would make it big - cost if wrong: one Accept tap.
- one proposal holds small and big ops together; any big op makes the whole proposal pending.
- the daily limit applies to small (automatic) changes only; a big change the student accepts is applied even on a 4th revision - the student consented - cost if wrong: more than 3 revisions on a busy day.
- the workflow ID carries a pause generation (count of changes_resumed events), so an event held while paused is processed after an admin resumes the plan.
- request_from_student sends an outbox message (key replan:<proposal>:<step>, template replan_request) - the item is already in the inbox; the message is the nudge.
- Supervisor spend has its own monthly cap OS_REPLAN_MONTHLY_USD (default 5); over it -> support case.
- accept re-checks every op against the current plan and refuses (ProposalStale) if any is now refused; a declined/expired/answered proposal is ProposalStale.
- the inbox response gains `proposals` and `changes_paused` (beside items and notes), and the student's "what changed" is GET /plans/{id}/changes for their own plan only (404 otherwise); accept/decline 404 for another student's proposal, 409 when stale, expired or answered.
- added GET /v1/os/changes (the student's open plan) - the screens have no plan id; /plans/{id}/changes stays for the id case.
- there is no student plan page, so "What changed" and the suggestion cards live on the inbox page (which is the student's plan view) - cost if wrong: moving two sections.
- the admin support page takes the admin token per visit, in memory only, sent in its own header (never stored or in a URL) - there is no admin session in the student app.
- re-graded minor "upgrade goes to the newest, not the accepted version" to Important (with the self-found bug: same fix) - invariant 10.
- accept refuses on a changed contract (a swap, a reorder) and on any op that no longer passes the checks, but not on any revision at all - small automatic changes elsewhere in the plan must not kill a pending suggestion, and every op is re-checked against the current plan - cost if wrong: a suggestion applied after an unrelated change.

## 3. Deferred minors (from the final review)
1. accept is allowed while the plan's changes are paused (an admin is checking it).
2. the os.replan workflow body reads plan state outside a step before the Supervisor call (DBOS determinism; model calls are replayed).
3. refused operations are not passed back to the Supervisor, and there is no re-prompt after a refusal.
4. spend_usd_per_wake in supervisor.v1.yaml is not enforced (the monthly cap and the request limit are).
5. an empty Supervisor answer (ops=[]) closes the event as applied instead of escalating.
6. CancelProgramme says "its remaining steps are removed" even when some are started or protected (the kernel keeps those).
7. a proposal that made no revision records the plan's current revision; "What changed" lists an empty change.
8. events.record dedupe is check-then-insert with no unique index; overlapping job runs can duplicate an event.
9. ADMISSION_TEMPLATE and REVIEW_TEMPLATES hold template keys in Python (no country terms).
10. detect_approved_changed lists the student's artifacts once per review step, every 5 minutes.
11. the admin page lists open cases only, without events or the refused proposal's ops.
12. PlanOut (admin plan read) does not show changes_paused.
13. resolving an already resolved case overwrites its note; unpausing ignores other open cases of the plan.
14. replanner_for reloads the replan YAML on every accept/decline.
15. Ruling Task 5 order (reprioritise and request together, not "if still at risk").

## 4. Open items for the owners
- **Run the billed Supervisor evaluation** (spec §8): `python scripts/os_supervisor_eval.py --i-have-the-owners-ok`
  in `backend/`, with `OS_OPENAI_API_KEY` set. About 20 strong-tier calls, well under $5. Pass mark 18 of 20. Not run.
- **S7-D11** (built as recommended): a changed approved file re-adds its review step. Confirm.
- **6b follow-up** (recommended, not built): an "I checked the amount" tick before approving an unconfirmed funds
  amount.
- Everything still open from `slice-6b-handoff.md` §4.

## 5. Next: Slice 8, the Counsellor connection
Parent spec §6: the Counsellor adapter (its decision record → a RouteContract), the summary, escalation through the
`EscalationSink` port (today the standalone adapter writes `os_support_cases`), the frozen contract and contract
tests both teams run. It needs the Counsellor team (@memsa771-hub); start with their brainstorm.

## 6. Environment notes (native Windows, this machine)
- As `slice-6b-handoff.md` §6. Docker Desktop is now at `%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe`.
- The crash tests (now including `test_crash_during_replan`) fail on native Windows by design; Linux CI runs them.
