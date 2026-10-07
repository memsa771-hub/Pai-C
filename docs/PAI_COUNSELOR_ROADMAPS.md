# Counselor Roadmaps

Roadmaps are sourced research artifacts for the Counselor Journey. They are separate from the student's canonical Profile and from application execution. A student may discuss, favorite, explore, dismiss, restore, or choose a route. Those actions live in `pai_roadmap_student_state`; they do not rewrite the research content.

## Flow

1. Accepted student goals and profile facts pass through the existing candidate and reconciliation path. The Counselor or the student can request research.
2. `roadmap_research` is owned by `roadmap.build`. It calls the registered discovery, program research, qualification, scholarship, and deterministic gap capabilities. Requirement rows start unconfirmed. `SourceVerifier` records official-domain, cycle, schema, agreement, and freshness checks on each row. Only a passing row is verified.
3. The registered builder publishes versioned rows through `RoadmapService`. One row is keyed by journey, origin, and route, so a refresh updates the same card and keeps student actions. New ready cards use the central notification system.
4. Missing facts pause the same ExecutionRun. Reconciliation enqueues the existing resume handler; no second student “continue” turn is required.
5. The Roadmaps view and Counselor message cards call workspace authenticated APIs. Focus is included in bounded Counselor context for text and voice. Choosing requires a presented, ready card and a short-lived server token; the server moves the Journey to `CHOSEN` and records the decision.
6. Accepted profile changes, changed research evidence, and student reports mark affected research stale. The durable job worker starts fresh research. A stale card shows why it needs a fresh check and cannot be chosen until refreshed. Favorite, dismissed, exploring, and chosen state are retained.

## Operations

- Apply migrations through `090_automatic_research_verification`; it maps old `proposed` rows to `unconfirmed` and removes the operations token gate.
- The backend worker must run for fact acceptance, pause/resume, and source refresh jobs. A report through `POST /v1/roadmaps/requirements/{id}/report` requires the student's workspace credentials, marks the row unconfirmed, and queues refresh.
- An unconfirmed requirement is not an eligibility verdict. Source URLs, checked timestamps, and failed checks remain available; unknown costs and dates stay blank.
- A provider-backed catalog institution with a trusted website seeds its domain allowlist. When no local identity exists, the `web.institution_registry` tool checks the public ROR registry for a unique active organization whose listed website owns the researched page. The result is cached for 24 hours and stored as a provider-backed catalog identity. Student-added institution websites and web search hits cannot seed that allowlist. Institutions outside the registry remain unconfirmed until a trusted catalog identity is available.
- Unconfirmed programme rules are visible with their source and failed checks, but cannot drive eligibility gaps or a confident fit verdict.
- The live evaluation script needs configured model and web credentials. Its five workflow invariants also run offline in backend tests.

PAI OS application submission, visas, university accounts, and parent accounts are outside this Counselor phase.
