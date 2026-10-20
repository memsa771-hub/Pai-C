# PAI C documentation

Work in `workspace` on branch `pai-c`. `pai-os` is the PAI OS developer's branch. Both start from `dev`.

## Read first (source of truth)
1. Figma board (LOCKED v1): https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF (sections 00-12)
2. `AGENT_MASTER_PROMPT_V1.md` - full instructions for agents: rules, phases, report format
3. `PAI_C_WORKFLOW_LOCK_V1.md` - the locked workflow A-K, PAI OS contract, Operator and background work
4. `COUNSELING_POLICY.md` - universal counseling loop and hard guardrails
5. `SPINE.md` - how the code is built (services, jobs, policy modes)

## Working files
- `BUILD_REPORT_V1.md` - locked-workflow implementation, card checklist, tests and founder start command
- `UI_REPORT_V2.md` - the v2 UI redesign: screens, design system, verification
- `DECISIONS.md`, `BLOCKERS.md` - implementation choices and safely unavailable/deferred items
- `COUNSELOR_V3_PROMPTS.md` - copy of the runtime prompts; tests check it matches the prompt files
- `COUNSELING_CONVERSATIONS.md`, `DEEP_COUNSELING_DANISH.md` - persona examples; a test uses them to make sure no persona name is hardcoded in code

## Archive
Finished briefs and audits, kept for history in `archive/`: `UI_REDESIGN_PROMPT.md` and `UI_CHECKLIST.md`
(v2 redesign, done), `CLEANUP_AUDIT.md` and `OS_REMOVAL_AUDIT.md` (OS removal inventory), `UI_CLEANUP_V1.md`
(deferred UI deletion evidence), `ADAPTIVE_COUNSELING_REPORT.md` (adaptive counseling evidence).

## Screenshots
Screenshots are not committed. The offline harness writes them to `screenshots/` (git-ignored); see
`frontend/tests/preview/README.md`.

## Other docs
- `../AUTH_SESSION.md` - sign-in and sessions
- `../VAULT_STEWARDS.md` - Vault ownership
- `../PAI_CAPABILITY_DEVELOPER_GUIDE.md` - how to add a capability (used by the Operator)

## Branch rules
- Shared code (memory, models, migrations, routers, tools, inference, security): keep changes small and merge to `dev` quickly.
- Pull `dev` into `pai-c` before creating any Alembic migration.
- End each task with local `pai-c` matching `origin/pai-c` and a clean Git status.
