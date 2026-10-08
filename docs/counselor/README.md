# Counselor documentation

Start here for the current deep Counselor. Work in `workspace`; branch from
latest `dev`, open PRs into `dev`, and return the checkout to latest `dev` afterward.

## Current architecture

- One Counselor model call per normal turn; a blocked-script reply permits one retry.
- The background Analyst updates the private Notebook after each successful human turn.
- The memory extractor sends candidates through reconciliation into the Vault per turn.
- No research during counseling: factual questions are noted for later research.
- The versioned Mirror requires student confirmation before light research; deep research is reserved for the chosen roadmap.
- One research gateway owns Counselor research delegation, including existing stale refreshes.

## File index

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

Authoritative runtime prompts live in `backend/app/counseling/deep/prompts/`.
Not every stored prompt has a wired feature yet. Offline evaluation prompts live
in `backend/scripts/eval/prompts/`; use recorded fixtures or fake models for tests.

## Next

Mirror generation, sensitive checking, Confirm/Edit and the research handoff are wired.
PR 7 adds the research cache and new light-research brief; PR 8 builds roadmaps
from the confirmed Mirror. Existing Roadmaps still loads. PAI OS is unchanged.
