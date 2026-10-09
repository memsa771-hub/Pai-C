# Counselor documentation

Start here for the current deep Counselor. Work in `workspace` on `pai-c`.

## Branches

- `pai-c` = PAI Counselor work (`backend/app/pai_c`, Counselor prompts, and Counselor/roadmap frontend). `pai-os` = PAI OS work by the other developer. Both start from `dev`.
- Shared code (memory, models, Alembic migrations, routers, tools, inference, security): keep changes small and merge them to `dev` quickly.
- Before creating any Alembic migration, pull `dev` into `pai-c` first so revision numbers do not collide; coordinate with the other developer if migrations are being created concurrently.
- Merge tested `pai-c` work into `dev` at least weekly; pull `dev` into `pai-c` after every `dev` change.
- `main` only receives code tested on `dev`.
- Counselor tasks use `pai-c` unless explicitly directed otherwise. End each task with local `pai-c` matching `origin/pai-c` and a clean Git status.

## Current architecture

- One Counselor model call per normal turn; a blocked-script reply permits one retry.
- The background Analyst updates the private Notebook after each successful human turn.
- The memory extractor sends candidates through reconciliation into the Vault per turn.
- No research during counseling: factual questions are noted for later research.
- The versioned Mirror requires student confirmation before light research; deep research is reserved for the chosen roadmap.
- One research gateway owns Counselor research delegation, including existing stale refreshes.

## File index

- [RESEARCH_ROADMAPS.md](RESEARCH_ROADMAPS.md): confirmed-Mirror research, evidence cache, budgets, grounded lanes and migrations 099/100; read before changing research or publication.

- [MIRROR.md](MIRROR.md): versioned Mirror jobs, validation, Confirm/Edit, voice and migration 098; read before changing the review flow.
- [LEAN_COUNSELOR.md](LEAN_COUNSELOR.md): current discovery, deferred questions, pre-Mirror safety and per-turn memory decisions; read before changing runtime behavior.
- [CLEANUP_AFTER_DEEP.md](CLEANUP_AFTER_DEEP.md): consolidation history, retained importers, database follow-up and offline startup check; read before removing compatibility code. Branch inventories are historical.
- [CODEX_COUNSELOR_V3_DEEP.md](CODEX_COUNSELOR_V3_DEEP.md): original implementation specification; read for design intent, with its historical branch/order warning.
- [COUNSELOR_V3_PROMPTS.md](COUNSELOR_V3_PROMPTS.md): prompt reference, including future Mirror/roadmap roles; read when reviewing prompt contracts, not as a feature availability checklist.
- [COUNSELING_CONVERSATIONS.md](COUNSELING_CONVERSATIONS.md): illustrative target conversations; read for counseling quality, not implemented-flow guarantees.
- [DEEP_COUNSELING_DANISH.md](DEEP_COUNSELING_DANISH.md): extended illustrative discovery scenario; read for hidden-truth evaluation, not real student data.
- [COUNSELOR_REAL_WORLD_AND_LIFECYCLE.md](COUNSELOR_REAL_WORLD_AND_LIFECYCLE.md): product scenarios and future lifecycle guidance; read when planning adaptive counseling.
- [Profile foundation](../PAI_COUNSELOR_PROFILE_FOUNDATION.md): current Profile/Vault/Notebook boundaries and evidence rules; read before changing profile intake.
- [Local testing](../COUNSELOR_LOCAL_TEST.md): environment settings, Compose commands and the current manual-test scope.

## Runtime prompts

Authoritative runtime prompts live in `backend/app/pai_c/deep/prompts/`.

Read-only session export: from `backend`, run `python -m scripts.export_counselor_session --workspace <id>`; optional `--out <path>` and repeated `--usage-log <saved-log>` include attributable per-call usage. Default exports in `eval_reports/sessions/` are gitignored. Missing logs and historical Mirror statuses are explicitly marked unavailable; exports remain private student data.
Not every stored prompt has a wired feature yet. Offline evaluation prompts live
in `backend/scripts/eval/prompts/`; use recorded fixtures or fake models for tests.

- [TARGETS.md](TARGETS.md): measurable release gates and evaluation caps.
- [RESTRUCTURE.md](RESTRUCTURE.md): moved files and verified shared/OS import boundaries.

## Next

Mirror generation, sensitive checking, Confirm/Edit and the research handoff are wired.
The evidence cache, light-research brief and grounded Mirror roadmaps are wired. Chosen-roadmap deep research is deferred. PAI OS is unchanged.

Validate the release gates in TARGETS.md; the PR 9 consolidated paid run was incomplete.
