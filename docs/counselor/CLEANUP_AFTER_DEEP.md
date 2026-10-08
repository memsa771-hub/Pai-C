# Counselor consolidation (PR 5b-2)

Backup: `legacy-counselor-final` points to merged PR 18, commit
`3cb324b1e3e53014c17e86ea568a6d667e60cd31`, and is pushed to origin.
Deep is the sole conversational runtime. This PR does not implement Mirror,
change PAI OS features, or migrate/drop any database objects.

## Deleted modules

All paths below are under `backend/app/counseling/`:

- `core.py`: replaced by the existing `deep/turn.py`.
- `turn_plan.py`, `turn_semantics.py`: old intake/classifier turn routing.
- `goal_transition.py`: old conversation classifier for goal activation.
- `evaluator.py`, `continuous_discovery.py`, `decision_sufficiency.py`: old turn policy derivation.
- `reply_guard.py`, `turn_contract.py`: old response repair/model loops and envelopes.

The pre-consolidation importer inventory was retired during docs cleanup; the
retained-module inventory below records the relevant callers and rationale.
The package-export importer `tests/test_pai_core_architecture.py` also used
`CounselingEvaluator`; its obsolete evaluator test was removed. Final searches
cover both module imports and exported symbol names. No production importer of
the deleted modules remains. The regression test also checks this boundary.

Deleted tests: `test_continuous_discovery.py`, `test_counselor_response_quality.py`,
`test_counselor_tool_loop.py`, `test_counselor_reply_guard.py`,
`test_direction_discovery.py`, `test_goal_transition.py`,
`test_multilingual_semantic_contract.py`, `test_student_voice_decision_sufficiency.py`.
These tested removed evaluators, classifiers, tool loops or repair behavior.
Deep tests retain one-call, language retry, research gating, isolation, chat/voice,
notebook, extraction, context and no-direct-profile-write coverage. Projection,
Vault, onboarding, Journey and Operator tests remain; their obsolete runtime
parts were ported or removed. `test_counselor_core.py` now tests only the retained
context projection; it was not renamed merely for organization.

## Moved helpers and active callers

| Helper | Destination | Production callers |
| --- | --- | --- |
| `_post_response` | `counseling/posting.py` | `runtime.py`, `services/operator.py`, `routers/roadmaps.py` |
| `_build_conversation_context` | `counseling/posting.py` | `services/operator.py`, `routers/roadmaps.py` |
| `is_counselor_fallback` | `counseling/deep/polish.py` | `posting.py`, `routers/counselor_voice.py`, `deep/turn_input.py` |

Posting still commits through the existing pipeline, publishes Redis, schedules
workflow advancement and integration relay before returning. No OS hook was
removed. Historical fallback matching retains its exact two strings.

Roadmap discussion calls `run_deep_turn` with the existing Counselor prompt,
bounded conversation history and a workspace-checked selected roadmap in
`<research>`. It posts via the shared function. It does not enqueue analysis or
extraction for a synthetic page-opening action. A failed opening does not undo
the persisted focus. Handoff uses deterministic deep polish, with no repair call.

The mode setting and validation were removed from application code, Compose,
environment examples and docs. Successful human turns always queue existing
extraction and analysis. Discovery advances at most to DIRECTION automatically;
new research requires a confirmed mirror. Stale refreshes remain supported.

## Retained modules and importers

Production importer inventory after the follow-up code cleanup (relative to
`backend/app/`):

| Module | Importers | Why retained |
| --- | --- | --- |
| `understanding.py` | `counseling/baseline.py`, `services/operator.py`, `memory/handlers.py` | Canonical student understanding for research and baseline checks |
| `discovery.py` | `counseling/understanding.py`, `memory/discovery_intake.py` | Existing discovery data projection/status compatibility |
| `baseline.py` | `services/operator.py` | Background result baseline validation |
| `context_projection.py` | `counseling/research_gateway.py` | Compact research brief projection |
| `research_gateway.py` | `memory/handlers.py` | Single guarded research entry point and private brief/delegation helpers |

`understanding.py`, `baseline.py`, `discovery.py`, `context_projection.py` and
`memory/discovery_intake.py` are scheduled for removal in PR 7/8, when the research
brief is built from the confirmed Mirror, Notebook and student snapshot. Their
remaining consumers must be migrated first; deep profile context already uses
the student snapshot independently. This cleanup does not remove or replace
their current behavior.

### Follow-up code cleanup

Removed the dead Counselor policy/state modules and emptied the package exports.
Before deletion, the policy was imported only by the Counselor package initializer;
the state was imported only by that policy and initializer. `tools/policy.py` and
`journey/state.py` are separate active modules and remain unchanged.

The old research-flow module was folded into `research_gateway.py`. The brief
builder and delegation implementation are private there; reconciliation now calls
the public `request_research` directly, removing the redundant forwarding wrapper.
The old module's importers were the gateway, memory handler and two test files;
all were updated. The two old journey/recorded-research evaluation scripts were
imported only by `tests/test_counselor_research.py`. Their meaningful assertions
now live in `tests/test_counselor_deep_research_contracts.py`: reported evidence,
cited remediation, missing documents, rethink transitions, one question, and
sourced stated/alternative/family routes with deterministic missing-fact requests.
Repeated persona labels were replaced by the four distinct score/family cases.

The cleanup is verified by both reference searches and an offline `python -c`
import sweep of every Python module under `app/`, including the routers and job
handlers. Importing modules does not start the application's lifespan or workers;
network access is disabled for the sweep and backend suite.

Other retained compatibility: `services/counselor_prompt.py` is imported by
`services/pai.py`; its shared prompt is used by background handoff. It is not the
student-turn runtime. `memory/foundation_intake.py` has no production caller after
this consolidation; it remains outside the specified deletion list. Its tests
and canonical candidate/reconciliation behavior are retained. No additional
module was moved/deleted solely to reorganize files.

## Database follow-up inventory (no migration in this PR)

| Migration | Objects/data | Current use / later action |
| --- | --- | --- |
| 082 | Journey stage constraint; `uq_counselor_journey_active`; requirement selector constraint including `any_present`; seeded `goal.stated_preference`, `goal.underlying_objective`, `goal.constraints`, `goal.drivers` requirements | Journey constraints/index and selector remain active. Old direction-question seeds no longer drive deep conversation. Audit their profile/export consumers before removing rows. No new columns/table were added by 082. |
| 085 | `pai_counselor_slot_answers`: `id`, `workspace_id`, `source_event_id`, `slot_key`, `value`, `status`, `confidence`, `quote`, `created_at`; unique/status constraints and recent index | No active application reader/writer beyond the ORM declaration. Candidate for later archival/drop migration after checking existing user data. |
| 085 | `pai_profile_requirements.stage`, `question_intent`, `canonical_questions`, `accepts_unknown`, stage check/index; discovery requirement rows | `stage` is still read by `ProfileRequirementRegistry` and the profile-completion engine: retain. The other three columns are no longer read by conversation code; ORM/API serialization still exposes them, so audit clients before a later migration. |
| 087 | Version-2 `discovery.goal_reason` requirement row using `student_voice_statement.statement` | Data-only migration, no table/column. Superseded as deep conversational intake; durable student voice records remain canonical and must not be dropped. |
| 089 | Version-2 `discovery.field_interest`, `discovery.envisioned_outcome`, `discovery.timing` requirement rows using `student_voice_statement.statement` | Data-only migration, no table/column. Same audit requirement as 087. |

Notebook state replaces conversational intake routing, not the canonical Vault.
Do not blanket-drop profile requirements, student voice records or Journey fields.

## Branch and worktree inventory (read-only)

At inspection, `git ls-remote --heads origin` lists only `main`, `dev` and
`feature/counselor-deep`. **No old remote branch exists to delete.** Cached remote
tracking refs still list the following superseded branches. If approved later,
remove only those cached refs with these exact commands:

```powershell
git branch -dr origin/feat/counselor-v2-baseline origin/feat/counselor-v2-eval origin/feat/counselor-v2-extraction origin/feat/counselor-v2-slots origin/feat/counselor-v2-summary origin/feat/counselor-v2-turn origin/feat/counselor-v2-writer
git branch -dr origin/feature/counselor-complete origin/feature/counselor-deep-pr1 origin/feature/counselor-deep-pr2 origin/feature/counselor-deep-pr3 origin/feature/counselor-deep-pr4 origin/feature/counselor-deep-pr5 origin/feature/counselor-deep-pr5b1
```

Merged local branches (ancestry verified against the backup tag) may later be
removed with `git branch -d`, after freeing any associated stale worktree:

```powershell
git branch -d feat/counselor-v2-baseline feat/counselor-v2-eval feat/counselor-v2-extraction feat/counselor-v2-slots feat/counselor-v2-summary feat/counselor-v2-turn feat/counselor-v2-writer feature/counselor-complete feature/counselor-deep-pr1 feature/counselor-deep-pr2 feature/counselor-deep-pr3
```

`git worktree prune --dry-run --verbose` finds missing worktree directories:

- `C:/Users/MSA/Desktop/PAI-CORE/PAI-OS/counselor-complete` (`feature/counselor-simple`).
- `C:/Users/MSA/Desktop/PAI-CORE/PAI-OS/counselor-v2-baseline` (`feat/counselor-v2-eval`).

After separate approval, rerun the dry-run, then `git worktree prune --verbose`
to remove those stale metadata entries. No file deletion is needed because the
directories are already absent. `feature/counselor-simple` is **not an ancestor**
of the backup tag; do not delete it with a force command without separate review.
The active `workspace` (`dev`) and this consolidation worktree remain untouched.

## Reproducible offline startup check

```powershell
docker compose -p pai-consolidation-check -f backend/scripts/eval/docker-compose.offline.yml up -d --build
$src = (Resolve-Path backend).Path
docker run --rm --network pai-consolidation-check_host_access --mount "type=bind,source=$src,target=/app,readonly" -w /app --entrypoint python placement-ai-backend:prod -m scripts.eval.offline_startup_check
docker compose -p pai-consolidation-check -f backend/scripts/eval/docker-compose.offline.yml down
```

This disposable stack uses no `.env`, only synthetic credentials/data. Database
migrations run against its separate PostgreSQL. Fake identity verification feeds
the real application-session flow; fake completion feeds the real event pipeline.
Real model factories and external backend hostname resolution are blocked. Voice
checks the authenticated route with a fake SDP response, **not live microphone,
audio, interruption or provider connectivity**. Browser requests to third parties
are aborted. Test ports are loopback-only 13000/18000. Existing stacks are untouched.
The test entry point is explicitly guarded and must never be used for deployment.

### Verification results

- Merged PR 18 base: backend 642 passed, 3 skipped, 8 subtests passed; frontend
  15 passed; production frontend build passed.
- Consolidated backend: 585 passed, 3 skipped, 8 subtests passed. Removed tests
  exercised deleted implementations; retained shared behavior is tested above.
- Final focused delivery/roadmap regression run: 17 passed.
- Frontend: 15 passed across 4 test files; production build passed. The separate
  Docker frontend build and fresh cloud backend image build also passed.
- Compose: migrations completed, `/health` returned OK, fake provider login
  created a real application session, a human event produced the fake deep reply
  through the real pipeline, voice returned a fake session/SDP, Roadmaps API
  returned 200, and Playwright rendered the Roadmaps heading and empty state.
- No real model API calls. No branch/worktree deletion or database schema removal.
  The disposable Compose stack was stopped and removed after verification.
