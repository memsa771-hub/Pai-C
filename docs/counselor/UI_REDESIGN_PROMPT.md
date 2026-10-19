ROLE
You are a senior product designer + frontend engineer. Redesign the whole PAI C app so it feels like a polished,
modern consumer app (reference feel: Kollegio - friendly, colorful, guided, alive), not an admin panel.
Read CLAUDE.md first and follow it. Branch pai-c only. Reply to the founder in Roman Urdu.

STACK (use it, add nothing heavy)
Next.js 16 + React 19, Tailwind CSS 4, shadcn/radix components in frontend/components/ui, lucide-react icons,
motion for animation, next-themes for light/dark, inline SVG for charts. If a UI/UX or frontend-design skill
is available in this Claude Code setup, use it.

SCOPE: EVERY SCREEN THE STUDENT CAN REACH
1. Auth: sign in, sign up, forgot/reset password, email verification states.
   Warm brand panel (logo, one-line promise, soft illustration or gradient) and a clean form.
   Clear errors, loading buttons, show/hide password.
2. Onboarding: the 4 tap cards (name, level, city, reply language) as a friendly step-by-step flow
   with progress dots and big tappable chips. Not a form page.
3. App shell: sidebar (desktop) and bottom tab bar (phone), top bar with a stage chip,
   notifications and an avatar menu. Smooth page transitions.
4. Counselor chat: modern chat bubbles, typing indicator, inline cards (tap choice, upload, rating 0-10,
   first picture, Mirror, path cards, try-it, check-in) designed as rich cards. Voice button styled.
   No duplicate labels.
5. Journey A-K: a visual path or timeline with the current stage highlighted. Done / now / next states.
6. Paths: cards with a color accent per path, "why it fits you" quote, and Explore / Save / Not for me.
7. Path page (G): section cards with icons. "Needs checking" shown as a calm info state, not as an error.
8. Where to study (H): consent step, then program cards with source + date and labels
   (safe / realistic / stretch / not yet) as colored pills.
9. Compare and choose: side-by-side columns and a decision card with a certainty slider.
10. Plan and check-ins, Documents, Settings (language, theme, notifications, privacy, export, delete).
11. Empty, loading (skeletons) and error states on every screen.

THE PROFILE - THE HERO OF THE APP (spend the most care here)
Two views with a toggle: "Visual" and "Details".
VISUAL VIEW
- Header card: avatar (initials), name, level, city, stage chip, last updated.
- Mirror reflection, top and center: the confirmed Mirror as a beautiful 4-quadrant card
  (You say / Your life shows / The pressure / You want) with agree/edit actions and "felt understood" rating.
  If there is no Mirror yet, show the first picture, or a friendly "PAI is still getting to know you" state.
- Understanding heatmap: a 10-area grid or wheel (current life, education, interests, strengths, family,
  values, pressures, certainty, goals, options). Color intensity = amount and strength of evidence
  (none / stated / shown / confirmed). Legend. Tap an area to filter the details. Never shown as a score.
- Certainty over time: small line chart from real ratings only.
- Interests and strengths: chip clouds with evidence badges and capability status.
- People around me: a small family map (avatars with role, wish and worry).
- Education timeline: vertical timeline (Matric / O-level -> FSc / A-level), marks, board, subjects, tests,
  "shown" badge on uploaded documents.
- "PAI still wants to know": soft chips that open the chat on that topic.
DETAILS VIEW (text, like a clean read-only form - readable, never raw)
- Grouped sections with label : value rows for every Vault fact, for example
  "Qualification: FSc Pre-Engineering". Never show raw keys like "qualification_name:".
- Each row: evidence badge, source on tap ("You said on 12 Oct: ..."), and Confirm / Edit / Remove
  (existing reconciler endpoints).
- A label map in data or i18n files turns every backend key into a human label.
PRIVACY: private interpretation and sensitive items are hidden by default.
Nothing is shared with any university without explicit consent.

DESIGN SYSTEM FIRST (before screens)
- Tokens in one place (CSS variables + Tailwind theme):
  - brand color from the logo blue plus 4-5 accent colors for areas and paths
  - neutral scale, success / warning / danger
  - radius, shadows, spacing, type scale (one font)
- Light and dark themes, both designed (not just inverted). WCAG AA contrast.
- Shared components: PageHeader, SectionCard, StatChip, EvidenceBadge, AreaHeatmap, Timeline,
  QuadrantCard, EmptyState, ErrorState, Skeletons.
  Reuse frontend/components/ui. No copy-paste variants.
- All copy from data or i18n files. No hardcoded country, institution or persona.

RULES
- Reuse existing API endpoints and data. Backend changes only if a read field is missing:
  small, typed, behind access checks.
- Do not change counseling logic, prompts or policies. Do not touch dev or pai-os. No .env edits.
  No live model calls. No new heavy libraries (charts are SVG).
- Phone first: check 375, 768 and 1440 px widths. No horizontal scroll. Touch targets at least 44 px.
- Keyboard navigation, focus rings and aria labels on every control.

SELF-CHECK LOOP (repeat until everything passes; do not stop to ask)
For each screen, in order (design system -> auth -> onboarding -> shell -> profile -> chat -> journey ->
paths -> path page -> where to study -> compare -> plan -> documents -> settings):
1. Build it.
2. Run: npm run build, npm test, and the existing preview harness in frontend/tests/preview
   (Playwright, synthetic data, network blocked).
3. Capture screenshots: light and dark x 375 / 1440 px. Look at every screenshot yourself and fix:
   - clipped or overflowing text, raw keys, broken layout, low contrast
   - empty-looking areas, misaligned elements, duplicate labels
4. Run a link crawler over every nav item and button that navigates: no 404s, no dead buttons,
   no console errors, no unhandled promise rejections.
5. Tick the screen in docs/counselor/UI_CHECKLIST.md only when steps 2-4 are clean.
   Otherwise fix and repeat.
6. Commit per screen with a clear message and push.

If something cannot be done, write it in docs/counselor/BLOCKERS.md and continue with the next screen.
Product choices go in DECISIONS.md with the reason.

DONE MEANS
- Every screen in scope is ticked in UI_CHECKLIST.md.
- Build and all tests pass. Zero console errors in the crawler.
- Screenshots of every screen (light and dark, phone and desktop) are in docs/counselor/screenshots/v2/.
- docs/counselor/UI_REPORT_V2.md lists the screens, components, tokens, screenshots and any blockers,
  plus the docker command for the founder to see it live.
