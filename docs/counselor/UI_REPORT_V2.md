# UI report v2: PAI C redesign

Brief: `archive/UI_REDESIGN_PROMPT.md`. Checklist: `archive/UI_CHECKLIST.md` (all 15 rows ticked). Decisions and blockers: see the "UI redesign v2" sections of `DECISIONS.md` and `BLOCKERS.md`.

## See it live

```
docker compose --env-file .env -p pai-c-test2 -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
```

Then open http://localhost:3000. The backend runs at :8000. This starts normal use with the configured providers, so real conversations can cost money.

To review offline with synthetic data (no account, no network, no provider):

```
cd frontend
npx vite --config tests/preview/vite.config.mjs        # http://127.0.0.1:4173/student
node tests/preview/workspace.e2e.cjs <path-to-playwright> # screenshots, crawler, A-K flow
```

Useful preview URLs: `/sign-in`, `/sign-up`, `/student?onboarding=1`, `/student?view=profile`, `/student?view=profile&tab=details`, `/student?view=threads&mirror=1`, `/student?view=paths&path=path-one&stage=H&programs=1`, `/student?view=compare&roadmap=1`, `/student?view=plan&roadmap=1&family=1`, `/student?kit=1` (design system). Add `&theme=dark` for dark mode, or `&state=loading|error|empty` to force a state.

## Screens

| Screen | What changed |
|---|---|
| Auth (sign in, sign up, forgot, reset, callback) | Brand panel with the promise and a path illustration, then a clean form card. Show/hide password, field-level errors, loading buttons. Email-check, link-expired and sign-in-failed states. All copy is in i18n. |
| Onboarding | The four backend fields, one question per card. Progress dots, Back/Next, big tap chips (Other opens a text box), focus moves to each new question. |
| App shell | Sidebar grouped by purpose with a journey-progress card. Phone bottom tab bar (four tabs plus More sheet). Top bar with stage chip, notifications and avatar menu. Pages fade in, and reduced motion is respected. |
| Profile (the hero) | **Visual:** gradient header; the Mirror as four quadrants with agree/change and a felt-understood rating; a ten-area heatmap (strength = colour + icon, amount = dots, tap to filter details); certainty line from real ratings; interest and strength chip clouds; people map; education timeline with marks bars; "PAI still wants to know". **Details:** readable label/value rows, source on tap, Confirm/Edit/Remove; read-only rows for what was shared in conversation. Private items are hidden until the student opts in. |
| Chat | Brand bubbles for the student, card bubbles for PAI, typing dots, welcome state. Rich cards: first picture, 0-10 rating, fact tap-choice + upload, path card, Mirror, check-in. Voice pill and a rounder composer. |
| Journey A-K | Timeline with done / you are here / coming up, and a link back to each conversation moment. |
| Paths (F) | One colour accent per path, "why it fits you" in the student's own words, Explore / Save / Not for me. Dismissed paths are tucked away. |
| Path page (G) | Section cards with icons. "Needs checking" is a calm information state. Try-it card and a call to look at places. |
| Where to study (H) | Consent step first, then program cards with source, checked date, Verified/Unconfirmed, eligibility pills, sourced fees, entry rules and routes. |
| Compare and choose (I) | Side-by-side columns with aligned rows. A decision card with a certainty slider that sends nothing until Share. Family conversation and reviewed roadmaps below. |
| Plan and check-ins (J/K) | Check-in prompt, the chosen route's next steps as a timeline, risks and Try-it. Empty state when no route is chosen. |
| Documents | Upload action, "why upload" (stated becomes shown), file list and preview. Works on phone with a back control. |
| Settings | Appearance and reply-language option cards (current language shown), notifications and channels, privacy and export, separate danger zone. |
| States | Every data screen has a skeleton, a friendly error with retry, and an empty state with a next step. |

## Design system

- **Tokens** (`frontend/styles/globals.css`): brand `#2f63f6` (dark `#7c9cff` with dark ink); accents blue, violet, teal, amber, rose, sky (solid / soft / ink); neutrals; success, warning, danger and info (solid / soft / ink); evidence ladder 0-3; radius base 12px (2xl, 3xl); elevation soft, card, lift; a hero gradient. Light and dark were each chosen for WCAG AA, not inverted.
- **Type:** Plus Jakarta Sans, self-hosted (`public/fonts`, OFL).
- **Components** (`frontend/components/pai`): PageHeader, SectionCard, StatChip, EvidenceBadge, AreaHeatmap, Timeline, QuadrantCard, EmptyState, ErrorState, Skeletons, plus tone helpers. Shared domain parts: `PathCardView`, `FeltUnderstood`, `AuthShell`. Buttons have `tap` (44px), `tap-icon` and `soft` variants.
- **Copy:** `components/counselor/workspace/copy.json`, `profile-layout.json`, `components/pai/kit-copy.json`, `lib/evidence-labels.json`, `lib/i18n/messages/en-US.ts` (auth, onboarding, chat, roadmaps).

## Backend

One read-only field: `coverage_areas` returns `evidence`, the strongest public evidence level in each area. It comes from the same endpoint and the same access checks, and is covered by `tests/test_spine_areas.py`. Nothing else changed in the backend. Counseling logic, prompts and policies are untouched.

## Verification

- `npm run build`: passes. `npm test`: 65 tests pass. That includes a new guard that every profile key the backend writes has a human label.
- Backend, both policy modes: `PAI_POLICY_MODE=guided` 1369 passed, 3 skipped; `PAI_POLICY_MODE=strict` 1369 passed, 3 skipped (key unset). On this machine a stray `tests` package in the global Python site-packages hides the repo's `backend/tests`. The suite was run through a small runner that pins `tests` to the repo folder. No repo or environment change was made for this.
- Offline harness: light and dark at 375 / 768 / 1440 px, checking horizontal overflow, raw keys and console/page errors. A crawler clicks every enabled control and link on every screen and fails on dead buttons and unknown routes. The A-K flow (`tests/preview/flow.cjs`) re-checks the product boundaries: one onboarding field per step, eleven stages with one current, Mirror feedback only after agreement and for the exact version, no program search without consent, no automatic choice, the certainty slider sends nothing until Share, check-ins only fill the draft, profile confirm uses the exact digest, and the phone account menu and tabs are 44px.
- Independent review: six review lenses (behaviour, accessibility, copy rules, visual/theming, React correctness, tests/harness integrity). Each finding was checked by three skeptics. 28 findings were upheld and all were fixed. Among them: Documents was unreachable on phone, attachments had low contrast in the student bubble, row names were hidden from screen readers, the journey stage went stale, raw enum labels showed, a slider could not record 5, and the fee shape was wrong.

## Screenshots

Not committed (they were 40 MB). Run the harness and it writes `docs/counselor/screenshots/v2/<screen>-<light|dark>-<phone|desktop>.png` locally (git-ignored), for every screen and state in `frontend/tests/preview/screens.cjs`. Main ones:

- Design system: `design-system-*`
- Auth: `auth-sign-in-*`, `auth-sign-in-error-*`, `auth-sign-up-*`, `auth-sign-up-error-*`, `auth-check-email-*`, `auth-forgot-*`, `auth-forgot-sent-*`, `auth-reset-*`, `auth-reset-expired-*`, `auth-callback-failed-*`
- Onboarding: `onboarding-name-*`, `onboarding-level-*`, `onboarding-language-*`
- Shell: `shell-*`, `shell-account-menu-*`, `shell-notifications-*`, `shell-more-*`
- Profile: `profile-*`, `profile-mirror-check-*`, `profile-private-shown-*`, `profile-details-*`, `profile-details-filtered-*`, `profile-details-row-open-*`
- Chat: `chat-*`, `chat-empty-*`, `chat-typing-*`, `chat-first-picture-*`, `chat-rating-*`, `chat-fact-upload-*`, `chat-path-card-*`, `chat-mirror-*`, `chat-mirror-rate-*`, `chat-check-in-*`
- Journey, paths, places: `journey-*`, `paths-*`, `path-*`, `programs-consent-*`, `programs-*`, `programs-none-verified-*`
- Decide and plan: `compare-*`, `compare-family-*`, `decision-*`, `compare-chosen-*`, `roadmap-details-*`, `plan-empty-*`, `plan-*`
- Documents and settings: `documents-*`, `settings-*`, `settings-delete-*`
- States: `states-<profile|journey|paths|compare|plan>-<loading|error|empty>-*`, `states-path-error-*`, `states-programs-loading-*`

## Blockers

See `BLOCKERS.md`, "UI redesign v2". In short:
- No live run on real data.
- Shared OS file-manager and settings sub-pages only received the new tokens.
- The A-K stage chip is derived on the client.
- Eligibility bands still need reviewed packs.
- The follow-up brief `PROFILE_ONBOARDING_PROMPT.md` has not been started.
