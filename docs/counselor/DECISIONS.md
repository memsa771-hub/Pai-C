# Locked workflow implementation decisions

## Execution

The founder authorized autonomous completion on pai-c. Clear implementation,
fixture and prompt-document fixes have no attempt limit. Existing coverage stays.
No live providers, dotenv edits, table drops or shared-code deletion are allowed.

## Factual cards

Choices come only from schema/catalog data. Every catalog card supports editable
Other. Missing catalogs use text or an upload invitation; no invented options are
seeded. Prefills require an exact quote from the current student message and
explicit confirmation. Other values retain stated evidence and a review flag.
Coverage may require several distinct facts in one area. The existing
question-intent and policy repetition guards remain responsible for repeated questions.

## Shared OS contract

tasks.list, tasks.create and workflow advancement stay pending OS developer
agreement. Browser backend, integration relay/settings, notifications, all
models/tables and shared registries remain.

## Evidence confirmation

Confirmation reviews the exact active value, protected by a digest and a
workspace lock. A stale card requires reload. Idempotent reviews use existing
candidate evidence; no table is added. Confirmed is a separate evidence label,
not an external credential-verification claim. Record reviews cover the complete
displayed record; changing it invalidates the digest. Edits return to stated.
Document-supported/externally verified provenance remains shown. Restricted
Vault fields are excluded using the existing safe profile projection.

## Knowledge

The existing RequirementStore remains the cache. Authoritative season bounds
supplement its TTL; absent calendars do not invent a season. Merit rules require
an explicit reviewed program/season rule. The shipped catalog is empty.
Voice declares specific world assertions with fact ids. The guard requires an
exact current sourced value/quote, appends source/date, and removes unsupported
assertions and numeric currency/percentage claims. Student evidence is exempt.
No extra foreground model call is introduced. General explanations remain model
generated; deterministic validation cannot identify every unannotated qualitative
claim. That residual quality limitation is recorded for the founder evaluation.

## Phase 2, step 5: paths before places
Mirror confirmation now materializes evidence-backed possibilities without delegating institutional research. Explore queues `path.explain` through the same Research Gateway and durable Operator workflow. A repeated request reuses its run per possibility and Mirror version. Existing stale-refresh and student-answer jobs retain their behavior.
The general explanation is validated separately from sourced world claims. Fit quotes must exist in the supplied student evidence. Jobs, myths and outlook without verified sources remain unavailable, never asserted as facts. All web work remains budgeted and the model uses the existing gateway.
Regression tests for confirmation now assert no Operator run; the old payload/dedupe test exercises the preserved student-answer research trigger. Architecture assertions are unchanged: delegation still has a single call site.

## Phase 2, step 6: explicit program search
`program.search` is a native workflow composing existing `program.discover` and `program.research`, one capability nesting level. A POST with explicit consent and a completed current-Mirror path run is required; GET never initiates research. Runs reuse the path+Mirror key and student budget. Missing destination evidence produces a missing-information result, not a guessed country.
Eligibility uses shown/confirmed values only. Meeting entry rules is labelled eligible, not safe: safe/realistic/stretch require an independently reviewed program+season rule. Not-yet routes use only cited remediation. Existing research cache and SourceVerifier remain the source of facts.

## Phase 2, step 7: private reliability surface
An authenticated workspace health endpoint checks database-backed analysis backlog, a data-configured lag threshold, failed jobs and daily guard/fallback counts. Counts use existing durable turn decisions, with idempotent provider/unconfigured records; no text or credentials are returned. The existing public liveness endpoint is unchanged. Planner lag is an in-app attention state, not a new notification channel or scheduler. There is no provider ping and no paid health call.

## Phase 3: one student shell and existing contracts
The main workspace mounts only Counselor, Journey, Paths, Profile, Compare, Plan,
Documents, Settings and the existing notification center. Four entry cards are
advertised by the backend; old eight-field submissions remain accepted for old
clients. No new institution or exam catalog is invented.
Profile confirmation, editing and removal all create reconciled candidates.
Removal retires an active record with an audit revision; it does not erase its
history. No database table or schema is removed. The existing account-erasure
endpoint is available only after a separate explicit irreversible-deletion
confirmation. The export scope is explicitly described below.
A completed current-Mirror program check may explicitly request a reviewed
roadmap through the existing builder. It does not choose the path. Existing
roadmap choice, decision records and planning remain the authority for I/J.
Check-ins open a draft in the same Counselor; no OS reminder scheduler is added.
Journey links use durable event ids and page older chat history when necessary.
Screenshots and browser navigation use a separate test-only Vite entry with fake
API/workspace adapters and blocked network access; no fake data is in app routes.


## Final review: freshness, export and inline presentation
Program pages re-read the current workspace's RequirementStore rows and the student's current shown/confirmed facts. Changed routes or expired evidence require another explicit search; pending runs still deduplicate. Expired path world claims are hidden and may be refreshed explicitly. Generic path prose is kept. No GET initiates research and the existing Mirror budget still applies.
The legacy Add goal/program-research shortcut is hidden in the new Compare/Plan surfaces. Reviewed roadmap creation follows a completed path-specific program check; the existing choice-token dialog remains the authority for a student's decision.
A first-picture presentation card and a 0?10 rating control follow the existing policy action/topic. Care overrides both; a rating is a normal student message only after Send, and the Analyst remains the Truth Map writer.
The locked board itself supplies the four named level choices. Those labels are data in entry_fields.json, with editable Other; non-catalog student wording is retained with a catalog-review flag. No board/subject or seasonal threshold is invented.
Public profile sections use explicit data selectors for interests, values, goals and options. The ten coverage keys match the backend (family_social/sure). Capability depth is not presented as evidence verification. Undated education remains visible without an invented date.
The owner-only /v1/counselor/export endpoint exports student-visible data (conversation, profile, paths, roadmaps, confirmed picture, ratings and document metadata), reusing the existing export redactor. Original document downloads remain in Documents. Internal model notes/archives and credentials are excluded. No export or deletion is automatic. Account deletion logging no longer includes an email.
Daily health now includes open student requests and noted questions as counts only. Health is checked by the authenticated app; no new scheduler or paid provider ping was added.

### Test adjustments in final review
New fixtures now supply notebook last_event_id and noted-question event foreign keys, matching the unchanged schema. Existing profile rendering assertions were expanded for separate Values, Pressures, Interests and Options sections. The headless choice test selects the footer Close button explicitly because the accessible dialog also has an X Close control. Production TypeScript found a nullable path access and the translator's special Other-key type; both were fixed in implementation. No security/contract assertion was removed or weakened.
