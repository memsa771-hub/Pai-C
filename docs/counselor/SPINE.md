# PAI C spine: P1a Model Gateway

Source: `CLEAN_ARCHITECTURE.md` sections 2/5 and
[FigJam diagram 1: The spine](https://www.figma.com/board/e3MSmJw0s6wOdGvUubx6SU)
(central Model Gateway, node `1:22`). P1a only; no new runtime, queue, registry,
language policy, retry policy or model calls were added.

## Call site -> role -> config

Paths below are relative to `backend/app/`. Every listed call now enters
`inference/gateway.py`; `inference/client.py` remains the internal transport.

| Call site | Role | Model config / existing fallback | Reasoning setting |
| --- | --- | --- | --- |
| `pai_c/deep/turn.py` (normal + language retry) | counselor | `PAI_COUNSELOR_MODEL` -> `PAI_MODEL` | `PAI_COUNSELOR_REASONING_EFFORT` |
| `pai_c/deep/analysis.py` | analyst | `PAI_ANALYST_MODEL` -> Counselor model | `PAI_ANALYST_REASONING_EFFORT` |
| `pai_c/deep/mirror.py` | mirror | `PAI_MIRROR_MODEL` -> Counselor model | Counselor effort |
| `pai_c/deep/roadmaps.py` | roadmap | `PAI_ROADMAP_MODEL` -> Counselor model | Counselor effort |
| `pai_c/deep/sensitive.py` | sensitive | `PAI_SENSITIVE_CHECK_MODEL` -> Analyst model | `PAI_SENSITIVE_CHECK_REASONING_EFFORT` |
| `memory/extractor.py` | extractor | `MEMORY_EXTRACTOR_MODEL` -> `PAI_MODEL` | No explicit effort, as before |
| `memory/embeddings.py` | embeddings | `MEMORY_EMBEDDING_MODEL` | Not applicable |
| `documents/extractor.py` | document_extractor | `DOCUMENT_EXTRACTOR_MODEL` -> `PAI_MODEL` | `DOCUMENT_EXTRACTOR_REASONING_EFFORT` |
| `documents/ocr.py` | ocr | `DOCUMENT_OCR_MODEL`; existing empty-value fallback preserved | No explicit effort, as before |
| `plugins/program_research/__init__.py` | research_extract | `PAI_MODEL` | No explicit effort, as before |
| `plugins/scholarship_discovery/__init__.py` | research_extract | `PAI_MODEL` | No explicit effort, as before |
| `services/operator.py` (understand, plan, execute, verify) | operator | `PAI_OPERATOR_MODEL` -> `PAI_MODEL` | `PAI_OPERATOR_REASONING_EFFORT`; existing transport tool adaptation unchanged |
| `eventing/handlers/routing.py` | router | `PAI_MODEL` | No explicit effort, as before |
| `eventing/handlers/workflows.py` | router | `PAI_MODEL` | Existing synchronous classifier, no effort |

`complete` preserves text vs tool-message outputs; `tool_response=True` retains
Operator's dictionary result even on its last, tool-free iteration. `complete_sync`
keeps the transaction-bound classifier synchronous. `get_client` is used only by
OCR to keep one raw-response client across pages, with usage recorded per call.
`embed` keeps per-call close-on-success/failure, vectors, dimension checks and the
provider's existing credential compatibility/Null fallback. Explicit injected
provider models/endpoints remain supported, without adding new configuration.

## Logging and compatibility

- Usage formatting and turn ContextVar moved from `pai_c/deep/usage.py` into the
  gateway. The exact `counselor_token_usage phase=... turn_id=... model=... input=...
  cached_input=... output=... reasoning=...` record format is unchanged.
- `pai_c/deep/usage.py` is now a compatibility re-export only; existing instrumentation
  imports keep working. Original inference public transport functions also remain
  available for existing external/offline harness consumers.
- SDK resource warming moved into the internal transport and still runs at the
  same memory-provider import point. Embeddings retain SDK constructor defaults;
  chat/OCR/classifier retain the configured retry/timeout/endpoint behavior.
- Existing research-budget callbacks remain unchanged, including the pre-existing
  explicit callbacks in program extraction and roadmap building. No accounting
  cleanup or budget-policy change was bundled into this behavior-preserving task.
- Language prompts, blocked-script retries and response validation remain in their
  existing owners. P1a does not add a prompt or a language rewrite.
- `git fetch origin` showed no `origin/pai-os` branch to inspect. No shared public
  transport names, provider classes or PAI OS contract tables/routes/config were
  removed or renamed. Contract regression tests remain part of the full suite.

## Checks

`test_model_gateway.py` checks all 12 roles, existing fallback chains/efforts,
credential fallback, exact request/tool shapes, usage format/privacy, OCR raw
response/client reuse seam, embeddings/vector metadata and close-on-error.
Its AST architecture test scans every Python module under `backend/app/` outside
`inference/`, including function-local imports and literal dynamic imports, and
rejects imports of `app.inference.client`, `openai` or `AsyncOpenAI`.
48 new gateway tests passed. Seven inline runtime prompt constants were also
compared to the committed baseline and remained exactly unchanged. Existing
behavior tests retain their assertions; only the usage logger target
moved to the gateway. No model request was sent to a real provider.

| Verification | Before P1a | After P1a |
| --- | --- | --- |
| Backend | 733 passed; 3 production-only skips; 8 subtests | 781 passed; same 3 skips; 8 subtests |
| Frontend | 23 passed (P0 baseline) | 23 passed |
| Frontend production build | PASS (P0 baseline) | PASS |

## Open questions

1. Two dormant PAI OS helpers (`services/workflow.py::_judge` and
   `routers/routines.py::_generate_routine_context_sync`) reference `_get_llm_client`, which no
   longer exists in routing. Their local helper import fails before reaching the
   provider code. Neither is a listed
   P1a call site; restoring/replacing them would change behavior and needs a separate
   task. Their dead provider branches were left unchanged, not presented as migrated.
2. Evaluation-only scripts still use the internal transport for simulator/grader,
   smoke and call-cost instrumentation. Those roles and harness refactors are not
   specified here. They were left unchanged; the architecture boundary in this task
   scans application modules, not offline scripts/tests.
3. Browser live-session SDP/authentication HTTP exchanges have no specified gateway
   role and are not chat/embedding calls in these backend modules. They remain
   unchanged; Counselor intelligence uses the migrated turn path.
4. Calls without an event identifier retain the existing empty `turn_id` semantics.
   Session export needs an event id to associate a usage record; no new attribution
   scheme was invented here.
5. No new safety, judge or summarizer model roles, language hooks or budget behavior
   were invented beyond the role list in this task. Existing research callbacks can
   count usage in both the transport and a caller callback; changing that accounting
   needs separate approval under the unchanged-behavior rule.

Final document regression: 151 passed plus 8 subtests. Gateway/student-record
regression: 130 passed. Temporary offline socket guards and parser dependencies
were removed after testing; no runtime test mode or provider configuration shipped.


## P1b: system capabilities and Task Runtime

All existing durable job identifiers now resolve in the existing Capability
Registry. Every row below has kind `system`; capability id equals job type.
Registration is centralized in `app/capabilities/system.py`. The original
handler functions, SQL queue, tables, idempotency keys, priority, leases,
retry/backoff, per-workspace analysis ordering and locks are preserved.

| Job type / capability id | Handler (unchanged owner) |
| --- | --- |
| counselor.analyze | pai_c.deep.analysis.analyze_job |
| counselor.mirror | pai_c.deep.mirror.mirror_job |
| counselor.mirror_research | pai_c.deep.mirror.confirmed_research_job |
| memory.extract | memory.handlers.extract_memory |
| memory.reconcile | memory.handlers.reconcile_memory |
| memory.embed | memory.handlers.embed_memory |
| memory.unindex | memory.handlers.unindex_memory |
| memory.reindex | memory.handlers.reindex_workspace |
| memory.resume_research | memory.handlers.resume_research |
| research.refresh_stale | memory.handlers.refresh_stale_research |
| document.parse | documents.handlers.parse_document_job |
| document.extract | documents.handlers.extract_document_job |
| document.index | documents.handlers.index_document_job |
| document.unindex | documents.handlers.unindex_document_job |
| document.notify | documents.handlers.notify_document_job |
| agent.run (new adapter) | services.operator.run_agent_job -> existing _execute loop |

### Owners and compatibility

| Previous entry / owner | Current owner | Compatibility |
| --- | --- | --- |
| Handler modules register on import | Capability Registry system loader | Handler functions and existing job strings retained |
| BackgroundJobService.enqueue callers | runtime.task_runtime.enqueue | BackgroundJobService public queue API retained |
| Worker run_job dispatch | runtime.task_runtime.run | jobs.service.run_job forwards to Task Runtime (temporary) |
| JobHandlerRegistry / job_handlers | Capability Registry | Temporary facade only; no second handler map |
| Agent business discovery / invocation | Existing CapabilityRouter and capability tools | Registry.all() still means business; all(kind="system") is internal |
| Owned fixed-input Operator execution | Operator workflow invoking ToolExecutor capability.invoke | Same execution_runs row, resume(), status hooks and handoff |
| Open-ended Operator execution | Existing five-phase loop; agent.run system adapter | Existing delegate/resume scheduling and _execute public seam retained |

System capability input schemas describe the existing payloads, with optional
fields and additional properties retained. Optional null fields keep their old
handler-default behavior; validation checks supplied non-null fields and leaves
the original job payload untouched. Dispatch does not add a second timeout or
retry wrapper around handlers; the existing worker owns retries and leases.
`agent.run` requires a run_id and checks that the run belongs to the job workspace.
System capabilities cannot own agent task types, be listed, described, invoked,
or used as nested business capabilities.

`git fetch origin` / `git branch -r`: only origin/dev, origin/main and origin/pai-c
were present; origin/pai-os was unavailable for importer grep. Shared public job
names and Operator delegate/resume/_execute are retained. No PAI OS files, tables,
escalation route or service-token configuration were changed. The temporary
JobHandlerRegistry/job_handlers/run_job facades should be removed only after
checking the other developer's branch when it becomes available.

### Workflow mode and result mapping

Workflow selection uses persisted `run.constraints.capability_input` (object)
and `resolve_run_policy(...).owner`, before generic workspace/context reads or
any Operator model call. Input is passed unchanged to the owner through the
ordinary ToolExecutor -> capability.invoke -> CapabilityRouter path. Student
scopes, permissions, declared tool broker, approval rules, composition depth,
research-budget propagation and capability validation remain in that path.

| Outcome | Saved status and handoff |
| --- | --- |
| Successful capability, no pending action | completed; completed steps; existing result envelope with summary, plan, tool_calls, observations, artifact_id and capability_result (including artifacts); _post_result |
| approval_required | needs_user_action; original approval payload and purpose/capability_id; no completed_at; unchanged resume() carries host approval |
| Capability pending_action | needs_user_action; original action; need_from_student translated to the existing fact/items shape; same row and resume() |
| Capability/tool/schema/permission error | failed; error and completed_at; failed tool observation; _post_result; no generic model fallback |
| No owner or no fixed object input | Original five-phase loop, including its fallback policy, unchanged |

`run_status_hook` runs on executing and terminal/pause updates as before, so
roadmap publication, stage transitions and student requests remain owned by the
existing plugin hook. Existing artifacts stay in capability_result; no new
artifact writer or result schema was introduced. Unconfirmed non-decisive facts
alone do not create a pending action or force a completed capability to fail.

| Model calls | Before P1b | After P1b |
| --- | --- | --- |
| Operator phases for normal fixed-input roadmap research | 3 plain calls (understand/plan/verify) + E execute calls (normally E=2, total 5; bounded by existing iteration config) | 0 |
| Research/extraction/roadmap calls inside the owner capability | Existing configured calls and budgets | Unchanged |
| Counselor result explanation / handoff | Existing path | Unchanged |
| Open-ended / missing-input Operator run | Existing five-phase calls | Unchanged (offline regression: 3 plain + 2 execute) |
| Student reply + background Analyst + memory extractor | Existing calls | Unchanged |

No existing test expected roadmap_research model phases. Existing agent-loop
assertions were left unchanged. Only
`test_retry_of_same_student_event_uses_one_extraction_key` moved its mock target
from the old enqueue service constructor to the runtime enqueue seam; its
idempotency assertions are unchanged. New
`test_roadmap_research_installed_owner_uses_workflow_without_operator_phases`
checks the intended behavior change and the actual installed owner's stage hook.

### P1b checks

- test_system_capabilities.py: all 15 contracts and dispatch signatures, hidden
  list/describe/invoke surface, invalid contracts/payloads, queue idempotency,
  compatibility forwarding, AST checks for no job_handlers.register calls,
  no direct enqueue outside Task Runtime, and every enqueued type registered.
- test_operator_workflow.py: real checked invocation, zero Operator calls,
  scoped context, permission/schema failures, approval and text resume on the
  same row, pending fact shape, status hooks, installed roadmap owner, agent.run
  workspace isolation, and unchanged owned-without-input / unowned phases.
- App import check: 247/247 modules imported with external sockets blocked.

| Verification | Before P1b (last green P1a baseline) | After P1b |
| --- | --- | --- |
| Backend | 781 passed; 3 production-only skips; 8 subtests | 831 passed; same 3 skips; 8 subtests |
| Frontend | 23 passed | 23 passed |
| Frontend production build | PASS | PASS |
| Import every app module | Prior P1a check passed | 247/247 imported |

Full backend run: 178.81 seconds, external socket connections blocked by a
local-only test guard; no real model calls. PAI OS contract and authorized
internal escalation regressions are included and passed. Fifty new tests were
added (38 system/runtime tests and 12 workflow tests). No test expectations
were weakened. Temporary guards/dependencies were removed before committing.

### P1b open questions

1. origin/pai-os is not present, so cross-branch import evidence cannot be
   obtained. Shared compatibility facades are kept until that audit is possible.
2. Existing Operator delegate/resume use in-process scheduling. This task adds
   the worker-dispatchable agent.run adapter but does not specify migration of
   scheduling, worker-crash recovery or resume-job deduplication. Scheduling is
   left unchanged rather than inventing a new policy or job type.
3. The existing scoped capability context has no text/file/choice resume-input
   field. Those responses remain saved in run.resume_input; approval and accepted
   facts use their existing host/context paths. No new context field or input
   mutation was invented. A capability needing free-text resume data needs an
   explicit contract decision.
4. services/workflow.py::_judge and routers/routines.py retain the pre-existing
   broken helper references documented under P1a; this task explicitly excludes
   changing them. No live provider calls or end-to-end live evaluation were run.


## P1c: shared Research Gateway and durable Operator runs

This section supersedes P1b's in-process scheduling open question and agent.run
adapter name. Source: CLEAN_ARCHITECTURE.md sections 4/5 and FigJam diagram 3,
https://www.figma.com/board/e3MSmJw0s6wOdGvUubx6SU.

Decision: research.run is the existing program.discover + program.research
family, RequirementStore evidence cache and Source Verifier. It is an
architecture label, not a new capability id. roadmap.build still invokes those
business capabilities through context.capabilities at one level of nesting.
No search, verifier, cache, budget or roadmap-building behavior was rebuilt.

### Moved owners

| Previous | Current | Change |
| --- | --- | --- |
| app/pai_c/research_gateway.py | app/research/gateway.py | Same authorization, Mirror-version budgets, research_key dedupe and workspace lock; trigger attribution added |
| memory.handlers.resume_research / JOB_RESUME_RESEARCH | research.jobs.resume_research / JOB_RESUME_RESEARCH | Same accepted-fact matching and job string memory.resume_research; resume now enters the gateway |
| memory.handlers.refresh_stale_research / JOB_REFRESH_RESEARCH | research.jobs.refresh_stale_research / JOB_REFRESH_RESEARCH | Same stale-source handling and job string research.refresh_stale |
| memory.handlers._deep_foundation_ready / _research_delegate_allowed | research.jobs (private helpers) | Existing research-stage checks moved with their users |
| app/pai_c/light_research.py | app/research/light.py | Pure move; plugin import updated |
| services.operator.run_agent_job / agent.run | services.operator.run_operator_job / operator.run | Durable adapter invokes _execute; policy chooses workflow or agent loop |
| Operator delegate/resume create_task | runtime.task_runtime.enqueue | Same background_jobs and execution_runs tables |

There are no pai_c re-exports for moved research modules. All production/test
imports were updated. Memory enqueues the existing memory.resume_research job
identifier without importing the research package; system contracts resolve it
to research.jobs. scheduler and RequirementStore use the moved refresh constant
and the existing Task Runtime.

### Trigger -> gateway -> run

| Trigger | Producer | Gateway / run |
| --- | --- | --- |
| mirror_confirmed | deep.mirror.confirmed_research_job | request_research(roadmap_light) -> roadmap_research + operator.run |
| student_route | routers.roadmaps add student route | request_research(roadmap_light, roadmap_id) -> roadmap_research + operator.run |
| route_retry | routers.roadmaps retry route | request_research(roadmap_light, roadmap_id, refresh_key) -> roadmap_research + operator.run |
| stale_refresh | research.jobs.refresh_stale_research (reported/expired source queue) | request_research(stale_refresh) -> roadmap_research + operator.run |
| student_answer | research.jobs.resume_research | request_research(..., resume_run_id, resume_action) -> existing Operator resume + operator.run; otherwise existing gated light/stale research path |

Each newly created research run stores the enum in constraints.trigger. A
student-answer resume updates that same run's trigger before queueing it;
accepted-candidate checks remain in Operator.resume. A deduplicated creation
retains the original run's creation trigger and research_key, rather than
creating another run. Existing pending requests, source refresh allowances,
Mirror-confirmation gates and CHOSEN-stage handling are unchanged.

### Durable run lifecycle

- New delegation flushes ExecutionRun, enqueues operator.run with payload
  {run_id}, then commits both in the same transaction. A queue failure cannot
  leave an unscheduled run. Repeated delegation reuses the run/job idempotently.
- The idempotency key is operator:<run_id>:resume:<count>. Initial count is zero;
  accepted resumes store the incremented count in the existing resume_input JSON.
  No migration, additional table, queue, registry or runtime was introduced.
- Resume keeps existing text/file/choice/fact/approval validation and host-approved
  inputs; it commits saved resume state and the new-generation job atomically.
  Declines retain existing failure behavior and do not enqueue execution.
- Worker dispatch reconstructs WorkspaceApi from the scoped workspace row,
  ends its read transaction, and calls the existing _execute. Owned task + object
  capability_input chooses workflow mode; other tasks use the existing loop.
  Resumed execution receives response exactly as before, not the bookkeeping JSON.
- A claimed job survives a crashed process; existing lease reclamation and retry
  rules allow a fresh worker to execute the same persisted run. Finished/failed
  or paused runs are returned without restarting; an old resume-generation job
  is marked superseded without executing the new generation.
- Existing Operator failure handling still records failed runs. Queue/dispatch
  errors retain worker backoff. This does not promise exactly-once external
  effects after a crash; existing capability/cache/tool behavior is preserved.
- The evaluation harness now dispatches the persisted Operator job instead of
  waiting on the removed in-process task set. No live evaluation was run.

### Checks and compatibility

New test_research_spine.py covers atomic scheduling and rollback, queue/run
idempotency, claimed-worker crash/reclaim/restart, resume generations, replay
of completed/failed/paused runs, all five trigger values and attribution,
same-run accepted-fact resume and cross-workspace rejection. AST checks scan all
app modules: research delegation only in research/gateway.py, no research imports
from memory, no create_task in Operator, no old module imports. System registration
checks require operator.run, reject agent.run/research.run, and verify the moved
research handler owners. Existing research/roadmap/PAI OS regressions remain.

Existing asynchronous tests now dispatch the queued job explicitly:
- test_delegation_returns_while_execution_is_still_waiting proves delegation does
  not execute inline and leaves a pending durable job.
- Workflow approval/text resume tests execute that job on the same run.
- Adapter test targets operator.run and confirms _agent_only is absent.
- test_operator_resumes_same_run_and_preserves_completed_actions dispatches the
  queued job; completed-step/action preservation assertions remain unchanged.
- Research/mirror tests use new import targets and assert trigger metadata.
No model-output, permission, research grounding or PAI OS contract assertion was
weakened. _judge and routers/routines.py were not changed.

| Verification | Before P1c (last green P1b baseline) | After P1c |
| --- | --- | --- |
| Backend | 831 passed; 3 production-only skips; 8 subtests | 846 passed; same 3 skips; 8 subtests |
| Frontend | 23 passed | 23 passed |
| Frontend production build | PASS | PASS |
| Import every app module | 247/247 | 248/248 |

Fifteen new research/durability tests passed. Final full backend run: 231.50s.
External socket connections were blocked by the temporary offline test guard;
providers in tests were fake. Full suites include PAI OS contract table/token
checks and the authorized internal-escalation regression. Temporary test guards
and dependencies were removed before the final commit. No .env edits or real
model/provider calls were made.

### P1c open questions

1. No origin/pai-os branch exists to audit. Shared Operator delegate/resume/_execute
   and public queue compatibility names remain; removed private scheduling state
   has been replaced in repository tests/harness consumers. Cross-repository
   consumers must use persisted run/job state.
2. No backfill of pre-existing in-process ExecutionRun rows was specified. New
   runs/resumes are durable; repeating an identical active delegation queues its
   missing job. No startup sweep or recovery policy for old unqueued rows was added.
3. Free-text/file/choice responses remain in run.resume_input. The existing business
   capability context does not expose them separately; defining that context field
   remains a later contract decision. Approval and accepted-fact paths are retained.
4. Chosen-route deep research and the excluded PAI OS broken helpers remain deferred
   exactly as before. FigJam's other future triggers were not added in this task.


## P1d: Memory Service, Messenger and Orchestrator

### Memory ownership

| Facade method | Existing implementation | Callers / ownership |
| --- | --- | --- |
| recent_turns | deep/turn_input.shared_history | Counselor turn, Mirror; same causal chat/voice history |
| profile | StudentSnapshotService.build | context and confirmed-Mirror handoff; one read per context |
| truth_map | NotebookService.get | context, Analyst, Mirror, pre-Mirror sensitive check |
| latest_episode | EpisodicMemoryService.recent | context and Analyst |
| agent_capabilities | permissions.capabilities_for_agent | confirmed-Mirror handoff |
| apply_truth_map | NotebookService.apply | Analyst and sensitive check only; same validation/version locks |
| enqueue_turn_extraction | shared memory.turn_hook | runtime after a successful human reply; unchanged candidate/reconciliation flow |

No new memory store, write ownership or extraction cadence. The facade's extraction
hook is required to remove runtime's direct shared-memory import; it queues the
existing extractor, rather than writing Vault facts. Context retains snapshot
profile, latest episode and notebook open threads, and removes the duplicate
foreground block. No existing test asserted that duplicate block. A new regression
asserts one profile read and the retained memory fields.

### Input entry points

| Caller | Orchestrator entry | Scheduling |
| --- | --- | --- |
| routers/events (chat and delegated voice) | handle_student_message | same FastAPI background task |
| main application review | handle_student_message | same asyncio task |
| services/workflow | handle_student_message | same thread/coroutine runner |
| services/integrations | handle_student_message | same asyncio.run |
| services/operator result handoff | handle_research_result | same awaited result explanation |
| routers/roadmaps focus | handle_roadmap_discussion | same awaited deep turn and post; router keeps exception handling |
| documents/handlers notify | handle_document_update | same queued document job and awaited post |

### Outbound path

Counselor runtime, Mirror, Operator result, roadmap discussion and document notify
use posting.send_to_student -> existing private _post_response -> event pipeline,
commit, Redis, workflow advance and integration relay. Arguments, payloads, voice
metadata and post-commit hooks remain unchanged. Orchestrator wrappers do not change
job scheduling or add model calls. Notifications outside this existing message
pipeline remain unchanged: no new notification design was specified.

### Checks

AST ownership checks cover shared-memory dependencies, private-post imports,
external runtime/handoff/turn imports, Truth Map write callers and Counselor-visible
event construction. Fake-provider regressions cover argument forwarding and one
profile read. Existing tests change only moved patch targets; existing shared-memory
foreground tests remain intact. Model calls per ordinary turn are unchanged: one
Counselor call (optional one blocked-script retry), background Analyst and existing
per-turn memory extraction; sensitivity remains batched before Mirror.

### P1d open questions

- Generic PAI OS workflow/agent events, onboarding welcome messages and independent
  notification producers are not rerouted: this task defines existing Counselor
  entry points and does not specify their shared contracts.
- Semantic retrieval has no new facade method in this task's specified API; no new
  retrieval or memory-writing behavior is added.
- origin/pai-os is absent; public shared services and OS contract tests are retained.

### Approved shared-module signaling

"Shared modules signal PAI C only by enqueueing a named job through the Task
Runtime; they never import pai_c."

The reconciler queues roadmaps.mark_stale with {workspace_id, reason} and
idempotency key roadmap-stale:<candidate.id>, in the same transaction as the
accepted Vault fact/student record and memory.resume_research. The owner is
pai_c/roadmaps/jobs.py; the system capability is installed centrally by the
existing Capability Registry. Its typed contract requires both payload fields,
and its handler rejects a workspace that differs from the job workspace.

The existing RoadmapService.mark_stale implementation is unchanged: same rows,
stale reason, student flags, notification text and dedupe key. The accepted
behavior change is asynchronous invalidation by the worker. Job retries on
already-stale rows do not create another notification. No code moved into
JourneyService, and no new queue/table/runtime was added.

Tests prove one job per accepted vault_fact/student_record candidate, unchanged
ready status until dispatch, matching stale status and notifications afterward,
retry dedupe, transaction rollback and workspace rejection. No existing test
asserted immediate stale status through reconciliation, so no existing expected
behavior assertion needed changing; direct mark_stale tests remain unchanged.

### P1d verification (offline)

| Check | Before P1d | After P1d |
| --- | --- | --- |
| Full backend suite | 846 passed, 3 production-only skips, 8 subtests | 865 passed, same 3 skips, 8 subtests |
| New spine checks | Not present | 17 passed; 2 additional system-capability parameter cases |
| Frontend | 23 passed | 23 passed |
| Production build | PASS | PASS |
| Every app module imported | 248/248 | 251/251 |

No real model/API calls or .env edits. Providers are fake, and the temporary test
guard prohibits external socket connections. Full suites include PAI OS table,
service-token and internal-escalation contract checks. Temporary offline guard and
dependency folders are removed before the final commit. Existing tests change moved patch targets and the system-job catalog (including
the new job's required test payload); existing behavior assertions remain. _judge
and routers/routines.py are untouched.

P1a-P1d spine complete: Model Gateway, Task Runtime/Capability Registry, Research
Gateway/durable Operator runs, PAI C Memory Service, Orchestrator and Messenger.
Remaining future behavior and API decisions are listed above under Open questions.

Final full backend run: 170.68 seconds. The initial catalog assertion failure was
fixed by adding the approved new capability and its required test payload; the
final complete run is green.

## Truth Map v2 (P2a)

### Approved decisions and ownership

The PAI C Memory Service owns access to the Truth Map. The shared memory package
remains facts-only and never imports PAI C or reads interpretation. Existing Vault
rows remain readable; only new extractor proposals change. Research, plugins and
Operator receive interpretation through MemoryService.understanding_summary:
said, source, pressures, self, sure, excluding private fields. The research gateway
builds the brief once; refresh/resume jobs use the same facade.

| Part | Shape | Purpose |
| --- | --- | --- |
| said | Item list | Stated wishes, claims and situation |
| shown | Item list | Demonstrated work, with evidence level |
| source | Item list + generic category | Origins: self/family/peers/media/need/other/unknown |
| pressures | items + people | Generic student-described roles, wishes and concerns |
| self | Item list | Strengths, growth, drivers, values, preferences and limits |
| sure | score/reason/would_raise/asked_at/history | 0-10 or null; every earlier rating retained |

Items: id, key, value, required nonempty evidence, kind, confidence, optional
level, first_seen, last_confirmed, active/retired status, optional vault_fact_ref.
People additionally require evidence and both dates. Objective fact-family keys
require a Vault reference; the Analyst prompt forbids copying objective data.
Free-text semantic ownership is instructed by the prompt, not guessed with a
word list. Private fields: tensions, identity_status, decision_difficulties,
hypotheses, private_notes. Existing open_questions, mirror fields, depth,
engagement, chapter and goal_history remain. Coach data is deferred and archived.

Coverage is said/shown/source/pressures/self/sure. Data-defined requirements:
full = all six; focused = said/shown/source/pressures/sure;
light = said/source/sure. No daily_life prerequisite.
One foundation_ready(truth_map), exposed by MemoryService, requires coverage.said
AND coverage.self. Analyst stage advancement and research jobs use that function.

### Migration 101 (no new tables)

Both counselor_notebooks.notebook and counselor_notebook_history.notebook become
schema_version 2. Every original JSON object is retained verbatim in legacy_v1.
It is immutable at the write boundary, deep-copied on read, hidden from repr and
normal serialization, excluded from context, Analyst schema/input, sensitivity,
research and exporter. Exports expose has_legacy_v1 only. V1 input is rejected.
Current rows lack created_at: use the earliest history.created_at for first_seen,
or updated_at when history is absent; last_confirmed uses updated_at. Each
history row uses its own created_at for both dates. Downgrade restores the archive
and fails safely for new v2 rows with no v1 archive.

| V1 field | V2 mapping |
| --- | --- |
| stated_goal.text | said/stated_goal |
| source_of_goal | source/source_of_goal, normalized category |
| claims | said/claim; level retained; sustained/proven also shown |
| claim.interest_source | source/claim_source with claim text |
| claim.probed | claim item value.probed |
| person.current_situation/location_context/daily_life | said items with same keys |
| strengths/growth_areas | self/strength or growth_area; confidence retained |
| drivers | self/driver; value.text and value.weight |
| values/learning_style/work_preferences | self/value, learning_style, work_preference |
| constraints | self/limit; type/detail/hard retained in value |
| family father/mother/others | pressures.people, roles father/mother/other for migration only |
| family.pressure_level | pressures.items/family_pressure |
| emotional_notes | private_notes |
| hypotheses/open_questions/mirror_blockers/depth/engagement/chapter/goal_history | Retained |
| old coverage | Recomputed from v2 parts; certainty remains unknown |
| old mirror_ready | Cleared: v1 never established v2 certainty coverage |

Source category mapping: reels -> media; friend -> peers; relative/family ->
family; need -> need; own_experience -> self; unknown -> unknown.
Missing migrated evidence uses exactly "migrated from v1 notebook (no evidence recorded)"
with low confidence, kind said and null reference. New items require real nonempty
evidence; a migration placeholder is not new evidence. Unmapped original fields
remain only in legacy_v1: stated_goal.first_said_turn, old coverage, coach, plus
any unknown or additional v1 fields. Original claim ids remain stable in items.

Example: {claim:"Built independently", evidence_level:"proven", probed:true,
interest_source:"own_experience"} becomes said/claim and shown/claim with
value {text:"Built independently",probed:true}, level proven, supporting evidence,
both dates and low confidence unless recorded; source/claim_source category self.
The untouched original entry is also retained privately in legacy_v1.

### Vault boundary and consumer scan

New memory extractor proposals reject student_voice_statement,
external_influence and career.primary_interest. Goal details keep only
stated_preference, target_countries, degree_level, field_of_study, target_intake.
underlying_objective/drivers/constraints/career_direction and other interpretive
goal details are removed before validation. The prompt's supplied extraction
schemas and Vault-field list use the same restriction. Shared record schemas and
legacy reads are unchanged.

| Reader | Change |
| --- | --- |
| deep/context | V2 ordered trimming; archive excluded |
| deep/analysis | V2 schema/context, facade foundation gate |
| deep/mirror + prompt | Existing context builder supplies v2; same mirror output contract |
| deep/sensitive | V2 batching; private archive excluded |
| research/gateway | Public understanding_summary; stated goal from said |
| research/jobs | Same facade gate and summary for refresh/resume |
| deep/roadmaps + prompt | Existing brief now carries v2 public understanding |
| session exporter | Facade reads latest/history and emits v2 + archive flag |
| evaluation harness | V2 replay fixtures and claim-level metrics |
| workspace deletion | Facade lifecycle method, no direct NotebookService import |

Grep found one intentional interpretive write retained: routers/roadmaps.py
stores the student's manually added route why as details.underlying_objective.
This is explicitly unchanged. Shared profile view/student context/snapshot,
records, stewards, voice attribution and Vault intake retain existing-row reads,
as required by the approved decision; none reads the Truth Map.

### P2a open questions

- No additional semantic checker for arbitrary item.value text was specified.
  Structural objective-family keys are checked in code; semantic separation is
  enforced by the Analyst instruction and evidence schema, with no keyword classifier.
- Objective-family validation checks structural keys, not arbitrary prose.
  Analyst profile input now includes the existing scalar Vault ids for references;
  missing references must never be invented. No shared snapshot redesign is included.
- Goal-history's existing source enum remains unchanged as requested. New source
  items use the generic categories; historical source labels remain in goal_history.

### P2a verification (offline)

| Check | Before P2a (clean d944f40 baseline) | After P2a |
| --- | --- | --- |
| Full backend | 865 passed, 3 production-only skips, 8 subtests | 885 passed, same 3 skips, 8 subtests |
| Frontend | 23 passed | 23 passed |
| Production build | PASS | PASS |
| All app modules imported | 251 | 252/252, no failures |

The final backend run completed in 160.91 seconds. Two SQLite reflection warnings
concern an existing expression index; migration assertions passed. Full suites
include unchanged PAI OS decision/request tables, service-token and escalation
contract tests. Dedicated tests cover actual Alembic conversion of both tables,
verbatim archives, v1 rejection, schema evidence/reference requirements,
foundation gating, all depth-mode readiness requirements, Analyst v2 output,
sensitivity/archive separation, certainty history, interpretation ownership,
extractor restrictions, prompt parity and v2 exports with history. Existing
replay/storage/sensitivity assertions are ported to the new field structure.

No live model calls, external test sockets, .env edits, new tables or shared
profile redesign. Ordinary turn model-call counts are unchanged. Temporary test
guard/dependency folders are removed before the final commit. The migration is
verified offline; it has not been applied to the founder's local database.
