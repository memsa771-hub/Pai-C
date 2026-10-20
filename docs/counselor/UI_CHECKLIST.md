# UI redesign v2 checklist

Source: `UI_REDESIGN_PROMPT.md`. A screen is ticked only when all of these are clean:
`npm run build`, `npm test`, the offline preview harness (`frontend/tests/preview`),
screenshots reviewed (light and dark at 375 and 1440 px, with overflow checked at 768 px too),
and the link crawler (no dead buttons, no 404 links, no console errors, no page errors).

| # | Screen | Status | Screenshots (`screenshots/v2/`) |
|---|---|---|---|
| 0 | Design system (tokens, kit components) | [x] | `design-system-*` |
| 1 | Auth: sign in, sign up, forgot, reset, email check | [x] | `auth-*` |
| 2 | Onboarding (4 tap steps) | [x] | `onboarding-*` |
| 3 | App shell (sidebar, bottom tabs, top bar) | [x] | `shell-*` |
| 4 | Profile: Visual and Details | [x] | `profile-*` |
| 5 | Counselor chat and inline cards | [x] | `chat-*` |
| 6 | Journey A-K | [x] | `journey-*` |
| 7 | Paths | [x] | `paths-*` |
| 8 | Path page (G) | [x] | `path-*` |
| 9 | Where to study (H) | [x] | `programs-*` |
| 10 | Compare and choose | [x] | `compare-*`, `decision-*` |
| 11 | Plan and check-ins | [x] | `plan-*` |
| 12 | Documents | [x] | `documents-*` |
| 13 | Settings | [x] | `settings-*` |
| 14 | Empty, loading and error states | [ ] | `states-*` |
