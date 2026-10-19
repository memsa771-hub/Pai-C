# PAI C locked workflow v1 — build report

## Result and scope

Implementation head: **eb1db6c**, branch **pai-c** (backend fixes through **61e9c19**). This report's commit contains documentation and refreshed synthetic screenshots.

The Counselor-only workspace, evidence review, paths-first workflow, explicit place-search consent and deferred UI cleanup are implemented. This continuation adds sourced myth checks, guided family preparation, scheduled check-ins, daily reliability notifications and readable evidence labels. **The complete board is not yet production-complete:** the checklist records **24 done, 13 partial, 7 not done** work cards. Missing authoritative data, semantic grounding limits and the joint OS contract remain explicit below. Nothing is represented as verified merely because a model produced it.

No live model, search, OCR, voice or other provider API calls were made. Provider spend in this build: **0**. Tests use fake providers and block external socket connections. No database tables were dropped, no migrations were added, and no .env settings were edited. dev and pai-os were not changed.

Sources: [locked workflow](PAI_C_WORKFLOW_LOCK_V1.md), [SPINE](SPINE.md), [Counseling policy](COUNSELING_POLICY.md), and [locked FigJam](https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF). The autonomous instruction replaced the earlier stop/attempt-limit rules; concrete fixes continued without weakening assertions.

## Commits

| Step | Commit | Main changes / data |
| --- | --- | --- |
| Approved OS UI removal | 2be2fee | Nine approved UI files, mounts, navigation and task/workflow UI flags/build arguments. |
| Approved backend detachment | a1950e5 | Application Workspace/deadline routers and their scheduler blocks detached; transport, models and tables retained. |
| Phase 2 step 1 | f46e9d7 | Ten-area spine restored; Planner prompt/document synchronized. areas_policy.json and existing coverage data. |
| Step 2 | f46a39e | Follow thread; fact/story selection; catalog-backed cards; fact_cards.json and action prompt files. |
| Step 3 | 134dcf8 | Profile confirmation/edit via candidates/reconciler; source-bound evidence labels. |
| Step 4 | b10b8ae | Grounding guard; season-scoped cache data/expiry; grounding.json and season_policy.json. |
| Step 5 | 56dcf66 | path.explain workflow; strict explanation; paths/policy.json and explain.md; fixed published-fact lookup to use the actual Opportunity model. |
| Step 6 | a49802b | program.search workflow; explicit consent, current Mirror/path checks, shown/confirmed eligibility. |
| Step 7 | 94767d9 | Owner-only health counts and Planner lag; reliability.json. |
| Phase 3 | e361e7e | Counselor shell and screens, canonical fact removal, public workspace projection, existing reviewed-roadmap/choice flow; workspace copy.json/settings-data.json. |
| Deferred UI cleanup | 131decb | Twelve unmounted OS UI files removed after importer checks; shared branches retained. |
| Final engineering review | 2cc212e | Evidence freshness/current facts, pending polling, consent bypass closure, safe owner export, inline cards, public profile selectors, board-supplied entry choices, open-request health counts. |
| Previous final verification | a92168a | Report, SPINE updates, real theme provider for the choice dialog; prior captures. |
| Myth correction | c7820bf | clear_myth selector/action, research.claim capability, source quotation, myths.json and myth_check.md. |
| Family preparation | d9827e1 | Guided family/evidence selection, authenticated API, idempotent Messenger delivery; family_talk.json and family-talk.json. |
| Scheduled check-ins | b035e23 | counselor.checkin, delayed chosen-path and accepted-try-it triggers; checkins.json. |
| Daily health alert | 907e965 | Existing sweep and notification service; counselor.health_alert and reliability.json thresholds. |
| Reliability review | 61e9c19 | Bounded belief-check budget windows, answered-request receipts, stable family evidence ids; exact capability inventory updated. |
| Readable UI | eb1db6c | Evidence/field/enum label data; one idle Talk to PAI label; readable profile and roadmap cards. |
| Continuation verification | This report's commit | Updated board checklist, decisions/blockers, refreshed light/dark screenshots and existing offline preview fixtures. |

Final data files also include pai_c/policy/inline_cards.json and pai_c/understanding/profile_sections.json. Catalog content remains data, and no authoritative board/subject or merit threshold was invented. Prompts remain Markdown; runtime/document consistency tests pass.

## Every orange NEW card, sections 00–12

**B/** means backend/app/; **F/** means frontend/. “Done” means implementation with retained offline regression checks, not a live quality certification or exhaustive new feature coverage. Extensive new tests are deferred per the latest instruction. “Partial” names the missing element. Blocking evidence and safe behavior are detailed in [BLOCKERS](BLOCKERS.md).

Sections **00 and 08 contain no orange work cards** in the inspected board. Card **35:219** is the orange legend, not a feature; it is accounted for here and excluded from the 44-work-card count. The remaining cards are listed individually by Figma node id.

| Board section / node | Card | Status | Commit(s) | Files | Evidence / limitation |
| --- | --- | --- | --- | --- | --- |
| 01 What the student sees / `36:204` | Tap cards: level (Matric, O-level, FSc, A-level, other), city, reply language. Nothing else. | **done** | e361e7e, 2cc212e | B/memory/entry_fields.json; F/components/onboarding/onboarding-view.tsx | Four cards; board-provided level catalog plus editable Other. |
| 01 What the student sees / `36:212` | Inline cards only when useful: tap your board, upload your result card, how sure are you 0-10. | **done** | f46a39e, e361e7e, 2cc212e | B/pai_c/fact_cards.py; F/components/counselor/workspace/{fact-card,inline-card}.tsx | Catalog choices only; absent catalogs use text/upload. Rating is sent only by the student. |
| 01 What the student sees / `36:240` | Path page: what it is, what you study, a normal work day, skills needed, fit with you, myths vs reality, jobs and future, ways in. | **partial** | 56dcf66, e361e7e, 2cc212e | B/pai_c/paths/explain.py; F/components/counselor/workspace/paths.tsx | All sections render; verified jobs/myths/outlook need a reviewed career-source pack. |
| 01 What the student sees / `36:248` | Programs for this path: entry rules, merit, fee, scholarships - each with source and date. | **partial** | a49802b, e361e7e, 2cc212e | B/pai_c/paths/programs.py; F/components/counselor/workspace/paths.tsx | Dated sources and verification labels supported; no live search or comprehensive institutional data verified. |
| 01 What the student sees / `36:252` | Labels: safe / realistic / stretch / not yet - not yet shows the route to get there. | **partial** | a49802b, 2cc212e | B/research/seasons.py; B/pai_c/paths/programs.py | Bands require reviewed seasonal rules; not-yet route requires cited remediation. Unknown stays unknown. |
| 01 What the student sees / `36:268` | Check-in: how did the test go? A new result updates the profile. | **done** | b035e23 | B/pai_c/checkins.py; B/pai_c/roadmaps/service.py; B/routers/counselor_paths.py; F/components/counselor/workspace/paths.tsx | Delayed in-app check-in after choice or explicit try-it acceptance; same conversation/extraction updates facts. No new OS outcome intake. |
| 02 One turn - the engine / `36:389` | Grounding guard: no fact about an institution without a source | **partial** | b10b8ae, 2cc212e | B/pai_c/deep/grounding.py; B/pai_c/policy/grounding.json | Declared world claims and numeric assertions checked. Unannotated qualitative institutional claims remain a semantic limitation. |
| 02 One turn - the engine / `36:429` | Health checks: Planner lag alert, count of every fallback per day | **done** | 94767d9, 907e965 | B/pai_c/reliability.py; B/pai_c/reliability.json; B/pai_c/sessions.py | Daily counts and in-app lag state; threshold crossings enqueue one existing-inbox alert per workspace/day. |
| 03 Understanding spine / `37:396` | Tap cards: level, board, subjects, 0-10 rating | **done** | f46a39e, 2cc212e | B/pai_c/policy/fact_cards.json; F/components/counselor/workspace/{fact-card,inline-card}.tsx | No generated catalogs; approved text/upload fallback and Other review metadata. |
| 03 Understanding spine / `37:400` | Upload: result card, transcript, certificates | **done** | f46e9d7, e361e7e | B/documents/handlers.py (existing); F/components/counselor/workspace/fact-card.tsx | Reuses Documents and validated document extraction; no live OCR call. |
| 03 Understanding spine / `37:436` | 9  Goals and dreams - what they say they want, and whose wish it is.  Min 1 | **done** | f46e9d7, 2cc212e | B/pai_c/policy/areas_policy.json; B/pai_c/planner/prompts/planner.md; B/pai_c/understanding/profile_sections.json | Goals and whose wish included in the same evidence spine. |
| 03 Understanding spine / `37:440` | 10  Options they know - fields and careers they know, myths they believe.  Min 1 | **done** | f46e9d7, 2cc212e | B/pai_c/policy/areas_policy.json; B/pai_c/understanding/profile_sections.json | Known options/myths retained with evidence; not treated as verified world facts. |
| 04 Evidence model / `37:527` | Profile card: the student sees each fact and can confirm or edit it | **done** | 134dcf8, e361e7e | B/routers/counselor_profile_cards.py; B/pai_c/memory.py; F/components/counselor/workspace/profile.tsx | Canonical fact/record Confirm/Edit/Remove creates candidates; digest check and reconciliation preserve history. |
| 04 Evidence model / `37:531` | Merit and eligibility numbers only from shown or confirmed facts | **done** | 134dcf8, a49802b, 2cc212e | B/memory/evidence.py; B/pai_c/paths/programs.py | Stated marks excluded from numerical eligibility. Confirmed means student-reviewed, not external credential verification. |
| 05 Next move / `37:614` | Follow their thread - reflect what it means to them | **done** | f46a39e | B/pai_c/policy/controller.py; B/pai_c/policy/decision_table.json | Care and persisted requests retain priority over following the student's thread. |
| 05 Next move / `37:646` | A fact or a story? | **done** | f46a39e | B/pai_c/policy/decision_table.json; B/pai_c/fact_cards.py | Fact collection separated from one-question story exploration. |
| 05 Next move / `37:650` | Fact - tap card or upload invite | **done** | f46a39e, e361e7e | B/pai_c/policy/fact_cards.json; F/components/counselor/workspace/fact-card.tsx | Exact-quote prefill requires confirmation; no model-created choices. |
| 06 Counseling stages / `38:611` | Where to study | **done** | a49802b, e361e7e, 2cc212e | B/routers/counselor_paths.py; F/components/counselor/workspace/paths.tsx | Stage H only from a completed current-Mirror path plus explicit consent; GET does not research. |
| 07 Failures / `38:740` | Lag alert when the Planner falls behind | **done** | 94767d9, e361e7e | B/pai_c/reliability.json; F/components/counselor/workspace/shell.tsx | Private workspace-scoped lag state; data-defined threshold. |
| 07 Failures / `38:804` | Daily health check: count of every fallback, Planner lag, open requests, failed jobs - so problems show up before students feel them | **done** | 907e965 | B/pai_c/reliability.py; B/pai_c/reliability.json; B/capabilities/system.py | Existing worker sweep, durable daily dedupe and notification service; failed-job counts scoped to UTC day; no provider ping. |
| 09 World knowledge / `39:850` | Entry and merit rules for programs a student is looking at - checked once per season | **partial** | b10b8ae, a49802b | B/research/{seasons.py,season_policy.json}; B/research/requirements.py | Cache and seasonal expiry implemented; authoritative seasonal rule pack is empty. |
| 09 World knowledge / `39:854` | Merit calculator with the student's shown or confirmed marks | **partial** | a49802b, 2cc212e | B/pai_c/paths/programs.py; B/plugins/gap_assessment/__init__.py (reused) | Shown/confirmed threshold comparisons and reviewed bands; no invented weighted merit formula or admission probability. |
| 09 World knowledge / `39:858` | Reply has an institution fact without a source? | **partial** | b10b8ae, 2cc212e | B/pai_c/deep/grounding.py | Same deterministic limitation as 36:389; no additional model verifier added. |
| 10 Paths to a decision / `39:971` | What it is and what you study | **done** | 56dcf66, e361e7e | B/pai_c/paths/{explain.py,explain.md}; F/components/counselor/workspace/paths.tsx | Strict explanation schema; generic description follows language policy. |
| 10 Paths to a decision / `39:975` | A normal work day and the skills it needs | **done** | 56dcf66, e361e7e | B/pai_c/paths/explain.py; F/components/counselor/workspace/paths.tsx | Work-day and skills sections; actual prose quality has not been live-evaluated. |
| 10 Paths to a decision / `39:979` | How it fits you - evidence for and against | **done** | 56dcf66, e361e7e | B/pai_c/paths/explain.py; F/components/counselor/workspace/paths.tsx | Fit quotes must occur in supplied student evidence; for and against both have a home. |
| 10 Paths to a decision / `39:983` | Myths vs reality, jobs and future | **partial** | 56dcf66, 2cc212e | B/pai_c/paths/{explain.py,policy.json} | SourceVerifier and current sourced claims; missing reviewed domains prevent verified jobs/myths/outlook. |
| 10 Paths to a decision / `39:987` | Ways in: the main route and other routes | **done** | 56dcf66, e361e7e | B/pai_c/paths/explain.py; F/components/counselor/workspace/paths.tsx | General routes and try-it supported; institutional entry requirements belong to H. |
| 10 Paths to a decision / `39:999` | Programs for this path - search, source check, cache | **done** | a49802b, 2cc212e | B/plugins/program_search/__init__.py; B/research/gateway.py; B/routers/counselor_paths.py | Existing discovery/research/cache/verifier reused; expired results require another explicit search. |
| 10 Paths to a decision / `39:1003` | Eligible with shown or confirmed marks? | **done** | a49802b, 2cc212e | B/pai_c/paths/programs.py | Current workspace and current shown/confirmed facts re-read on results; ambiguous comparisons fail closed. |
| 10 Paths to a decision / `39:1007` | Safe / realistic / stretch - with fee and scholarships | **partial** | a49802b, e361e7e | B/research/season_policy.json; F/components/counselor/workspace/paths.tsx | Fee/scholarship source/date rendering and bands supported; reviewed seasonal data absent. |
| 10 Paths to a decision / `39:1011` | Not yet - the route to become eligible | **partial** | a49802b | B/pai_c/paths/programs.py; B/plugins/gap_assessment/__init__.py (reused) | Shows only cited remediation. Missing remediation cannot safely produce a route. |
| 11 PAI C and PAI OS contract / `41:1029` | Planner turns outcomes into shown evidence; check-in with the student (stage K) | **not done** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md | New OS outcome-to-shown contract requires joint schema/signoff; existing extraction unchanged. |
| 11 PAI C and PAI OS contract / `41:997` | Add to the record: chosen path and chosen place as separate fields, reasons with evidence, and an execution summary (limits, strengths, family concerns, certainty, language, check-in rhythm) | **not done** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md | Existing decision records retained; no unapproved chosen-path/place schema extension. |
| 11 PAI C and PAI OS contract / `41:1009` | OS becomes a request source: typed requests (question, document, approval, decision), reason, urgency, and an answered event back to OS | **not done** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md | Existing requests/escalations retained; no new OS typed-request/answer-event protocol. |
| 11 PAI C and PAI OS contract / `41:1025` | 3 UPDATES  OS to C - authenticated event intake, versioned event types, idempotent (same event never counted twice) | **not done** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md | No new versioned OS update intake without joint agreement. |
| 11 PAI C and PAI OS contract / `41:1037` | Typed reason: not eligible, deadline passed, cost, changed mind, other | **not done** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md | Typed OS reason protocol deferred with the shared contract. |
| 11 PAI C and PAI OS contract / `41:1065` | Contract rules: versioned schema (v1, v2 only with a migration path) / service-to-service token on every call / idempotency key on every event / contract tests on both sides that fail when one side breaks the other / no student private data in OS logs / changes only with both developers signing off | **partial** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md; existing contract/security tests | Existing token/isolation/idempotency contract preserved; new bilateral versioned tests need the OS developer. |
| 12 Behind the counselor - Operator and background work / `43:1112` | path.explain | **done** | 56dcf66 | B/plugins/path_explainer/__init__.py; B/research/gateway.py | path.explain is an installed workflow owner using existing durable operator.run. |
| 12 Behind the counselor - Operator and background work / `43:1128` | program.search | **done** | a49802b | B/plugins/program_search/__init__.py; B/research/gateway.py | program.search uses existing Task Runtime and Operator workflow mode. |
| 12 Behind the counselor - Operator and background work / `43:1176` | contract.intake | **not done** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md | No duplicate or guessed contract.intake capability. |
| 12 Behind the counselor - Operator and background work / `43:1116` | Operator in workflow mode: model for general understanding + research.run for jobs and future (cache, web.search, web.fetch, SourceVerifier) | **partial** | 56dcf66 | B/pai_c/paths/explain.py; B/plugins/path_explainer/__init__.py | Workflow/model/cache/tools/verifier wired; real verified career-source coverage unavailable. |
| 12 Behind the counselor - Operator and background work / `43:1132` | Operator: research.run + requirements plugin + per-season entry and merit rules + merit calculator | **partial** | a49802b, 2cc212e | B/plugins/program_search/__init__.py; B/pai_c/paths/programs.py; B/research/seasons.py | Research/requirements workflow works offline; authoritative season packs and merit formula data remain absent. |
| 12 Behind the counselor - Operator and background work / `43:1180` | Authenticated, idempotent intake; Planner turns outcomes into shown evidence | **not done** | 2cc212e (blocker documentation) | docs/counselor/BLOCKERS.md | Same joint OS intake blocker; existing contract is preserved. |

### Important boundaries

- One conversation is retained. Voice and text still enter the existing orchestrator; this build does not create another counselor, profile, queue or inference client.
- Mirror confirmation materializes paths without starting institutional research. Path explanation is G; H requires a completed current path and an explicit student POST consent.
- Repeated requests reuse durable runs. A changed route or expired evidence requires explicit refresh; GET never starts research. Existing Mirror budgets apply.
- Program results are rechecked against current workspace sources and current shown/confirmed student values. Meeting entry requirements is **eligible**, not an admission probability.
- The general explanation is model prose. Strict schemas and exact student evidence checks do not prove every qualitative claim true, nor universally detect an unmentioned institution name. Unsupported structured facts are withheld.
- SourceVerifier and the existing research family are reused. No new capability named research.run was created; existing research-family ownership remains.
- Profile review controls apply to canonical Vault facts/records. Interpretation chips remain evidence-backed projections; their corrections go through the conversation and Analyst ownership, not direct Truth Map editing.
- Certainty visualization uses durable Mirror before/after feedback. It does not fabricate a continuous time series from missing measurements.
- No university-sharing flow is enabled. A later sharing flow needs exact-data, per-university consent.

### Five requested continuation items

| Item | Engineering status | Entry point / data | Remaining verification or data dependency |
| --- | --- | --- | --- |
| Stage D myth correction | Implemented | policy/state.py -> clear_myth -> research/gateway.py -> research.claim; myths.json, myth_check.md | Exact source quotation and date; reviewed domain/registry required. No source means an open request. Live relevance/source coverage untested. |
| Stage I family talk | Implemented | Compare panel -> GET/POST /v1/counselor/family-talk -> Messenger; family_talk.json | Student selects a recorded concern and evidence; chosen path with H proof required. No guarantee that the selected evidence resolves the concern. |
| Stage K proactive check-ins | Implemented | Explicit roadmap choice or POST /paths/{id}/try-it -> counselor.checkin -> Messenger; checkins.json | Existing delayed queue; care/quiet-time/spacing deferral; no historical backfill or OS dependency. Real worker delay not live-tested. |
| Daily health alert | Implemented | session.sweep -> counselor.health_alert -> notify_once; reliability.json | At most one workspace/UTC-day alert after threshold crossing; existing worker and inbox required. |
| Readable evidence and voice control | Implemented | evidence-labels.json, evidence-text.ts, profile/roadmap renderers, counselor-voice-copy.json | Unknown schema keys omitted rather than exposed. Synthetic light/dark screenshots; no live microphone session. |

These are updates to the locked workflow, not additional invented orange cards. Full new feature testing is deferred by instruction; retained regression suites and the browser fixture remain the acceptance checks for this run.

## Phase 3 screens and screenshots

Screenshots use real production components with synthetic, network-blocked backend/workspace adapters. They are **not** screenshots of a live student account. There are **34 desktop captures plus one mobile capture**. Light/dark theme tokens, accessible controls and mobile overflow were checked; existing unit snapshots remain. Chat now shows one Talk to PAI label; profile/evidence and roadmap labels come from data.

| Screen / stage | Light | Dark |
| --- | --- | --- |
| Onboarding (A) | [Light](screenshots/onboarding-light.png) | [Dark](screenshots/onboarding-dark.png) |
| Chat (B-D) | [Light](screenshots/chat-light.png) | [Dark](screenshots/chat-dark.png) |
| First picture (C) | [Light](screenshots/first-picture-light.png) | [Dark](screenshots/first-picture-dark.png) |
| Fact / upload invitation | [Light](screenshots/fact-card-light.png) | [Dark](screenshots/fact-card-dark.png) |
| Certainty rating | [Light](screenshots/rating-light.png) | [Dark](screenshots/rating-dark.png) |
| Mirror / agree-change (E) | [Light](screenshots/mirror-light.png) | [Dark](screenshots/mirror-dark.png) |
| Journey (A-K) | [Light](screenshots/journey-light.png) | [Dark](screenshots/journey-dark.png) |
| Paths (F) | [Light](screenshots/paths-light.png) | [Dark](screenshots/paths-dark.png) |
| Path explanation / try-it (G) | [Light](screenshots/path-light.png) | [Dark](screenshots/path-dark.png) |
| Where to study / consent (H) | [Light](screenshots/programs-light.png) | [Dark](screenshots/programs-dark.png) |
| Compare (I) | [Light](screenshots/compare-light.png) | [Dark](screenshots/compare-dark.png) |
| Guided family preparation (I) | [Light](screenshots/family-talk-light.png) | [Dark](screenshots/family-talk-dark.png) |
| Explicit choice confirmation (I) | [Light](screenshots/decision-light.png) | [Dark](screenshots/decision-dark.png) |
| Plan and check-ins (J-K) | [Light](screenshots/plan-light.png) | [Dark](screenshots/plan-dark.png) |
| Living profile | [Light](screenshots/profile-light.png) | [Dark](screenshots/profile-dark.png) |
| Documents | [Light](screenshots/documents-light.png) | [Dark](screenshots/documents-dark.png) |
| Settings / privacy | [Light](screenshots/settings-light.png) | [Dark](screenshots/settings-dark.png) |

[Mobile profile, dark](screenshots/profile-mobile-dark.png).

### Routes, components and APIs

All workspace pages reuse the existing /[workspaceId] route and query navigation, rather than adding a second app shell:

| Surface | Query / component | API path reused or added |
| --- | --- | --- |
| Chat, inline cards, Mirror | view=threads; existing ChatView and Mirror card, workspace/inline-card.tsx and fact-card.tsx | Existing events, voice, Mirror confirm/edit/feedback; added /v1/counselor/fact-cards. |
| Journey | view=journey; workspace/journey.tsx | Added GET /v1/counselor/workspace; links to durable conversation event ids and older history. |
| Paths / explanation | view=paths, path=<id>; workspace/paths.tsx | Existing possibilities save/dismiss; added GET /v1/counselor/paths/{id}, POST /explore. |
| Where to study | view=paths&path=<id>&stage=H | Added GET/POST /v1/counselor/paths/{id}/programs; POST requires explore_places consent. |
| Compare / choose | view=compare; workspace/decisions.tsx, existing RoadmapsView | Added path-scoped POST /roadmap after completed program check; existing roadmap choice-token and choose endpoints. |
| Plan / check-ins | view=plan; workspace/decisions.tsx | Existing chosen roadmaps and manual check-in draft; new delayed counselor.checkin posts in-app after choice/accepted try-it. POST /v1/counselor/paths/{id}/try-it requires acceptance. |
| Family preparation | view=compare; workspace/family-talk.tsx | GET/POST /v1/counselor/family-talk, existing access checks; selected own evidence and submission idempotency, posted through Messenger. |
| Profile | view=profile; workspace/profile.tsx | Existing student profile; added profile-cards read/review and public workspace projection. Confirm/Edit/Remove use the reconciler. |
| Documents | view=files; existing document components | Existing authenticated files/document pipeline; no alternate uploader or store. |
| Settings | view=settings; workspace/settings.tsx | Existing language/preferences, notification center and integration settings; added owner-only GET /v1/counselor/export; existing explicit account deletion. |
| Reliability | workspace/shell.tsx | Added owner-only GET /v1/counselor/health; public liveness unchanged. |

All new endpoint families are exercised by the existing P0 anonymous/cross-workspace security matrix. Export includes student-visible conversation/profile/paths/roadmaps/confirmed picture/ratings/document metadata; original files remain downloadable in Documents. Internal notes, legacy archives and credentials are excluded.

Empty, pending/loading, error and missing-evidence states are present. Pending path/program jobs poll only their read endpoints. No fake backend data is mounted in production routes.

## Tests and verification

Final production-code head tested: **eb1db6c** (backend **61e9c19**). Baseline was **a92168a**, with 1,324 backend tests passing in each mode and 60 frontend tests.

| Check | Result |
| --- | --- |
| Full backend, guided | **1,330 passed, 3 skipped, 8 subtests passed**, 488.83 seconds |
| Full backend, strict | **1,330 passed, 3 skipped, 8 subtests passed**, 483.66 seconds; PAI_POLICY_MODE=strict asserted before collection |
| Production-only security tests | **3 passed, 4 subtests passed**, 1.39 seconds |
| Full frontend | **60 passed in 18 files**, 24.39 seconds |
| Frontend production build | **PASS**; TypeScript, lint/build checks and static page generation completed |
| Import every app module | **288/288 imported**, no unresolved dynamic imports |
| Architecture / PAI OS contracts | **PASS**, included in both full backend suites; existing gateway, runtime, memory, Messenger, orchestrator, research and escalation contracts retained |
| Offline browser A–K UI flow | **PASS**; onboarding, Mirror feedback, Explore, explicit H consent, roadmap preparation/choice, plan and check-in draft |
| Browser screenshots | **34 desktop + 1 mobile**; both themes; guided family panel, readable profile/roadmaps, single voice label; no page errors; mobile profile no horizontal overflow |
| Live providers / live conversations | **Not run**, as required |

The three default-suite skips are the production-only security class, run separately above with its required public production origin, without changing code or .env. Three SQLAlchemy warnings concern SQLite reflection of an existing expression index in migration tests. The test-only Vite preview also warns about the existing highlight.js CSS import order; the production build passes and browser captures have no page errors.

### Before / intermediate / after

- Before the approved removal: 1,240 backend tests per mode; restored step 1: 1,260 per mode and 41 frontend tests.
- Step 2: 1,271 backend tests per mode. Step 3: 1,279 per mode.
- Step 4 exposed an incorrect published-fact lookup (1,283 passed, 1 failed); fixed against the actual model in 56dcf66, not bypassed.
- Steps 5–7 integrated checkpoint: 1,302 passed per mode, 3 skips, 8 subtests.
- Phase 3 checkpoint: 1,313 passed per mode, 3 skips, 8 subtests.
- Previous final: 1,324 per mode and 60 frontend tests. These checkpoints do not claim an independent full-suite run at every historical intermediate commit.

Continuation: the first complete run found one outdated capability inventory assertion (1,329 passed, one failed, three production-only skips). Its exact expected job set now includes research.claim, counselor.checkin and counselor.health_alert; the test still requires every enqueue to resolve to a system contract. The P0 route matrix automatically covers six additional anonymous/cross-workspace cases for the new endpoints. No new test file was added. TypeScript found a missing fallback label; it now uses the existing Other copy, and the production build passes. No regression/security/contract assertion was weakened.

Final continuation: **1,330 passed per mode, 60 frontend tests, production build green, 288 imports**. An initial shell wrapper used an unused mode-variable name; the reported strict result above is the subsequent explicit PAI_POLICY_MODE=strict run with a config assertion, not that wrapper's run. Provider keys were unset, dotenv loading disabled and external sockets blocked throughout verification.

### Coverage and test changes

| Concern | Evidence |
| --- | --- |
| Empty/contradictory profile, retired items, quoted facts, mixed-language input | Existing policy/Truth Map tests; test_spine_areas.py, test_next_move.py, test_profile_evidence.py |
| Distress/request interruption and one-question behavior | Existing safety/guided/strict/request tests plus new thread/card priority cases |
| Timeout, invalid JSON, duplicate work and return visits | Existing deep-turn/session/task tests; new reliability, path/program run reuse and freshness cases |
| No source, outdated source, ambiguous data, not eligible yet | test_world_knowledge.py, test_path_explanation.py, test_program_search.py |
| Family versus own wish, rejecting paths | Existing possibility lifecycle/Mirror/planner tests; new evidence-only profile projection |
| Profile review/erasure/export ownership | test_profile_evidence.py, test_counselor_workspace.py, existing P0/record/security/export tests |
| Cards, coverage, profile, paths, settings, themes | One new feature test file each under frontend/components/counselor/workspace; retained existing frontend tests |
| A–K and consent boundaries | frontend/tests/preview/workspace.e2e.cjs with explicit network blocking and synthetic fixtures |

Existing test changes match intended behavior: ten areas instead of eight; no research on Mirror confirmation; valid auth fixtures now contain required network/UUID/const values; durable fixture foreign keys are present; profile assertions cover the new separate sections. The choice-dialog test selects the footer Close explicitly because its X control has the same accessible name. The final capture change uses the actual theme provider and waits for dialog animation. No security/contract expectation was weakened and no failing assertion was deleted.

In this continuation the only unit-test edits are the exact registered-job inventory and the existing profile editor test's public label (Name instead of identity.full_name). The screenshot adapter supplies synthetic family/evidence and accepted-activity responses. These are fixture updates, not live calls. New extensive tests for the new behaviors remain explicitly deferred as requested.

## Deferred UI cleanup and shared code kept

[UI_CLEANUP_V1.md](UI_CLEANUP_V1.md) contains commands and pre-deletion importer evidence. Commit 131decb deleted 12 files: monitor grid/overlay/tile, agent profile panel, thread list, routines view/list/format helper, and knowledge view/list/editor/utils. **2,954 file lines plus six ListPanel branch/import lines** were removed.

Kept because shared or still imported: wrapper/context/API/notifications, AppSidebar/MobileHeader, CreateRoutineDialog, orchestration/sharing controls, Browser backend, integration relay/settings, generic Operator, workflow advancement, tasks.list/tasks.create, shared tools/plugins, auth/workspaces/onboarding, memory/Vault/reconciler/documents, gateways/Task Runtime, decision records/student requests/escalations/service token.

The import graph still reaches services.workflow from Counselor dependencies; it is not safe to delete. Detached application/deadline packages were not deleted. Tables for a separate approved migration review: pai_saved_institutions, pai_application_plans, pai_application_requirements, pai_application_routines, pai_student_deadlines, pai_deadline_settings. **No drop was performed.**

## Decisions and blockers summary

[DECISIONS.md](DECISIONS.md):

1. Catalog-only factual cards, editable Other, exact student quote for prefill, explicit confirmation.
2. Confirmation is value-bound and audited; editing returns to stated; removal reconciles and preserves history.
3. Paths before places; explicit program-search consent; current evidence revalidated on reads; no GET-triggered research.
4. Eligibility is distinct from admission bands; no guessed equivalence, threshold or probability.
5. Existing shell/services/contracts reused. Delayed in-app check-ins reuse Task Runtime; no OS scheduler. Manual drafts remain available.
6. Reliability is private daily aggregation, in-app lag and threshold-based existing-inbox delivery. Export is public student data only.
7. Board-supplied entry choices are data; family/interpretation remain safe projections.
8. Myth checks quote only current trusted sources; missing verification leaves the question open. Care and requests take priority.
9. Guided family preparation uses a chosen path, recorded family concern and student-selected evidence. No invented resolution or guaranteed outcome.
10. Display labels/enum text live in data, technical ids stay hidden, and the voice control has one idle label.

[BLOCKERS.md](BLOCKERS.md):

- Reviewed board/subject catalogs absent: editable text/upload remains.
- Reviewed occupational domains and seasonal merit packs absent: verified world sections/bands are unavailable rather than invented. Weighted merit formula data is not supplied.
- Deterministic grounding cannot prove all free prose true or detect every unsourced qualitative institutional claim.
- Exact fact/rule identity or unit ambiguities stay unknown.
- Board 11/contract.intake needs bilateral versioned schema agreement and both developers' tests. Existing contract remains; no pai-os edits.
- Daily alerts/check-ins reuse the existing worker and inbox; no new university-sharing flow. Historical choices are not backfilled.
- New feature depth/quality testing is deferred as instructed. Delayed delivery and live source coverage have not been exercised on a real configured deployment.
- No live Supabase, microphone, OCR, search-provider or conversation-quality validation was authorized.

## Founder local test

From the existing **workspace** folder, using the founder's existing ignored configuration:

~~~powershell
git checkout pai-c
git pull --ff-only origin pai-c
docker compose --env-file .env -p pai-c-test2 -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
~~~

Open **http://localhost:3000**. If another Compose project owns ports 3000/8000/8080, stop that project first; do not remove its volumes.

1. Sign in; a new account sees name, level, city and reply-language entry cards.
2. Use Counselor; try a factual reply, a document invitation, a correction and a request. Profile should show sources and review controls.
3. Confirm/edit the Mirror and submit feedback. Inspect Journey and Profile.
4. Explore a path. Its page has general explanation, evidence for/against and a try-it; programs require the separate Where to study consent.
5. Missing verified sources/rules show missing information. They must not turn into invented eligibility or admission chances.
6. Where a verified program check supports a reviewed roadmap, prepare it and use the existing explicit choice dialog. Open family preparation in Compare, select the recorded concern and evidence, then save it to the same conversation. Missing evidence stays a visible missing-information state.
7. Explicitly accept a try-it to schedule its in-app follow-up (default three days); a chosen path schedules one after seven days. Data files control timing; care/recent conversation defers delivery. Plan's manual check-in draft remains yours to send. Daily reliability thresholds use the existing notification bell.
8. Check light/dark, phone layout, export and privacy settings. Account deletion has a separate explicit destructive confirmation.

The stack was **not started as part of this autonomous verification**, to avoid waking real configured provider jobs. The command above starts normal founder use, which can incur the founder's configured provider costs. The offline test preview is not a substitute for that live acceptance test.

