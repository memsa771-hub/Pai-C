# PAI C software architecture (Core v1)

Date: 9 Oct. Status: proposal for founder approval. Builds on the approved core (FigJam 97yQ5hwTjywjMDazpqBUmc) and the existing `pai-c` code.
Diagrams: FigJam wuPJaFgpIJmCfDPI12N1Ed (1 deployment, 2 module layers, 3 one turn, 4 core data model).

## 1. Design principles

1. Fast path is small. While the student waits, only three things run: save the message, safety check, Voice reply. Everything else (Planner, memory, mirror, research, roadmaps, judge) runs in background jobs.
2. One writer per data. Only the Planner changes the Truth Map, and only through validated patches. Only the stage machine changes the journey stage. The Voice never writes the map.
3. Think ahead, speak now. The Planner prepares the next plan after each reply, so the next reply never waits for planning.
4. Contracts everywhere. Every model output is JSON validated by a schema; invalid output is retried once, then a safe fallback is used.
5. Config, not code. Models per role, language policy, depth requirements, budgets, playbooks and freshness windows come from config or data files. Nothing country-, language- or institution-specific in code.
6. Idempotent and ordered. Every job has an idempotency key; per-student lock; jobs for one student run in order. (Already built.)
7. Measured by default. Every turn writes metrics; every session can be exported and scored.
8. Private by design. Student data never in logs or URLs; exports redacted; the student can see, correct and delete.
9. Reuse before build. New code only where the core needs it.

## 2. Deployable units (diagram 1)

| Unit | Role |
|---|---|
| Student Web App (Next.js) | Chat, voice, mirror card, roadmaps, profile |
| Caddy | TLS and routing |
| Backend API (FastAPI) | Fast path: events, turn orchestrator, safety gate, Voice; mirror/roadmap/voice endpoints |
| Background Worker (same image) | Planner, memory extraction, mirror, research, roadmaps, judge |
| PostgreSQL | Source of truth: events, Truth Map, plans, journey, mirror, roadmaps, research cache, metrics, job queue |
| Redis | Cache and live event push |
| Qdrant | Memory vectors |
| Job queue | Table in PostgreSQL with SKIP LOCKED (no extra broker needed) |
| External | OpenAI (models, voice), web search API, official source pages |

No new infrastructure is needed for Core v1.

## 3. Module layers inside the backend (diagram 2)

Dependencies only point downward: Interface -> Orchestration -> Counseling core -> Outcomes -> Shared platform.

Target layout of `backend/app/pai_c/` (current file -> new place):

```
pai_c/
  orchestrator/   turn.py (deep/turn.py), runtime.py, posting.py, stages.py, context.py, turn_input.py
  safety/         gate.py (new)
  voice/          voice.py (from deep/turn.py model call), polish.py, prompts/voice.md (from counselor.md), prompts/language_retry.md
  planner/        planner.py (deep/analysis.py), patch.py (new), prompts/planner.md (from analyst.md)
  truth_map/      schema.py (notebook_schema.py), service.py (notebook.py), sanitize.py, coverage.py,
                  coverage_requirements.json, migrate_v1.py (new), sensitive.py
  playbooks/      registry.py (new), *.md (new, one per situation)
  mirror/         mirror.py, mirror_schema.py, prompts/mirror.md
  research/       research_gateway.py, light_research.py, noted_questions.py
  roadmaps/       service.py, roadmaps.py, prompts/roadmap_builder.md
  quality/        metrics.py (new), judge.py (new), replay.py (new), prompts/judge.md (new)
  shared/         usage.py, prompts loader, voice_context.py, summary_access.py, handoff.py
```

Shared platform stays outside `pai_c`: inference client, memory and Vault, jobs, config, security, models.

## 4. One turn (diagram 3)

Fast path (student waits):
1. API saves the event (existing pipeline, ordering, dedupe).
2. Orchestrator takes the per-student lock and runs the Safety gate.
3. If not safe: wellbeing reply from the wellbeing playbook, counseling paused, event recorded.
4. If safe: read map summary + latest plan + selected playbooks (+ research facts if any), call Voice, validate JSON, polish and guards (one question, no blocked script, no repeated question), save reply and turn metrics, return the reply.
5. Enqueue background jobs: Planner (always), memory extraction (existing), mirror if the stage machine says it is due.

Background:
- Planner reads map + rolling summary + last N turns, returns a patch + next plan. Code validates and applies the patch as a new map version, stores the plan for the next turn.
- Mirror, research, roadmaps: existing jobs, now reading the Truth Map.

## 5. Data model (diagram 4)

- Truth Map is stored as one versioned JSON document per student (as today), now with typed items (part, key, value, evidence, kind, confidence, first_seen, last_confirmed, status). Every version is kept (existing history table), which gives item history without a new table. Separate item tables only if we later need to query across students.
- New small tables: turn_plan (plan per student event, linked to map version), turn_metric (per reply), session_score (understood rating, certainty before/after, judge scores).
- Existing: events, journey + stage, mirror drafts, noted questions, roadmaps, research cache, background jobs, usage logs.

## 6. Failure handling

| Failure | Behaviour |
|---|---|
| Voice model error or timeout | One retry, then the configured fallback reply; logged |
| Voice returns invalid JSON or rule break | Polish and guards; one retry for blocked script or repeated question |
| Planner fails or is late | Voice uses the last valid plan and the raw message; job retried |
| Planner patch invalid | Rejected whole, map unchanged, logged; never a partial write |
| Safety gate error | Continue with Voice, whose prompt keeps its own wellbeing rule (defence in depth); alert logged |
| Mirror invalid twice | Visible "need a little more" path (built in PR 7+8) |
| Research or budget exhausted | Roadmap needs_info with the missing fact named (built) |
| Worker down | Jobs wait in the queue; fast path still works |

## 7. Cost and performance

- Model per role from config: Voice = strong model; Planner, Safety, Judge = cheap models.
- Planner input is bounded (summary + last N turns), so cost per turn stays flat.
- Prompt caching: stable prompt prefixes (role prompt first, student context last).
- Budgets per student from config; usage logged per call (existing).
- Targets: fast path p50 under 3 s; cost per first session measured in metrics.

## 8. Quality and testing

- Unit and contract tests (offline, existing style).
- Replay set: anonymised real conversations as fixtures; one command replays them through Voice + Planner with recorded or cheap models and produces a scorecard (judge rubric: reflections vs questions, value given, repeated questions, family respect, facts without sources).
- Capped live smoke only when asked.
- Session export for human review (built).

## 9. Security and privacy

- No student text in logs; ids and statuses only (existing rule).
- Redacted exports (built); delete and correct via the student's profile.
- Prompt-injection: student text and web pages are data, never instructions (existing rule in prompts).
- Minors: extra care in playbooks; no sensitive data stored.

## 10. What changes vs today

- New: safety gate, Planner patches + plans, playbook registry, Voice prompt v4, Truth Map schema v2 + migration, turn metrics, session score, judge, replay.
- Moved: files reorganised into the layers above (pure move, no behaviour change, done first or last).
- Unchanged: deployment, job queue, mirror/research/roadmap pipelines, research cache, exporter.

## 11. Data layer review and decisions (10 Oct, code review of pai-c 479513b)

Findings (verified in code):
- Per student turn today: Counselor call + memory extractor call + Analyst call + an embeddings call (3 model calls + 1 embedding).
- Extractor (Vault) and Analyst (Notebook) read the same turn independently and both capture goal, education, family influence, constraints and interests: two versions of the truth that can disagree.
- Qdrant/embeddings are write-only in production: the Counselor context calls foreground memory with lexical_only=True; the hybrid retriever, reranker and document search have no production caller. We pay for embeddings and run Qdrant for nothing.
- No session summary exists; "latest episode" is just the newest extracted decision.
- Counselor context shows the profile twice (snapshot profile + lexical foreground block over the same Vault).
- "Foundation ready" has two definitions (Notebook coverage vs Vault profile requirements); the Counselor uses only the Notebook one.
- Legacy form-based discovery still present: profile requirements/completion/responses (questions seeded in migration 085), education_journey, orphan table pai_counselor_slot_answers, explicit_commands.py, eval_dataset.py/eval_retrieval.py (not production imports), profile_captured always False, counselor-only memory tools with no caller.
- Hardcoded: education_journey qualification names of one country; tests.ielts.score and a CGPA cap of 10 in field definitions; a currency map limited to a few currencies.

Decisions (proposal):
1. Three stores, one owner each:
   - Vault = objective, checkable facts (identity, education, tests, documents, money, places). Writers: extractor, documents, student edits, all through the existing reconciler. Feeds the CV profile.
   - Truth Map = counseling understanding (SAID/SHOWN/SOURCE/PRESSURES/SELF/SURE, tensions, plan). Writer: Planner only. It references Vault facts by id instead of copying them.
   - Conversation events = raw history.
2. Clear boundary now: extractor captures only objective facts; the Planner reads the Vault and owns interpretation (goal source, family concern, interests depth, certainty). Merging both into one call is a later cost optimisation, only if measurements ask for it.
3. Embeddings and Qdrant: switch off for PAI C via config (no deletion of shared code; PAI OS may use document search). Revisit with return visits (v1.1) if long-term recall needs it.
4. Session summary job (v1.1) for return visits; until then the Truth Map with dates carries memory.
5. Counselor context: one compact profile block from the snapshot; drop the duplicate foreground block.
6. Remove legacy discovery (profile requirements/completion/responses, education_journey, orphan slot table, explicit_commands, profile_captured, unused counselor memory tools) after checking with the PAI OS developer, since memory is shared code; the new CV profile reads Vault records directly.
7. Make field definitions and parsers generic (no exam- or country-specific keys or caps; currency handled generically).
Target per turn: Counselor (+ Safety) inline; Planner + extractor in background; no embedding call.

## 12. PAI Operator in PAI C (10 Oct, code review)

What it is today (backend/app/services/operator.py, app/capabilities, app/plugins):
- A shared execution runtime: ExecutionRun rows (status, plan, budget, resume, student requests), a capability registry where plugins own task types (roadmap_builder owns roadmap_research; program_discovery, program_research, gap_assessment, qualification_recognition, scholarship_discovery own theirs), and a generic agent loop UNDERSTAND -> PLAN -> EXECUTE (tool calls) -> VERIFY on PAI_OPERATOR_MODEL.
- PAI C uses it for light research and roadmaps: research gateway -> operator.delegate(task_type roadmap_research, capability_input = brief) -> agent loop -> capability.invoke(roadmap_builder) -> program discovery/research (cache, verifier, budget) -> roadmaps -> handoff to the Counselor.

Problem: for roadmap_research the input and the owner are already fixed, yet the run still goes through several LLM phases (understand, plan, a tool-calling execute step whose only job is to pass the given input to the owner, and verify). That adds model calls, latency and a place where the input can be changed or a correct run marked failed. Anthropic's guidance: use workflows (predefined code paths) for predictable tasks and agents for open-ended ones.

Decision (proposal):
- Keep the Operator as the shared runtime (runs, budgets, resume, student requests, capability registry, plugins).
- Add a workflow mode: when a task type has an installed owner and constraints carry capability_input, invoke the owner capability directly (same run row, budgets, status, verification inside the capability), no generic LLM phases.
- Agent mode (the five-phase loop) stays for open-ended objectives, which is where PAI OS action-plan tasks belong.
- PAI C uses only workflow mode: roadmap_light, stale_refresh, later roadmap_deep.
- The Operator core is shared with PAI OS: the workflow mode is additive, agent mode unchanged; agree the change with the PAI OS developer. Scheduled in P4.
