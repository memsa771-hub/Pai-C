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
