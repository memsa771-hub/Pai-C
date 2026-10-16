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


## Episodic and semantic memory (P2b)

| Memory | Writer / trigger | Reader | Owner |
| --- | --- | --- | --- |
| Working | Existing chat/voice message events | Counselor and Analyst | Messenger / Memory Service |
| Vault facts / records | Existing extractor/document candidate -> reconciliation; accepted active rows only are indexed | Snapshot/profile and Analyst recall | Shared memory services |
| Truth Map | Analyst after each successful turn | Counselor, Mirror, session version diff | PAI C Memory Service |
| Episodic | session.sweep -> session.summarize after inactivity | First return turn (last 1-2 summaries), Analyst older-session context/recall | PAI C session capabilities via Memory Service |
| Semantic index | memory.embed for accepted facts/records and session summaries; document.index for chunks | Analyst only in PAI C; existing external readers remain | Existing hybrid index / canonical retriever |

### Session flow

The shared worker periodically enqueues `session.sweep` by name through the
existing Task Runtime, with a time-bucket idempotency key. It never imports PAI C.
The PAI C capability groups persisted owner/PAI messages by the configured
student-message gap. It also detects an older ended session when the student
has already returned. Covered last student events are skipped.

Each uncovered ended session queues one `session.summarize`, keyed by workspace
and last student event. The handler waits for pending session Analyst jobs to
finish, using the existing retry rules. It reads turns and the actual Truth Map
history diff through Memory Service. Private legacy_v1 archives never enter the
diff or model input. The summarizer uses the Model Gateway and records usage.
No database read transaction is held across its model call.

The JSON contains discussed, truth_map_changes, open_threads and commitments.
Changes must match supplied diff entries exactly; commitments must be verbatim
student quotations. Invalid shape, invented changes/commitments or blocked
scripts fail the job for the existing retry policy. Internal prose is English.
A workspace row lock and a session-specific fingerprint protect storage
idempotency in existing pai_episodes, event_type session_summary; source ids
cover student and Counselor turns. Duplicate jobs do not call the model again.
The write and derived embed enqueue are in the same transaction. No message is
posted to the student. On the first return turn, context includes the last two
session summaries; normal turns include none. Legacy episodes stay readable
by existing shared readers, but are not injected into PAI C context.

### Index boundaries and real reader

Before P2b, reconcile/embed and reindex wrote general semantic memories and
all episode types; document chunks had their existing separate writer. After
P2b, new memory vectors represent only active canonical Vault facts/records
and session summaries. Extractor schema and prompt allow only vault_fact and
student_record proposals. Existing semantic/episode rows are not deleted.
Document indexing continues with its existing chunks and capability.

After the reply, the Analyst queries MemoryService.recall with the latest
student message. It uses the existing dense+sparse hybrid MemoryRetriever,
existing reranker and existing PAI_MEMORY_CONTEXT_TIMEOUT_MS budget; unavailable
or timed-out retrieval falls back to workspace-scoped canonical lexical reads.
Hits are re-read from PostgreSQL. Deleted files, inactive facts/records and
missing ids cannot become recall results. Document text is reconstructed from
its canonical artifact rather than trusting stale index text. Recall results
are supplied as semantic_recall in Analyst input. The Counselor fast path
never calls recall or embeds the student query.

| New environment variable | Default |
| --- | --- |
| PAI_SESSION_GAP_MINUTES | 30 |
| PAI_SESSION_SWEEP_SECONDS | 300 |
| PAI_SUMMARIZER_MODEL | PAI_ANALYST_MODEL |
| PAI_SEMANTIC_RECALL_ENABLED | true |
| PAI_SEMANTIC_RECALL_TOP_K | 5 |

Summarizer reasoning uses PAI_ANALYST_REASONING_EFFORT. Shared production compose
passes the new settings to backend and worker; local compose inherits them.
No .env edits. Disabled semantic recall queues no automatic fact/session embed
or document index jobs, skips reindex enqueue/handlers and recall, and guards
Model Gateway embeddings. Existing unindex jobs remain allowed for cleanup.

| Calls per ordinary student turn | Before P2b | After P2b |
| --- | --- | --- |
| Counselor, fast path | 1 (optional script retry) | Same |
| Analyst, background | 1 (optional version-conflict rerun) | Same |
| Vault extractor, background | Existing per-turn call | Same, objective candidates only |
| Sensitive check | Before Mirror only | Same |
| Semantic query embedding | No PAI C reader | Up to 1 per Analyst analysis attempt, never Counselor; 0 disabled/unconfigured |
| Derived source embeddings | General memory/episode batches + document chunks | Accepted fact/record batches + session summaries + document chunks; 0 disabled |
| Session summarizer | None | 1 per ended session (existing retry policy on failure), outside per-turn reply |

### P2b open questions / unchanged items

- Summary prose quality and actual embedding-provider latency are not evaluated
  live; this task explicitly allows only fake models. Grounding of diffs and
  commitment provenance is verified deterministically and offline.
- No new retention/deletion policy was specified; existing workspace deletion,
  episode/index lifecycle and document purge rules remain.
- No origin/pai-os branch was available at fetch. Existing shared public names,
  queue/runtime and PAI OS contract behavior remain; architecture/contract suites
  verify the boundaries. No shared memory module imports PAI C.
- Reindex rebuilds the memory-source set; existing document.index remains the
  document recovery path. No new combined reindex workflow was specified.


### P2b verification (offline)

| Check | Before (a4ea808, isolated tracked-source baseline) | After |
| --- | --- | --- |
| Backend full suite | 885 passed, 3 production-only skips, 8 subtests | 904 passed, same 3 skips, 8 subtests |
| Production-only security gate | Previously included as skips | Separately: 3 passed, 4 subtests |
| Frontend full suite | 23 passed | 23 passed |
| Frontend production build | Existing P2a baseline PASS | PASS |
| App module import graph | 252 (P2a) | 254/254, zero failures |

Final backend full suite: 170.60 seconds. The 19 P2b tests cover ended-session
boundaries, job/storage idempotency, actual history diff and archive exclusion,
student-only commitments, return-visit injection, canonical source filters,
accepted fact/record enqueue, document canonical revalidation and deletion,
Analyst-only recall/query, configured latency fallback, disabled zero embeddings,
summarizer model/reasoning fallback and worker ownership. Existing memory,
research, roadmap, architecture and PAI OS contracts remain green.

Offline test defaults install a NullMemoryIndex; dedicated retrieval tests supply
fake hybrid hits. External sockets were blocked during all suite/import runs.
A declared python-docx dependency was installed in a temporary test folder to
avoid the older system package's fixture failures. The corrected baseline uses
the original tracked code and docs, not edited runtime files. Temporary baseline,
network-guard and dependency folders are removed before the final commit.

No new tables, queue, runtime, .env edits or live calls. No session-specific
truncation/token budget was specified: session input remains complete, with the
existing gateway/provider limits. Provider quality and long-session sizing need
an explicitly authorized later evaluation; neither was invented in this task.


## P2c: Legacy discovery removal and generic field definitions

### Removed modules and callers (Parts 1-2)

| Removed piece | Importer check / change |
| --- | --- |
| memory/profile_completion.py, profile_requirements.py, education_journey.py | Removed student_profile completion endpoints and tools/builtin/memory answer_profile_requirement; removed obsolete completion tests and gap assertions |
| memory/explicit_commands.py, eval_dataset.py, eval_retrieval.py | No production importers; eval_retrieval imported eval_dataset |
| profile_captured | Removed runtime tuple/payload flag, turn hook argument, extraction skip and capability input property |
| profile.answer, memory.remember, memory.forget registry entries | No production callers; Counselor-only audience/manage permissions exclude them from Operator's dynamically discovered read tools |
| CounselorSlotAnswer | Only ORM declaration and offline counselor_eval_support fixture references remained; removed both |
| FoundationChecklist, completion state/type and API methods | Removed the form-based collection UI; existing Profile sections and canonical edit flow remain |

ReadinessService / STAGES remain. The available origin branches at the audit were
main, dev and pai-c; there was no pai-os branch to grep. No shared OS contract,
queue, inference configuration or environment file was changed.

### Migration 102 and pending data check before drop

Migration 102 drops only pai_counselor_slot_answers. Grep found no production
reader/writer before the migration; the historical migration 085 stays unchanged.
Downgrade restores the schema and index, not deleted rows. An offline migration
test proves the other two tables survive.

**Pending data check before drop:** pai_profile_requirements and
pai_profile_field_responses. Both tables and ORM classes remain. Their legacy
service users were removed; no data deletion or retention decision was made.

### Decision 1: retire legacy field keys as data

Migration 103 sets enabled=false for all versions of education.cgpa,
education.backlogs and tests.ielts.score in pai_vault_field_definitions. It deletes
no definitions or facts. Downgrade sets all matching versions back to true, as
specified. Migration 055 remains unchanged. The three entries are removed from
the test seed tuple, rather than relocated into another code/data exclusion list.

| Previous ENTITY_BACKED_LEGACY_FIELDS user | Replacement |
| --- | --- |
| plugins/program_research | list_definitions supplies enabled fields; canonical record schemas remain; requirements/unconfirmed output shape unchanged |
| documents/handlers | list_definitions supplies enabled allowed_keys/field_specs; extraction output shape unchanged |
| memory/handlers | list_definitions supplies enabled allowed_keys/field_specs |
| memory/reconciler | Upsert uses the existing Vault apply_fact -> validate path; missing/disabled definition rejects with no enabled field definition for <key>. Retraction bypasses validation and checks get() only on that path |

No ENTITY_BACKED_LEGACY_FIELDS constant remains. Grade/test/backlog canonical
record schemas and the qualification-recognition plugin contract are unchanged.
The builtin tool example now uses a generic field example.

### Existing fact reads and stopped reader items

The offline retirement regression checks Vault get_fact, snapshot (safe and
internal), history, StudentSnapshotService and StudentProfileView facts after a
definition is disabled. Stored accepted values and provenance are retained.
Migration tests also prove definition rows/all versions and existing fact rows
survive. The student_profile/raw export view uses the internal Vault snapshot.
No reader implementation was changed (only generic wording in Vault comments).

Two boundaries found during the required reader inspection remain unchanged:
- StudentProfileView._safe_field_key/_safe_values hide **issue** field names and
  evidence values when get() finds no enabled definition. The accepted fact is
  still in the Profile facts dictionary. Whether historical issue evidence should
  use its original definition is an open question; no reader fix was authorized.
- export_counselor_session.py exports research_facts_used from roadmap payloads,
  not a standalone Vault snapshot. It has no field-definition filter. Adding a
  Vault history/snapshot export is unspecified and was not implemented.

### Decision 2: preserve currency schemas and written values

Currency remains a string under the existing schemas. _CURRENCY_SYMBOLS is gone.
The recursive normalizer uppercases values of exactly three alphabetic characters;
all other string values are trimmed and preserved, including symbols. It does not
check membership in an ISO list, infer from a symbol, or write null. Examples:
trimmed currency symbol -> same symbol; eur -> EUR; US$ -> US$; somecoin -> somecoin.
The extractor prompt contains the supplied generic ISO 4217 instruction without
currency/country examples. Existing amount/evidence validation remains unchanged.

### Guard and findings for later

The Python-only guard in tests/test_memory_cleanup.py scans memory, pai_c and
journey for the specified retired exam/grade/currency tokens and two currency
symbols, case-insensitively with token boundaries (including identifier separators).
It excludes prompt/fixture data and does not scan plugins or historical migrations.
Retired specifics in comments/docstrings were replaced with generic examples;
there is no additional conversation logic change.

coordinator.py removes only the two exam brands from its language-requirement
regex. Its English-only intent phrases, English-language requirement wording,
ASCII place recognizers and degree-name recognizers are unchanged findings for
later. plugins/qualification_recognition retains its cgpa input key and existing
output behavior for the PAI OS developer; it is deliberately outside this guard.

### Offline verification (Parts 3-4)

| Check | Before (7633b54, Parts 1-2 green) | After Parts 3-4 |
| --- | --- | --- |
| Full backend | 880 passed, 3 production-only skips, 8 subtests | 888 passed, same 3 skips, 8 subtests |
| Production-only security gate | 3 passed | 3 passed, 4 subtests |
| Frontend full suite | 23 passed | 23 passed |
| Frontend production build | PASS | PASS |
| Every app module imported | 248/248 | 248/248, zero failures |
| Dedicated architecture/migration/OS checks | Existing boundaries retained | 9 passed, including 2 OS contract regressions |

Final full backend run: 153.44 seconds. The two existing SQLite reflection
warnings concern an expression index in migration 101. The first full run exposed
an old lifecycle fixture that still relied on the removed exam recognizer;
its input now uses language test, with every lifecycle assertion unchanged.
The final full run includes the disabled-key retraction case as well as upsert.
The document/research-focused run passed 259 tests and 8 subtests before that
additional parameter case; the final focused lifecycle/records run passed 94.

Existing document/research tests confirm unchanged output shapes. New/updated
checks cover disabled-key upsert/retraction rejection, preserved fact reads,
migration 103 all-version retirement/downgrade, the Python guard and currency
cases. All tests use fake providers; a temporary socket guard rejects external
connections. Temporary guard/dependency folders are removed before the last commit.
No live API calls, .env edits, new queue/runtime or reader refactor.


## P3 Round 1 - Step A: concurrent safety gate

Step A is implemented. At its checkpoint Step B (Planner patches/plans) was pending
a decision on bounding the growing Truth Map input; Step B is implemented below.
No existing files were moved, and the Analyst remains unchanged.

### Flow and ownership

Human event -> Memory Service recent turns fetched once -> concurrent safety
classification and normal deep Counselor turn -> post exactly one selected reply
through Messenger. Safety receives text only (current message + last four chat
entries), never a database session. All model calls use the Model Gateway.

| Gate outcome | Posted reply | Turn decision |
| --- | --- | --- |
| none | Existing normal reply | Existing action; classification metadata only |
| concern / urgent | Discard normal reply; generate with wellbeing instructions | move=wellbeing; level and category |
| Error / timeout / invalid JSON | Existing normal reply (fail open) | No classification metadata |
| Wellbeing generation fails | Configured care fallback, plus configured resources if present | move=wellbeing |

The wellbeing prompt reflects feelings, pauses counseling tasks, avoids career
questions, encourages trusted support, follows the student language policy, and
uses configured resources for urgent cases. No resources are invented.
The gate returns only a strictly validated level/category pair; no reasons are
returned, stored or logged. Error logs contain error type only.

### Config and migration

Only the specifically authorized .env.example documentation was edited; .env and
all other .env.* files were untouched.

| Config | Default / resolution |
| --- | --- |
| PAI_SAFETY_MODEL | PAI_ANALYST_MODEL -> PAI_MODEL |
| PAI_SAFETY_REASONING_EFFORT | low |
| PAI_SAFETY_TIMEOUT_MS | 3000 |
| PAI_WELLBEING_RESOURCES | Empty |
| PAI_WELLBEING_FALLBACK_REPLY | Generic care + trusted person / local emergency support |

Migration 104 currently adds nullable safety_level and safety_category to
pai_counselor_turn_decisions. Its downgrade removes these two columns and
preserves existing decisions. The pai_turn_plans table specified for Step B has
not been added yet. The unreachable disabled-definition validation branch was
removed; the existing missing-enabled-definition rejection stays unchanged.

### Calls, timing and offline checks

Normal human turn: one Counselor + one safety call inline, existing Analyst and
extractor in the background. Flagged turn: the normal Counselor call is discarded
and one wellbeing Counselor call is added. Existing language repair remains an
exceptional retry. No live model calls were made.

safety_ms is included in the existing counselor_deep_turn timing log. The gate
runs concurrently, so normal-path waiting is the slower of gate and Counselor,
not their sum. A gate slower than the Counselor can still delay posting until the
classification completes or its timeout expires. This is an inherent limitation
of waiting for classification before posting; concurrency tests verify that a
flagged normal reply never leaks to the student.

The 24 new offline checks cover English and romanized intent/abuse/distress,
ordinary exam/family/career concerns, invalid JSON, timeout/error fail-open,
pre-post concurrency, fallback/resource behavior, the real wellbeing prompt with
fake models, role fallback resolution, text-only input, and migration roundtrip.
Test conftest installs a fake safety provider for existing runtime tests.

### Step B map-budget decision (resolved)

The founder rejected reusing the Counselor trimming function. Step B uses its own
4000-token map budget, newest-confirmed items first with round-robin omission,
and applies patches to the complete stored map. If mandatory content cannot fit,
the analysis is rejected and the last good map/plan remain unchanged.


### Step A verification results

| Check | Before (3a07547) | Step A checkpoint |
| --- | --- | --- |
| Full backend | 888 passed; 3 production-only skips; 8 subtests | 912 passed; same 3 skips; 8 subtests |
| Production-only security | 3 passed; 4 subtests | 3 passed; 4 subtests |
| Frontend | 23 passed | 23 passed |
| Production frontend build | PASS | PASS |
| All app modules imported | 248 | 250; zero failures |
| Focused OS contract + gateway + architecture | Existing green | 54 passed |

Final full backend run: 165.86 seconds. The two existing SQLite expression-index
reflection warnings in migration 101 are unchanged. The dedicated production run
covers the three cases skipped in the normal test environment. All providers
were fake; a temporary socket guard rejected external network connections.
Temporary guard/dependency folders were removed before the documentation commit.
Fixture checks prove routing and prompt contracts, not live-model classification
accuracy; no live classification quality or paid latency measurement was run.


## P3 Round 1 - Step B: Planner patches and next-turn plans

Sources: ARCHITECTURE sections 1/4/6/7, CORE_V1_SPEC F2/F5,
CLEAN_ARCHITECTURE, COUNSELING_METHOD, and the approved architecture/core FigJam
boards wuPJaFgpIJmCfDPI12N1Ed (diagram 3) and 97yQ5hwTjywjMDazpqBUmc.
No existing module was moved. The existing counselor.analyze capability/job keeps
its idempotency, ordering, nonblocking locks, queue/backoff and stage advancement.
Gateway role, model and reasoning remain analyst / PAI_ANALYST_MODEL /
PAI_ANALYST_REASONING_EFFORT. The background writer is now the Planner.

### Bounded view and complete-map ownership

planner/view.py builds a view independent of Counselor _trim_notebook and
PAI_COUNSELOR_NOTEBOOK_CONTEXT_TOKENS. It includes active items only, with id,
key, value, kind, confidence, level, last_confirmed, source category, and evidence
limited to 200 characters. pressures.people, sure (including history), tensions,
identity_status, decision_difficulties, hypotheses, open_questions, coverage,
depth_mode and engagement_style are always included; private_notes is limited to
1000 characters. Private legacy_v1 is never included, even in model schema.

When over budget, each part (said/shown/source/self/pressures.items) loses its
oldest-confirmed item in turn, stopping before the part becomes empty. Token
count uses the existing estimated_tokens over the serialized map plus its tags
and omitted_items counts. Newest-confirmed items survive. Offset dates are
compared chronologically; accepted naive historical dates are treated as UTC for
ordering only, without rewriting stored values.

If mandatory fields plus one item per nonempty part cannot fit, return
input_rejected without any model call or map/plan write (founder decision).
Otherwise the Planner receives the bounded view, omitted counts, schemas,
existing compact profile, latest session summary, semantic recall, and the last
PAI_PLANNER_HISTORY_TURNS chat entries. Existing 1500-character chat caps remain.
The fixed schema/profile/summary/recall blocks are separate from the map budget.

### Atomic patch operations

| Operation | Validation and effect |
| --- | --- |
| add | Allowed part; required evidence/kind/confidence; category source-only; code assigns UUID and both timestamps |
| update | Visible id only; required evidence; optional value/confidence/level; code updates last_confirmed |
| confirm | Visible id only; required evidence; code updates last_confirmed |
| retire | Visible id only; nonempty reason; status becomes retired, never deleted |
| upsert_person | Role match case-insensitive; required evidence; first_seen retained on update, dates assigned by code |
| set_sure | Strict integer 0-10 must appear in latest student message; evidence required; previous rating retained in history; asked_at assigned by code |
| set_private | Only the eight specified private fields; strict resulting notebook schema |
| set_coverage | Six parts; true requires active evidence (people count as pressure evidence); sure requires a score |

The patch is applied to a copy of the complete stored map. update/confirm/retire
cannot reference an unknown, retired/hidden or omitted id. Unmentioned items,
including omitted items, remain unchanged. Every operation and the whole result
are validated, then existing sanitize_notebook and enforce_mirror_readiness run.
No lenient partial patch is saved. Code-generated dates/ids cannot be supplied by
the model. Existing v2 notebooks and private v1 archives remain readable/lossless.
Retirement reasons and rating evidence validate their operations; no new item or
rating fields were invented to store them separately.

Invalid patch/JSON logs only op index and error type, then retries once with that
safe error appended. A second rejection returns patch_rejected with no writes.
Provider failures keep existing worker retry behavior. An optimistic version
conflict still refetches and re-runs once; any uncommitted plan is rolled back.

### Plan contract and storage

Strict TurnPlan: next_move understand/tell/both/care; intent <=200 characters;
target_gap said/shown/source/pressures/self/sure or null; give <=200 characters;
avoid_questions up to five strings; playbooks must be []. If the latest causal
workspace turn decision is wellbeing, code forces care and target_gap=null.
Invalid plans are not saved and do not discard an otherwise valid patch.

Migration 105 (down_revision 104) creates pai_turn_plans:
id UUID PK, workspace_id UUID FK workspaces (cascade), source_event_id text FK
 events (cascade), notebook_version integer, plan JSONB, created_at timestamptz;
unique(workspace_id, source_event_id). Downgrade drops only pai_turn_plans.
Migration 104 is unchanged. Plans and notebook versions commit together through
the existing notebook transaction. Workspace deletion purges plans too.
MemoryService.latest_plan reads the latest valid stored workspace plan;
Counselor context includes next_move, intent, give and avoid_questions only.
The requested one line was appended to counselor.md; no other Voice rewrite.

planner/prompts/planner.md replaces deep/prompts/analyst.md, preserving six-part,
evidence/levels, Vault, privacy, coverage, rating and student-data rules. Runtime
loader and prompt-document tests now use planner. Before deletion the importer
check found only the loader/analysis plus two prompt tests and prompt docs; those
were updated. Historical architecture/restructure references remain historical.
COUNSELOR_V3_PROMPTS sections 1/2 match both runtime prompts.

### Config and model-call count

Added PAI_PLANNER_MAP_CONTEXT_TOKENS=4000 and PAI_PLANNER_HISTORY_TURNS=12,
documented in .env.example only. Removed PAI_ANALYST_HISTORY_SIZE from code and
startup validation; it was already absent from .env.example. No .env or other
.env.* file was edited.

| Turn path | Before Step B | After Step B |
| --- | --- | --- |
| Normal human turn inline | Counselor + safety | Same |
| Flagged human turn inline | Counselor + safety + wellbeing Counselor | Same |
| Background normal turn | Analyst + extractor | Planner (same analyst role) + extractor |
| Semantic recall embedding | Existing configured reader | Same; disabled switch still makes zero calls |

Patch correction or version conflict can cause exceptional Planner retries;
existing language repair and provider retry behavior remain unchanged.
No sensitive-check call was added per turn; existing pre-Mirror checking remains.

### Offline size evidence and fixture changes

Synthetic context-only estimates (UTF-8 bytes/4, excluding fixed system prompts;
50 active map items; 1500-character student messages):

| Exchanges | Old chat entries | Old context tokens | New chat entries | New context tokens |
| --- | --- | --- | --- | --- |
| 12 | 24 | 16371 | 12 | 9954 |
| 100 | 60 | 23954 | 12 | 9954 |

The map view was 3973 tokens at the 4000 budget, with omitted counts
said=5, shown=5, source=4, self=4, pressures.items=4. These are estimates from
fake data, not live provider usage or a cost measurement.

Historical offline full-map recordings remain unchanged as data. The replay-only
scripts/eval/recorded_planner.py adapter produces valid patches referencing ids
from the actual bounded view. Fake helper schemas now include pai_turn_plans.
Tests that previously asserted partial sanitization now assert whole-patch
rejection. Goal switching is checked in immutable notebook versions; goal_history
is preserved but is not a writable patch field in this round. Ordering, stage,
conflict, sensitive-check and PAI OS behavior assertions remain intact.

### Open questions and findings for later

No blocking open questions remain. The impossible-budget case follows the
founder's explicit rejection decision.
- Counselor's own _trim_notebook remains unchanged; its selection policy belongs
  to the later Voice work, not this Planner implementation.
- Fixed input overhead includes full validation schemas; the independent map
  budget is not a total request-token budget.
- The session exporter was not extended to include plans; no export redesign was
  requested in this round.
- Historical architecture/restructure docs still mention the deleted Analyst
  prompt as an old path; runtime imports and current prompt docs do not.


### Step B verification results

| Check | Before (5f51b23) | Step B |
| --- | --- | --- |
| Full backend | 912 passed; 3 production-only skips; 8 subtests | 962 passed; same 3 skips; 8 subtests |
| Production-only security | 3 passed; 4 subtests | 3 passed; 4 subtests |
| Frontend full suite | 23 passed | 23 passed |
| Frontend production build | PASS | PASS |
| All app modules imported | 250 | 254; zero failures |
| Dedicated OS contract/gateway/spine checks | Existing green | 71 passed |

Final full backend run: 245.87 seconds. Two existing migration-101 SQLite
expression-index reflection warnings are unchanged. No live model/API evaluation
was performed. All model tests used fake providers; the temporary socket guard
rejected external connections. Temporary guard and dependency folders were
removed before the final documentation commit.

The 50 new Planner checks cover all eight ops, atomic rejection and correction,
unknown/omitted ids, evidence, UUID/date ownership, student certainty, coverage,
per-part retention/newest-first omission, mandatory-input rejection without calls,
unchanged omitted items/private archives, bounded 100-exchange input, strict plans,
care override, previous-plan fallback, workspace deletion, version-conflict plan
rollback, migration-105 upgrade/downgrade, and accepted mixed-format dates.
Existing prompt parity, v2 migration/loading, ordering, idempotency, stage,
sensitive-check, disabled embedding, chat/voice and PAI OS regressions remain green.

## P3 Round 2: Planner fixes, Voice v4 and playbooks

The Round 2 task supersedes Round 1's impossible-budget rejection decision.
References checked: CORE_V1_SPEC F3/F4, COUNSELING_METHOD, ARCHITECTURE 3/4,
architecture FigJam diagram 3 and the vision board Planner/Voice/playbooks.
No live model/API evaluation was performed.

### Fix first

- Active-item omission still takes turns across the five item lists, removes the
  oldest last_confirmed first and keeps one item in each nonempty part.
- If mandatory content still exceeds the map budget: remove rejected hypotheses;
  keep the last 8 hypotheses, last 6 tensions, last 6 decision_difficulties,
  first 3 open_questions, then cut private_notes to 500 characters. Check the
  budget after each operation and stop trimming when it fits. The founder
  confirmed that "newest" private entries means last in stored list order.
- If still over budget, proceed and log only planner_input_over_budget tokens=N.
  There is no input_rejected/zero-call path. The view never alters stored data.
- set_private rejects the whole patch when hypotheses exceeds 8, tensions or
  decision_difficulties exceeds 6, or open_questions exceeds 3. The Planner prompt
  states these caps; code owns mirror blockers.
- PAI_PLAN_MAX_AGE_TURNS=3: latest_plan is absent once more than three later human
  workspace.message.posted events exist in the workspace. Assistant messages do
  not age a plan. The latest plan still undergoes strict validation.

### Voice v4 and outbound contract

| Owner | Change |
| --- | --- |
| voice/prompts/voice.md | Supplied Voice v4 text verbatim |
| deep/prompts.py | Registry name voice; Voice path replaces the deleted counselor.md |
| deep/turn.py | Same gateway counselor role/model; reply, moves, action parsing and guards |
| runtime.py | Stores moves and guard_violations; logs moves instead of reply_without_question |
| migration 106 | Nullable JSONB moves on pai_counselor_turn_decisions; downgrade drops only moves |

Moves are reflect/affirm/give/summarize/ask. Missing or malformed moves become [];
unknown values are dropped. Action handling remains unchanged. The final model's
moves are stored as its declarations, including when deterministic polish removes
text; they are not a judge's independent assessment.

Before deleting the old prompt the importer/reference check found the prompt
registry, deep/turn.py, scripts/eval/counselor_smoke.py, prompt loader/parity tests,
and current prompt docs. All active loaders now use voice. Historical architecture,
cleanup and restructuring references remain historical. COUNSELOR_V3_PROMPTS
sections 1/2 match runtime Voice and Planner text.

Repetition guard: find question sentences with polish._question_positions and
Unicode sentence terminals; casefold, remove Unicode punctuation, split on
whitespace; token Jaccard similarity. Compare against the last configured window
of Counselor questions in recent history and the valid plan's avoid_questions.
Defaults: PAI_REPEAT_QUESTION_WINDOW=5, PAI_REPEAT_QUESTION_SIMILARITY=0.6.
On a match, append the reviewer's exact retry line and make one Voice retry.
If that draft repeats, remove its repeated sentence when other text remains;
otherwise retain the retry draft as requested. Record repeated_question and,
when removal happens, repeat_removed. Never run this guard on wellbeing replies.

Language policy, polish and language_retry.md are unchanged. At most one language
repair is allowed across the whole turn, including repetition repair. A normal
Voice turn makes one call; repetition adds at most one and language repair adds
at most one. Combined failures therefore make at most three Voice calls, then use
the existing configured blocked-script fallback. Every call retains gateway usage
logging and the same shared chat/voice posting path.

### Playbooks

playbooks/registry.py loads local front matter and bodies at startup (API lifespan
and the worker's existing system-capability imports). It validates unique nonempty
ids, version 1, nonempty when/body, and body <=120 whitespace-separated words.
The loaded registry is immutable. All supplied when/body text is verbatim.

The Planner system input appends <available_playbooks> with id + when. A TurnPlan
can select at most two installed ids; unknown ids invalidate the plan. Context
includes full selected bodies in <playbooks>, with no block for an empty selection.
Explicit wellbeing context and care plans omit playbooks. The standard Voice prompt
still names the block; wellbeing calls receive none of its selected content.

Replay fixtures (one four-message anonymised English conversation per id):

| Playbook and fixture stem | Moment |
| --- | --- |
| impatient | Hurry or frustration with questions |
| short_answers | Minimal answers |
| parent_speaking | Another person speaks on the account |
| sure_not_explored | Commitment without direct experience |
| no_idea | No clear direction |
| family_conflict | Student and family wishes differ |
| setback | Rejection or disappointing result |
| returning | Return after a gap |
| facts_only | Wants facts and resists personal exploration |
| goal_switcher | Changing goals |

Files are playbooks/<id>.md and tests/fixtures/playbooks/<id>.json. The existing
retired-specific-token and documentation-persona guards now include playbook texts.
The judge remains deferred; fixtures are stored for replay, not live evaluations.

### Configuration and calls

Only .env.example documents the three requested new settings (3 / 5 / 0.6).
No .env or any other .env.* file was edited. Settings have env overrides and startup
validation; role models and other configuration defaults are unchanged.

| Path | Before Round 2 | After Round 2 |
| --- | --- | --- |
| Normal human turn inline | Voice + safety | Same |
| Flagged human turn inline | Normal Voice + safety + wellbeing Voice | Same |
| Background normal turn | Planner + Vault extractor | Same |
| Repeated question | No dedicated guard | Up to one extra Voice call |
| Blocked script | Up to one repair call | Same, shared across all drafts |
| Planner mandatory input above budget | Zero-call rejection | Trim then one call (normal valid output) |
| Playbook selection/loading | None | No additional model/embedding call |

### Findings for later

- Token Jaccard at 0.6 can flag different short questions sharing most tokens;
  it also does not detect every semantic paraphrase. Keep the requested algorithm.
- Always-retained content can still exceed the map budget. The task explicitly
  requires proceeding, so this is a soft budget rather than a hard token cap.
- Counselor _trim_notebook selection is unchanged; Round 2 did not request a
  replacement for that separate Voice context projection.
- When removing a repeated question would leave no text, the requested fallback
  intentionally leaves that question. Moves remain model-declared labels.
- Conversation quality/OARS cadence needs the later replay judge or an explicitly
  authorized evaluation. Offline checks prove mechanics, not live counseling quality.

No blocking Open questions remain. Private-list ordering follows the founder's
explicit answer; .env.example is the task's explicit documentation exception.

### Round 2 verification

| Check | Before (047b638) | After Round 2 |
| --- | --- | --- |
| Full backend | 962 passed; 3 production-only skips; 8 subtests | 1003 passed; same 3 skips; 8 subtests |
| Production-only security | Existing green | 3 passed; 4 subtests |
| Frontend full suite | 23 passed | 23 passed |
| Frontend production build | PASS | PASS |
| All app-module imports | 254 | 258; zero failures |
| Dedicated OS/gateway/spine checks | Existing green | 71 passed |

Baseline backend duration: 276.84 seconds; final backend: 280.99 seconds.
The two existing migration-101 SQLite reflection warnings are unchanged. The
three conditional skips were run separately with APP_ENV=production and passed.
External connections were blocked by a temporary socket guard; every model test
used fake providers. No live evaluation, spend or model-quality claim was made.

New regression coverage: ordered private trimming and whole-patch caps; plan
expiry; oversized private content still produces one Planner call and remains
unchanged in storage; moves parsing and persistence; Unicode punctuation and
near-duplicate questions; history window and avoid_questions; one repetition
retry, removal and empty-result behavior; wellbeing exclusions; combined guards
with only one language repair; migration-106 upgrade/downgrade; registry validation,
strict plan selection, actual context bodies, startup loading and ten replay files.
Existing history/job tests keep their behavior assertions: the repeated-question
fake was changed to a permitted reflection, and safety fakes gained the new result
fields. The obsolete missing-question warning test now asserts no such warning.
Temporary offline/dependency folders were removed before the verification commit.


## Core R1: Living Student Model v3 and Request Intake

Scope: Board A `tyIdCoQrgJxPOcIvFWNt1L`, Board B `MOJ1Efh5LWzYDZFy0W3VsX`,
and Board C `97yQ5hwTjywjMDazpqBUmc`. One Counselor retains UNDERSTAND ->
DISCOVER -> GUIDE; execution remains PAI OS. R1 adds storage and read-only
projections, not a controller, opening rewrite, new Mirror, discovery pipeline,
roadmaps, UI pages or OS life events. No model calls or environment changes added.

### Approved R1 boxes -> code

Paths are relative to `backend/app/` unless stated otherwise.

| Board / R1 box | Code owner |
| --- | --- |
| A Every turn: Request Intake, store request | pai_c/deep/actions.py, noted_questions.py; runtime.py supplies the committed reply event id |
| A Background: Understanding Engine, Truth Map patches | pai_c/planner/patch.py, view.py, prompts/planner.md |
| A Background: Evidence and hypothesis levels | pai_c/deep/notebook_schema.py; understanding/policy.json; existing private hypothesis contract retained |
| A Living Student Model: six parts + WORLD; B Living Student Model; C same six parts | pai_c/deep/notebook_schema.py, migrate_v2.py; alembic/versions/107_truth_map_v3.py |
| A Living Student Model: Requests and noted questions | models.CounselorNotedQuestion; pai_c/deep/noted_questions.py; alembic/versions/108_counselor_request_intake.py |
| A Academic profile | pai_c/understanding/views.py academic_view; MemoryService.academic_view |
| A Personal profile | pai_c/understanding/views.py personal_view; MemoryService.personal_view |
| A Capability and development profile | pai_c/understanding/views.py capability_view; MemoryService.capability_view |
| B Current status; Background/history; Interests/hobbies; Strengths/difficulties | understanding/areas.json; views.coverage_areas; MemoryService.coverage_areas |
| B Family/social/support; Motivations/values; Pressures/constraints; Certainty | Same data-driven coverage reader |
| B Came with a request: storage side only | noted_questions.py; deep/context.py open_requests; reply-choice policy deferred to R2 |

### Schema and evidence

| Field | Stored shape / validation |
| --- | --- |
| schema_version | 3 |
| said, shown, source, self, sure | Existing shapes; source categories and certainty 0-10/history unchanged |
| pressures | items only; people moved into world.people |
| world | people, social, daily_life, responsibilities, education_story |
| world.people | Person: id, role, relation, occupation, relationship_note, wish, worry, influence, supportive, evidence, first_seen, last_confirmed, status |
| Person enums | relation parent/sibling/relative/partner/friend/mentor/other; influence low/medium/high/unknown; supportive true/false/null; status active/retired |
| Person provenance | Required nonempty role/evidence; Planner code assigns UUID/dates; upsert matches role case-insensitively; existing person must be visible |
| Other four World lists | Existing Item schema, including evidence/kind/confidence/level/dates/status and Vault references |
| Item.capability_status | Optional demonstrated/emerging/untested/development_need/blocked |
| Demonstrated rule | kind shown/document/action OR level sustained/proven, loaded from understanding/policy.json. Said with absent/claimed/tried level is rejected. This is the prompt's explicit OR rule, not a new ability score. |
| Values / motivations | SELF key prefixes value. and motivation., described in Planner prompt |
| Private interpretation / readiness | Existing fields and six coverage flags unchanged; new eight areas do not drive readiness |
| Private archives | legacy_v1 and legacy_v2 are read-only, excluded from model schema/input and views; exporter exposes only presence flags |

Planner adds the four World item paths and people to its bounded view. It keeps
newest-confirmed entries, omits oldest round-robin, and retains at least one per
nonempty part, including people. The existing Round 2 soft-budget behavior and
private-field trimming remain unchanged. update/confirm/retire require visible
ids and apply atomically to the complete map. Hidden/unmentioned items survive.
The prompt includes the required invented-person prohibition verbatim.

Founder clarification: Voice's existing notebook block includes world.people at
the former pressures position, followed by daily_life, social, responsibilities,
education_story, then pressure items. The same _trim_notebook function, budget,
shortening and existing private-field selection remain; retired items are excluded.
No Voice prompt text changed. A migrated role/wish/concern remains visible as
role/wish/worry. This does not guarantee retention of every item when the existing
context budget is exhausted; context redesign remains R2.

### Migration behavior

- 107, down_revision 106: converts every current notebook and history row, moves
  concern to worry, assigns stable person ids, sets relation other/influence
  unknown/supportive null, and stores the complete original JSON in legacy_v2.
  Earlier legacy_v1 remains private and lossless. All other v2 fields are retained.
  Downgrade restores each archived original exactly. As with migration 101,
  downgrading a newly created notebook with no prior-version archive fails rather
  than silently discarding data; no new reverse-conversion policy was invented.
- 108, down_revision 107: adds kind (default information), needs_research (default
  true), answered_event_id (nullable text) to counselor_noted_questions. Existing
  rows and status strings remain unchanged. Downgrade removes only the three
  new columns; rows/statuses survive, but their new metadata is lost.
- Both revisions are tested offline. The founder's local database was not migrated
  or rebuilt during this task.

### Computed coverage: committed areas.json

```json
{
  "status": [{"vault_field_prefixes": ["identity."]}, {"path": "world.daily_life"}],
  "history": [{"path": "world.education_story"}, {"path": "shown"}, {"vault_records": ["education", "test_attempt", "document"]}],
  "interests": [{"path": "self", "key_prefixes": ["interest."]}, {"path": "world.daily_life"}],
  "strengths": [{"path": "self", "nonempty": "capability_status"}, {"path": "shown", "nonempty": "capability_status"}],
  "family_social": [{"path": "world.people"}, {"path": "world.social"}],
  "values": [{"path": "self", "key_prefixes": ["value.", "motivation."]}, {"path": "source"}],
  "pressures": [{"path": "pressures.items"}, {"path": "world.people", "nonempty": "worry"}],
  "sure": [{"path": "sure", "not_null": "score", "timestamp": "asked_at"}]
}
```

The reader loads this JSON at use time. It counts distinct active items in any
listed location; Vault data comes from the existing accepted/active snapshot.
identity.* is the actual Vault field family. A non-null certainty score, including
zero, counts. Each area returns covered, item_count and the latest last_confirmed
(or Vault updated_at/valid_from/created_at or certainty asked_at), otherwise null.
Editing the mapping changes results without changing code. No model writes these
computed fields; they are evidence coverage, not a questionnaire or completion gate.

### Derived views (no tables, no writes)

| View | Exact field selection |
| --- | --- |
| academic_view | records.education, records.test_attempt, records.document; education_story from world |
| personal_view | world (all five active lists); self items without capability_status; source; pressures.items; sure including history |
| capability_view | All active items with capability_status across policy item_paths, grouped under the five status keys; full item evidence/kind/level preserved |

Views return copies. No tensions, hypotheses, identity_status,
decision_difficulties, private_notes or legacy archives are included. Profile
queries remain behind MemoryService; shared memory never imports PAI C.

### Request lifecycle (founder-corrected vocabulary)

Policy: deep/request_policy.json. Kinds: information, task, decision_help, other.
Statuses: open, answered_now, answered, unanswered, handed_off, dropped.
There is no researched status and no rename/migration of existing research statuses.

- note_question defaults to information + needs_research true -> open.
- needs_research false -> answered_now, only with the actual posted PAI reply id
  validated against the same workspace and assistant-message source/type.
- Existing source-event dedupe and student ownership checks remain.
- open_requests contains newest five open rows only, text + kind, workspace scoped.
- Research still selects open/unanswered; additionally needs_research must be true.
  Existing roadmap publication still writes answered/unanswered with sourced facts.
- answered_now never enters research. handed_off/dropped are vocabulary only;
  R1 adds no code that writes them. pai_student_requests remains untouched.

### Verification

| Check | Before R1 | Step A | Final Step B |
| --- | --- | --- | --- |
| Full backend | 1002 passed, 3 skipped, 8 subtests | 1021 passed, 3 skipped, 8 subtests | 1036 passed, 3 skipped, 8 subtests |
| Production-only security (separate environment) | Conditional in baseline | 3 passed, 4 subtests | 3 passed, 4 subtests |
| Frontend | Unchanged source | 23 passed | Same verified frontend source: 23 passed |
| Production frontend build | Unchanged source | PASS | Same verified frontend source: PASS |
| Import every app module | Existing source baseline | 261/261 | 261/261, no failures |
| Architecture boundary regressions | Existing checks | Included in full suite | Dedicated 9 passed |
| PAI OS contracts | Existing checks | Included in full suite | Dedicated 2 passed |

Baseline backend duration: 251.71s; final Step A: 231.44s; Step B: 249.42s.
Three SQLite reflection warnings concern the existing expression-based user index
in migration tests (101 and 107); all migration assertions passed. The three
production-only skips were separately executed and passed. External network
connections were blocked for every backend/import run; providers were fake.
Frontend tests and build ran after Step A; Step B changes no frontend source or
configuration. No temporary repository test folders or environment edits.

Nineteen new Step A cases cover migration/history roundtrip, immutable archives,
capability policy and atomic rejection, data-edited coverage, view field/privacy
selection, all World patch paths, people visibility/omission, preserved family
context and unchanged readiness/private interpretation selection. Fifteen Step B
cases cover kinds/defaults, real posted-event binding, dedupe, invalid metadata
and reply provenance, scoped newest-five context, research exclusion and migration
108 roundtrip. Existing research publication additionally checks both answered
and unanswered writes; PAI OS table names, service-token authentication and
escalation behavior remain green.

Commits: Step A `934b580`; Step B `412e7f4`. The final documentation commit records
these results. Normal/exceptional model and embedding call counts are unchanged;
R1 adds only deterministic validation, storage metadata and read-only projections.

### Open questions / findings for later

- No blocking implementation question remains after the two founder decisions.
- A downgrade policy for notebooks created entirely under v3 (no legacy_v2)
  was not specified; downgrade refuses those rows, following the existing safe
  archive-only migration pattern. A future reverse mapping needs approval.
- Existing Mirror/roadmap prompts still describe v2, and the research
  understanding_summary keeps its existing five-part selection. Updating these
  readers/prompts to explicitly use World is outside R1's permitted changes.
- Existing Voice identity formatting checks unprefixed field names, while the
  Vault stores identity.*. R1 coverage uses the actual keys; the separate Voice
  formatting issue is left unchanged for the context redesign.
- Existing one-noted-request-per-source-event uniqueness remains; multiple
  separately tracked requests in one message were not specified.
- Offline tests prove contracts, privacy and mechanics, not live model extraction
  or counseling quality. No live model/API evaluation or paid calls were made.

## Core R2 — Conversation Value Controller and opening

Implemented on `pai-c`, starting at `0d49fb0`. The three supplied FigJam boards
were read; R2 implements only the boxes below. Mirror v2, possibility discovery,
exploration roadmaps and OS life events remain outside this round.

| Board box | Owner/code |
| --- | --- |
| A: Safety gate / Every turn | `backend/app/pai_c/policy/classifier.py`, `policy/prompts/turn_classifier.md`; replaces the separate safety call |
| A: Conversation Value Controller; B: What does the student need now? | `policy/controller.py`, `policy/state.py`, `policy/decision_table.json`, `policy/areas_policy.json` |
| A: Voice LLM writes the reply | `voice/prompts/voice.md` v5, `deep/context.py`, `deep/turn.py` |
| A: Guards | `deep/turn.py`, existing `voice/guards.py` and `deep/polish.py` |
| B: Came with a request — help, then invite | Classifier request -> `deep/noted_questions.py`; answer/invite instructions in policy/actions |
| B: Sharing / gap / pattern / answer / deciding / periodic summary | First-match decision rows below and their action instruction files |
| B: Picture clear | Controller mirror decision -> existing readiness validation and Mirror job, unchanged |
| B: Opening — tell me about yourself | `memory/onboarding.py` named enqueue -> `pai_c/opening.py` -> Messenger; existing frontend working indicator |
| C: Core Truth Map | Existing R1 map, computed coverage and latest valid Planner plan; no R2 map shape change |

### Hermetic tests

`tests/conftest.py` fails an unpatched provider-client creation and a Session bound
to the application's database engine or a non-test database. Tests bind isolated
SQLite engines; production-only API surface tests run separately with fake inputs.
Verification launchers disable dotenv loading and block external socket connections.

The guard exposed two database-dependency leaks:
`AuthBoundaryTests.test_desktop_session_refresh_rotates_previous_pai_token` and
`test_voice_route_is_mounted`. Both now override the request DB dependency with a
test double and restore dependency overrides afterward. The requested
`test_answered_now_uses_actual_posted_reply_and_is_idempotent` already inherited a
global safety fake; it now explicitly fakes the classifier at its own call site.
Three boundary regression tests prove provider rejection, production-session
rejection, and acceptance of a factory bound to the test database.

### Classifier, latency and request ownership

One sequential classification precedes the controller and Voice. Input is only
the latest student text plus four prior text turns. Strict, extra-forbidden
validation covers safety, intent, emotion, request, mentioned areas and declined
area. Error/invalid JSON/timeout uses the committed `classifier_fallback.json`
(none/sharing/neutral, no request or areas); logs contain error type, not text.
The Voice retains its safety instruction. Classified care routes directly to the
existing wellbeing reply and fallback, with no discarded ordinary Voice call.

| Config | Default / resolution |
| --- | --- |
| `PAI_CLASSIFIER_MODEL` | safety -> analyst -> base model fallback |
| `PAI_CLASSIFIER_REASONING_EFFORT` | low |
| `PAI_CLASSIFIER_TIMEOUT_MS` | 4000 |
| `PAI_SUMMARY_EVERY_TURNS` | 4 |
| `PAI_STATEMENT_FALLBACK_REPLY` | Founder-approved statement below |
| `PAI_OPENING_FALLBACK_REPLY` | Founder-approved named opening |

`classifier_ms` is logged beside existing turn span timings. The sequential
classifier can add up to its configured four-second timeout before the Voice.
No live latency or quality result is claimed. Requests are inserted before Voice
with source-event uniqueness; after an answer_request reply is actually posted,
non-research requests become answered_now with that reply's validated event id.
The Voice's note_question cannot add a second row for the same student event.

### Committed decision and area policy

Authoritative executable data (including the full no_repeat post-check):
[decision_table.json](../../backend/app/pai_c/policy/decision_table.json) and
[areas_policy.json](../../backend/app/pai_c/policy/areas_policy.json).
Tests edit each file in isolation and demonstrate changed decisions with unchanged
Python code. First match wins in this exact order:

| rule_id | Condition | Action | Question allowed |
| --- | --- | --- | --- |
| care | safety concern/urgent | care | false |
| adjust | pushback | adjust | true |
| answer | request and asking_info/asking_task | answer_request, topic request | needs_context |
| guide | deciding | guide | true |
| mirror | mirror_ready | mirror | false |
| summarize | summary_due | summarize | true |
| listen | stressed/frustrated | listen_reflect | false |
| rest | previous two replies asked questions | insight if available, otherwise listen_reflect | false |
| choice | short_reply streak >=2 and askable area | ask_choice | true |
| ask | askable area | ask | true |
| default | always | insight if available, otherwise listen_reflect | false |

Area priority: status, interests, history, family_social, values, strengths,
pressures, sure. Choose uncovered candidates: latest mentioned area first,
previous mentioned area second, then priority. Declined areas cool down for 12
student messages. Family/social waits for three messages and pressures for four,
unless mentioned in the latest or previous message. The committed topic texts
are verbatim. Summary requires two covered areas and the configured cadence;
invite is once per workspace and only while fewer than three areas are covered.
Latest plan selection retains the existing validation and expiration checks.

The founder-approved `no_repeat` post-check compares action AND topic (null equals
null). It never changes question_allowed from false to true. Repeated statement
reflection becomes insight when available, otherwise remains a reflection;
repeated insight becomes reflection. Repeated ask/ask_choice uses another askable
area, or becomes an insight/reflection without a question. Repeated adjust uses
ask or summary; repeated summary uses ask or insight/reflection. Care, mirror,
answer_request and guide are exempt. The rule suffix `+no_repeat` is recorded only
when the decision changes.

### Voice instructions, guards and log

`policy/actions/` contains answer_request, invite, listen_reflect, insight, ask,
ask_choice, summarize, guide, adjust, mirror, and opening. Care uses the existing
wellbeing prompt. The insight text uses `insight_candidate` from `<decision>` as
approved; there is no `<plan>` block. `<decision>` carries the instruction, topic
text/request, question permission, avoid_questions and insight_candidate.
Playbooks remain style notes. Voice v5's prefix is verbatim; the scope, grounding,
language, safety and output sections are preserved. The runtime prompt and prompt
reference document match.

The controller chooses WHAT; Voice chooses HOW. A prohibited question is removed
by sentence boundaries; if nothing remains, one retry receives the exact
question_retry instruction. Language and repetition checks share that same retry
allowance: at most two Voice calls in total. Care bypasses these guards.
If both drafts contain only questions, the configured statement is posted:

> Thank you for sharing that with me. I'm taking it in, and I'll keep it in mind as we continue.

Startup rejects an empty statement, Unicode question marks, or blocked script.
`statement_fallback` is stored both in guard_violations and the decision object;
it is never used for care. Offline tests verify the actual posted text and log.

Migration **109**, down_revision **108**, adds nullable JSONB `decision` to
`pai_counselor_turn_decisions`. Downgrade drops only that column. Existing rows
remain. The decision stores rule/action/topic/flags and the permitted signal
metadata, never student text; request topic is the literal `request`.
Session export includes the decision alongside each event's existing decision
records. Roundtrip migration and exporter tests pass.

### Founder replay (corrected replay semantics)

Fixture: `backend/tests/fixtures/policy/founder_test_1.json`. The initial opening
counts as a question. Subsequent question history uses replayed decisions, not
old stored PAI replies. Coverage, signals and insight availability are the
founder's fixed inputs.

| Turn | rule_id | action | topic | question_allowed |
| --- | --- | --- | --- | --- |
| S1 | ask | ask | history | true |
| S2 | rest | insight | null | false |
| S3 | ask | ask | interests | true |
| S4 | summarize | summarize | null | true |
| S5 | adjust | adjust | null | true |
| S6 | rest | insight | null | false |
| S7 | choice | ask_choice | status | true |

S5 is the explicitly permitted adjust exception to the three-question assertion.
S7 differs from S6; no_repeat unit tests cover statement preservation and all
action branches, including permitted repeats.

### Opening lifecycle

Workspace creation creates an empty canonical channel, without a seeded greeting
or suggestion chips. First successful onboarding completion stamps onboarded_at
and enqueues `counselor.opening` in the same transaction, using a per-workspace
idempotency key. The existing Task Runtime dispatches the system capability.
The job uses the existing workspace lock, checks for an existing PAI message,
builds context, ends the read transaction, and calls the Voice once per attempt.
It rechecks before posting through Messenger. Existing queue retries apply; the
last failed attempt posts the configured opening with the onboarding name.
An existing PAI message suppresses both generation and posting. The frontend
uses its existing working indicator while the canonical conversation is empty,
then renders the delivered opening. The identity block now recognizes the real
`identity.*` Vault keys. Tests cover queue-once, posting-once, existing-message
suppression, retry/fallback, prefixed identity and empty-to-opening UI.

### Model calls and verification

| Path | Before R2 | After R2 |
| --- | --- | --- |
| Normal human foreground | safety + Voice, concurrently | classifier + Voice, sequentially |
| Care foreground | safety plus discarded normal Voice, then wellbeing Voice | classifier + wellbeing Voice |
| Guard repair | separate repair paths could reach three Voice calls | at most one shared Voice retry |
| Background Planner / extractor | existing calls | unchanged |
| First onboarding opening | static seeded message | one Voice call per job attempt; deterministic final fallback |

| Check | Result |
| --- | --- |
| Backend baseline | 1036 passed, 3 skipped, 8 subtests |
| Hermetic test commit | 1039 passed, 3 skipped, 8 subtests |
| Step A full backend | 1080 passed, 3 skipped, 8 subtests |
| Step B final backend | 1088 passed, 3 skipped, 8 subtests |
| Separate production security | 3 passed, 4 subtests (covers the three skips) |
| Frontend | 24 passed in 9 files; baseline 23 in 8 |
| Production frontend build | PASS |
| Import every app module | 265/265, no unresolved dynamic imports |
| Dedicated architecture boundaries | 9 passed |
| Dedicated PAI OS contracts | 2 passed |

Full suite Step A took 228.74s; Step B took 314.82s. The three existing SQLite
expression-index reflection warnings remain; their migration assertions pass.
All model providers were fake; no real model calls or live evaluation took place.
Only the requested settings were appended to `.env.example`; `.env` was untouched.

Commits: `f35e24a` hermetic tests; `89eaab3` Step A; `2fcaf90` Step B.
The following documentation commit records final verification.

### Open questions and findings for later

- No remaining counseling-policy ambiguity after the founder's clarification of
  insight_candidate, no_repeat/replay, and the statement fallback.
- Local startup is blocked: Docker Desktop reports **unable to start**. It was
  launched from its installed location and rechecked. The requested fresh
  `pai-c-r2` deployment and migration 109 on that database remain unverified;
  no existing volumes were removed. Start its Linux engine, then use
  `docker compose --env-file .env -p pai-c-r2 -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d`.
- Offline passes do not establish model conversation quality. Founder live testing
  remains necessary and was not performed by the agent.
- Opening retries use the existing queue policy. A worker killed on its final
  leased attempt can still exhaust retries without executing a fallback; no
  queue lifecycle redesign was specified in R2.
- Existing compose files enumerate their environment pass-throughs. New R2
  configuration uses defaults in that deployment until those pass-throughs are
  explicitly added; R2 only requested new values in config and `.env.example`.
- Mirror/roadmap World-aware prompts and multi-request intake from the R1
  findings remain later work. The R1 prefixed-identity finding is fixed here.

## Core R3 — Picture review and Agree / Changes loop

Implemented on `pai-c` from `ccd333c`. All three supplied FigJam boards were
read. R3 reuses the existing Mirror job, Journey transitions, summary endpoints,
Messenger and review card. Possibility discovery and exploration roadmaps remain
R4; PAI OS life events remain R5.

### Board box -> code

| Board box | Owner/code |
| --- | --- |
| B: Every few turns, summary / picture clear | Existing R2 summary row retained; `policy/state.py` computes Mirror eligibility |
| B/C: You say / life shows / pressure / you want | `deep/mirror_schema.py` CorePicture; `deep/prompts/mirror.md`; `deep/context.py` public Mirror views |
| C: Gap between stated wishes and lived evidence | Tensions-only `<private_gap_context>`; generation validation rejects verbatim private quotations |
| B/C: Picture review | `counselor-mirror-card.tsx`: four labelled lines before collapsed Details |
| B/C: Student agrees? Yes | Existing confirm path in `journey/service.py`, durable confirmation proof, feedback endpoint |
| B/C: Changes / talk more on that gap | Existing edit message metadata -> `mirror_changes` -> `explore_correction.md`; two-message + applied-patch gate |
| C: Routes built on the truth | Existing confirmed research handoff retained; no R4 possibility changes |

### FIX FIRST

Autouse `offline_api_key` sets a fake config key without weakening the provider
and database hermetic guards. The suite also runs with the process key unset.
Both Compose files pass through 16 settings: classifier model/effort/timeout,
opening and statement fallback, summary cadence, safety model/effort/timeout,
wellbeing resources/fallback, repeat window/similarity, plan max age, Planner
history and map budgets. Bare environment mappings preserve config.py defaults
when a setting is absent. Synthetic Compose checks verified both absent and
supplied values for backend and worker. No dotenv file was opened or edited.

### Mirror v2 contract and privacy

`CounselorMirror` is the GENERATE contract: `core_picture` is required and has
exactly `you_say`, `life_shows`, `pressure`, `you_want`. Each is
`{text: string, evidence: string, unknown: boolean}`; text is nonempty and
evidence is nonempty unless unknown is true. Nine dimensions, blockers, opinion,
final question and roadmap lanes retain their existing contracts.

Spoken order: intro -> you_say -> life_shows -> pressure -> you_want -> opinion
-> final confirmation question. Validation requires exactly one question.
The prompt includes the founder's CORE PICTURE and v3 TRUTH MAP INPUT verbatim,
plus the approved private-gap instruction; the runtime and reference document
match.

The Mirror context reads MemoryService personal_view and capability_view, active
said/shown items, world.people (including role/wish/worry), and Vault profile.
Only tensions' between/evidence/status enter the separate private gap block.
private_notes, hypotheses, identity_status, decision_difficulties and both legacy
archives are excluded. Free-text tension quotations in spoken or card fields
reject generation: regenerate once, then keep discovery and the existing failed
draft path, without posting a broken card. No sensitive-check rebuild or extra
per-turn check was added.

`SavedCounselorMirror` is the READ contract: missing core_picture remains valid.
Old cards show existing details with no empty section or invented lines, and
saved spoken text is preserved. A new generation after an older draft must pass
v2. Delivery recovery of an already saved draft remains a read/repost operation,
not a model generation or database rewrite.

### Correction policy and Mirror eligibility

`mirror_allowed` requires mirror_ready, DIRECTION, no pending/running
counselor.mirror job, and either no edit or both:
- at least `derived.mirror_after_edit_min_student_messages = 2` later student
  messages (the correction itself is excluded);
- accepted Truth Map history for the edit or a later student event, read through
  MemoryService.patch_applied_since. Rejected patches create no accepted version.
  The existing sensitive pass retains its old source event and cannot advance
  this boundary by itself.

The mirror row now reads mirror_allowed. Immediately after care, the data-driven
mirror_changes row selects explore_correction for a mirror_edit_version message:
one question, first mentioned area or null, no invitation. The action instruction
is verbatim, with the optional topic clause. Existing no_repeat branches do not
apply to this action. Care retains priority. Policy tests use the new eligibility
signal rather than raw readiness.

### Confirmation proof, feedback and migration 110

Generation stores sure.score as certainty_before in the draft. Actual confirmation
appends a `counselor.mirror.confirmed` StudentJourneyEvent in the same transaction,
containing workspace_id, mirror_version, confirmed_at and certainty_before (null
when absent). The existing Journey row lock and confirmed-path return prevent
duplicate confirmation events. No historical proof is inferred or backfilled.

`POST /v1/counselor/summary/feedback` uses the confirm authentication boundary.
Only an exact workspace/version proof permits rating; otherwise it returns 409,
`This Mirror version cannot be rated`. This continues to work after the current
draft changes. A workspace lock and unique constraint make repeated submissions
idempotent: the first saved response is returned, never overwritten. Feedback
does not write the Truth Map.

Migration `110_counselor_mirror_feedback.py`, down_revision `109`, adds
`pai_counselor_mirror_feedback`: id, workspace_id, mirror_version, understood
(1..5), certainty_after (nullable 0..10), certainty_before (nullable 0..10),
created_at. Unique(workspace_id, mirror_version), range checks and workspace
cascade are database-enforced. Downgrade drops only this new table; the existing
Journey event log remains. Soft workspace deletion also purges feedback.

The frontend offers feedback only immediately after a successful Confirm, for
that exact version. Understood is required; certainty is optional; Send persists
and Skip writes nothing. All labels use the existing i18n mechanism. The card
retains its responsive width, scrolling and wrapping. Session export now includes
feedback and explicit confirmation proofs per version.

### Verification


| Check | Result |
| --- | --- |
| FIX FIRST / pre-R3 behavior count, key unset | 1088 passed, 3 skipped, 8 subtests |
| Step A full backend, key unset | 1093 passed, 3 skipped, 8 subtests |
| Final Step B backend, key unset | 1108 passed, 3 skipped, 8 subtests; 499.01s |
| Final Step B backend, fake key supplied | 1108 passed, 3 skipped, 8 subtests; 497.87s |
| Production-only security (separate synthetic config) | 3 passed, 4 subtests; covers the three skips |
| Frontend | 24 before -> 25 Step A -> 28 final, 9 files |
| Production frontend build | PASS after Step A and Step B |
| Import every app module | 265/265; no unresolved dynamic imports |
| Dedicated architecture checks | 9 passed |
| Dedicated PAI OS contract checks | 2 passed |
| Compose pass-through checks | All 16 settings, supplied and unset, backend and worker |
| Migration 110 | Offline upgrade/downgrade, uniqueness, ranges and workspace cascade passed |

The first Step B full run found one older isolated deletion fixture missing the
new table (1107 passed, one failed). Its schema now includes feedback and the
test explicitly verifies feedback is purged. Both final full runs above pass.
Three existing SQLite reflection warnings for expression indexes remain; the
migration assertions pass.

Additional coverage includes new-generation requirements, unknown evidence,
spoken order, private-gap exclusions/quotation retry, old draft read/retry,
draft certainty capture, correction policy priority and no_repeat exemption,
pending/stage/edit gating, exact-version durable proof, missing-proof 409,
historical proof after draft replacement, null certainty, authentication and
workspace isolation, rating validation/idempotency, exporter contents, feedback
Send/Skip/retry, and old-card rendering without placeholder lines.

Commits:
- `80779dd` — core R3: test key and compose config
- `3ae1038` — core R3 step A: mirror v2 picture from truth map v3
- `6f276f6` — core R3 step B: picture review loop and feedback
- The following documentation commit records verification.

### Open questions

None remain within R3 after the founder's private-gap, READ/GENERATE and durable
confirmation-proof decisions. Historical versions without proof intentionally
cannot be rated; the endpoint does not infer evidence from old status events.

### Findings for later

- No live model quality, latency or acceptance-rate claim is made. All model
  tests used fakes; no live API calls or founder conversation was run.
- Migration 110 was exercised offline, not applied to the founder's running
  database. Deploy the migration before using the feedback endpoint.
- Existing Mirror generation retry limits and sensitive-check behavior remain;
  R3 does not redesign their lifecycle.
- No dotenv files were opened or edited. Existing example-file documentation was
  left unchanged under the explicit rule; Compose behavior was verified using an
  empty temporary environment file and synthetic values.
- R4 possibilities/exploration and R5 OS events remain out of scope.

## Core R4: Discover and Guide

R4 follows the two approved boards and the founder's title, lifecycle and spacing
decisions. R5 life events and OS outcomes remain outside this change.

### Board box to code

| Board box | Implementation |
| --- | --- |
| A: Possibility Discovery; B: PAI-found possibilities with evidence | Planner optional possibility, visible-evidence validation, `pai_c/possibilities.py` |
| A: Possibility candidates | `pai_possibilities`, migration 111, workspace-scoped router, inline and Roadmaps Possibilities cards |
| B: Student's own goals | Mirror lane conversion and existing `RoadmapService.create_custom` linked to student-added possibilities |
| A/B: Exploration roadmaps and research | Existing `research/gateway.py`, light research and roadmap builder; Explore uses `student_route` |
| B: Compare trade-offs and fit | Guide-only `<compare>` inside `<research>` in `deep/context.py` |
| A: Student chooses roadmap; B: Ready to choose / Confirm / OS executes | Existing choose and decision-record path; linked possibility becomes chosen; OS contract unchanged |

### Storage and lifecycle

Migration `111_possibilities.py` follows 110 and creates `pai_possibilities` with
id, workspace_id, journey_id, title, normalized_title, kind, why, evidence,
unknowns, status, source, roadmap_id, mirror_versions, mentioned_at, created_at
and updated_at. Evidence, unknowns and processed Mirror versions use JSONB.
Workspace/title uniqueness and status/source/kind checks are database constraints.
Workspace and journey deletion cascade; roadmap deletion clears the link.
Downgrade drops only this table. No existing records are rewritten.

| Trigger | From | To / effect |
| --- | --- | --- |
| Explore | suggested, saved, dismissed | exploring; research starts once through the gateway |
| Explore | exploring | 200 no-op; no research restart |
| Save | suggested, dismissed | saved |
| Save | saved | 200 no-op |
| Dismiss | suggested, saved, exploring | dismissed; existing RoadmapService dismisses any linked roadmap |
| Dismiss | dismissed | 200 no-op |
| Existing roadmap choose | linked possibility | chosen; existing decision record retained |
| Existing roadmap restore | linked dismissed possibility | exploring |
| New confirmed Mirror version | suggested, saved | exploring |
| New confirmed Mirror version | exploring, chosen | unchanged |
| New confirmed Mirror version | dismissed | remains dismissed; new linked roadmap also dismissed |
| Reprocessed Mirror version | any | no change |

All unlisted Explore/Save/Dismiss transitions return 409 without changing state.
Chosen cannot be changed through these endpoints. Titles are unique per workspace
after whitespace normalization and case folding. Later Mirrors reuse that row,
keep title/why/kind, and append evidence deduplicated by text and the new version.
Bindings in the draft keep lane-to-possibility links stable across publication.

New Mirror lanes require a 2-8 word title, no URLs or digits. Strength-based and
test-the-dream lanes require evidence. Saved old Mirrors remain readable.
Old lane title fallback is published roadmap title, then route.field, then
`policy/lane_labels.json`. Later publication updates that legacy title unless it
collides: the old title remains, rows are not merged, and
`possibility_title_collision` logs both IDs without student text.

### Planner and discovery

Optional Planner possibilities need two distinct IDs visible in its bounded map,
including at least one shown/action item, and a structurally valid title. Invalid
possibilities are dropped without rejecting the rest of the plan. Duplicate and
dismissed titles are not re-added. Stored titles are present in the plan and
possibility logs for review. Institution/place exclusion is a prompt rule; no
entity model or word list was introduced, as explicitly agreed.

Research routes never use a possibility title: field uses student goal data or
the stored student evidence; level/place use student goal records, otherwise
remain empty. The invented-place-title isolation test verifies this boundary.

The data-driven `discover` row sits immediately after summarize:
`discover_available AND NOT questions_in_last_two` -> discover, topic possibility
ID, question_allowed true, invite false. `discover_min_student_messages_between`
is 6. Count from the later of current Mirror confirmation and the last discover
decision: first discovery is eligible at six messages, not immediately after
confirmation. The next requires six more. Existing no_repeat leaves discover
unchanged. Successful posting adds possibility_id metadata and sets mentioned_at
once. A failed post cannot consume the suggestion.

### Try-it and comparison

New roadmap output requires `try_it: {kind, what, time_needed, questions}`.
Kinds are talk_to_someone (exactly three nonempty questions) and taste_the_work
(empty questions). What and time_needed must be nonempty. The roadmap prompt uses
the exact requested TRY IT paragraph and Mirror v3 Truth Map input, and exempts
self-set Try-it action targets from external fact citations. Existing citation
requirements and research labels remain. Old test_30_days cards still render
their saved text without a database rewrite.

The localized I tried it form sends one normal student event with
try_it_roadmap_id and the requested title/feeling/note text. The normal event and
Planner input paths handle it. Not for me does not dismiss the roadmap. The
Planner prompt records reported action in shown, feelings in self, and certainty
only when the student provides a number.

For Guide only, comparison includes up to five ready, non-dismissed roadmaps from
the current journey: title, origin, why_for_you, strengths_used, family_fit,
constraints_fit, gaps (need/have/gap), risks, Try-it kind/what/time, favorite/focus
flags, stored facts and source labels. It introduces no facts or model calls.
The five-card limit lives in `policy/guide.json`; guide.md is unchanged.

### Verification and limits

Offline providers only; PAI_API_KEY unset, dotenv loading disabled and external
socket connections blocked in the backend test launcher. No dotenv file was
opened or edited. No founder conversation or live evaluation was run.

| Check | Result |
| --- | --- |
| Baseline backend | 1108 passed, 3 skipped, 8 subtests |
| Step A backend | 1142 passed, 3 skipped, 8 subtests |
| Step B backend | 1151 passed, 3 skipped, 8 subtests; 647.34s |
| Production security checks | 3 passed, 4 subtests; covers conditional baseline skips |
| Frontend | 28 baseline -> 30 Step A -> 32 Step B, 11 files |
| Frontend production build | PASS after both steps |
| Imports | 268/268, no unresolved dynamic imports |
| Architecture | 9 passed |
| PAI OS contracts | 2 passed; new choose test additionally preserves decision record |
| Focused Step B backend | 41 passed |

Migration upgrade/downgrade and title uniqueness were tested offline. Migration
111 has not been applied to the founder database. All lifecycle transitions,
Mirror version idempotency, collision handling, discovery spacing, auth/scoping,
Planner evidence validation, Explore dedupe, old/new artifacts and feedback
intake have offline coverage. An initial Step A run found a missing requested_by
value in a new test fixture; the fixture was corrected before the passing run.

Open questions: none remain within R4 after the founder's explicit decisions.

Findings for later: real-model quality and title-policy adherence are not proven
by fake tests; no live claim is made. R5 integration remains separate. Existing
SQLite expression-index reflection warnings are unchanged. Deploy migration 111
before enabling these endpoints in a running stack.

Commits: `98c09b3` (Step A), `28ba6f5` (Step B); the following documentation
commit records the final verification. All work remains on pai-c.
