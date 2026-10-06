# Counselor Roadmaps

Roadmaps are sourced research artifacts for the Counselor Journey. They are separate from the student's canonical Profile and from application execution. A student may discuss, favorite, explore, dismiss, restore, or choose a route. Those actions live in `pai_roadmap_student_state`; they do not rewrite the research content.

## Flow

1. Accepted student goals and profile facts pass through the existing candidate and reconciliation path. The Counselor or the student can request research.
2. `roadmap_research` is owned by `roadmap.build`. It calls the registered discovery, program research, qualification, scholarship, and deterministic gap capabilities. Requirements start as proposed and remain labelled unconfirmed until operations review.
3. The registered builder publishes versioned rows through `RoadmapService`. One row is keyed by journey, origin, and route, so a refresh updates the same card and keeps student actions. New ready cards use the central notification system.
4. Missing facts pause the same ExecutionRun. Reconciliation enqueues the existing resume handler; no second student “continue” turn is required.
5. The Roadmaps view and Counselor message cards call workspace authenticated APIs. Focus is included in bounded Counselor context for text and voice. Choosing requires a presented, ready card and a short-lived server token; the server moves the Journey to `CHOSEN` and records the decision.
6. Accepted profile changes and reviewed requirement sources mark affected research stale. The durable job worker starts fresh research. A stale card shows why it needs a fresh check and cannot be chosen until refreshed. Favorite, dismissed, exploring, and chosen state are retained.

## Operations

- Apply migration `084_roadmaps` after `083_requirements_store`.
- The backend worker must run for fact acceptance, pause/resume, and source review refresh jobs.
- `PAI_OPS_REVIEW_TOKEN` from the research capabilities milestone remains required for restricted requirement review. This milestone adds no environment variables.
- A proposed requirement is not an eligibility verdict. Source URLs and checked timestamps remain visible on cards; unknown costs and dates stay blank.
- The live evaluation script needs configured model and web credentials. Its five workflow invariants also run offline in backend tests.

PAI OS application submission, visas, university accounts, and parent accounts are outside this Counselor phase.
