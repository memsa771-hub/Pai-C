# PAI C (Placement AI Counselor) - context for Claude Code

## Who and what
- Founder: MSAQLAIN (UNIFUSION Dynamics). Product: Placement AI. This repo branch builds PAI C, the counselor.
- Talk to the founder in Roman Urdu (or English). Never Hindi or Devanagari, even if his voice typing produces Devanagari.
- Be honest and critical. Do not just agree.

## Read first
1. docs/counselor/README.md (index)
2. docs/counselor/PAI_C_WORKFLOW_LOCK_V1.md (locked workflow A-K, PAI OS contract, Operator)
3. docs/counselor/AGENT_MASTER_PROMPT_V1.md (rules, phases)
4. docs/counselor/COUNSELING_POLICY.md and docs/counselor/SPINE.md (how the code is built)
5. docs/counselor/BUILD_REPORT_V1.md, DECISIONS.md, BLOCKERS.md (what is built, what is missing)
6. docs/counselor/VAULT_SPEC.md (the student Vault: spec and build status)
Figma board (locked): https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF

## Product rules
- One counselor voice. Paths first, places later (no university before stage H).
- No fact about the student without evidence (stated / shown / confirmed). No world fact without a source.
- Safety first: distress goes to care. At most one question per reply.

## Engineering rules
- Branch pai-c only. Never touch dev or pai-os. PAI OS is another developer's work.
- Reuse: Model Gateway, Task Runtime, Operator (workflow mode), research gateway, Memory Service, reconciler.
- No hardcoding of country, institution, exam, language or persona. Policies, copy and catalogs live in data files.
- Prompts live in .md files. When a prompt changes, sync docs/counselor/COUNSELOR_V3_PROMPTS.md (tests compare them).
- DB changes only via Alembic migrations. Drop a table only with the founder's explicit approval (migration 115
  dropped the PAI OS tables). Never edit .env. Never print secrets.
- This repo is PAI C only. PAI OS meets it through the decision record (handoff), student requests and escalations.
- No live model/API calls without the founder's approval and a cost cap.

## Commands
- Backend tests (from backend/, key unset): `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider`
- Frontend: `npm test` and `npm run build` in frontend/.
- Local stack: `python scripts/run.py` (rebuilds and restarts only what changed, keeps data), then http://localhost:3000 (frontend)
  and :8000 (backend). `python scripts/del.py` wipes all containers, volumes, images and build cache of this project;
  `python scripts/run.py --fresh` does both.

## Current direction (19 Oct 2026)
- Core engineering is mostly built (see BUILD_REPORT_V1.md). Freeze new modules.
- Next: validate with real students (assessment -> profile report with traffic lights -> counselor), using
  established frameworks (RIASEC interests, work values) and a small Pakistan eligibility data layer.

## PAI OS working rules (from the `pai-os` branch)
These rules apply to PAI OS work: code under `backend/app/os`, `backend/app/pai_os_bridge.py`,
`frontend/components/os/` and the `os-*` app routes. They came in with the trial merge of `pai-os` into `pai-c`.
- Never paste API keys or real student data into Claude.
- One component per PR.
- Task branches start from and rebase on `pai-os`. `pai-os` merges into `dev` only at slice gates.
- OS code lives only in `backend/app/os`.
- Shared files need a reviewer from each team.
- Run `tach check` and `pytest tests/os` before pushing.
