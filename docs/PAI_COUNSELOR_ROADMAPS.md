# Counselor Roadmaps

Roadmaps are sourced research artifacts for the Counselor Journey. They are separate from the student's canonical Profile and from application execution. A student may discuss, favorite, explore, dismiss, restore, or choose a route. Those actions live in `pai_roadmap_student_state`; they do not rewrite the research content.

## Flow

1. Accepted student goals and profile facts pass through the existing candidate and reconciliation path. The Counselor or the student can request research.
2. `roadmap_research` is owned by `roadmap.build`. It calls the registered discovery, program research, qualification, scholarship, and deterministic gap capabilities. Requirement rows start unconfirmed. `SourceVerifier` records official-domain, cycle, schema, agreement, and freshness checks on each row. Only a passing row is verified.
3. The registered builder publishes versioned rows through `RoadmapService`. One row is keyed by journey, origin, and route, so a refresh updates the same card and keeps student actions. New ready cards use the central notification system.
4. Missing facts pause the same ExecutionRun. Reconciliation enqueues the existing resume handler; no second student “continue” turn is required.
5. The Roadmaps view and Counselor message cards call workspace authenticated APIs. Focus is included in bounded Counselor context for text and voice. Choosing requires a presented, ready card and a short-lived server token; the server moves the Journey to `CHOSEN` and records the decision.
6. Accepted profile changes, changed research evidence, and student reports mark affected research stale. The durable job worker starts fresh research. A stale card shows why it needs a fresh check and cannot be chosen until refreshed. Favorite, dismissed, exploring, and chosen state are retained.
7. A failed or stale card may be retried from Roadmaps or Counselor chat. Retry keeps the original research brief and route origin, starts a new run, and retains the card and student actions.

## Operations

- Apply migrations through `095_roadmap_scholarships`. Revision 090 maps old `proposed` and manually `verified` rows to `unconfirmed`, because those rows have none of the automatic checks, and removes the operations token gate. Recheck them before treating them as verified.
- The backend worker must run for fact acceptance, pause/resume, and source refresh jobs. A report through `POST /v1/roadmaps/requirements/{id}/report` requires the student's workspace credentials, marks the row unconfirmed, and queues refresh.
- An unconfirmed requirement is not an eligibility verdict. Source URLs, checked timestamps, and failed checks remain available; unknown costs and dates stay blank.
- A provider-backed catalog institution with a trusted website seeds its domain allowlist. When no local identity exists, the `web.institution_registry` tool checks the public ROR registry for a unique active organization whose listed website owns the researched page. The result is cached for 24 hours and stored as a provider-backed catalog identity. Student-added institution websites and web search hits cannot seed that allowlist. Institutions outside the registry remain unconfirmed until a trusted catalog identity is available.
- Unconfirmed programme rules are visible with their source and failed checks, but cannot drive eligibility gaps or a confident fit verdict.
- Research pauses create shared `student_requests`; an accepted profile candidate or document extraction resumes the same run. The future OS may read requests and the latest `decision_records` row. `PAI_OS_SERVICE_TOKEN` protects the future OS escalation intake and must stay on the backend.
- A confirmed choice snapshots the goal summary, objective, accepted gaps and risks, roadmap version, and channel. Escalation from `CHOSEN` requires an authenticated, typed reason and preserves that snapshot.
- Research runs retain `research_metrics` with search/registry queries, page fetches, model calls, input/output tokens reported by the provider, and elapsed milliseconds. A token count is not a currency estimate. Internal logs emit duration spans for Counselor scope, extraction, planner, writer, guard, each capability call, and source verification. Logs include identifiers and statuses, never student text or profile values.
- `python -m scripts.eval_counselor_research_recorded` runs the ten-persona synthetic research-contract evaluation without credentials or network calls and writes a report under `backend/eval_reports`. It checks roadmap composition and source gates, not real institution coverage or natural conversation quality. The default `pytest` suite uses recorded or synthetic providers and runs without network access. A deep conversation evaluator follows in a later milestone.

## Configuration

| Variable | Purpose |
| --- | --- |
| `PAI_ENABLED`, `PAI_API_KEY`, `PAI_MODEL`, `PAI_BASE_URL` | Server-only Counselor and Operator inference. Never expose the key to the browser. |
| Consolidation | Deep is the sole Counselor path; successful human posts queue extraction and analysis. |
| `WEB_SEARCH_PROVIDER`, `WEB_SEARCH_API_KEY`, `WEB_SEARCH_BASE_URL` | Search provider. An unset provider yields a visible research failure; no result is fabricated. |
| `WEB_SEARCH_MAX_RETRIES`, `WEB_SEARCH_CACHE_TTL_SECONDS` | Transient search retry count and cache lifetime. |
| `PAI_RESEARCH_MAX_QUERIES`, `PAI_RESEARCH_MAX_FETCHES`, `PAI_RESEARCH_MAX_SECONDS` | Per-run search, fetch and time bounds. |
| `PAI_RESEARCH_FRESHNESS_DAYS`, `PAI_RESEARCH_DEADLINE_FRESHNESS_DAYS` | Maximum age of verified sources, with a shorter window near deadlines. |
| `PAI_RESEARCH_SWEEP_SECONDS` | Worker interval for stale-source checks. |
| `PAI_OS_SERVICE_TOKEN` | Backend-to-backend escalation token for later OS integration. |

The backend API and job worker must both run. Apply migrations before starting either. Source refresh and reconciliation require the worker. The ROR organization registry is consulted through the declared `web.institution_registry` tool and needs outbound access; unavailable registry results leave research unconfirmed.

PAI OS application submission, visas, university accounts, and parent accounts are outside this Counselor phase.
