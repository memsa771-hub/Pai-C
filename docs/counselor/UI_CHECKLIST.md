# UI redesign v2 checklist

Source: `UI_REDESIGN_PROMPT.md`. A screen is ticked only when all of these are clean:
`npm run build`, `npm test`, the offline preview harness (`frontend/tests/preview`),
screenshots reviewed (light and dark at 375 and 1440 px, with overflow checked at 768 px too),
and the link crawler (no dead buttons, no 404 links, no console errors, no page errors).

| # | Screen | Status | Screenshots (`screenshots/v2/`) |
|---|---|---|---|
| 0 | Design system (tokens, kit components) | [x] | `design-system-*` |
| 1 | Auth: sign in, sign up, forgot, reset, email check | [x] | `auth-*` |
| 2 | Onboarding (4 tap steps) | [ ] | `onboarding-*` |
| 3 | App shell (sidebar, bottom tabs, top bar) | [ ] | `shell-*` |
| 4 | Profile: Visual and Details | [ ] | `profile-*` |
| 5 | Counselor chat and inline cards | [ ] | `chat-*` |
| 6 | Journey A-K | [ ] | `journey-*` |
| 7 | Paths | [ ] | `paths-*` |
| 8 | Path page (G) | [ ] | `path-*` |
| 9 | Where to study (H) | [ ] | `programs-*` |
| 10 | Compare and choose | [ ] | `compare-*`, `decision-*` |
| 11 | Plan and check-ins | [ ] | `plan-*` |
| 12 | Documents | [ ] | `documents-*` |
| 13 | Settings | [ ] | `settings-*` |
| 14 | Empty, loading and error states | [ ] | `states-*` |
