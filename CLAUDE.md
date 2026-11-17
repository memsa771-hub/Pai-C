# Placement AI (PAI Counsellor + PAI OS) - context for Claude Code

## Who and what
- Founder: MSAQLAIN (UNIFUSION Dynamics). Product: Placement AI. This repo is Placement AI: the PAI Counsellor (PAI C) and PAI OS in one app.
- Talk to the founder in Roman Urdu (or English). Never Hindi or Devanagari, even if his voice typing produces Devanagari.
- Be honest and critical. Do not just agree.

## Read first
1. docs/superpowers/specs/2026-11-03-pai-connect-design.md sections 2-3 (master spec: decisions and requirements R-01...). FigJam overview: https://www.figma.com/board/X25QOs43qaDABBYEmzUPxk
2. The current phase spec in docs/superpowers/specs/ (P1: 2026-11-04-p1-connection-core-design.md)
3. The latest handoff in docs/connect/handoff/ (p<N>-handoff.md)
4. docs/counselor/README.md (index)
5. docs/counselor/PAI_C_WORKFLOW_LOCK_V1.md (locked workflow A-K, PAI OS contract, Operator)
6. docs/counselor/AGENT_MASTER_PROMPT_V1.md (rules, phases)
7. docs/counselor/COUNSELING_POLICY.md and docs/counselor/SPINE.md (how the code is built)
8. docs/counselor/BUILD_REPORT_V1.md, DECISIONS.md, BLOCKERS.md (what is built, what is missing)
9. docs/counselor/VAULT_SPEC.md (the student Vault: spec and build status)
Figma board (locked): https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF

## Product rules
- One counselor voice. Paths first, places later (no university before stage H).
- No fact about the student without evidence (stated / shown / confirmed). No world fact without a source.
- Safety first: distress goes to care. At most one question per reply.

## Engineering rules
- Reuse: Model Gateway, Task Runtime, Operator (workflow mode), research gateway, Memory Service, reconciler.
- No hardcoding of country, institution, exam, language or persona. Policies, copy and catalogs live in data files.
- Prompts live in .md files. When a prompt changes, sync docs/counselor/COUNSELOR_V3_PROMPTS.md (tests compare them).
- DB changes only via Alembic migrations. Drop a table only with the founder's explicit approval (migration 115
  dropped the PAI OS tables). Never edit .env. Never print secrets.
- No live model/API calls without the founder's approval and a cost cap.

## Commands
- Backend tests (from backend/, key unset): `env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider`
- Frontend: `npm test` and `npm run build` in frontend/.
- Local stack: `python scripts/run.py` (rebuilds and restarts only what changed, keeps data), then http://localhost:3000 (frontend)
  and :8000 (backend). `python scripts/del.py` wipes all containers, volumes, images and build cache of this project;
  `python scripts/run.py --fresh` does both.
- Traceability (repo root): `python scripts/check_traceability.py [--gate P<N>]`
- Freeze check (repo root): `python scripts/check_freeze.py --base origin/pai-connect`
- Before pushing OS code: `tach check` and `pytest tests/os`.

## Connection work (master spec 13.2)
- Read master spec sections 2-3 and the phase spec before any task. Name the R-IDs the task builds.
- Never invent data: no institution, date, fee, merit figure or rule from memory. Data enters only through the
  registry, research and the review queue.
- No Pakistani or other country-specific names in `app/os` code (red-flag search, R-58).
- Do not touch the frozen Counsellor files in connection work (R-43, master spec section 10) except through the freeze exception process (master §10: `freeze-exception` label, the R-ID, a replay showing only the intended answers changed, and the Counsellor lead's approval).
- Every change of data ownership follows master spec section 4. A copy of another owner's data is a defect.
- Stop and ask when unclear. Never weaken a test to make it pass.
- The OS developers build the connection work, Counsellor side included (D-16). The Counsellor lead
  (`@memsa771-hub`) reviews every PR that touches Counsellor files.
- Branches: integration branch `pai-connect` (cut from `pai-merge`). Task branches `pc/p<N>-t<M>-<name>`,
  squash-merged. Nothing merges into `pai-merge` until the whole plan is complete (owner, P0-D14); then merge with a
  merge commit. Phase handoffs are signed off by the owner alone (P0-D13).

## Current direction (7 Nov 2026)
- Connection work per the master spec. P0 done (signed off 4 Nov). P1 done (signed off 7 Nov; handoff
  docs/connect/handoff/p1-handoff.md). Now: phase P2 (national data system); its phase spec is drafted and awaits the
  owner's approval. Research batches 1-5 (v4) are on branch pc/p2-research-batches. Next: P3.

## PAI OS working rules
These rules apply to PAI OS work: code under `backend/app/os`, `backend/app/pai_os_bridge.py`,
`frontend/components/os/` and the `os-*` app routes.
- Never paste API keys or real student data into Claude.
- One component per PR.
- OS code lives only in `backend/app/os` (glue only in `backend/app/pai_os_bridge.py`).
- Shared files need a reviewer from each team.
