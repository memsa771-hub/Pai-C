# Counselor package boundaries

Pure moves; no legacy import shims. HTTP routers, authentication, database models,
Vault/memory, inference, tools, Journey, plugins and research stores remain shared.

## Moved files

| Previous | Current |
| --- | --- |
| `backend/app/counseling/posting.py` | `backend/app/pai_c/posting.py` |
| `backend/app/counseling/research_gateway.py` | `backend/app/pai_c/research_gateway.py` |
| `backend/app/counseling/runtime.py` | `backend/app/pai_c/runtime.py` |
| `backend/app/counseling/stages.py` | `backend/app/pai_c/stages.py` |
| `backend/app/counseling/student_requests.py` | `backend/app/pai_c/student_requests.py` |
| `backend/app/counseling/__init__.py` | `backend/app/pai_c/__init__.py` |
| `backend/app/counseling/deep/actions.py` | `backend/app/pai_c/deep/actions.py` |
| `backend/app/counseling/deep/analysis.py` | `backend/app/pai_c/deep/analysis.py` |
| `backend/app/counseling/deep/context.py` | `backend/app/pai_c/deep/context.py` |
| `backend/app/counseling/deep/coverage.py` | `backend/app/pai_c/deep/coverage.py` |
| `backend/app/counseling/deep/coverage_requirements.json` | `backend/app/pai_c/deep/coverage_requirements.json` |
| `backend/app/counseling/deep/mirror.py` | `backend/app/pai_c/deep/mirror.py` |
| `backend/app/counseling/deep/mirror_schema.py` | `backend/app/pai_c/deep/mirror_schema.py` |
| `backend/app/counseling/deep/notebook.py` | `backend/app/pai_c/deep/notebook.py` |
| `backend/app/counseling/deep/notebook_sanitize.py` | `backend/app/pai_c/deep/notebook_sanitize.py` |
| `backend/app/counseling/deep/notebook_schema.py` | `backend/app/pai_c/deep/notebook_schema.py` |
| `backend/app/counseling/deep/noted_questions.py` | `backend/app/pai_c/deep/noted_questions.py` |
| `backend/app/counseling/deep/polish.py` | `backend/app/pai_c/deep/polish.py` |
| `backend/app/counseling/deep/prompts.py` | `backend/app/pai_c/deep/prompts.py` |
| `backend/app/counseling/deep/roadmaps.py` | `backend/app/pai_c/deep/roadmaps.py` |
| `backend/app/counseling/deep/sensitive.py` | `backend/app/pai_c/deep/sensitive.py` |
| `backend/app/counseling/deep/turn.py` | `backend/app/pai_c/deep/turn.py` |
| `backend/app/counseling/deep/turn_input.py` | `backend/app/pai_c/deep/turn_input.py` |
| `backend/app/counseling/deep/usage.py` | `backend/app/pai_c/deep/usage.py` |
| `backend/app/counseling/deep/__init__.py` | `backend/app/pai_c/deep/__init__.py` |
| `backend/app/counseling/deep/prompts/analyst.md` | `backend/app/pai_c/deep/prompts/analyst.md` |
| `backend/app/counseling/deep/prompts/counselor.md` | `backend/app/pai_c/deep/prompts/counselor.md` |
| `backend/app/counseling/deep/prompts/handoff.md` | `backend/app/pai_c/deep/prompts/handoff.md` |
| `backend/app/counseling/deep/prompts/language_retry.md` | `backend/app/pai_c/deep/prompts/language_retry.md` |
| `backend/app/counseling/deep/prompts/mirror.md` | `backend/app/pai_c/deep/prompts/mirror.md` |
| `backend/app/counseling/deep/prompts/roadmap_builder.md` | `backend/app/pai_c/deep/prompts/roadmap_builder.md` |
| `backend/app/counseling/deep/prompts/sensitive_check.md` | `backend/app/pai_c/deep/prompts/sensitive_check.md` |
| `backend/app/services/counselor_handoff.py` | `backend/app/pai_c/handoff.py` |
| `backend/app/research/light.py` | `backend/app/pai_c/light_research.py` |
| `backend/app/roadmaps/service.py` | `backend/app/pai_c/roadmaps/service.py` |
| `backend/app/roadmaps/__init__.py` | `backend/app/pai_c/roadmaps/__init__.py` |

## Router helper moves

- `_target_for_conversation` and `_recent_dialogue` plus the unchanged voice instructions: routers/counselor_voice.py -> pai_c/voice_context.py.
- `_journey`: routers/counselor_summary.py -> pai_c/summary_access.py.
- Routes, provider handshake, credential resolution and response contracts remain in routers.

## Import graph

`python -m scripts.import_graph --import-all --out /reports/pr9-import-graph.json`
in a network-disabled container imports every module and exports static dependencies,
including function-local imports, relative/package imports and all allowlisted first-party plugins.
Graph JSON: eval_reports/pr9-import-graph.json.

No operational application/deadline/workflow module is eligible for a separate OS package yet:
`pai_c.runtime -> services.pai -> app.main -> routers.application_workspace -> application_workspace`
and `app.main -> routers.deadlines -> deadlines.service` are real transitive imports.
WorkspaceApi lazily imports app.main for its internal ASGI transport. Moving these
OS modules would break the required isolation rule. No empty OS placeholder is kept;
the shared transport is not refactored to manufacture isolation.

`services.pai` stays shared: security, event routing, application operations and
workflow scheduling also import it. Roadmap domain service moved with Counselor;
its HTTP routes and shared research evidence storage stay shared.

Docker COPY includes the entire backend and Alembic imports app.models; neither
has a path pointing at an old Counselor package. Historical migrations and DB
tables remain unchanged. New imports, monkeypatch paths and documentation paths
are updated directly. No duplicate models or tables are created.

## Evaluation limitation

After the moves: 243/243 app modules import; backend 631 tests and 8 subtests pass (3 production-only tests skipped); frontend 22 tests pass; production build passes. A final targeted check of voice, Mirror and review fixes passes all 32 tests. The one paid consolidated
evaluation was incomplete; see eval_reports/pr9-results.md. This structure change
does not claim production conversation quality or founder acceptance.
