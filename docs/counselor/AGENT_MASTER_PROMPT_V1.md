ROLE
Senior engineer on PAI C (the counselor). Branch: pai-c only. Never touch dev or pai-os.
Build like production software: simple, safe, readable, easy to change, nothing hardcoded.

SOURCE OF TRUTH (read all before any code)
- Figma board (LOCKED v1): https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF
  Sections 00-12. White card = built. Orange border "NEW" = your work.
- docs/counselor/PAI_C_WORKFLOW_LOCK_V1.md
- docs/counselor/COUNSELING_POLICY.md
- docs/counselor/SPINE.md
- docs/counselor/archive/CLEANUP_AUDIT.md (OS removal only)
- The board decides behavior. If code and board disagree, stop and report. Never guess a product decision.

PRODUCT RULES (never break)
1. One counselor. The student always talks to one PAI. PAI OS never talks to the student.
2. Same 10-area spine for every student. The order follows the student. Never a form.
3. Paths first, places later. Never name or push a university before stage H (board 10).
4. No fact about the student without evidence (stated / shown / confirmed).
   Merit numbers only from shown or confirmed facts.
5. No fact about the world without a source and date. The model only explains in general terms.
6. Safety first: distress always routes to care. A request is never dropped.
   Replies in English or Roman Urdu only, never Devanagari.
7. At most one question per reply. No question after two asking replies in a row, for every action
   except care. The action still happens; only the question is removed.

ENGINEERING RULES
- Reuse before building. Never add a new framework, a parallel service or duplicate logic. Use:
  - Model Gateway for every model call
  - Task Runtime for every background job (idempotency keys, order per student)
  - Operator in workflow mode for counselor background work
    (research, roadmaps, path explainer, program search)
  - Capability Registry and Tool Registry (web.search, web.fetch, files)
  - research gateway, web_search (Tavily/Brave), SourceVerifier, requirements plugin
  - Memory Service, reconciler, possibilities, roadmap builder, policy controller, Messenger
- Zero hardcoding. No country, institution, exam, language or persona in code.
  - Policies, thresholds, area lists, rules, copy and labels live in data files (json/md), config or i18n.
  - Pakistan content lives only as data.
- Prompts live in .md files. All model output is validated with strict schemas.
  - Conversation fails open: the student always gets a reply.
  - Facts fail closed: if unsure, drop the fact and say it will be checked.
- Module boundaries:
  - Shared modules signal PAI C only through named Task Runtime jobs.
  - Writes to student facts go only through the Memory Service and reconciler.
  - The Truth Map is private to PAI C.
- DB changes only through migrations, backward compatible and lossless. Never drop tables in this work.
- Readable code:
  - small functions, clear names, one responsibility
  - no dead code, no copy-paste, no commented-out code
  - comments say why, not what
- Security:
  - never print or log secrets or student personal data
  - never edit .env
  - access checks on every new route
- No live model or API calls without written approval and a cost cap.

TESTS
- Build the feature first, then add its tests in the same step. A step is not done without its tests.
- Keep all existing tests (regression, security, contract). Do not delete them.
  They prove nothing broke. Each new feature gets one new test file.
- Offline only, fake providers. Run the full backend suite in both policy modes, with PAI_API_KEY unset.
  Also run the frontend tests and build.
- Edge cases to cover where relevant:
  - empty profile; contradictory facts; Roman Urdu input
  - distress or a request in the middle of any flow
  - provider timeout or bad JSON; duplicate jobs
  - student returns after days
  - no source found; not eligible yet
  - student rejects every path; family wish vs own wish

WORK ORDER (one step = one commit; if a step fails, revert it, stop and report)

PHASE 0 - Fix the question limit
- Add a data-driven cap in guided_table.json, and the same in strict mode:
  when questions_in_last_two is true, question_allowed = false for every action except care.
- first_picture ends with an invitation ("Tell me what feels right and what feels wrong"), not a question.
- Test the two reproductions: first_picture and guide after two asking replies.

PHASE 1 - Remove PAI OS from pai-c (frontend and backend)
- Tag pre-os-removal (done). Step 1 is AUDIT ONLY, no deletion.
  Audit table: file / module / route / table -> OS-only | shared | C-only | shared-split-later,
  with evidence from the import and call graph.
- KEEP (PAI C core and contract, Figma sections 11 and 12):
  - auth, workspaces, onboarding
  - Vault, memory, Memory Service, reconciler, documents
  - Model Gateway, Task Runtime, Operator + operator.run, agent.run (generic engine)
  - Capability and Tool Registries and every capability PAI C calls
  - research gateway, web_search, SourceVerifier, research plugins
  - workflow and posting code the counselor imports, Messenger
  - decision records, student requests, escalations + service token
- Rule: if PAI C imports it, calls it, or a PAI C job runs through it, it stays.
  Mixed modules are marked "shared - split later" and not deleted in this round.
- Send me the audit table and wait for approval. Then delete only what is proven OS-only:
  OS pages, components, routes, services, routines, OS task templates, OS-specific agents and tools.
- One commit per area. After each commit: full test runs.
- Remove dead imports, env keys, navigation links and flags that only OS used.
- Never drop tables. List OS-only tables for a later migration.

PHASE 2 - Backend core (orange NEW items)
1. Spine: areas 9 (goals, whose wish) and 10 (options known, myths).
   Tap cards and uploads write into status, history and strengths.
2. Next move: a follow-their-thread step, and fact vs story (fact = tap card, story = one question).
3. Evidence: confirm/edit of facts through the reconciler, and a "confirmed" evidence level.
4. Knowledge:
   - cache first, season expiry
   - grounding guard on replies
   - per-season verified entry and merit rules as data
5. Path explainer, stage G (path.explain job via Operator):
   what it is, what you study, a work day, skills, fit for/against with evidence,
   myths vs reality, jobs and future, ways in.
6. Where to study, stage H (program.search job via Operator):
   - programs, eligibility from shown/confirmed marks
   - safe / realistic / stretch / not yet + route
7. Reliability: health checks, Planner lag alert, a daily count of every fallback.

PHASE 3 - Frontend: only PAI C, complete and polished
- English UI, light and dark mode. Existing stack, tokens and components.
- Screens (every stage A-K has a home):
  1. Onboarding: 4 tap cards (name, level, city, reply language).
  2. Chat (home) with inline cards:
     - tap choice, upload, 0-10 rating
     - first picture, Mirror (agree/change + ratings)
     - path cards (Explore / Save / Not for me)
     - try-it, check-in
  3. Journey: stages A-K as a calm progress view (no badges or streaks).
  4. Paths, with "why it fits you" in the student's own words.
  5. Path page (G). No universities.
  6. Where to study (H), only opened from a path.
  7. Compare and choose (I): paths first, then places, family-talk help, decision card with certainty.
  8. Plan (J) and check-ins (K).
  9. Profile.
  10. Settings: language, theme, notifications, privacy (export, delete, who sees what).
- PROFILE = the Vault inside a professional, visual profile.
  Kollegio shows the same content as forms (Details form, 8 "Your story" questions, completion %, missing details).
  We show a living picture built from conversation:
  - Header: name, level, city; a 10-area coverage wheel (shaded by evidence, not a score);
    certainty over time (small line chart); last "felt understood" rating.
  - "Who I am": the confirmed Mirror in 4 lines.
  - Education timeline: marks, board, subjects, tests. Uploads carry a "shown" badge.
  - Interests and strengths as chips with an evidence level and capability status. Never a personality or ability score.
  - People around me: a family map (role, what they want, the worry behind it).
  - Values, pressures and limits; goals with "whose wish"; options known and myths cleared.
  - Every fact is a card: tap to see the source ("you said on 12 Oct: ..."), then Confirm / Edit / Remove,
    all through the reconciler.
  - "PAI still wants to know": soft chips that open the chat on that topic. Never a form, never nagging.
  - Private interpretation and sensitive items are hidden by default.
    Nothing is shared with any university without explicit per-university consent.
  - Do not copy from Kollegio: identity or ethnicity prompts, form-first fields,
    "multiply your chances" nags, US-only fields.
- Frontend engineering:
  - all copy from data or i18n files
  - reuse endpoints; add small typed endpoints behind access checks only if missing
  - accessible, phone-first, SVG over heavy chart libraries
  - every screen has empty, loading and error states
- Frontend tests: component tests per card and profile section, an e2e happy path A-K with a fake backend,
  dark-mode snapshots.

REPORT AFTER EVERY STEP
- commit SHA
- files changed
- data files added
- test counts (both modes, frontend)
- edge cases covered
- screenshots light + dark for UI steps
- open questions (never decide product questions yourself)

REFERENCE - WHAT WE ARE BUILDING (for understanding only; never hardcode anything from it)
A senior school counselor who has known the student for years, available 24/7. It knows the person first,
shows the paths they could take, helps them understand one path, and only then shows where to study it.
The student decides. PAI never decides for them.

Example: Ali, FSc Pre-Engineering, replies in Roman Urdu.
- B: "Abbu chahte hain engineer banun. Mujhe phone repair karna acha lagta hai."
  Saved with quotes:
  - family wish (father)
  - interest (repairs phones)
  - strength shown (fixes friends' phones)
  Marks: a tap card invites a result card upload, so the marks become "shown".
  GOOD: one question that follows his thread.
  BAD: "CGPA? Budget? City?" (that is a form)
- C: "Jo mein samjha: ... Ye raaste dekhne layak hain: electronics/electrical kaam, mobile/embedded tech,
  applied IT. Kya sahi laga, kya ghalat?" No universities.
- D: the father's job-security worry; a myth fixed with a source.
- E: the Mirror in 4 lines. Understood 5/5, certainty 4/10.
- F: paths with "why it fits you". Ali explores Electrical Engineering.
- G: what it is, a work day, fit for (repairs, logic) and against (heavy maths), myths, jobs, ways in.
  Try-it: build a simple LED circuit.
- H (only because Ali asks to go deeper): programs with source and date;
  confirmed marks give safe / realistic / stretch; not eligible = the route.
- I: compare, help talking to his father, Ali chooses, certainty 4 to 8, decision record with evidence.
- J-K: plan handed to PAI OS later; check-ins after results.

SUCCESS: Ali feels understood (4/5+), certainty rises, and the decision is his own and backed by evidence.
Any of these is a bug:
- a reply invents a fact
- a university is named before H
- form-style questions
- distress is ignored
