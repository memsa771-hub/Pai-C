ROLE
Senior product designer + full-stack engineer on PAI C. Read CLAUDE.md first and follow it.
Branch pai-c only. Reply to the founder in Roman Urdu.
Start this only after the UI redesign (docs/counselor/UI_REDESIGN_PROMPT.md) is finished; build on its design system.

GOAL
1. A clean, short onboarding with the right basic fields.
2. A profile that is as easy as Kollegio's (the student just edits, no approve step), but more beautiful and visual.
3. A hidden "PAI memory" area inside the profile (like Claude's memory and history):
   a summary, a relation graph and a change history, where the student can see and correct what PAI knows.
   Nothing raw from the Vault is ever dumped on the screen.

PART 1 - ONBOARDING (replace the current one)
Steps, one card per step, progress dots, back/next, phone first:
1. Full name: First name + Last name. No username anywhere in the app; remove the username field and any
   username-based display.
2. Date of birth (date picker) and Gender (Male / Female / Prefer not to say).
3. Highest education completed: a choice list from a data file (education_levels.json), for example
   Matric / SSC, O-level, FSc / HSSC (Pre-Medical, Pre-Engineering, ICS, Commerce, Arts), A-level, DAE,
   Bachelor's, Master's, Other (free text). Plus "Currently studying?" with level.
4. Country (searchable list from data, default from browser/locale, not hardcoded) and City (searchable).
5. Phone number: optional, clearly marked "Optional", with a country code picker.
No language step. The app is English only. Remove any reply-language picker from onboarding and settings.
The counselor replies in English by default and simply follows the student if they write in Roman Urdu
(existing language policy, no setting). Never Hindi or Devanagari.
Rules:
- Only the name and education are required. Every other step can be skipped.
- Validation messages are friendly.
- All values are saved as profile facts through the existing Memory Service / reconciler,
  with source = "onboarding" and level = confirmed.
- Under-18 students (from the date of birth): show a short privacy note. Store nothing extra.
- All labels and lists come from data or i18n files.

PART 2 - PROFILE (two main tabs + one hidden area)
Tab A "My picture" (visual) - keep the spec from the UI redesign:
- header with a "how well PAI knows you" ring
- Mirror card, understanding heatmap (10 areas x evidence level)
- interest radar, strengths/difficulties, education timeline with marks bars, values bars
- family map, pressures/limits gauges, goals with "whose wish", certainty line chart
- directions with traffic lights
- "PAI still wants to know" chips

Tab B "Details" (like Kollegio, but cleaner):
- Sections: About you (name, DOB, gender, phone), Location (country, city),
  Education (highest completed, current, board, group, marks, tests), Family & limits (budget band,
  can move city), Goals & preferences.
- Each field is an inline editable field (input, select or date). Edit and save, with no approve step.
  A student edit is saved directly as confirmed with source = "student_edit" through the reconciler.
  The old value goes to history, never silently lost.
- A right-side "Missing details" panel (bottom sheet on phone) lists empty important fields;
  tapping one focuses that field. Calm tone. No nagging, no percentages that pressure.
- Never show internal keys, JSON, model notes, confidence numbers, or raw evidence objects.
  Every value has a human label from a label map.
- Do not add identity fields like ethnicity or religion. Do not add US-only fields (SAT, GPA/4, ZIP).

Hidden area "What PAI knows about you" (a third tab or a "View PAI memory" button inside the profile):
- Summary: a short readable paragraph of who PAI thinks the student is (from the Mirror/Truth Map summary).
- Relation graph (SVG, interactive): the student in the center; nodes for people, interests, strengths,
  goals, values, pressures and directions; labeled edges such as "father wants -> Engineering",
  "repairs phones -> practical interest -> Electrical Engineering". Tap a node to see its sources.
  Simple force or radial layout; works on phone (pinch/zoom or a list fallback).
- Text view of the same: grouped readable list of every fact and understanding item,
  each with its source ("You said on 12 Oct ...", "From your result card") and Edit / Remove.
- History: a timeline of changes, newest first (added from chat / from upload / edited by you / removed),
  with the before and after values in plain words. Removing or editing is written back through the
  reconciler and appears in the history.
- Private interpretation, sensitive items, internal notes and legacy archives stay hidden.
  Only student-safe projections are shown.

BACKEND (small and typed, reuse first)
- Reuse the Memory Service, reconciler, student profile endpoints and the profile projection already built.
- Add only what is missing:
  - (a) onboarding fields and field definitions as data
  - (b) a direct edit endpoint that writes a student_edit candidate auto-accepted as confirmed
  - (c) a relations projection endpoint (nodes + edges, student-safe)
  - (d) a history endpoint (fact revisions in plain words)
  All behind access checks, owner only.
- No table drops. Migrations only if a field truly needs storage, backward compatible.
- Remove "username" from the UI and API responses. Keep the database column if it exists;
  do not drop it. Note it in DECISIONS.md.

SELF-CHECK LOOP (repeat until clean; do not stop to ask)
For onboarding, Details, My picture and PAI memory:
1. npm run build, npm test, and the backend suite in both policy modes (PAI_API_KEY unset).
2. Playwright preview with synthetic data: screenshots in light and dark at 375 and 1440 px.
   Look at each screenshot and fix:
   - clipped text, raw keys or JSON on screen, broken layout
   - charts that look empty or wrong, poor contrast
3. Flow checks:
   - new user: onboarding to profile
   - edit a field: the history shows it
   - remove a fact: the graph and lists update
   - skip optional steps
   - under-18 date of birth
   - empty profile states
4. Link crawler: no 404s, no dead buttons, no console errors.
5. Tick each item in docs/counselor/UI_CHECKLIST.md only when clean. Commit and push per part.
Blockers go in BLOCKERS.md, product choices in DECISIONS.md. Then continue.

DONE MEANS
- Onboarding has exactly the fields above and no username.
- The profile has: My picture (visual), Details (inline edit, no approve step, missing details panel),
  and PAI memory (summary, relation graph, text list, history).
- Nothing raw from the Vault is visible anywhere.
- All checks pass.
- docs/counselor/PROFILE_REPORT.md has screenshots (light/dark, phone/desktop), endpoints added,
  and the docker command to see it live.
