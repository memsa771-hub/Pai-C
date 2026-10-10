# PAI C clean architecture: one spine, everything plugs in

Date: 10 Oct. Status: proposal for founder approval. Supersedes the layering in ARCHITECTURE.md sections 2-4 where they differ; sections 6-12 still apply.
FigJam: e3MSmJw0s6wOdGvUubx6SU (1 spine, 2 everything is a capability, 3 research through one door, 4 one message, 5 today vs target).

## 1. Why
The code works, but the same kind of thing is done in many places:
- Three registries: 15 separate background job handlers (app/jobs), the Tool Registry (app/tools), the Capability Registry with plugins (app/capabilities, app/plugins), plus Operator runs with their own loop.
- Research is triggered from three places with separate code: memory handlers (resume and refresh), the mirror module (confirmed research job), research_gateway + light_research.
- Model calls are made from many modules directly.
- The Counselor context reads memory twice.
Every new feature would add one more handler or path. That is how spaghetti grows.

## 2. The spine: six central services, one of each
| Service | Owns | Notes |
|---|---|---|
| Conversation Orchestrator | Every input to PAI C (student chat/voice, document events, PAI OS requests/events) and the fast reply path | One entry point; nothing else talks to the student |
| Journey Service | Stages and transitions | Exists; only writer of stage |
| Memory Service | The five memories behind one API (working, facts/Vault, Truth Map, episodic, semantic) with ownership rules | Facade over existing services; no module reads tables directly |
| Model Gateway | Every model and embedding call: model per role from config, language policy, retries, budgets, usage logging | Wraps the existing inference client |
| Messenger | Every outbound message: chat, voice, notifications | Existing posting; the "one voice" rule lives here |
| Task Runtime | All background work: one queue (existing Postgres jobs), one run record (existing execution runs for tracked tasks), status, retry, budgets, resume | Executes capabilities only |

## 3. Plug-ins: two registries, nothing else
- Capability Registry: every business function is a capability with a typed input/output contract: planner.update, facts.extract, session.summarize, memory.index, documents.read, mirror.build, research.run, roadmaps.build, judge.score, and operator.run (durable execution selecting workflow or the open-ended plan-act-verify loop for PAI OS tasks).
- Tool Registry: atomic actions used by capabilities: web.search, web.fetch, files, and the rest.
- Rule: a background job is never written as its own handler again; it is a capability invoked by the Task Runtime. Fixed-input capabilities run in workflow mode (no generic LLM phases); only the agent mode of operator.run plans.

## 4. Research through one door
All triggers (mirror confirmed, source reported or expired, student answered a request, noted question, chosen route deep research, PAI OS needs a fact) call the Research Gateway (rules, budget per Mirror version, dedupe) -> Task Runtime -> research.run -> evidence cache hit or web.search/web.fetch -> Source Verifier -> cache -> facts with source and label. If it cannot verify: a student request. Roadmaps.build only consumes research.run results.

Decision for P1c: "research.run is the research family program.discover + program.research with the evidence cache (research/requirements.py RequirementStore) and the Source Verifier. No new capability id is created, because capability nesting is limited to one level."

## 5. Dependency rules (anti-spaghetti)
1. Inputs only enter through the Orchestrator; output only leaves through the Messenger.
2. Capabilities talk to memory only through the Memory Service and to models only through the Model Gateway.
3. Capabilities do not call each other directly except declared composition (roadmaps.build uses research.run through the runtime).
4. One writer per data (Truth Map: planner.update; Vault: facts.extract/documents/student edits via reconciler; stage: Journey Service).
5. No new registry, queue or runtime without an architecture decision.
6. Everything generic and config-driven.

## 6. Today -> target mapping
- 15 job handlers -> capabilities in the Capability Registry run by the Task Runtime.
- Operator runs and loop -> Task Runtime (runs) + operator.run capability (workflow or agent loop).
- Research in memory handlers, mirror module, gateway, light_research -> Research Gateway + research.run.
- Counselor context reading memory twice -> Memory Service read model (one profile block).
- Direct model calls -> Model Gateway.
Shared code (jobs, operator, capabilities, tools, inference, memory) is also used by PAI OS: changes are additive behind the same tables; agree with the PAI OS developer before merging.

## 7. Effect on the build order
The spine comes before new memory work, so new features are built once in the right place:
P0 Entry audit -> P1 Spine (pure refactor, no behaviour change) -> P2 Memory foundation -> P3 Turn engine -> P4 First meeting and Mirror v2 -> Gate 1 -> P5 Roadmaps on the Truth Map, Try it, coach basics, OS contract -> P6 Profile CV support and quality loop -> Gate 2.
