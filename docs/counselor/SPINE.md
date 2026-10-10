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
