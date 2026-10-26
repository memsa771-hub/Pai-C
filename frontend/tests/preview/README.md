# Offline UI review

Real app components, synthetic data, no network. Nothing here talks to the API,
an identity provider or a model.

```
npm run preview:offline          # http://127.0.0.1:4173/student
npm run test:ui -- <playwright>  # needs the preview running; <playwright> = path to the playwright module
```

`test:ui` checks every screen in `screens.cjs` in light and dark at 375, 768 and 1440 px
(overflow, raw keys, console and page errors). It clicks every control (dead buttons,
unknown routes) and runs `flow.cjs`, which checks the A-K boundaries. Screenshots go to
`docs/counselor/screenshots/v2/`, which is git-ignored. Options: `--only=<prefix>`,
`--skip-crawl`, `--skip-flow`, `--flow-only`.

Useful URLs: `?kit=1` (design system), `?onboarding=1`, `?view=profile|threads|journey|paths|roadmap|files|settings`,
`&theme=dark`, `&state=loading|error|empty`, `&mirror=1`, `&card=picture|rating|fact|paths|typing|empty`.

| File | Role |
|---|---|
| `main.tsx`, `index.html`, `vite.config.mjs` | Preview entry; swaps API, auth and hooks for fakes |
| `fake-*.ts`, `next.tsx` | Synthetic API, auth, workspace and Next.js shims |
| `kit-gallery.tsx` | Design-system review page |
| `screens.cjs`, `workspace.e2e.cjs`, `flow.cjs` | Screen list, checks and crawler, A-K flow |
