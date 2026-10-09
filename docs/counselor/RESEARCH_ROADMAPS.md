# Mirror research and roadmaps (PR 7/8)

Research starts only after the student confirms the current versioned Mirror.
Discovery replies still make one Counselor call, with the Analyst and existing
candidate/reconciliation memory extraction running in the background.

## Flow

1. The confirmed-Mirror job builds a private brief from the Mirror, Notebook,
   canonical student snapshot/goals and open or unanswered noted questions.
2. The single research gateway delegates the existing `roadmap_research` task.
   It checks workspace ownership, Mirror status/version and duplicate research
   keys. A nonblocking PostgreSQL advisory lock serializes gateway submissions;
   no workspace row lock or read transaction is held across the Operator call.
3. Light research invokes existing discovery and program research capabilities
   for eligibility, required tests, costs, intake/timing and noted questions.
   It does not compose scholarship or qualification research in this light pass.
4. One roadmap model call builds the confirmed lanes. Code validates citations
   and numeric support, preserves evidence labels and publishes one card per lane.
   Incomplete or failed research creates `needs_info` cards instead of invented
   requirements. An original-dream test remains when distinct from strengths.
5. The existing deep Counselor handoff receives saved cards and sourced answers.
   The journey advances RESEARCHING -> ASSESSING -> PROPOSED. Existing route
   actions and custom-route research use the same gateway and Mirror gate.

## Evidence reuse and privacy

The cache is the existing Opportunity + RequirementSet store, not another table.
The key is SHA-256 of a JSON array containing normalized official source URL,
country, level, intake and program identifier. Matching is exact; separate source,
program or intake scopes are not interchangeable.

Only explicitly public facts extracted from official pages, verified by the
existing SourceVerifier, are eligible. Provider-backed official identity is checked
again on reads. Freshness uses PAI_RESEARCH_FRESHNESS_DAYS and
PAI_RESEARCH_DEADLINE_FRESHNESS_DAYS. Unknown sources still need discovery before
an exact cache key is available; known sources check the cache before live tools.

Cross-workspace hits materialize workspace-owned evidence copies. They copy only
public evidence and public route scope, not student annotations, questions,
answers, profile/Notebook data or source-workspace identifiers. Question IDs used
for the current research are transient and excluded from persisted public facts.
The existing scheduler marks expired evidence unconfirmed and queues refresh.

## Configuration and migrations

- `PAI_ROADMAP_MODEL`: defaults to PAI_COUNSELOR_MODEL.
- `PAI_RESEARCH_MAX_CALLS_PER_STUDENT`: default 40, a persistent workspace/student
  allowance per confirmed Mirror version covering searches, fetches, registry and model calls.
  Stored in Workspace.settings.counselor_research_budgets with separate version keys.
  Existing per-run query/fetch/time limits also apply. Cache hits do not spend it.
- `PAI_RESEARCH_REFRESH_MAX_CALLS`: default 8, a separate allowance per confirmed Mirror version for stale refreshes.
- Migration 099 adds answer JSON and fact_id to counselor_noted_questions.
- Migration 100 adds nullable lane and a unique workspace/journey/lane index to
  pai_roadmaps. Fit metadata and questions use existing route JSONB; gaps use gaps.

## Validation and offline coverage

Model output is untrusted. The publisher resolves fact IDs to the student's
RequirementSets again and restores stored quotes, values and verification labels.
Numbers must occur in cited quotes/values; structured requirements need citations.
A route is ready when all decisive fields have cited facts, including honestly labeled unconfirmed facts. Missing decisive facts prevent readiness. Student-evidence numbers and self-set action targets do not require research citations.
Personal-fit prose is constrained by the prompt to student evidence, not world
requirements. Deterministic checks cannot prove the semantics of arbitrary prose;
no claim of live conversation quality is made from these offline tests.

Examples for every lane: backend/tests/fixtures/roadmaps/mirror_lanes.json.
No live model, web search or other paid API evaluation was run for this change.

## Files added, changed or deleted in this task

- `.env.production.example`
- `backend/alembic/versions/099_counselor_light_research.py`
- `backend/alembic/versions/100_mirror_roadmap_lanes.py`
- `backend/app/config.py`
- `backend/app/pai_c/baseline.py`
- `backend/app/pai_c/context_projection.py`
- `backend/app/pai_c/deep/context.py`
- `backend/app/pai_c/deep/mirror.py`
- `backend/app/pai_c/deep/mirror_schema.py`
- `backend/app/pai_c/deep/prompts/counselor.md`
- `backend/app/pai_c/deep/prompts/handoff.md`
- `backend/app/pai_c/deep/prompts/mirror.md`
- `backend/app/pai_c/deep/prompts/roadmap_builder.md`
- `backend/app/pai_c/deep/roadmaps.py`
- `backend/app/pai_c/discovery.py`
- `backend/app/pai_c/research_gateway.py`
- `backend/app/pai_c/understanding.py`
- `backend/app/memory/discovery_intake.py`
- `backend/app/memory/handlers.py`
- `backend/app/models.py`
- `backend/app/plugins/_shared/budget.py`
- `backend/app/plugins/_shared/sources.py`
- `backend/app/plugins/program_research/__init__.py`
- `backend/app/plugins/roadmap_builder/__init__.py`
- `backend/app/pai_c/light_research.py`
- `backend/app/research/requirements.py`
- `backend/app/pai_c/roadmaps/service.py`
- `backend/app/routers/roadmaps.py`
- `backend/app/services/operator.py`
- `backend/tests/fixtures/roadmaps/mirror_lanes.json`
- `backend/tests/test_counselor_core.py`
- `backend/tests/test_counselor_deep_lean.py`
- `backend/tests/test_counselor_deep_research_contracts.py`
- `backend/tests/test_counselor_light_research.py`
- `backend/tests/test_counselor_mirror.py`
- `backend/tests/test_counselor_research.py`
- `backend/tests/test_mirror_roadmaps.py`
- `backend/tests/test_roadmaps.py`
- `backend/tests/test_student_understanding.py`
- `docker-compose.prod.yml`
- `docs/counselor/CLEANUP_AFTER_DEEP.md`
- `docs/counselor/COUNSELOR_V3_PROMPTS.md`
- `docs/counselor/README.md`
- `frontend/components/roadmaps/roadmap-card.tsx`
- `frontend/components/roadmaps/roadmap-detail-dialog.tsx`
- `frontend/components/roadmaps/roadmap-fit.test.tsx`
- `frontend/components/roadmaps/roadmap-fit.tsx`
- `frontend/lib/i18n/messages/en-US.ts`
- `frontend/lib/roadmaps.ts`
- `docs/counselor/RESEARCH_ROADMAPS.md`
