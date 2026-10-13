# PAI C master plan (implement against the master map)

Date: 10 Oct. Status: proposal for founder approval.
Master map: FigJam NyfnqKOPD7rIAxUxky5dag (1 whole system, 2 memory, 3 journey states, 4 build phases).
Details: ARCHITECTURE.md (incl. section 11 data review), CORE_V1_SPEC.md, PRODUCT_FEATURES.md, COUNSELING_METHOD.md.

## Areas of the system
A Entry: sign up/in (Supabase, exists), onboarding (exists), workspace per student (exists).
B Conversation: chat text + voice (exists), documents (exists).
C Turn engine: safety gate (new), Voice (rewrite), Planner (Analyst v2), fact extractor (exists, narrowed to facts), playbooks (new).
D Memory, five kinds with one owner each:
  1 Working memory: recent turns (exists).
  2 Facts (Vault): objective facts; writers extractor, documents, student edits via the reconciler (exists, boundary to tighten).
  3 Understanding (Truth Map): Planner only (Notebook v2).
  4 Episodic: session summaries written when a session ends (new; today only extracted decisions exist).
  5 Semantic: embeddings index of session summaries, verified facts and documents, used by a real reader for recall on return visits and by the Planner (today write-only; must get a reader or be off).
E Outcomes: first picture (new), Mirror (exists, v2), light research + cache (exists), roadmaps (exists), Try it (new), coach basics (new).
F Screens: Profile CV, My Picture, Roadmaps (design later).

## Phases and gates
(Updated 10 Oct by CLEAN_ARCHITECTURE.md: P0 audit, P1 Spine refactor, P2 Memory foundation, P3 Turn engine, P4 First meeting and Mirror v2, Gate 1, P5 Roadmaps/Try it/coach/OS contract, P6 Profile CV and quality loop, Gate 2. The list below is the earlier order.)
P0 Audit entry (no rebuild): verify sign-up, sign-in, onboarding, workspace creation and session security work end to end; fix only real defects.
P1 Memory foundation: Vault boundary (facts only), Truth Map v2 + migration, session summaries, semantic index with its reader, remove legacy discovery (after checking with PAI OS), generic field definitions, single profile block in context.
P2 Turn engine: safety gate, Planner (patches + next plan), Voice v4, playbooks, repetition guard.
P3 First meeting order, first picture, Mirror v2, understood rating, certainty before/after.
Gate 1: founder test passes on the replay set and live.
P4 Roadmaps reading the Truth Map, Operator workflow mode for research and roadmaps (ARCHITECTURE.md section 12), Try it, coach basics (plan, check-ins on own commitments), PAI C side of the OS contract.
P5 Profile CV backend support, quality loop (judge, scorecard).
Gate 2: 7 of 10 real students reach the Mirror, average understood >= 4/5.

## Why not start by rebuilding authentication
Authentication, onboarding and workspaces already exist and work. Rebuilding them adds risk and no student value. P0 is an audit against the map; P1 (memory) is where the real foundation work is.

## PAI C and PAI OS contract (keep it working from day one)

Roles: PAI C owns understanding, the conversation (one voice to the student) and the choice. PAI OS turns the chosen roadmap into an action plan and runs agentic execution (applications, documents, deadlines, tasks).

Contract (master map diagram 5):
1. Handoff C -> OS: decision record, a versioned immutable snapshot when the student chooses (exists: pai_decision_records with roadmap version, confirmed summary, real objective, accepted gaps and risks, assumptions, channel). To add in P4: a Truth Map summary for execution (constraints, strengths, family concerns, certainty, preferred language and check-in rhythm).
2. Requests OS -> student through C: typed student requests (question, document, approval, decision) with reason and urgency (exists: pai_student_requests, today created by research). PAI C asks in its own voice (chat, voice or notification), saves answers to the Vault, marks the request answered. To add in P4: OS as a request source, request types, urgency, and a pull or event for answered requests.
3. Updates OS -> C: progress and outcome events (submitted, test score, admitted, rejected). To add in P4: an authenticated intake; the Planner turns outcomes into SHOWN evidence and coach moments.
4. Escalation OS -> C: route no longer works (exists: POST /v1/escalations with PAI_OS_SERVICE_TOKEN; CHOSEN -> routes needs a typed reason).
Rules: OS never chats with the student directly; one voice is PAI C. Shared Vault writes go through the reconciler. Every contract change is versioned and agreed with the PAI OS developer.
P0-P3 must not break the existing contract pieces (decision records, student requests, escalations, service token).
