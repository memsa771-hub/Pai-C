ROLE
You are a senior product engineer and product designer on PAI C (the student side of Placement AI).
Read CLAUDE.md first and follow it. Branch pai-c only. Never touch dev or pai-os. Never edit .env.
Reply to the founder in Roman Urdu. Work autonomously: do not stop to ask; log decisions and blockers and keep going.

MISSION
Build the full student app v3: clearly better than Kollegio, Appily and Common App for Pakistani
Matric / O-level / FSc / A-level students. Phone first, visual first, honest, private by default.
This prompt replaces UI_REDESIGN_PROMPT.md and PROFILE_ONBOARDING_PROMPT.md (keep them as history).

SOURCES OF TRUTH (read all before code)
1. Figma design file "PAI Student App - UI v3": https://www.figma.com/design/EVPWN8pE0Yl9ivvOWE4giA
   Frames 01-18 (phone; 18 = Visual Mirror), dark versions of Home/Chat/Profile, D1-D2 (desktop), "Spec" frame (tokens, motion, responsive).
   Match layout, hierarchy, copy tone and visuals. You may improve details; never drop a feature shown there.
2. Blueprint board (what and why): https://www.figma.com/board/rmqJjhkgbqK5sT7X2Wv8cJ (sections 01-12).
3. Engineering board (how, locked): https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF
4. docs/counselor/PAI_STUDENT_APP_RESEARCH.md (competitors, design rules, audit of the current build).
5. docs/counselor/PAI_C_WORKFLOW_LOCK_V1.md, COUNSELING_POLICY.md, AGENT_MASTER_PROMPT_V1.md (product and engineering rules).
If code and these sources disagree, the boards win. Never guess a product decision: write it in DECISIONS.md with your choice and reason, then continue.

BEFORE YOU START
- Run git status. If work from the previous UI redesign run is uncommitted, finish it to a building state,
  run the tests, commit it ("chore: checkpoint before v3"), then start v3.
- Tag pre-v3.
- Make docs/counselor/V3_CHECKLIST.md from the DONE MEANS section below: one line per item, unticked.

NON-NEGOTIABLE PRODUCT RULES
1. One counselor voice (PAI). Paths first, places later: no institution name before the student asks to go deeper on a chosen path (stage H) and gives consent.
2. No fact about the student without evidence (said / shown / confirmed / verified). Merit numbers only from shown or confirmed marks.
3. No world fact without source + date; otherwise label it "general" and keep its light yellow.
4. Traffic lights describe what a path needs, never the student's worth. No scores, no percentages of a person, no ranking of people.
5. Max one question per counselor reply. Distress always goes to care first. A request is never dropped.
6. App UI is English only. The counselor mirrors the student's language (English or Roman Urdu), never Devanagari.
7. Sharing with universities is OFF by default, per field, previewable, logged and revocable. Students are never sold.
8. No ethnicity, religion, SAT, GPA/4, ZIP or other US-only fields. No "multiply your chances" nags.
9. The Mirror is VISUAL and comes LATE (founder decision, 19 Oct). Never show "How PAI sees you" text quadrants.

JOURNEY ORDER (founder decision, 19 Oct - this overrides any earlier UI that showed the Mirror early)
Phase 1 - Getting to know (conversation): chat + small tap cards + uploads fill the MAIN profile first:
  current status, education and marks, interests, strengths, family. No Mirror, no interpretation of the person.
  The profile shows a "building" portrait (empty petals fill as facts arrive) with "Keep talking" - never a text summary.
Phase 2 - First picture / First Snapshot: interest shape + 3-4 directions with lights. This is about directions,
  not a mirror of the person.
Phase 3 - Deepening (counseling): values, pressures and limits, whose wish, certainty, options and myths.
Phase 4 - Visual Mirror: unlocks only when the Mirror gate passes. The gate is DATA (e.g. mirror_gate in the policy
  tables: minimum covered areas incl. values, pressures and goals, minimum evidence per area, no pending correction).
  The Mirror is a portrait, not sentences: 10 petals (one per area, colour per area, size = evidence level
  none / said / shown / confirmed), the student's initials in the centre, a "whose wish" mine <-> family slider,
  3 key tiles (how sure: before -> now, strongest, matters most), "Does this look like you?" 1-5,
  "This is me" / "Something is off". Tapping a petal shows its sources and lets the student fix it.
  The backend Mirror content (4 parts) stays; only its presentation becomes visual. Text appears only on tap.

ENGINEERING RULES
- Reuse first: Model Gateway, Task Runtime (idempotency keys, per-student order), Operator in workflow mode,
  Memory Service + reconciler (only writer of facts), documents pipeline, Capability/Tool registries, Messenger.
- Zero hardcoding: all lists, labels, copy, rules, thresholds, archetypes and catalogs live in data/i18n files.
  Pakistan content lives only as data (boards, groups, levels, cities). Code stays generic.
- Prompts in .md files; model output validated with strict schemas; conversation fails open, facts fail closed.
- New routes: typed, owner-only access checks, tests. DB changes only by backward-compatible migrations; never drop tables.
- No live model or paid API calls. Tests are offline with fake providers.
- Readable code: small functions, clear names, no dead or commented-out code, no copy-paste variants.

STACK
Next.js 16, React 19, Tailwind 4, shadcn/radix (frontend/components/ui), lucide-react, motion, next-themes,
inline SVG charts (no chart library). Font: Plus Jakarta Sans (already self-hosted). Keep and extend the existing
tokens in frontend/styles/globals.css and the kit in frontend/components/pai. If a frontend-design / UI skill is
available in this Claude Code setup, use it.

DESIGN SYSTEM (do first; everything uses it)
- Tokens from the Figma "Spec" frame: brand #2F63F6, violet #7C5CFF, teal #14B8A6, amber #F59E0B, coral #F43F5E,
  green #16A34A, orange #F97316, pink #EC4899, ink #0F172A, bg #F5F7FB; each accent has a Soft tint; dark theme
  (bg #0B1124, card #141C33) designed, not inverted. One shadow level. Radius 20 cards, 14-16 tiles, pill chips.
- Shared components (one each, no variants copied): AppShell (sidebar >=1024, rail 768-1023, bottom tabs <768),
  NextStepCard, LevelRing, Light (dot + word), EvidenceBadge (icon + word), InterestBars, InterestRadar,
  ValuesRank, AreaHeatmap, MirrorPortrait (building + complete states; replaces QuadrantCard), WishSlider, FamilyMap, CertaintyLine, PathCard, Part360Tile, CompareTable,
  StoryCards (tap-through, progress segments), ShareCard (9:16 image), UploadCapture, ExtractReview,
  InlineEditRow, MissingDetailsPanel, RelationGraph, HistoryTimeline, ConsentToggleRow, OfferCard,
  EmptyState, ErrorState, Skeletons, Toast ("PAI noted 2 things · View").
- Motion: micro 100-200 ms, enter 225 ms ease-out, exit 195 ms ease-in, full screen 300-375 ms, never > 400 ms.
  Transform and opacity only. Wrap the app in MotionConfig reducedMotion="user". Bars and radar grow on first view,
  lights pop with a 40 ms stagger, the level ring fills, story cards slide. One celebration per milestone
  (snapshot ready, marks verified, path chosen); skip it when navigator.deviceMemory <= 2.
- Accessibility: WCAG AA contrast in both themes, focus rings, aria labels, keyboard paths, touch targets >= 48 px,
  body text >= 15 px (inputs 16), never colour alone.
- Performance: initial JS <= 300 KB gz (aim 170 KB critical), LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1 on a
  mid Android profile. Lazy-load heavy parts (story cards, graph, capture). Cache saved paths and profile for offline;
  queue chat messages when offline and send on reconnect. Stay signed in (refresh tokens) - never surprise logouts.

SCREENS AND FLOWS (each one: Figma frame -> build -> states -> tests)

A. Welcome and auth (frames 01-02)
- Welcome: promise, two preview cards (snapshot + path with lights), "Start in 2 minutes", "I already have an account".
- Sign up: Google + email; first name + last name (no username anywhere in UI or API responses; keep the DB column,
  note it in DECISIONS.md); password rules shown live; trust line. Sign in, forgot/reset, verify email, expired link,
  callback failed: all designed states.

B. Onboarding (frame 03) - one question per screen, progress bar, Skip where allowed, Back always
Steps: 1 name (prefilled from sign up) -> 2 date of birth + gender (Male / Female / Prefer not to say) ->
3 highest education completed (option cards from education_levels.json: Matric/SSC, O-level, FSc/HSSC with group
chips Pre-Medical / Pre-Engineering / ICS / Commerce / Arts, A-level, DAE/Diploma, Bachelor's, Other with text)
+ "Currently studying?" -> 4 country + city (searchable, from data; default from locale) -> 5 phone (optional, country code).
- Only name and education are required. No language step.
- Under 18 (from DOB): short privacy note; store nothing extra.
- Saved as facts via the reconciler with source "onboarding", level confirmed.
- FIX the current bug: raw "Catalog level" / "Reviewed catalog entry" chips must never appear. If a catalog is empty,
  show the option cards from data plus "Other"; never a placeholder label.
- Ends on a recap card ("Here is what I heard") -> first session in chat.

C. Home (frame 04, D1)
- Greeting, NextStepCard (one clear next action computed from journey state: finish snapshot / see snapshot /
  upload result / explore a path / compare / plan), LevelRing (Started, Known, Confirmed, Verified, Match-ready;
  "never a score of you"), journey progress, "Directions for you" cards with lights, "PAI still wants to know" chips,
  desktop: chat box on Home. Empty state for a brand-new student.
- Backend: GET /me/home returns next_step, level, journey, directions, wants_to_know (small, typed, owner-only).

D. Chat (frame 05)
- Header (PAI, "here 24/7"), streamed replies with typing state within 300 ms and a Stop button, 2-3 reply chips after
  each counselor turn (from the reply's structured output; hidden when none), inline cards: tap choice, 0-10 rating,
  upload card, first picture, Visual Mirror card (only after the gate: portrait thumbnail, 1-5, This is me /
  Something is off, opens frame 18), path card, try-it, check-in, snapshot ready.
- "PAI noted N things · View" toast when facts are saved; View opens PAI memory filtered to them.
- Composer: +, text, one mic button (remove the duplicate floating "Talk to PAI").
- Offline: message queued with a clock badge; retry on reconnect. Errors: friendly retry, never lost text.

E. First session and First Snapshot (frames 06-07)
- Activity taps: 12 "like / not for me" cards from riasec_activities.json (each mapped to R/I/A/S/E/C, generic).
  One story question on a "like" (counselor). Values: drag to rank from values.json; keep top 3.
  Pressures: taps (family wish, budget band, can move city, time). Certainty 0-10 + "whose wish".
- NEW job snapshot.build (Task Runtime, idempotent): interest shape (6 scores from taps + stated/shown facts),
  archetype name + one line from archetypes.json (top-2 combination; deterministic, no model needed),
  top 3 values, 3-4 directions in general words (existing planner/possibilities) with "why it fits you" quotes,
  lights from fit.assess, wants_to_know. Versioned; rebuilt when facts change.
- Reveal: StoryCards (4-6 cards: you are, what you enjoy, what matters, directions, what PAI still wants to know),
  final ShareCard 9:16 for WhatsApp Status (no private data on it: archetype + strengths only).
- Results page: archetype header, InterestBars (radar as optional detail), ValuesRank, directions with lights and
  "Why" quotes, "Does this feel like you?" 1-5 rating saved as evidence.

F. Documents: upload, extraction, placement (frames 08-09)
The extraction engine already exists and is strong - REUSE it. Build the complete UX and placement around it:
- Entry points: chat upload card, Home chip, Profile Details "Add result", Documents screen.
- Capture: camera with edge/light/sharpness hints, auto-capture, manual fallback, Gallery and PDF.
  Client-side compression (~1600 px long edge, quality ~0.7), resumable upload with a real % bar.
- Review screen: thumbnail beside every extracted field (board, exam + year, group, roll no. masked, each subject
  marks / total, total). Low-confidence fields in amber with icon + "Please check"; every field editable inline;
  nothing saved until "Confirm and save". Retake. Option "Delete photo after saving".
- Placement: confirmed fields go through the reconciler as level "shown" (document) -> profile Academic layer,
  education timeline, Details rows with a Verified badge, fit.assess re-runs, Home next step updates, toast in chat.
  Conflicts with earlier stated values: show both, student picks; the old value goes to history.
- Edge cases (test each): blurry photo, wrong document type, two pages, PDF, duplicate upload, partial marks,
  different board formats, upload fails midway, offline, student cancels at review, extraction timeout,
  student edits a value, student is under 18.
- Documents screen: list with status (reading / needs check / verified), open, re-check, delete.

G. Profile (frames 10-12, dark, D2) - the hero
Tabs: My picture | Details | PAI memory.
- Header: avatar initials, name, level and city, LevelRing, "Marks verified" badge when true.
- My picture: MirrorPortrait at the top - "building" state (petals fill, "Keep talking", N of 10) until the gate passes,
  then the complete Visual Mirror (frame 18); never text quadrants. Then AreaHeatmap (10 areas x none/said/shown/confirmed, legend, tap to
  filter), InterestRadar + InterestBars, ValuesRank, strengths chips with evidence badges, education timeline with
  marks bars, FamilyMap (role, hope, worry), pressures/limits, goals with "whose wish", CertaintyLine (real ratings
  only), directions with lights, "PAI still wants to know" chips. Every widget has an empty state that invites,
  never nags.
- Details: sections About you / Location / Education / Family and limits / Goals and preferences.
  InlineEditRow: tap -> input/select/date -> Save/Cancel. No approve step: saved as source "student_edit",
  level confirmed, through the reconciler; old value to history. MissingDetailsPanel (bottom sheet on phone):
  tap focuses the field. Human labels from a label map; never keys, JSON, confidence numbers or model notes.
- PAI memory (hidden behind the tab, lock icon): "In short" summary; RelationGraph (SVG, student in the centre;
  people, interests, strengths, values, limits, directions; labelled links such as "Father - hopes for - Electrical
  engineering"; tap a node for sources; list fallback on small screens); List view (every fact with its source
  "You said on 12 Oct ..." / "From your result card" + Edit / Remove); History timeline (added from chat / upload /
  edited by you / removed, before and after). Never shown: Truth Map, private interpretation, sensitive items,
  internal notes, legacy archives.
- Backend: PATCH /me/profile/fields/{key} (student_edit), GET /me/profile/relations (nodes + edges, student-safe),
  GET /me/profile/history. Owner-only, typed, tested.

H. Paths and Path 360 (frames 13-14)
- Paths: filter chips (All / Saved / Explored / Not for me), PathCard (accent, "why it fits you" quote, lights,
  Explore, Not for me with a reason saved as evidence), "Add a path you are thinking about".
- Path 360: hero (what it is in one line, years, fee band, key demand), Honest summary (good for you / hard for you /
  first step), 8 Part360Tiles that open sheets: What it is, Why YOU (quotes + evidence), Challenges for YOU,
  What it will not give you, Reality (sourced, dated; "needs checking" when no source), Time and cost,
  What is needed (lights with action or route), Plan B (nearby paths). Actions: Try it, Compare, Where to study
  (locked until the student asks + consents). No institution names on this page.
- NEW job fit.assess: path needs (data rules with source + season; "general" when none) x student facts ->
  green / yellow / red per need with evidence refs and an action or route. Red always has a route.

I. Compare and choose (frame 15)
- 2-3 paths side by side (fit, marks, years, cost, family view, hard part, lights), certainty slider, family-talk
  help entry (existing family-talk feature), "Choose" -> decision record (existing; immutable, versioned),
  "Not yet - and that is fine". Then Where to study (existing program.search, consent first) and Plan.

J. Plan, check-ins, notifications
- Plan list with next steps and check-ins (existing scheduler). In-app notifications centre. WhatsApp/SMS reminders
  are FUTURE: design the settings row, keep it behind a flag.

K. Privacy and sharing (frame 16), Offers (frame 17, FUTURE behind a flag)
- Sharing switch OFF by default; Profile Card preview exactly as a university would see it (name hidden until the
  student taps Interested); per-field toggles disabled while sharing is off; "Never shared" note; who-saw-my-card
  log; Export my data; Delete account (confirm screen).
- Data model now (migrations, no UI flows beyond the above): Consent (per university/scope/expiry/revoked_at),
  ProfileCard projection (versioned, student-safe), Offer (FUTURE table only).
- Offers inbox UI exists behind a feature flag with an empty state; no fake offers in production.

L. Settings and the rest
- Account, theme (light/dark/system), notifications, privacy link, help, sign out.
- Every screen: loading skeleton, empty state, error state with retry, offline banner.
- 404 and error pages in the same style.

DATA FILES TO ADD (generic structure, Pakistan values as data)
education_levels.json, boards.json, groups.json, countries.json, cities/<country>.json, riasec_activities.json,
archetypes.json, values.json, pressures.json, path_needs/<path>.json (needs + source + season, may be empty),
labels.en.json (every backend key -> human label), copy files per screen. Add a schema test for each file.

SELF-CHECK LOOP (repeat for every screen until clean; do not stop to ask)
1. npm run build, npm test, backend suite in both policy modes with PAI_API_KEY unset.
2. Playwright preview harness (frontend/tests/preview) with synthetic data and network blocked:
   screenshots light + dark at 360, 390, 768, 1024 and 1440 px into docs/counselor/screenshots/v3/.
   Open every screenshot and compare with its Figma frame. Fix: clipped or overflowing text, raw keys or JSON,
   placeholder labels, empty-looking widgets, misalignment, low contrast, duplicate controls, horizontal scroll.
3. Flow tests (Playwright, fake backend): new student sign up -> onboarding -> first session -> snapshot reveal ->
   upload result -> review -> Verified badge appears in Details and Home updates -> explore path -> Path 360 ->
   compare -> choose -> plan. Also: skip optional steps, under-18, edit a field -> history shows it, remove a fact ->
   graph and list update, offline message queue, upload failure and retry, distress message routes to care.
4. Link and button crawler: no 404s, no dead buttons, zero console errors, zero unhandled rejections.
5. Lighthouse mobile run on Home, Chat and Profile: record LCP, INP, CLS, JS size; fix budget misses.
6. Axe accessibility run on every screen: zero serious or critical issues.
7. Tick the item in V3_CHECKLIST.md only when 1-6 are clean for it. Commit per screen with a clear message; push.
Blockers -> docs/counselor/BLOCKERS.md, product choices -> DECISIONS.md. Then continue with the next item.

DONE MEANS (every line ticked in V3_CHECKLIST.md)
- Design system tokens + all shared components, light and dark.
- Welcome, auth (all states), onboarding (5 steps, no username, no language step, no catalog leaks).
- Home with next step, level ring, directions with lights, wants-to-know.
- Chat with streaming, chips, all inline cards, toast, single mic, offline queue.
- First Snapshot: activity taps, values ranking, snapshot.build job, story cards, share card, results page, rating.
- Documents: capture, upload, review, placement, verified badge, all edge cases tested.
- Journey order enforced: no Mirror before the gate; profile basics filled by conversation first; mirror_gate in data with tests.
- Visual Mirror: building state + complete state (frame 18), petal tap -> sources/fix, rating saved as evidence.
- Profile: My picture (all widgets), Details (inline edit, missing panel, history), PAI memory (summary, graph,
  list, history), new endpoints tested.
- Paths, Path 360 with fit.assess job, Compare and choose, decision record.
- Plan, notifications, Privacy and sharing (consent model, card preview, log, export, delete), Offers behind a flag.
- Settings, empty/loading/error/offline states everywhere, 404.
- Performance budgets met, axe clean, crawler clean, all tests green in both policy modes.
- docs/counselor/V3_REPORT.md: screens with screenshot links, components, tokens, endpoints and jobs added,
  data files added, test counts, Lighthouse numbers, open blockers, and the docker command to see it live:
  docker compose --env-file .env -p pai-c-test2 -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d

REPORT TO THE FOUNDER (Roman Urdu, short) after each major part: what is done, screenshots, what is next, blockers.
