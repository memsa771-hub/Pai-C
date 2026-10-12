# PAI C cleanup audit - phases 1 and 2

**Phase 1 below is the original historical audit.** Approved Phase 2 results are recorded at the end; table notes now record each disposition. Historical evidence commands describe the pre-cleanup tree, not current availability.

Date: 2026-10-12. Branch: `pai-c`. Audited local and fetched origin base: `bd779b1ffce8d8a9a71962b1e4ad3499395aee43`.

Only this document is created. No existing file, code, prompt, dependency or migration is changed. No rebuild, test execution, database access, application import, or live model/API call occurred. Vulture 2.16 was installed outside the repository as explicitly requested. Git fetch established branch provenance.

`delete` means a candidate for a later approved phase, never deletion in this phase. `needs migration` means owner/data/schema review first. Counts below count table rows, some of which group files. CURRENT means current purpose or approved plan, not that every planned feature is built. SUPERSEDED does not automatically mean deletable: some older documents still serve tests and operations.

**Scope limits:** No `.env` or `.env.*` contents were opened, including the example files. Thus A5 example-key parity is unverified under the explicit prohibition. After fetch, remote branches are `origin/dev`, `origin/main`, `origin/pai-c` plus HEAD alias: no `origin/pai-os` is available. Shared/OS items are never recommended for deletion.

## Evidence commands and methods

Run from `workspace`. Searches restrict source extensions and never read environment files.

- **G1:** `python -B backend/scripts/import_graph.py`, followed by an inline Python inverse graph using the script's `graph(Path('backend/app'))`: **258 modules; zero unresolved dynamic imports; five modules with no app importer**. AST imports in tests, scripts and Alembic were checked separately.
- **G2:** Traverse that graph from `app.main` and `app.jobs.worker`: eight modules outside those roots. Inspect startup, registries, migration and script consumers before classifying them.
- **G3:** `python -B -m vulture backend/app --min-confidence 80`: **eight findings**, all confirmed/classified with symbol searches. Exit 1 means findings, not tool failure. Supplemental AST/name scans examine PAI C public definitions with only one occurrence.
- **G4:** AST inventory of **133 annotated Config attributes**, reference searches outside config.py, self-validation and computed Model Gateway attributes. Zero external backend references: HOST, PAI_COUNSELOR_RESEARCH_DAILY_LIMIT, PAI_PROFILE_COMPLETION_ROLLOUT_AT. ROLLOUT_MODE also has validation-only reads. Compose pass-throughs checked separately.
- **G5:** AST enumeration of ORM classes with `__tablename__`, symbol/raw-table references outside models.py, then tests/scripts/migrations: three classes have no application reader/writer.
- **G6:** Resolve every absolute app import in tracked backend tests/scripts: **zero imports of missing modules**. Check fixtures through literal paths, globs and generated ID paths.
- **G7:** Static import/path graph of **196 frontend TS/JS/CSS/config files**, including @/ aliases, relative paths, export-from and literal import/require. Traverse from **23 Next app/config roots**; eleven non-test sources outside roots. Confirm with independent grep. Knip/ts-prune were unavailable; no repository tooling added. Nonliteral dynamic accesses remain a limitation.
- **G8:** Safe tracked text inventory from `git ls-files`, excluding `.env*` contents; filename references, document bodies/headings and incoming links. Ignored local artifacts checked by names only.

Reproducible G1/G2 probe (PowerShell here-string piped to `python -B -`; imports no app module):

```python
from pathlib import Path
from runpy import run_path
from collections import defaultdict
modules, edges, unknown = run_path('backend/scripts/import_graph.py')['graph'](Path('backend/app'))
inverse = defaultdict(set)
for owner, targets in edges.items():
    for item in targets:
        inverse[item].add(owner)
print('no_app_importers', sorted(m for m in modules if not inverse[m]))
seen, pending = set(), ['app.main', 'app.jobs.worker']
while pending:
    item = pending.pop()
    if item not in seen:
        seen.add(item)
        pending.extend(edges.get(item, set()) - seen)
print('outside_main_worker', sorted(set(modules) - seen))
print('unresolved_dynamic', unknown)
```

Reproducible exact incoming-reference probe for a proposed file deletion:

```python
from pathlib import Path
from subprocess import check_output
name = 'LEAN_COUNSELOR.md'  # substitute candidate basename
suffixes = {'.md', '.py', '.ts', '.tsx', '.js', '.json', '.yml', '.yaml', '.sh', '.css'}
for filename in check_output(['git', 'ls-files'], text=True).splitlines():
    path = Path(filename)
    if path.name.startswith('.env') or path.name == name or path.suffix not in suffixes:
        continue
    if name in path.read_text(encoding='utf-8-sig', errors='replace'):
        print(filename)
```

### Dynamic-loading mechanisms checked

1. Uvicorn `app.main:app`, entrypoint.sh and Dockerfile COPY/ENTRYPOINT.
2. Main router imports/include_router registrations, including OS routes.
3. Compose worker `python -m app.jobs.worker`, time-based named sweeps and existing Task Runtime dispatch.
4. pkgutil/importlib plugin discovery, get_capabilities, system capability registrations and job-handler compatibility register.
5. Tool registry handlers and audiences; abstract local/MCP adapters distinguished from installed providers.
6. Alembic Base.metadata/models registration and migration 101 importing migrate_v1.
7. Prompt allowlist, load_prompt(instructions) for handoff/wellbeing, direct safety prompt path.
8. Playbook Markdown/YAML and JSON persona/playbook fixture globs; coverage requirements JSON.
9. Next filesystem routes, metadata, public assets, CSS imports, PostCSS/Vitest/TypeScript roots; desktop scaffolding assessed separately.
10. Offline startup Compose `scripts.offline_startup_app:app`, evaluation CLI/package/script imports.

## A. Backend Python

| Path (and symbol if inside a file) | Owner (PAI C / PAI OS / shared / repo) | Evidence (command + result) | Recommendation (delete / keep / ask OS dev / needs migration) | Risk (low / medium / high) | Notes |
| --- | --- | --- | --- | --- | --- |
| backend/app/ (258 modules) | shared | G1/G2: five no-importer modules; eight outside main/worker roots; all exceptions listed below. Zero unresolved dynamic imports. | keep | medium | Other modules have application edges or checked entry points. Static in-degree alone is not deletion evidence. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/jobs/worker.py | shared | G1: no app importer; `rg -n 'app.jobs.worker' docker-compose.prod.yml`: executable at line 148. test_research_spine.py also imports it. | keep | high | Worker CLI entry point. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/pai_c/deep/migrate_v1.py | PAI C | `rg -n 'migrate_v1' backend/alembic backend/tests --glob '*.py'`: migration 101, test_truth_map_v2.py, truth_map_fixtures.py. G1: no app importer. | keep | high | Migration replay depends on it. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/pai_c/deep/usage.py | shared | G1: test_counselor_deep_pr4.py:22 only external importer. File re-exports gateway symbols; SPINE:40-43 explicitly retains compatibility. | ask OS dev | medium | Test-only today, but public compatibility alias. No deletion without owner approval and test target migration. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/plugins/_shared/costs.py::route_cost | shared | `rg -n 'route_cost' backend --glob '*.py'`: definition and test_research_costs.py only. G1: no app importer. | ask OS dev | medium | Test-only fee helper; plugin discovery does not independently call this helper. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/journey/milestones.py::next_incomplete | shared | G1: no app/test/script/migration importer. `rg -n 'next_incomplete' backend docs --glob '*.py' --glob '*.md'`: definition only. | ask OS dev | medium | Shared journey API, not safe to delete for PAI C alone. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/tools/local/{__init__,provider}.py | shared | G2: neither module reachable from main/worker. `rg -n 'LocalToolProvider' backend docs --glob '*.py' --glob '*.md'`: class and package export only. | ask OS dev | medium | Abstract future local-daemon boundary, not installed provider. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/tools/mcp/{__init__,provider}.py | shared | G2: neither module reachable. `rg -n 'McpToolProvider' backend docs --glob '*.py' --glob '*.md'`: class and package export only. | ask OS dev | medium | Shared external-tool adapter boundary. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/main.py + routers/* | shared | `rg -n 'include_router' backend/app/main.py`: lines 718-747 register all Counselor and OS routers. G1: no orphan router. | keep | high | Decorated routes and startup registration count as consumers. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/plugins/*; capabilities/{loader,system}.py | PAI OS | Loader uses pkgutil.iter_modules/importlib/get_capabilities. system.py registers session, Counselor, memory, research, document, operator.run and roadmaps.mark_stale handlers. | keep | high | Dynamic registration verified; no plugin deletion proposed. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/jobs/service.py + runtime/task_runtime.py | shared | `rg -n 'register\|task_runtime' backend/app/jobs backend/app/runtime --glob '*.py'`: register wraps CapabilityContract and runner dispatches registry handlers. | keep | high | Named jobs/callbacks are actual consumers. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/app/models.py + Alembic metadata | shared | Read alembic/env.py: imports app.models/Base; target_metadata = Base.metadata. | keep | high | ORM registration is independent of business queries. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| capabilities/manifest.py::CapabilitySchemaError import | shared | Vulture 90%; `rg -n 'CapabilitySchemaError' backend --glob '*.py'`: test_capability_ownership.py imports/asserts it. | keep | medium | Intentional public alias, Vulture false positive. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| database.py::compiler lambda type_, **kw (four findings) | shared | Vulture 100%, lines 25/26; lambdas replace SQLiteTypeCompiler.visit_JSONB/visit_UUID. | keep | high | Framework callback parameters required for compatibility. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| memory/handlers.py::_records_for(memory_ids) | shared | Vulture 100%, line 300; `rg -n 'memory_ids\|_records_for' backend/app/memory/handlers.py` confirms payload/caller supplies it. | keep | medium | Unused compatibility argument in live shared indexing path. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/stages.py::advance_discovery_stage(goal_records) | PAI C | Vulture 100%, line 47; `rg -n 'goal_records' backend --glob '*.py'`: callers/tests still supply it; body uses only foundation/identity gates. | keep | medium | Confirmed unused parameter, not dead function. Coordinated signature cleanup is separate. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| services/integrations.py::_send_slack(is_agent) | PAI OS | Vulture 100%, line 345; `rg -n 'is_agent' backend/app/services/integrations.py`: caller at line 318. | ask OS dev | medium | OS attribution API decision required before argument removal. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/memory.py::MemoryService.latest_episode | PAI C | G3; `rg -n 'latest_episode' backend docs --glob '*.py' --glob '*.md'`: definition:51 and historical SPINE:375 only. context:139 and analysis:134 call session_summaries. | delete | medium | Two-line obsolete wrapper. Approval must reconcile its historical facade contract; no external pai-os branch available. **Phase 2: DELETED in 1d6b424b3980994d2a9553e85dd42cc00e8716b4.** |
| mirror_schema/notebook_schema/planner.plan validators | PAI C | Supplemental single-occurrence symbol scan; inspected @model_validator/@field_validator for valid_contract, objective_reference_required, trim_evidence, has_evidence, isolate_archive, known_playbooks. | keep | high | Pydantic invokes registered methods without textual calls. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| deep/polish.py::has_list; memory.py::export_truth_map | PAI C | `rg -n 'has_list\|export_truth_map' backend --glob '*.py'`: smoke calls has_list; exporter calls export_truth_map; tests also exercise them. | keep | low | Non-app script consumers are valid. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/student_requests.py::oldest_open | shared | `rg -n 'oldest_open' backend --glob '*.py'`: definition plus test_student_requests.py only. | ask OS dev | high | Explicit OS-facing contract; test-only does not authorize shrinking it. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/student_requests.py::mark_asked | shared | `rg -n 'mark_asked' backend --glob '*.py'`: definition plus test_student_requests.py only. | ask OS dev | high | Same student-request API ownership rule. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/voice/prompts/voice.md | PAI C | `rg -n 'load_prompt' backend/app/pai_c --glob '*.py'`: deep/turn.py loads voice. | keep | low | Live runtime prompt. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/planner/prompts/planner.md | PAI C | Same loader search: deep/analysis.py loads planner. | keep | low | Background Planner input. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/safety/prompts/safety.md | PAI C | safety/gate.py:18 reads file directly using Path/read_text. | keep | low | Direct path loader, not an orphan. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/deep/prompts/mirror.md | PAI C | deep/mirror.py:130 load_prompt('mirror'). | keep | low | Mirror job consumer. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/deep/prompts/roadmap_builder.md | PAI C | deep/roadmaps.py:158 load_prompt('roadmap_builder'). | keep | low | Roadmap generator consumer. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/deep/prompts/sensitive_check.md | PAI C | deep/sensitive.py:37 load_prompt('sensitive_check'). | keep | low | Batched pre-Mirror check consumer. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/deep/prompts/session_summary.md | PAI C | pai_c/sessions.py:46 load_prompt('session_summary'). | keep | low | Session job consumer. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/deep/prompts/language_retry.md | PAI C | deep/turn.py:101 load_prompt('language_retry'). | keep | low | Bounded repair consumer. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/deep/prompts/handoff.md | PAI C | handoff.py:26 supplies instructions='handoff'; turn.py:86 loads instructions dynamically. | keep | low | Loader allowlist and caller both checked. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/deep/prompts/wellbeing.md | PAI C | runtime.py:141 supplies instructions='wellbeing'; turn.py loads instructions. | keep | low | Safety path consumer. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/playbooks/*.md (10) | PAI C | registry.py globs *.md, parses YAML and populates BOOKS; Planner/context consume selected entries. | keep | low | All ten dynamically read; no orphan prompt found. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| application_workspace/README.md | PAI OS | Markdown inventory identifies module documentation; package/router registered in main.py. | keep | low | Not a prompt. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| config.py::PAI_COUNSELOR_RESEARCH_DAILY_LIMIT | PAI C | G4; `rg -n 'PAI_COUNSELOR_RESEARCH_DAILY_LIMIT' backend/app --glob '*.py'`: declaration:220 and validator:432 only. Compose local:15,48/prod:42 only pass it through. | delete | medium | Retired ask_research daily limiter has no enforcement consumer. Approval covers setting/validator operand only; coordinate shared Compose cleanup separately. **Phase 2: DELETED in 1d6b424b3980994d2a9553e85dd42cc00e8716b4.** |
| config.py::HOST | shared | G4: declaration only; entrypoint.sh hardcodes --host, not config.HOST. | ask OS dev | low | Deployment/shared config owner decision. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| config.py::PAI_PROFILE_COMPLETION_ROLLOUT_MODE / _AT | shared | `rg -n 'PROFILE_COMPLETION_ROLLOUT_MODE\|PROFILE_COMPLETION_ROLLOUT_AT' backend/app --glob '*.py'`: declarations and startup validators only. | ask OS dev | medium | Dormant legacy gate, validation-only rather than completely unread. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| config.py remaining attributes | shared | G4 reference scan plus gateway _MODELS/_EFFORTS and computed API_KEY/BASE_URL prefixes. | keep | medium | Names computed through getattr accounted for; reference use does not prove all branches reachable. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| .env.example / .env.production.example | repo | Filename inventory only; contents forbidden by explicit .env.* rule. | keep | high | Example-key parity unverified. No workaround using git show. **Phase 2: KEPT; explicit exception used only to remove the approved unused daily-limit line from production example. No other example lines changed.** |
| models.py::ModelAccess / model_access | shared | G5 + `rg -n 'ModelAccess\|model_access' backend docs --glob '*.py' --glob '*.md'`: no app reader/writer outside models, historical migration references. | needs migration | high | List only; owner, real data and schema dependencies unknown. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| models.py::ProfileRequirement / pai_profile_requirements | shared | G5: no app read/write outside models. Historical migrations/test schema references; SPINE:770-771 already flags pending data check. | needs migration | high | No table or model removal; test helper still builds metadata. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| models.py::ProfileFieldResponse / pai_profile_field_responses | shared | Same G5 result; counselor_eval_support.py imports for disposable test metadata, migrations retain schema history. | needs migration | high | Real row counts/FKs and OS use need later review. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| Other mapped ORM classes/tables | shared | G5 symbol/literal-table scan found only the three above without app references. Generic records dispatch, serializers and queries checked. | keep | high | Does not certify every individual column is used. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: fastapi, pydantic, sqlalchemy, alembic | shared | AST root-import counts: 48, 36, 168 and 39 backend files respectively; Compose invokes alembic upgrade head. | keep | low | Framework/migration dependencies used. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: uvicorn[standard], psycopg2-binary | shared | entrypoint.sh invokes uvicorn; config URL normalizer and Compose use postgresql+psycopg2. | keep | high | CLI/driver loading needs no direct Python import. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: python-dotenv, pyjwt[crypto], boto3 | shared | Config imports dotenv; security/human_auth imports jwt; files/storage imports boto3. | keep | low | Auth crypto extra needed for asymmetric verification. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: python-multipart | shared | `rg -n 'Form\(\|UploadFile' backend/app/routers/files.py`: live File/Form upload endpoints. | keep | high | FastAPI multipart loading is implicit. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: httpx, playwright, openai, regex, redis | shared | AST: httpx in 17 files; browser manager imports playwright; inference/client imports openai; four files import regex; infrastructure/cache imports redis. | keep | low | Every listed dependency has consumers. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: qdrant-client[fastembed] | shared | memory/index_qdrant imports qdrant_client; memory/sparse imports fastembed. | keep | low | Extra supplies sparse retrieval encoder. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: pypdf, pypdfium2, python-docx | shared | documents/parsers imports pypdf, pypdfium2 and docx. | keep | low | Parsing/OCR fallback consumers. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| requirements: tzdata | shared | `rg -n 'ZoneInfo' backend/app --glob '*.py'`: deadlines/calendar/routines timezone consumers. | keep | medium | ZoneInfo packaged fallback, especially Windows; direct tzdata import not expected. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| pai_c/playbooks/registry.py::yaml dependency | PAI C | Registry imports/uses yaml; requirements.txt has no direct PyYAML declaration. | keep | medium | Packaging finding: possibly transitive-only provisioning, not a deletion candidate. No fix authorized here. **Phase 2: KEPT for the reason above; not approved for deletion.** |

## B. Backend tests, fixtures and scripts

| Path (and symbol if inside a file) | Owner (PAI C / PAI OS / shared / repo) | Evidence (command + result) | Recommendation (delete / keep / ask OS dev / needs migration) | Risk (low / medium / high) | Notes |
| --- | --- | --- | --- | --- | --- |
| backend/scripts/counselor_eval_support.py | PAI C | G8 + AST imports: eval harness and numerous tests import StudentSession. | keep | low | Disposable offline student/workspace helper. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/eval_counselor_deep.py | PAI C | `rg -n 'eval_counselor_deep' backend/tests docs backend/scripts --glob '*.py' --glob '*.md'`: tests, eval README, roadmap docs. | keep | low | Active recorded/live harness; not executed here. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/export_counselor_session.py | PAI C | test_export_counselor_session.py and counselor/README.md reference CLI; Truth Map tests exercise archive exclusion. | keep | low | Read-only exporter, not obsolete evaluation output. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/import_graph.py | PAI C | RESTRUCTURE.md documents command; this audit uses graph() without app imports. | keep | low | Standalone CLI is itself an entry point. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/offline_startup_app.py | PAI C | `rg -n 'offline_startup_app' backend/scripts --glob '*.yml'`: offline Compose uvicorn target. | keep | low | Dynamic executable module. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/eval/cost.py | PAI C | `rg -n 'scripts.eval.cost' backend/scripts backend/tests --glob '*.py'`: exporter, smoke, deep eval and budget tests. | keep | low | Shared evaluation cost/budget utility. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/eval/counselor_smoke.py | PAI C | test_counselor_smoke_script.py and SPINE.md reference it. | keep | low | Script/test entry point. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/eval/offline_startup_check.py | PAI C | CLEANUP_AFTER_DEEP.md describes reproducible fake-provider procedure; founder checklist links that section. | keep | medium | Retain unique instructions if historical docs are consolidated. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/eval/recorded_planner.py | PAI C | eval harness plus Planner/Voice/playbook/Truth Map tests import it. | keep | low | Recorded test support, not unused model runtime. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/scripts/eval/__init__.py | PAI C | scripts.eval.cost/recorded_planner imports use this package. | keep | low | Package registration, not a filename-stem grep false positive. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| backend/tests/ (77 tracked Python files) | shared | G6: zero app imports resolve to missing code; pytest test_*.py convention; inspected historical-test consumers. | keep | medium | Old filenames still assert live deep/research/gateway behavior. No fresh suite result claimed. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| test_counselor_deep_pr4.py::usage compatibility test | shared | Imports deep.usage:22; tests log format:376. This is the shim's only importer outside the module. | ask OS dev | medium | Preserve assertions; API alias removal requires shared-owner approval. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| test_research_costs.py | shared | `rg -n 'route_cost' backend --glob '*.py'`: only consumer of plugins/_shared/costs.py. | ask OS dev | medium | Test-only helper pair; not safe to delete shared fee logic without owner review. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| test_student_requests.py::oldest_open/mark_asked | shared | Direct symbol search finds these service callers only in this test. | keep | high | Keeps OS-facing service API tested. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| tests/fixtures/deep_personas/*.json (18) | PAI C | eval_counselor_deep.py:38,56 reads directory.glob('*.json'); tests exercise load_personas. | keep | low | Seventeen lack literal filename references but are dynamically loaded. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| tests/fixtures/playbooks/*.json (10) | PAI C | test_counselor_playbooks.py:100-109 globs, checks IDs against BOOKS and reads every generated id+'.json'. | keep | low | All ten consumed. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| tests/fixtures/counselor_smoke/messages.json | PAI C | scripts/eval/counselor_smoke.py:8 documents explicit --messages fixture path; CLI loads the supplied path. | keep | low | User-supplied smoke input, not automatically loaded by filename or an old run output. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| tests/fixtures/mirror/valid.json | PAI C | test_counselor_mirror.py reads fixture; MIRROR.md links it. | keep | low | Offline contract example. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| tests/fixtures/roadmaps/mirror_lanes.json | PAI C | `rg -n "mirror_lanes\|fixtures/roadmaps" backend docs --glob "*.py" --glob "*.md"`: no code loader; RESEARCH_ROADMAPS.md:67,101 references it as examples. | keep | medium | Documentation-only fixture, not test-loaded. Retain until its examples are deliberately replaced; completes all 31 tracked fixtures. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| scripts/eval/prompts/*.md; model_prices.json; tool_prices.json | PAI C | Harness PROMPTS/PRICES, read_text and cost.py price loader; test_eval_counselor_deep.py exercises budgets. | keep | medium | No orphan evaluator prompt/data found. No evaluator run authorized. **Phase 2: KEPT for the reason above; not approved for deletion.** |

## C. Frontend

| Path (and symbol if inside a file) | Owner (PAI C / PAI OS / shared / repo) | Evidence (command + result) | Recommendation (delete / keep / ask OS dev / needs migration) | Risk (low / medium / high) | Notes |
| --- | --- | --- | --- | --- | --- |
| frontend source/config inventory (196 files) | shared | G7 graph from 23 roots: eleven production source files outside roots, listed below. Independent import-path searches confirm. | keep | medium | Static fallback because knip/ts-prune unavailable; external/dynamic consumers remain uncertain. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/agents/agent-status-card.tsx | PAI OS | G7 unreachable; `rg -n 'agent-status-card' frontend --glob '*.ts' --glob '*.tsx'`: no importer. | ask OS dev | medium | Agent/OS UI. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/agents/agent-status-indicator.tsx | PAI OS | G7 unreachable; corresponding filename import search returns no importer. | ask OS dev | medium | Agent/OS UI. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/layout/toolbar.tsx | shared | G7 unreachable; toolbar import-path scan finds no source importer. | ask OS dev | medium | Generic layout exports; do not delete shared UI. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/routines/routines-view.tsx | PAI OS | G7 unreachable; routines-view import search finds no importer. | ask OS dev | medium | Routines remain OS-owned even if this view is not mounted. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/sessions/new-session-button.tsx | shared | G7 unreachable; new-session-button import search finds no importer. | ask OS dev | medium | Session/thread UI may belong to OS. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/sessions/session-list.tsx | shared | G7 unreachable; session-list import search finds no external importer. | ask OS dev | medium | Retired visible threads does not authorize shared component deletion. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/sessions/section-header.tsx | shared | G7 unreachable; imported only by the orphan session-list.tsx. | ask OS dev | medium | Transitive orphan; same owner decision as session-list. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/ui/avatar.tsx | shared | G7 unreachable; @/components/ui/avatar import search finds no importer. | ask OS dev | medium | Shared primitive; TS include still type-checks it. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/ui/breadcrumb.tsx | shared | G7 unreachable; corresponding import-path search finds no importer. | ask OS dev | medium | Shared primitive. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/ui/card.tsx | shared | G7 unreachable; exact @/components/ui/card import search finds no importer. | ask OS dev | medium | Shared primitive; distinguish roadmap-card etc. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| components/ui/input-group.tsx | shared | G7 unreachable; corresponding import-path search finds no importer. | ask OS dev | medium | Shared primitive. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| frontend/app/** (18 conventional route/layout files) | shared | git filename inventory includes page/layout/not-found; package scripts use Next. | keep | high | File-based routes are entry points even without imports. Auth/callback/settings/share included. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| frontend/hooks/*; lib/*; remaining components | shared | G7: all other tracked production files have a path from route/config roots. | keep | medium | No orphan hook/lib file found. File-level audit does not certify every exported symbol. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| public/pai-logo.png | shared | G8 filename search across safe frontend/backend/docs files finds zero consumers. | ask OS dev | low | Brand/public URL contract may have external consumers. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| public/typing-indicator.gif | shared | Same filename scan: zero references. | ask OS dev | low | Chat/brand asset; confirm shared owner before removal. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| public/.well-known/agent-skills/index.json | PAI OS | No local importer; Next serves public path without importing it. | ask OS dev | high | External machine-discovery endpoint cannot be disproved by internal grep. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| public/.well-known/skills/index.json | PAI OS | Same asset/path analysis. | ask OS dev | high | OS/external discovery ownership. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| public/{favicon-32x32.png,pai-emblem.png,notification.wav,site.webmanifest} | shared | Asset-name searches find app/layout metadata, manifest favicon references, Counselor/nav images and notification playback. | keep | low | All four remaining tracked public assets have readers/references. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| package.json::date-fns | shared | `rg -n 'date-fns' frontend --glob '!package-lock.json'`: declaration only; no source import. | ask OS dev | medium | Candidate unused dependency; shared owner must approve removal/lockfile update. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| package.json::motion | shared | Same scan: declaration and prefers-reduced-motion CSS only; no package import. | ask OS dev | medium | CSS media query is not a motion library consumer. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| package.json::@tailwindcss/vite | shared | Import-specifier/config scan: no consumer outside package/lockfile. | ask OS dev | medium | Desktop scripts remain; owner decision required. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| package.json::@vitejs/plugin-react | shared | Same scan: no consumer; no tracked vite.config.ts. | ask OS dev | medium | Do not remove shared desktop tooling unilaterally. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| Remaining dependencies/devDependencies | shared | UI/lib/test imports and CSS/config consumers; postcss.config.cjs imports @tailwindcss/postcss, Vitest uses Vite, Next/TS load @types implicitly. | keep | medium | No direct @types import expected; package scripts and tool loading count. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| package.json desktop scripts; tsconfig Vite exclusion; next.config desktop comment | PAI OS | `git ls-files '*vite.config*' '*index.html'`: no tracked desktop entry/config, yet build:desktop/dev:desktop and Vite exclusion remain. | ask OS dev | medium | Stale desktop scaffolding; leave unchanged pending OS developer decision. **Phase 2: KEPT for the reason above; not approved for deletion.** |

## D. Repository files

| Path (and symbol if inside a file) | Owner (PAI C / PAI OS / shared / repo) | Evidence (command + result) | Recommendation (delete / keep / ask OS dev / needs migration) | Risk (low / medium / high) | Notes |
| --- | --- | --- | --- | --- | --- |
| backend/eval_reports/counselor_research_recorded_20261007.md | PAI C | G8: zero incoming filename references. `git ls-files '*eval_counselor_research_recorded*'`: none. Header: synthetic recorded contract run, 70/70 checks; generator previously removed. | delete | low | 22-line obsolete run output, not a fixture. Replaced by deep research-contract tests/eval harness; history preserved in Git. **Phase 2: DELETED in 73ef11e725bac3c76ad47a2de57c8351b390a41e.** |
| eval_reports/pr15-astra-v32.json | repo | pr15-model-matrix.md references it; previous explicit instruction retained pr15-* comparison history. | keep | low | Historical paid comparison, not current quality proof. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| eval_reports/pr15-model-matrix.json | repo | Same matrix Markdown reference and retention instruction. | keep | low | Preserve requested comparison history. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| eval_reports/pr15-model-matrix.md | repo | Links both comparison JSON files and Danish scenario; prior retention instruction. | keep | low | Historical provenance is a real purpose. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| eval_reports/pr9-import-graph.json | repo | RESTRUCTURE.md references it. | keep | low | Historical move-boundary evidence. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| eval_reports/pr9-results.md | repo | RESTRUCTURE.md references it; report links smoke artifacts. | keep | low | Historical evaluation limitations; no fresh results claimed. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| eval_reports/pr9-smoke-astra.json | repo | pr9-results.md links it. | keep | low | Preserve cost/evaluation history. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| eval_reports/pr9-smoke-sol.json | repo | Same report reference. | keep | low | No live evaluation rerun. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| Tracked *.bak/*.orig/*.tmp/*.log/*.pyc and cache paths | repo | git ls-files suffix/directory inventory: zero matches, including __pycache__, node_modules, .next, .coverage, .pytest_cache and tsbuildinfo. | keep | low | No committed temp/cache deletion candidate. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| .env.backup-20260920-183759 (ignored local file) | repo | Directory-name inventory only; .gitignore excludes .env.*. Not opened/copied. | keep | high | Contents and retention unknown; secret-file handling requires separate owner instruction. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| frontend/node_modules/; frontend/.next/ | repo | Directory-name inventory; ignored by root/frontend rules; initial git status clean. | keep | low | Active dependencies/build outputs, not committed clutter. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| .p0-offline/; .p0-test-deps/ | repo | Root/backend/frontend name inventory: neither exists. | keep | low | No stale P0 folders to delete. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docker-compose.prod.yml; docker-compose.local.yml; scripts/eval/docker-compose.offline.yml | shared | Inspected entrypoints: production stack, local override, separate fake-provider startup app. | keep | high | Complementary configurations, not duplicates. No rebuild performed. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| Root/frontend/backend .gitignore files | shared | Read rules: root credentials/common outputs, directory-specific desktop/InsForge/frontend exclusions. | keep | low | Overlapping patterns do not justify deleting useful rules. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| frontend/package-lock.json | shared | git lockfile inventory: one tracked npm lockfile. | keep | low | Pins reproducible shared dependency resolution. **Phase 2: KEPT for the reason above; not approved for deletion.** |

## E. Documentation

Every tracked file in docs/*.md and docs/counselor/*.md is classified below. Current approved planning documents can describe future targets; their proposal/date labels alone do not justify deletion. Historical documents with test or operational consumers are retained explicitly.

| Path (and symbol if inside a file) | Owner (PAI C / PAI OS / shared / repo) | Evidence (command + result) | Recommendation (delete / keep / ask OS dev / needs migration) | Risk (low / medium / high) | Notes |
| --- | --- | --- | --- | --- | --- |
| docs/counselor/ARCHITECTURE.md | PAI C | Read core layout/sections 11-12; CLEAN_ARCHITECTURE explicitly supersedes sections 2-4 where different. | keep | low | CURRENT approved architecture/data decisions, with target layout rather than every deployed path. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/CLEAN_ARCHITECTURE.md | PAI C | Read fully: six spine services, registries, research decision, Memory Service boundary and shared named jobs. Current gateway/runtime ownership matches. | keep | low | CURRENT. Opening proposal/old-problems wording is historical context. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/CORE_V1_SPEC.md | PAI C | Read F1-F4 Truth Map/Planner/Voice/playbooks and remaining core features; current planner/voice/safety packages match implemented portions. | keep | low | CURRENT approved target; dated test count is not a fresh result. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/MASTER_PLAN.md | PAI C | Read phases/gates and OS contract; explicitly updated spine-first ordering supersedes older inline order. | keep | low | CURRENT master plan, including planned work. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/PAI_C_VISION.md | PAI C | Read Truth Map/lifecycle/edge cases; matches approved core direction. | keep | low | CURRENT vision, not availability guarantee. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/PRODUCT_FEATURES.md | PAI C | Read screens/flow: Profile, My Picture, Roadmaps, My Plan; compare current components and approved future targets. | keep | low | CURRENT product target. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/COUNSELING_METHOD.md | PAI C | Read v4 method/student model/adaptive moves/measurement; current Voice/Planner/playbooks use those concepts. | keep | low | CURRENT method. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/SPINE.md | PAI C | Read owner/move tables, P2 Truth Map/episodes/semantic cleanup and latest P3 Round 2 implementation entries. | keep | low | CURRENT implementation evidence; earlier entries are dated history. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/P0_ENTRY_AUDIT.md | PAI C | Read security/entry evidence, defects/tests and open questions; tested auth entry remains live. | keep | low | CURRENT completed audit record. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/README.md | PAI C | Read branch/index/export sections; references live exporter and protected runtime/test docs. | keep | medium | CURRENT entry point; later maintenance needed for prompt paths and Analyst naming after Voice/Planner moves. **Phase 2: KEPT; current index, architecture summary and prompt paths updated by explicit approval in 73ef11e.** |
| docs/counselor/CODEX_COUNSELOR_V3_DEEP.md | PAI C | Read old step sequence and historical-order warning:3. G8: incoming link only from README. No runtime/test consumer. 413 lines. | delete | medium | SUPERSEDED by MASTER_PLAN + CORE_V1_SPEC + CLEAN_ARCHITECTURE + SPINE. Phase 2 must update index link. **Phase 2: DELETED in 73ef11e725bac3c76ad47a2de57c8351b390a41e.** |
| docs/counselor/LEAN_COUNSELOR.md | PAI C | Read line 3 counselor_v3_3, lines 7/19 pending PR 6 and old three-call count. G8 incoming links: README/profile-foundation. 19 lines. | delete | medium | SUPERSEDED by SPINE P2/P3 and CLEAN_ARCHITECTURE. Mirror/Safety/Planner/Voice have since landed. **Phase 2: DELETED in 73ef11e725bac3c76ad47a2de57c8351b390a41e.** |
| docs/counselor/RESTRUCTURE.md | PAI C | Old move table sends gateway into pai_c; current gateway is app/research/gateway.py. G8 incoming link: README. 80 lines. | delete | medium | SUPERSEDED by SPINE owner/move/trigger tables + CLEAN_ARCHITECTURE. Rehome pr9 report links; keep reports. **Phase 2: DELETED in 73ef11e725bac3c76ad47a2de57c8351b390a41e.** |
| docs/counselor/COUNSELOR_REAL_WORLD_AND_LIFECYCLE.md | PAI C | Read v3 family.father schema, old 8-key coverage and old roadmap/coach prescriptions. G8: README link only; no code/test reader. 211 lines. | delete | medium | SUPERSEDED by PAI_C_VISION + PRODUCT_FEATURES + COUNSELING_METHOD. Reviewer must confirm desired future lifecycle guidance is retained in these current plans. **Phase 2: DELETED in 73ef11e725bac3c76ad47a2de57c8351b390a41e.** |
| docs/counselor/CLEANUP_AFTER_DEEP.md | PAI C | Read completed consolidation/branch inventories and later removal notes; G8 links from local-test guide/README/research docs. | keep | medium | SUPERSEDED architecture replaced by SPINE/CLEAN_ARCHITECTURE, but unique offline startup recipe and DB inventory remain useful. Port those before considering deletion. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/COUNSELOR_V3_PROMPTS.md | PAI C | `rg -n 'COUNSELOR_V3_PROMPTS' backend/tests --glob '*.py'`: generic/pr1/mirror/truth_map_v2 tests read it for parity. Sections 1/2 now voice/planner. | keep | high | SUPERSEDED v3 framing; runtime prompt files/SPINE replace architecture. No drop-in replacement for live parity reference: deletion breaks tests. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/MIRROR.md | PAI C | Nine-dimension/versioned validation and Confirm/Edit match current job/schema; line 34 still says PR 7 will rebuild brief. README links it. | keep | medium | SUPERSEDED PR 6 narrative replaced by SPINE + PRODUCT_FEATURES; retain useful operational rules/fixture reference until consolidated. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/RESEARCH_ROADMAPS.md | PAI C | Read cache privacy, per-version budgets and migrations 099/100; README/CLEANUP_AFTER_DEEP links. Also sole documentation reader of mirror_lanes fixture. | keep | medium | SUPERSEDED PR 7/8 framing replaced by SPINE + CLEAN_ARCHITECTURE; unique cache/privacy/example details still serve a purpose. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/TARGETS.md | PAI C | Read eight numeric release targets and old one-shot PR 9 caps; README links it. Current method/spec do not reproduce all thresholds. | keep | medium | SUPERSEDED eval procedure; CORE_V1_SPEC/COUNSELING_METHOD replace approach, but threshold replacement unresolved. Retain pending owner decision. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/COUNSELING_CONVERSATIONS.md | PAI C | test_counselor_deep_generic.py reads scenarios to guard against persona hardcoding; README indexes illustrative examples. | keep | low | CURRENT illustrative/test data. Design authority is PAI_C_VISION/COUNSELING_METHOD, not a literal conversation script. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/counselor/DEEP_COUNSELING_DANISH.md | PAI C | Same generic test reads it; pr15 comparison report refers to the scenario. | keep | low | CURRENT test/history input; not a real student transcript or an authorized live test. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/PAI_COUNSELOR_PROFILE_FOUNDATION.md | PAI C | Read lines 57-70: Mirror not implemented, PR 7/8 upcoming; current mirror/research contradict availability. G8 README link. 70 lines. | delete | medium | SUPERSEDED by SPINE Truth Map/P2, CLEAN_ARCHITECTURE, PAI_C_VISION. Update incoming link in phase 2. **Phase 2: DELETED in 73ef11e725bac3c76ad47a2de57c8351b390a41e.** |
| docs/COUNSELOR_LOCAL_TEST.md | PAI C | Read implemented Mirror/roadmap founder checklist and Compose commands; stale dev branch/migration range 096-100; links unique offline startup recipe. | keep | medium | SUPERSEDED setup details, CURRENT manual-test purpose. SPINE/P0 audit replace implementation history, not this checklist. Update later; no full replacement exists. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/PAI_COUNSELOR_ROADMAPS.md | shared | Read migrations through 095 and old capability composition; includes decision records/student requests/escalations/service-token contracts. | ask OS dev | medium | SUPERSEDED Counselor flow replaced by SPINE + RESEARCH_ROADMAPS. Shared contract/verification details need owner review before updating or retiring. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/APPLICATION_WORKSPACE.md | PAI OS | Read navigation/workflows/integration seam; app.application_workspace router remains registered. | keep | low | CURRENT OS reference; other developer owns it. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/AUTH_SESSION.md | shared | Read Supabase cookie/JWKS/session operation; live security/auth modules match; P0 audit is complementary evidence. | keep | low | CURRENT shared authentication reference. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/PAI_CAPABILITY_DEVELOPER_GUIDE.md | shared | Native loader description matches capabilities/loader.py; line 23 still references removed DirectionDiscoveryService. | ask OS dev | medium | CURRENT registry/OS purpose with SUPERSEDED discovery paragraph. SPINE replaces Counselor specifics; do not delete shared guide. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/PLACEMENT_AI_PRODUCT_BLUEPRINT.md | PAI OS | Read wider product/design/workflow/boundary; scope includes agentic OS, not only Counselor. | keep | medium | CURRENT OS/product plan. PAI_C_VISION replaces Counselor details only. **Phase 2: KEPT for the reason above; not approved for deletion.** |
| docs/VAULT_STEWARDS.md | shared | Read stewardship/candidate/reconciliation boundaries; current memory/stewards and Vault retain ownership. | keep | low | CURRENT shared reference, complemented by SPINE Truth Map boundary. **Phase 2: KEPT for the reason above; not approved for deletion.** |

## Summary

Counts are table rows, not file counts; grouped rows cover registries, dependencies and retained inventories. Scope: 706 tracked files, 258 app Python modules, 77 backend test Python files, 31 backend fixtures, 196 frontend source/config files, eight root docs and 21 counselor docs before this audit.

| Section | Rows | delete | keep | ask OS dev | needs migration |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 52 | 2 | 37 | 10 | 3 |
| B | 20 | 0 | 18 | 2 | 0 |
| C | 25 | 0 | 5 | 20 | 0 |
| D | 15 | 1 | 14 | 0 | 0 |
| E | 29 | 5 | 22 | 2 | 0 |
| Total | 141 | 8 | 96 | 34 | 3 |

Estimated removals if approved: **6 complete files / 815 lines**, plus approximately **3-4 lines** of obsolete PAI C setting/wrapper code. Excludes replacement docs, link fixes and shared Compose changes; net diff will differ. No OS/shared implementation, dependency, binary asset, fixture, test or table is recommended for deletion.

### Highest-confidence delete shortlist (up to 15)

Only eight candidates are supported. This list is not padded with protected OS/shared code or required operational/test docs. Medium-risk entries still require the stated contract/reference checks.

1. `backend/eval_reports/counselor_research_recorded_20261007.md` - G8: zero incoming filename references. `git ls-files '*eval_counselor_research_recorded*'`: none. Header: synthetic recorded contract run, 70/70 checks; generator previously removed. Risk: low.
2. `config.py::PAI_COUNSELOR_RESEARCH_DAILY_LIMIT` - G4; `rg -n 'PAI_COUNSELOR_RESEARCH_DAILY_LIMIT' backend/app --glob '*.py'`: declaration:220 and validator:432 only. Compose local:15,48/prod:42 only pass it through. Risk: medium.
3. `docs/PAI_COUNSELOR_PROFILE_FOUNDATION.md` - Read lines 57-70: Mirror not implemented, PR 7/8 upcoming; current mirror/research contradict availability. G8 README link. 70 lines. Risk: medium.
4. `docs/counselor/CODEX_COUNSELOR_V3_DEEP.md` - Read old step sequence and historical-order warning:3. G8: incoming link only from README. No runtime/test consumer. 413 lines. Risk: medium.
5. `docs/counselor/COUNSELOR_REAL_WORLD_AND_LIFECYCLE.md` - Read v3 family.father schema, old 8-key coverage and old roadmap/coach prescriptions. G8: README link only; no code/test reader. 211 lines. Risk: medium.
6. `docs/counselor/LEAN_COUNSELOR.md` - Read line 3 counselor_v3_3, lines 7/19 pending PR 6 and old three-call count. G8 incoming links: README/profile-foundation. 19 lines. Risk: medium.
7. `docs/counselor/RESTRUCTURE.md` - Old move table sends gateway into pai_c; current gateway is app/research/gateway.py. G8 incoming link: README. 80 lines. Risk: medium.
8. `pai_c/memory.py::MemoryService.latest_episode` - G3; `rg -n 'latest_episode' backend docs --glob '*.py' --glob '*.md'`: definition:51 and historical SPINE:375 only. context:139 and analysis:134 call session_summaries. Risk: medium.

### Everything marked ask OS dev

- **A** `backend/app/pai_c/deep/usage.py` - Test-only today, but public compatibility alias. No deletion without owner approval and test target migration.
- **A** `backend/app/plugins/_shared/costs.py::route_cost` - Test-only fee helper; plugin discovery does not independently call this helper.
- **A** `backend/app/journey/milestones.py::next_incomplete` - Shared journey API, not safe to delete for PAI C alone.
- **A** `backend/app/tools/local/{__init__,provider}.py` - Abstract future local-daemon boundary, not installed provider.
- **A** `backend/app/tools/mcp/{__init__,provider}.py` - Shared external-tool adapter boundary.
- **A** `services/integrations.py::_send_slack(is_agent)` - OS attribution API decision required before argument removal.
- **A** `pai_c/student_requests.py::oldest_open` - Explicit OS-facing contract; test-only does not authorize shrinking it.
- **A** `pai_c/student_requests.py::mark_asked` - Same student-request API ownership rule.
- **A** `config.py::HOST` - Deployment/shared config owner decision.
- **A** `config.py::PAI_PROFILE_COMPLETION_ROLLOUT_MODE / _AT` - Dormant legacy gate, validation-only rather than completely unread.
- **B** `test_counselor_deep_pr4.py::usage compatibility test` - Preserve assertions; API alias removal requires shared-owner approval.
- **B** `test_research_costs.py` - Test-only helper pair; not safe to delete shared fee logic without owner review.
- **C** `components/agents/agent-status-card.tsx` - Agent/OS UI.
- **C** `components/agents/agent-status-indicator.tsx` - Agent/OS UI.
- **C** `components/layout/toolbar.tsx` - Generic layout exports; do not delete shared UI.
- **C** `components/routines/routines-view.tsx` - Routines remain OS-owned even if this view is not mounted.
- **C** `components/sessions/new-session-button.tsx` - Session/thread UI may belong to OS.
- **C** `components/sessions/session-list.tsx` - Retired visible threads does not authorize shared component deletion.
- **C** `components/sessions/section-header.tsx` - Transitive orphan; same owner decision as session-list.
- **C** `components/ui/avatar.tsx` - Shared primitive; TS include still type-checks it.
- **C** `components/ui/breadcrumb.tsx` - Shared primitive.
- **C** `components/ui/card.tsx` - Shared primitive; distinguish roadmap-card etc.
- **C** `components/ui/input-group.tsx` - Shared primitive.
- **C** `public/pai-logo.png` - Brand/public URL contract may have external consumers.
- **C** `public/typing-indicator.gif` - Chat/brand asset; confirm shared owner before removal.
- **C** `public/.well-known/agent-skills/index.json` - External machine-discovery endpoint cannot be disproved by internal grep.
- **C** `public/.well-known/skills/index.json` - OS/external discovery ownership.
- **C** `package.json::date-fns` - Candidate unused dependency; shared owner must approve removal/lockfile update.
- **C** `package.json::motion` - CSS media query is not a motion library consumer.
- **C** `package.json::@tailwindcss/vite` - Desktop scripts remain; owner decision required.
- **C** `package.json::@vitejs/plugin-react` - Do not remove shared desktop tooling unilaterally.
- **C** `package.json desktop scripts; tsconfig Vite exclusion; next.config desktop comment` - Stale desktop scaffolding; leave unchanged pending OS developer decision.
- **E** `docs/PAI_COUNSELOR_ROADMAPS.md` - SUPERSEDED Counselor flow replaced by SPINE + RESEARCH_ROADMAPS. Shared contract/verification details need owner review before updating or retiring.
- **E** `docs/PAI_CAPABILITY_DEVELOPER_GUIDE.md` - CURRENT registry/OS purpose with SUPERSEDED discovery paragraph. SPINE replaces Counselor specifics; do not delete shared guide.

### Open questions and limitations

- A5 requires example-env inspection while the explicit rule prohibits reading all .env.*. A later read-only exception for just the example files is needed to check parity; no contents were inspected here.
- Where is the OS branch/repository? Fetch found no origin/pai-os. Shared/OS consumers cannot be checked there; protected items need owner evidence.
- Is MemoryService.latest_episode's historical facade API an external contract? Current app/scripts/tests do not call it; session_summaries replaces it. Approve this public-method removal explicitly before phase 2.
- Is TARGETS.md still the release threshold authority? Current method/spec replace its approach but not every exact number. Retain until a replacement is approved.
- Where should the unique offline startup procedure and DB inventory from CLEANUP_AFTER_DEEP.md live? Founder testing still links them.
- Are local/MCP adapters, desktop scripts and public discovery endpoints deliberately retained for OS integrations? Leave that design to the OS owner.
- The playbook registry imports yaml without an explicit PyYAML requirement. Is transitive provisioning intentional? Packaging risk noted, no fix authorized.
- Real row counts, FK dependencies and external usage of model_access, pai_profile_requirements and pai_profile_field_responses remain unknown. Owner/data review and a later migration are required.
- Static graphs cannot prove external public URL/API consumers absent or detect every computed symbol. Knip/ts-prune were unavailable. No application import pass was run because config imports can load forbidden env files/startup behavior.
- Current plans retain proposal labels, dated test counts and future targets. These are not claims of implemented availability. README prompt paths/Analyst naming need later reconciliation with Voice/Planner.
- Test inventory is not a fresh pass count. Tests/build were not run or changed in this audit-only phase. No fresh quality, performance, auth or security validation is claimed.

### Phase-2 prerequisites (no action taken)

Approve exact paths/symbols, reconcile incoming links and unique instructions, confirm OS/public contracts and run full suites after code cleanup. Inspect table data only for an approved migration. Preserve parity files, historical migration helpers, fixtures and explicitly retained pr15 comparison history. Phase 1 changes only this document.

## Phase 2 - approved deletion results

Date: 2026-10-12. Branch: pai-c, base 6546925. Every code/file deletion was preceded by a fresh symbol/import/reference check. Incoming documentation links were replaced before deleting their targets. Historical mentions remain in this audit as evidence; there are no remaining deleted-file references elsewhere in tracked source/docs.

Only the eight approved original candidates and the explicit reviewer additions below were removed. All 96 keep, 34 ask-OS-dev and three needs-migration recommendations remain protected. The approved README/config/Compose maintenance is recorded separately; no protected OS implementation, table, fixture, dependency declaration or prompt was changed.

### Commits and group gates

Line counts are git diff additions/deletions, including replacement wording, test deletion and README link maintenance.

| Group | Commit | Added / deleted / net removed | Backend after commit | Frontend / build |
| --- | --- | ---: | --- | --- |
| 1 - foreground | 564c5eebd37c45dab8bc169d56c51d4806961e48 | 6 / 457 / 451 | 1002 passed, 3 skipped, 8 subtests; 224.87s | 23 passed; build PASS |
| 2 - tools | 3e5fc88198f2b9f6548cca3d2c2c27c2fd2ace4e | 3 / 134 / 131 | 1002 passed, 3 skipped, 8 subtests; 209.64s | Not required: no frontend/config changes |
| 3 - facade/config | 1d6b424b3980994d2a9553e85dd42cc00e8716b4 | 1 / 8 / 7 | 1002 passed, 3 skipped, 8 subtests; 234.02s | 23 passed; build PASS |
| 4 - docs/report | 73ef11e725bac3c76ad47a2de57c8351b390a41e | 39 / 851 / 812 | 1002 passed, 3 skipped, 8 subtests; 218.34s | 23 passed; build PASS |

Total groups 1-4: 49 added, 1450 deleted, **1401 net lines removed**, 16 changed paths. Six complete documentation/report files plus foreground_executor.py removed. The final verify/document commit changes only this audit and is followed by the mandatory full backend gate.

### Reviewer additions

| Path / symbol | Fresh evidence and disposition | Commit |
| --- | --- | --- |
| memory/foreground.py::build_foreground_context, _hybrid, _hybrid_blocking, _structured, _close_foreground_index | Symbol searches under backend app/tests showed only the removed slow-retrieval test consumed the foreground builder; helper edges were internal to that path. Removed these functions, ForegroundContext, fallback constant and exclusive imports. Updated module docstring. | 564c5ee |
| memory/foreground_executor.py | Import search after removing the foreground path showed zero remaining app/test importers. Entire 148-line module deleted. | 564c5ee |
| tests/test_counselor_journey.py::test_slow_vector_retrieval_keeps_time_for_canonical_fallback | Sole removed foreground-builder test; removed its exclusive imports. Kept renderer/rule and all other behavior tests. | 564c5ee |
| config.py::PAI_MEMORY_FOREGROUND_WORKERS / PAI_MEMORY_FOREGROUND_MAX_INFLIGHT | Only executor/config declarations remained before deletion. Removed declarations/exclusive pool comments; no validator/log operands for these keys remained. Keys were already absent from both examples and Compose files. Fixed obsolete retrieval-budget comment. | 564c5ee |
| memory/foreground.py retained rendering code | KEPT MEMORY_RULES, MEMORY_RULES_TRAILER, escape_value, render_block, block delimiters, _fit and required imports/config. Consumers include memory/context.py and services/operator.py. | 564c5ee |
| config.py::PAI_MEMORY_CONTEXT_TIMEOUT_MS / PAI_MEMORY_CONTEXT_MAX_CHARS | KEPT: fresh searches found pai_c/memory.py recall timeout and foreground.py renderer character budget, respectively. Conditional removal was not applicable. | 564c5ee |
| tools/builtin/memory.py::remember / forget | Fresh handler/registry/test searches found no registrations or callers. Removed both handlers and exclusive MemoryReconciler import; updated docstring. No test directly called them, so no tool tests needed deletion. Negative registration assertions remain. | 3e5fc88 |
| tools/builtin/memory.py retained handlers | KEPT get_context, vault_get, memory_search, episodes_recent, propose_profile and shared _session helper. No unrelated helper/import cleanup. | 3e5fc88 |

### Original candidates and links

- MemoryService.latest_episode had no actual callers/tests; removed only that method. Kept tests/fields named latest_episode_summary, which concern different data.
- PAI_COUNSELOR_RESEARCH_DAILY_LIMIT had declaration/validation/pass-throughs only. Removed those plus its single production-example line. The key was absent from .env.example. All other example-file bytes are unchanged apart from existing line-ending normalization in comparison; local .env was never opened or edited.
- Deleted the five approved superseded docs and one old recorded report. Per-file tracked reference scan excluded environment files and historical audit text and found zero remaining consumers after README links were fixed.
- README now indexes only current docs. Replacements: CODEX_COUNSELOR_V3_DEEP -> MASTER_PLAN/CORE_V1_SPEC/CLEAN_ARCHITECTURE/SPINE; LEAN_COUNSELOR and RESTRUCTURE -> SPINE/CLEAN_ARCHITECTURE; COUNSELOR_REAL_WORLD_AND_LIFECYCLE -> PAI_C_VISION/PRODUCT_FEATURES/COUNSELING_METHOD; PAI_COUNSELOR_PROFILE_FOUNDATION -> SPINE/CLEAN_ARCHITECTURE/PAI_C_VISION.
- The profile-foundation link to LEAN_COUNSELOR was contained in a deleted source doc. Protected runtime parity, operational docs, pr15/pr9 history and fixtures remain. README prompt paths and the Voice/Planner architecture summary were corrected within the approved index update.
- Verification: tracked extension-restricted scan for all six deleted basenames found no references outside this historical audit; README local link check found zero missing targets. Python searches found zero remaining deleted executable symbols/config readers.

### Offline verification and baseline

Tests were run with fake providers and an external-connection socket guard. The launcher disables dotenv loading, selects disposable SQLite configuration and resolves the repository tests namespace explicitly. No real model/API call, production database mutation, application rebuild via Docker, secret output or local .env edit was performed. Frontend production builds were run as required.

Initial baseline: 1001 passed, two DOCX-table parsing failures, three production-only skips, eight subtests. Installed test environment had python-docx 1.1.0 below the existing requirements.txt minimum (1.1.2); updating the installed dependency to 1.2.0 made all 15 parser tests pass without repository changes. Removing the single approved foreground test yields 1002 passing tests on every cleanup group. No cleanup group broke tests or required a patch/revert.

Final full suite after group 4: **1002 passed, three skipped, eight subtests**. The three skipped production checks were also run separately in production test configuration: **three passed, four subtests**. Two existing migration-101 SQLite reflection warnings remain.

Separate final checks:
- PAI OS/entry/contracts: test_p0_entry_audit.py, test_counselor_escalations.py, test_pai_core_architecture.py: **103 passed**; covers decision records, student requests, escalations and service-token contracts.
- Architecture/spine: test_model_gateway.py, test_capability_ownership.py, test_research_spine.py, test_p1d_memory.py, test_p1d_messenger.py, test_p1d_orchestrator.py, test_counselor_consolidation.py: **94 passed**.
- import_graph.py --import-all through offline bootstrap: **257/257 app modules imported**, zero unresolved dynamic imports.
- Frontend: **23 passed across eight test files**. Production TypeScript/Next build: **PASS**.
- git diff --check: PASS. Changed tracked paths checked against the approved scope.

### Open questions / retained findings

No approved deletion is blocked by a new consumer. No group was reverted.

1. Both context timeout/character settings are live and intentionally retained. The approved worker settings and daily limit were absent from some examples/Compose files; no lines were invented to delete.
2. Phase-1 broad example-env parity remains unverified; Phase 2 inspected/edited only explicitly approved keys and proved other lines unchanged.
3. All OS/shared owner questions, table-data/migration reviews, dependency/adapter findings and protected-doc replacement questions from Phase 1 remain outside scope.
4. A stale remember/forget registration comment in tools/builtin/__init__.py remains outside the approved handler-file change; it is not executable registration.
