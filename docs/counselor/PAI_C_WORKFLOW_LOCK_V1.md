# PAI C engineering workflow — LOCKED v1 (18 Oct 2026)

Figma board (source of truth): https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF
Sections: header (6 principles, legend), 00 A to K, 01 what the student sees, 02 one turn, 03 spine (10 areas), 04 evidence, 05 next move, 06 stages, 07 failures, 08 vs Kollegio, 09 world knowledge, 10 paths to a decision, 11 PAI C and PAI OS contract. White card = built in code; orange border "NEW" = new work.

## What PAI C is
An AI counselor for Matric/O-level and FSc/A-level students (Pakistan first, generic by design): knows the student deeply, shows them the paths they could take, helps them understand a path, and helps them reach their own decision. Stays with them. Applications, test prep, deadlines = PAI OS.

## Founder rule: paths first, places later
The counselor never sends a student to a university. It shows what they could do (paths = fields and kinds of work), helps them understand one path, and only when the student wants to go deeper on that path shows where to study it. Pilot universities are a business matter (PAI University), not counseling logic.

## A to K
A Entry (4 tap cards) → B Getting to know (conversation + small cards; 10 areas) → C First picture (directions in general words, no institutions) → D Deepening (gaps, tensions, myths) → E Mirror (4 lines, agree/change, understood 1-5, certainty 0-10) → F Paths (3-5 paths, own + found, why each fits; explore/save/not for me) → G Explore a path (what it is, what you study, a work day, skills, fit for/against with evidence, myths vs reality, jobs and future, ways in, try-it) → H Where to study (only for a path the student wants to go deeper on: programs, entry rules, merit, fee, scholarships, sourced; eligibility from shown/confirmed marks; safe/realistic/stretch; route if not eligible yet) → I Compare and choose (paths first, then places; family help; certainty again; decision record) → J Plan (handoff to PAI OS) → K Stay with them.

## Locked decisions
- Spine = 10 areas: status, history, interests, strengths, family, values, pressures, certainty, goals (whose wish), options they know (myths). Order follows the student.
- Evidence: no quote/document → no fact; stated / shown / confirmed; merit numbers only from shown or confirmed.
- World knowledge 3 layers: model explains fields and work in general; search (existing Tavily/Brave tool) + SourceVerifier + cache with source/date/season for jobs, programs, fees, scholarships; entry and merit rules checked per season for programs a student is looking at. Grounding guard: no institution fact without a source.
- Next move: care → request → their own thread → no question after two → first picture → highest-priority uncovered area → fact = tap card / story = one question.
- Success: confirmed decisions, understood ≥ 4/5, certainty gain.

## PAI C ↔ PAI OS contract (section 11)
Roles: C owns understanding, the one voice to the student, and the choice. OS owns the action plan and execution. OS never talks to the student directly; every message goes out through PAI C (Messenger).
1. Handoff C→OS: decision record (built: immutable, versioned; roadmap version, confirmed summary, objective, risks, assumptions). NEW: chosen path and chosen place as separate fields, reasons with evidence, execution summary (limits, strengths, family concerns, certainty, language, check-in rhythm).
2. Requests OS→student via C (built: pai_student_requests). NEW: OS as a request source, typed requests (question, document, approval, decision), reason, urgency, answered event back to OS. C asks in its own voice, saves the answer through the reconciler.
3. Updates OS→C. NEW: authenticated, versioned, idempotent event intake (applied, test score, admitted, rejected, deadline missed); Planner turns outcomes into shown evidence; check-ins (stage K).
4. Escalation OS→C (built: endpoint + service token). NEW: typed reason (not eligible, deadline passed, cost, changed mind, other); student goes back to Paths or Deepening, care first.
Data: Truth Map private to C (OS gets only the execution summary); Vault facts shared read, writes only via reconciler with evidence; shared code signals C only via named Task Runtime jobs.
Rules (NEW): versioned schema v1, service token on every call, idempotency keys, contract tests on both sides, no student private data in OS logs, changes only with both developers' sign-off.
Open, to agree with the PAI OS developer: decision record field list v1, event types, request types, escalation reasons, reminders (OS asks, C speaks), sign-off date.

## New work (orange "NEW")
Tap cards + uploads into profile; areas 9 and 10; profile confirm card; follow-their-thread + fact-vs-story; myth correction; path explainer (G); program search + eligibility + labels + not-eligible route (H); family talk help; cache-first + season expiry + grounding guard; health checks, Planner lag alert, fallback counts; OS contract items above; check-ins later.
