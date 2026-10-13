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

- Safety gate and one normal Voice call handle each human turn; language/repetition repairs are bounded.
- The background Planner updates the private Truth Map and next-turn plan.
- The memory extractor submits factual candidates through reconciliation into the Vault.
- Ended sessions produce summaries; semantic recall is read by the Planner.
- Counseling notes research questions. Confirmed Mirrors start light research through the shared gateway.
- Journey transitions, student requests and decision records preserve the shared PAI OS contract.

## Current documentation

- [MASTER_PLAN.md](MASTER_PLAN.md): phases, gates and the PAI C/OS contract.
- [CLEAN_ARCHITECTURE.md](CLEAN_ARCHITECTURE.md): central owners and dependency rules.
- [ARCHITECTURE.md](ARCHITECTURE.md): core data and execution decisions; defer to Clean Architecture where layering differs.
- [CORE_V1_SPEC.md](CORE_V1_SPEC.md): approved core features and remaining work.
- [PAI_C_VISION.md](PAI_C_VISION.md): Truth Map, counseling and lifecycle intent.
- [PRODUCT_FEATURES.md](PRODUCT_FEATURES.md): student screens and workflows.
- [COUNSELING_METHOD.md](COUNSELING_METHOD.md): adaptive counseling and quality measurement.
- [SPINE.md](SPINE.md): implemented ownership, memory, research, Mirror and turn-engine contracts.
- [P0_ENTRY_AUDIT.md](P0_ENTRY_AUDIT.md): authentication/onboarding/workspace audit evidence.
- [CLEANUP_AUDIT.md](CLEANUP_AUDIT.md): cleanup evidence, approved removals and protected items.
- [COUNSELING_CONVERSATIONS.md](COUNSELING_CONVERSATIONS.md): illustrative target conversations and test input.
- [DEEP_COUNSELING_DANISH.md](DEEP_COUNSELING_DANISH.md): illustrative hidden-truth scenario and evaluation history.

## Runtime prompts and offline tools

Authoritative prompts live under backend/app/pai_c/voice/prompts/,
planner/prompts/, safety/prompts/ and deep/prompts/. Prompt-parity tests retain
their existing reference document; the runtime files are the execution source.

From backend, run python -m scripts.export_counselor_session --workspace <id>;
optional --out <path> and repeated --usage-log <saved-log> include attributable
per-call usage. Default session exports are gitignored private student data.
Offline evaluation prompts live in backend/scripts/eval/prompts/. Tests use
recorded responses/fake providers; live calls need explicit authorization.

Historical pr15 comparison and pr9 smoke/results/import-graph artifacts remain in
eval_reports/. They record earlier runs, not current quality or release approval.

## Next

Follow the current phase/gate order in MASTER_PLAN.md and CLEAN_ARCHITECTURE.md.
Read SPINE.md for what is implemented and what remains deferred. PAI OS work
belongs to the other developer.
