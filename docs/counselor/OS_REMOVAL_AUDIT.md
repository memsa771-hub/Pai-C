# PAI C: OS removal audit — approval required

Date: 2026-10-18. Branch: `pai-c`. Inventory base: `1b4a80851e2518b80643ba03e589ba2bb4e469a9`.
The separate Phase 0 question-cap change does not change this dependency inventory.
Phase 0 commit: `abf1eef` (`fix: cap questions after two asking replies`).
Remote ownership cross-check: `origin/pai-os` at `de5c70e8426a0b8fe3a5c857484ac682c076dfa0` after fetch. No checkout or edit of that branch.
Sources: locked FigJam `NjVJfdxERWfRHPycy1wDkF`, sections 00–12; `PAI_C_WORKFLOW_LOCK_V1.md`, `COUNSELING_POLICY.md`, `SPINE.md`, and the historical `CLEANUP_AUDIT.md`.

The inventory below records the pre-removal audit. The founder approved the scoped changes on 2026-10-18; execution is tracked below. Existing tests remain.

## Approved execution

- UI removal: nine listed Applications/Deadlines/Tasks/Workflows components, their desktop/mobile mounts and navigation, and task/workflow UI flags plus Docker/Next/Compose build settings. Browser is removed from student navigation only. Shared shell, API, workspace context and notification infrastructure remain.
- Pre-deletion evidence: `rg -n 'ApplicationsView|ApplicationCalendar|ApplicationOperations|DeadlinesView|WorkflowsView|WorkflowBuilderDialog|TasksView|NewTaskDialog|TaskChatPopup' frontend --glob '*.tsx'` found wrapper imports of the four views, application view imports of calendar/operations, operations imports of builder/task popup, workflow view import of builder, and task view imports of dialog/popup. No other component consumer. After removal the same symbol search has no production matches. Calendar API types remain deliberately.
- Regression coverage: `frontend/components/layout/os-ui-removal.test.tsx` checks remaining shared navigation, old desktop view preferences, historical OS notification read behavior, and retained Counselor/roadmap notification destinations.
- UI commit `2be2fee`: guided/strict each 1240 passed, 3 production-only skips, 8 subtests; frontend 41 passed in 12 files; build passed; 268 modules imported; 9 architecture + 2 OS contract checks passed. Light/dark navigation captured with local fake state only.
- Router detachment: remove Application Workspace/deadline registration from main, deadline reminder sweep and the application-review augmentation/dispatch in the routine loop. Keep ASGI transport, generic routines, backend files, tables and models. Existing seven application/deadline regression tests mount their retained routers in an isolated test app; assertions are unchanged. `test_os_route_detachment.py` checks missing OS routes, retained shared routes/transport and scheduler boundary.
- Keep browser backend and integration backend/settings/relay. Defer monitor, threads, orchestration controls, routines, knowledge and agent-profile cleanup until the Phase 3 shell proves they have no importers.
- Open for OS developer: retain `tasks.list` / `tasks.create` and workflow advancement until their shared contract is agreed. No removal of them is authorized.
- Tables: no drops. Section 12 now correctly names `operator.run`; board re-read after approval confirms it supports workflow mode and the retained generic engine.

## Classification and evidence

- **C-only:** implements Counselor behavior; keep.
- **shared:** required infrastructure, contract, or a dependency of Counselor jobs; keep.
- **shared-split-later:** contains OS behavior but participates in a Counselor import/call path or mixed shell; keep the file in this round unless a separately reviewed boundary split is approved.
- **OS-only:** isolated application/execution UI or storage purpose; a candidate for later approval, not permission to delete now. An OS-only UI mount can be removed from a mixed shell without deleting the shell. Any proposed change to that shell must be reviewed separately.

Evidence commands below run from `workspace`, inspect source only, and exclude dotenv files. No database inspection, live provider calls, or external student data were used. Static imports include function-local imports, relative imports, package initializers and literal dynamic imports. They do not prove that every possible runtime branch executes.

| ID | Command / check | Observed result |
| --- | --- | --- |
| B1 | `python -B backend/scripts/import_graph.py` plus inverse edges from its `graph()` | 268 app modules; 261 reachable from all 53 `app.pai_c` module roots; zero unresolved dynamic imports. |
| B2 | Shortest paths over B1; inspect `services/pai.py::request/_raw_request`, `main.py` | `pai_c.deep.mirror -> services.pai -> main` reaches every registered router. This is an actual in-process ASGI transport, not an unused import. Registration-only reachability is distinguished from direct service calls below, but is not ignored. |
| B3 | `rg -n 'advance_workflow\|relay\|services.integrations' backend/app/pai_c/posting.py`; inspect Messenger | Messenger invokes workflow advancement and integration relay after posting. Both stay. |
| B4 | `rg -n 'register\|load_first\|load_system' backend/app/capabilities backend/app/tools --glob '*.py'`; inspect loader/system/registry | First-party plugins are discovered with pkgutil/importlib; tools are centrally registered; system jobs dispatch through Task Runtime. A lack of ordinary imports is not deletion evidence. |
| B5 | `rg -n 'DEPENDENCIES\|context.capabilities\|owns_task_types' backend/app/plugins/roadmap_builder backend/app/research/light.py --glob '*.py'` | `roadmap.build` owns `roadmap_research`; declares all five research capability dependencies. Light research invokes program discovery/research. |
| B6 | `rg -n '/v1/\|ctx.api' backend/app/tools/builtin --glob '*.py'`; inspect fetch/browser | Tools invoke tasks, files, browser, fetch and network routes. `web.fetch -> /v1/fetch -> BrowserManager`, including rendered pages. |
| B7 | `rg -n 'APIRouter\|include_router\|@router\.' backend/app/routers backend/app/application_workspace backend/app/main.py --glob '*.py'` | 31 router files plus package initializer; Application Workspace re-exports four subrouters. All are registered in main. |
| B8 | AST enumerate `__tablename__` in models.py; `rg -n '<ORM class>\|<table name>' backend/app --glob '*.py'` per family below | Reader/writer groups listed in the storage table. No row counts, retention or external consumers were inferred. |
| F1 | Resolve relative and `@/` import/from/export paths in tracked frontend app/components/hooks/lib TS/TSX; independent `rg -n '<component or path>' frontend --glob '*.ts' --glob '*.tsx'` | OS views mount inside shared wrapper/list-panel; Counselor research and roadmaps both use use-operator-status. Next filesystem routes count as entry points. |
| F2 | `rg -n 'ApplicationsView\|DeadlinesView\|WorkflowsView\|RoutineList\|TasksView\|MonitorGrid\|BrowserView\|KnowledgeView' frontend --glob '*.tsx'` | Concrete mounts in wrapper, list-panel and component subtrees; results reflected below. |
| F3 | `rg -n 'TASKS_UI_ENABLED\|WORKFLOWS_UI_ENABLED\|DMS_UI_ENABLED' frontend --glob '*.ts' --glob '*.tsx'` | Mixed navigation/context and notification handlers consume the flags. No whole config file is deletable. |
| O1 | `git grep -n -E 'app\.(services\.(operator\|workflow)\|pai_c\.posting\|research\.gateway\|runtime\.task_runtime)\|PAI_OS_SERVICE_TOKEN\|pai_decision_records\|pai_student_requests' origin/pai-os -- '*.py'` | Remote OS branch exists now. It retains Task Runtime users, operator.run registration, Messenger/workflow linkage, gateway callers, escalation token checks, and both contract tables. Read only; branch not checked out or modified. |

Reproduce the graph and exact direct importers without importing app/config:

```python
from collections import defaultdict, deque
from pathlib import Path
from runpy import run_path
g = run_path('backend/scripts/import_graph.py')
modules, edges, unknown = g['graph'](Path('backend/app'))
inverse = defaultdict(set)
for owner, targets in edges.items():
    for target in targets:
        inverse[target].add(owner)
roots = {name for name in modules if name.startswith('app.pai_c')}
paths = {}
pending = deque((name, [name]) for name in sorted(roots))
while pending:
    name, path = pending.popleft()
    if name in paths:
        continue
    paths[name] = path
    pending.extend((target, path + [target]) for target in sorted(edges[name]) if target not in paths)
for name in sorted(modules):
    print(name, 'importers=', sorted(inverse[name]), 'C_path=', paths.get(name))
print('unresolved_dynamic=', unknown)
```

### Important graph limitation and conservative decision

The ASGI transport and registries make almost the whole backend transitively reachable. Removing the `main` edge to make a module appear unused would violate the keep rule. The seven modules outside the static C closure are `jobs.worker`, `journey.milestones`, `plugins._shared.costs`, `tools.local`, `tools.local.provider`, `tools.mcp`, `tools.mcp.provider`. Worker is an executable entry point; the others are shared helpers/adapters. None is proven OS-only.

Therefore **no complete backend Python file is proposed for immediate deletion**. OS-only product purposes inside the backend are listed, but files on the graph stay shared-split-later. This does not claim that the application/deadline APIs are used by the Counselor's reasoning; it records their current composition-root dependency and the instruction not to break it.

## Backend modules and routes

Paths in this table are relative to `backend/app/`. Grouped rows cover the entire named package, including its initializer.

| File / module / route | Classification | Import/call evidence | Disposition |
| --- | --- | --- | --- |
| `pai_c/**` (53 Python modules, prompts and policy/playbook data) | C-only | Runtime/orchestrator, memory facade, Planner, Voice, Mirror, sessions, possibilities and roadmaps; B1 roots. | Keep all. Contract helpers inside this package remain public. |
| `services/operator.py`; `/v1/operator/runs*` | shared | research.gateway delegates/resumes; capabilities.system registers run_operator_job; tools/builtin/operator and memory.permissions import Operator; frontend C research status polls runs. | Keep workflow mode, generic five-phase loop, durable operator.run and execution_runs. |
| `runtime/**`, `jobs/**`, `capabilities/**` | shared | Mirror/Planner/memory/docs queue named jobs; worker dispatches via registry; B4/O1. | Keep queue, locks, leases, ordering, idempotency and system capabilities. |
| `inference/**` | shared | Gateway callers include Voice, Planner, memory, documents, plugins and Operator. | Keep transport, all role resolution and usage logging. |
| `memory/**`, `documents/**`, `files/**` | shared | pai_c.memory wraps shared services; document notify enters orchestrator; accepted candidates enqueue roadmap invalidation; B1/B4. | Keep all facts, records, extraction, reconciliation, parsing, storage and indexing. |
| `research/**` | shared | Mirror and roadmap routes enter gateway; light research uses capabilities; requirements/scheduler/jobs preserve cache and resume. | Keep gateway, budgets, dedupe, cache and Source Verifier. |
| `plugins/{program_discovery,program_research,roadmap_builder,qualification_recognition,scholarship_discovery,gap_assessment}/**` | shared | B4/B5: roadmap.build uses or declares each capability. Generic Operator can invoke installed capabilities. | Keep every installed plugin and its data packs. None is proven OS-only. |
| `plugins/_shared/**` | shared | Budget used by inference/research; sources by context/roadmaps; verification by public requirement cache. costs helper has tests and no OS-only proof. | Keep, including test-only shared helper. |
| `tools/**` and registered builtins | shared | B4/B6: Counselor/Operator share registries, audiences, broker and capability calls. tasks.list is in PAI_ALLOWED_TOOLS. | Keep all tools/adapters pending a separate capability-contract decision. |
| `services/pai.py` | shared-split-later | C imports PAI identity, workspace API transport and capabilities. API imports main lazily and dispatches through real access checks. | Keep entire module; no replacement transport. |
| `services/workflow.py` | shared-split-later | Messenger invokes advance_workflow; workflow._dispatch_turn calls C orchestrator; events/tasks/workspaces also import it. | Keep; no removal of _judge or workflow helper paths. |
| `services/integrations.py`; `/v1/integrations/*`, `/v1/workspaces/{id}/integrations*` | shared-split-later | Messenger calls relay; integrations calls orchestrator/events/workflow; main registers webhook routes. | Keep. External conversation relay is not isolated OS work. |
| `services/notify.py`; `/v1/notifications*` | shared | Roadmap service, student requests and roadmap plugin create notifications; same bell/inbox API as OS. | Keep shared notification center and durable records. |
| `services/email.py`; `/v1/feedback` | shared | feedback router imports mail sender; generic product feedback route. | Keep; not OS-specific. |
| `main.py` | shared-split-later | B2/B7: app, all routes, lifecycle/timer maintenance, application review invokes orchestrator at lines 327–355. | Keep. OS timer/application blocks need an approved selective split, not whole-file deletion. |
| `eventing/**`, `mods/**` | shared-split-later | Messenger -> eventing.factory -> WorkspaceMod -> messages -> workflow/task hooks; routing also supports C. | Keep complete event pipeline, auth and persistence. |
| `application_workspace/**`; router shim; `/v1/application-workspace/*` | shared-split-later | Product purpose OS-only (applications, saved institutions, calendar, requirements/tasks/routines). Main imports context and registers subrouters through ASGI graph B2; scheduled review calls C. | Retain current files. Candidate for a later composition/scheduler split after approval. |
| `deadlines/**`; `/v1/deadlines*` | shared-split-later | Main schedules reminders; application plans import DeadlineService; API registered in main. | Retain; OS-owned deadline behavior cannot be detached by deleting files alone. |
| `routers/tasks.py`; `/v1/tasks*` | shared-split-later | tools/builtin/tasks calls GET/POST; C allows tasks.list; generic Operator has tasks.create; workflow/knowledge/file/channel dependencies. | Keep until tool/public contract split is approved. |
| `routers/workflows.py`; `/v1/workflows*` | shared-split-later | Main route registration, services.workflow, workspace creation and task assignment consume workflows. | Keep; UI builder can be separately removed. |
| `routers/routines.py`; `/v1/routines*` | shared-split-later | application operations directly import it; main fires routines and can send application reviews to C. | Keep pending scheduler boundary decision. |
| `routers/todos.py`, `routers/timers.py`; `/v1/todos`, `/v1/timers*` | shared-split-later | main registration/maintenance; workspace context reads agent todos; generic agent event transport retained. | Do not assume timers/todos are disposable just from names. Confirm OS ownership/external clients first. |
| `browser/**`, `routers/browser.py`; `/v1/browser/*` | shared | web.fetch -> routers.fetch -> BrowserManager and _resolve_bf_key; Operator browser tools also invoke routes. | Keep browser execution/egress/storage backend. |
| `routers/fetch.py`, `routers/search.py`; `/v1/fetch`, `/v1/search/images` | shared | web.fetch uses fetch; search is registered generic media API; no OS-only proof for image search. | Keep. |
| `routers/knowledge.py`; `/v1/knowledge*` | shared-split-later | services.workflow loads KnowledgeEntry; tasks/workflows reference knowledge IDs; retained generic engine uses these contexts. | Keep. This is not the research evidence cache. |
| `routers/events.py`, `network.py`, `workspaces.py`; `/v1/events*`, network identity routes, `/v1/workspaces*` | shared-split-later | Authenticated C chat/voice/session membership and generic workspace/agent orchestration coexist; workflow calls network emit helper. | Keep shared transport and workspace services. |
| `routers/account.py`, `auth.py`, `app_version.py`; `/v1/account*`, `/v1/auth/*`, `/v1/app/version` | shared | User/session/onboarding/workspace entry and client version negotiation. | Keep. |
| `routers/student_profile.py`, `files.py`; `/v1/student-profile*`, `/v1/files*` | shared | Profile, onboarding and document consumers; C memory and file tools. | Keep all access checks and reconciled edit paths. |
| `routers/counselor_{summary,voice,possibilities}.py`, `roadmaps.py` | C-only | `/v1/counselor/*`, `/v1/roadmaps*`; frontend Mirror, voice, paths and C research entry points. | Keep. |
| `routers/decision_records.py`, `student_requests.py`, `escalations.py` | shared | `/v1/decision-records/current`, `/v1/student-requests`, `POST /v1/escalations`; O1 and contract tests. | Keep exact contract, service token, records and requests. |
| `routers/shares.py`; `/v1/shares*` | shared | Chat share-dialog/public share page; preserved conversation channels/events. | Keep; sharing is not proof of OS-only ownership. |
| `journey/**`, `workspace/**` | shared | Journey/stages/confirm/history and workspace naming/membership used by C; milestones helper is a public/shared candidate, not proven OS-only. | Keep. |
| `api/**`, `security/**`, `infrastructure/**`, `realtime/**`, `database.py`, `models.py`, `config.py`, package initializers | shared | Cross-cutting response/auth/cache/SSE/schema/config dependencies in B1 and all entry routes. | Keep; no whole-file deletion or DB-table drop. |

## Frontend files and mounts

Paths relative to `frontend/`. Views under `components/` are modes within `/[workspaceId]`, not independent Next routes. The distinction matters when approving navigation changes.

| File / view / route | Classification | Import/call evidence | Proposed action after approval |
| --- | --- | --- | --- |
| `components/applications/{applications-view,application-calendar,application-operations}.tsx` | OS-only | F1/F2: wrapper mounts ApplicationsView; calendar/operations used only by applications view; application APIs. | Remove application UI and its mounts, not shared shell or facts. |
| `components/deadlines/deadlines-view.tsx` | OS-only | Sole component importer wrapper; uses student-deadlines API. | Remove deadline UI/mount. Keep shared notifications. |
| `components/workflows/{workflows-view,workflow-builder-dialog}.tsx` | OS-only | View imported by wrapper; builder used by workflow view and application operations. | Remove builder/views only. Backend workflow engine stays. |
| `components/tasks/{tasks-view,new-task-dialog,task-chat-popup}.tsx` | OS-only | View mounted by wrapper; dialogs used by tasks/workflows/applications only. | Remove task-board UI/mounts. Keep task backend/tool contract pending split. |
| `components/routines/{routines-view,routine-list,create-routine-dialog}.tsx`, `use-routine-format.ts` | shared-split-later | List mounted in shell; create dialog imported by live chat-view and monitor; routine format shared inside group. | Keep whole group until the chat action/mount change is explicitly approved. No blanket directory deletion. |
| `components/monitor/{monitor-grid,monitor-tile,monitor-overlay}.tsx` | shared-split-later | Wrapper mounts grid; overlay embeds chat/routine interactions; grid watches all active sessions. | Keep pending a decision to remove this mixed conversation-monitor mode. |
| `components/agents/{agent-profile-panel,agent-status-card,agent-status-indicator}.tsx` | shared-split-later | Profile panel mounted in wrapper and includes builtin PAI handling; other two have no production importers. Generic agent management/identity boundary. | Keep until exact external/builtin UI behavior is approved. |
| `components/agents/agent-avatar.tsx` | shared | Imported by C chat messages/input/thinking/status and shared nav, as well as OS views. | Keep. |
| `components/chat/orchestration-control.tsx` | shared-split-later | chat-view imports it; exposes dynamic/master/workflow controls for non-primary conversations. | Keep until selective chat action removal is approved. |
| `components/browser/**` | shared-split-later | Wrapper/list-panel mount browser; backend browser still required by web.fetch and generic Operator; may expose human auth-required recovery. | Keep pending confirmation that recovery remains usable without UI. |
| `components/knowledge/**` | shared-split-later | Wrapper/list-panel mount document editor/list; backend workflows use KnowledgeEntry. | Keep; distinguish editable knowledge docs from uploaded files and research cache. |
| `components/threads/**`, `components/sessions/**` | shared-split-later | Thread list/new dialog mounted in wrapper; primary C conversation shares session state. Some session components have no importer. | Keep until primary conversation transport is separated from optional multi-agent UI. |
| `components/layout/{wrapper,list-panel,layout-context,workspace-navigation,nav-main,nav-rail,app-sidebar,app-header,mobile-header,use-desktop-workspace-state}.tsx/.ts` | shared-split-later | F1/F2: mounts both C and OS. Navigation consumes mixed files/browser/tasks/workflows state. | Keep files; approve only explicit OS view imports, mounts and menu entries for a later edit. |
| `lib/{workspace-context,api,types,config}`, `lib/helpers.ts`, i18n messages | shared-split-later | Shared session/chat/auth/profile plus OS state and API methods; workspace-context fetches tasks/workflows/routines. | Keep files. Any selective removal needs a caller list and retained C tests. |
| `lib/application-workspace.ts`, `lib/student-deadlines.ts` | shared-split-later | F1: OS views use types, but shared api.ts also imports/re-exports them. | Keep until associated API surface extraction is approved. |
| `hooks/use-operator-status.ts`, `layout/pai-system-status.tsx`, `chat/counselor-research-status.tsx` | shared | Hook imported by Counselor research status, roadmaps and global status. | Keep; Operator is Counselor infrastructure. |
| `components/notifications/**`, `layout/notifications-menu.tsx` | shared-split-later | Same bell and notification API used by C roadmaps/requests and OS tasks; navigation includes task branch. | Keep center, badges and preferences; only OS link branches are future candidates. |
| `components/{counselor,roadmaps,profile,onboarding}/**`, C chat cards/voice/research/request panels | C-only | Current inline Mirror/possibilities, profile evidence edits, roadmap actions, entry and voice. | Keep, including every existing component test. |
| `components/files/**`, shared chat rendering/input, `components/ui/**`, hooks and auth/i18n utilities | shared | C documents/uploads/messages and app shell depend on them. | Keep. No dependency removal inferred from OS-looking names. |
| `app/[workspaceId]/settings/integrations/page.tsx` | shared-split-later | Next filesystem route; service integration relay is called by Messenger. | Keep pending contract decision; do not silently disable an existing C channel. |
| Remaining `app/**` routes/layouts, settings components, `public/**`, feedback/tours/icons | shared | Next routes include sign-in/up/reset, account settings, share and workspace; public assets have URL contracts. | Keep. No OS-specific public URL proven disposable. |

## Storage: no tables are dropped

This is a later migration **review list**, not a DROP script. All models and Alembic revisions remain, including historical rows. Even an OS-only table needs owner agreement, live row/foreign-key inspection, export/retention policy, and removal of every reader/writer before a migration is proposed.

| Table(s) | Classification | Current reader/writer evidence (B8) | Later disposition |
| --- | --- | --- | --- |
| `pai_saved_institutions` | OS-only | SavedInstitution: application_workspace/catalog, plans only. | Review after Application Workspace detachment. |
| `pai_application_plans`, `pai_application_requirements` | OS-only | Application package queries/plans/operations/calendar/serializers/context; deadlines.service. | Review after applications/deadlines removal. |
| `pai_application_routines` | OS-only | Application operations/calendar/plans plus main scheduled review. | Review after main scheduler split; no drop now. |
| `pai_student_deadlines`, `pai_deadline_settings` | OS-only | deadlines.service and routers/deadlines only. | Review after reminders/API detachment. |
| `kanban_tasks`, `workflows`, `workflow_runs` | shared-split-later | workflow service/event hooks; task tools/routes; application operations; workspaces. | Keep: C Messenger and generic engine reach these paths. |
| `routines`, `timers`, `todos` | shared-split-later | Main timer/maintenance, routes; routines also application planning; todos feed generic workspace status. | Ownership and consumer review first. |
| `knowledge_entries` | shared-split-later | Workflow context loads KnowledgeEntry; tasks/workflows and knowledge router use it. | Keep while generic engine stays. |
| `integration_bindings` | shared-split-later | integrations routes and Messenger-called integrations service. | Keep channel delivery behavior. |
| `browser_tabs`, `browser_contexts`, `browser_usage` | shared | Browser manager/maintenance/routes used by retained browser tools and fetch. | Keep. |
| `execution_runs`, `background_jobs` | shared | Operator, research, requests, Task Runtime/worker and memory/docs jobs. | Keep; never classify durable jobs as OS-only. |
| `pai_decision_records`, `pai_student_requests` | shared | Roadmap choose, StudentRequestService, research jobs and exposed contract routes. | Keep exact C↔OS contract. |
| `pai_institutions`, `pai_institution_domains`, `pai_opportunities`, `pai_requirement_sets` | shared | Research store/discovery/scheduler and roadmap readers; institution catalog is also used by applications. | Keep research evidence/cache. |
| `pai_student_applications`, `pai_scholarship_applications`, `pai_visa_records` | shared | Canonical student_records services and record schemas, not only the OS application UI. | Keep historical/profile facts and reconciler ownership. |
| `counselor_notebooks`, `counselor_notebook_history`, `counselor_noted_questions`, `pai_turn_plans`, `pai_counselor_turn_decisions`, `pai_counselor_mirror_feedback`, `pai_possibilities` | C-only | Memory facade, Planner, Voice, Mirror, policy, requests and possibilities. | Keep. |
| `pai_student_journeys`, `pai_student_journey_events`, `pai_roadmaps`, `pai_roadmap_student_state` | C-only | Journey/Mirror history, paths, confirmation and choice. | Keep. |
| Remaining Vault/fact/record/evidence/revision/document/memory/episode tables | shared | memory/student_records, Vault/reconciler/retriever and document handlers. | Keep all; not OS-only because a record type concerns execution. |
| `users`, `auth_identities`, `pai_sessions`, `workspaces`, membership/channel/agent/event tables, `files`, `notifications`, `share_snapshots`, `feedback` | shared | Entry/security/chat/storage/delivery and common workspace services. | Keep, including notification dedupe and ownership. |
| `model_access`, `pai_profile_requirements`, `pai_profile_field_responses`, `invitations` | shared | No current business reader established for these legacy tables; metadata/migrations still contain them. Earlier audit flags three of these. | Unknown ownership/data is not OS-only proof. Separate migration review, not this removal. |

## Configuration, templates and docs

| File / key / data | Classification | Evidence | Disposition |
| --- | --- | --- | --- |
| `frontend/lib/config.ts::{TASKS_UI_ENABLED,WORKFLOWS_UI_ENABLED}` / `NEXT_PUBLIC_ENABLE_TASKS`, `NEXT_PUBLIC_ENABLE_WORKFLOWS` | OS-only | F3: OS view gates in navigation/layout; task flag also routes notifications. Dockerfile/Compose pass through build args. | Candidate key removal only after approved UI and notification branch edits. Keep mixed config files. |
| `DMS_UI_ENABLED` / `NEXT_PUBLIC_ENABLE_DMS` | shared-split-later | Thread list and shared workspace session selection consume it. | Keep pending primary/multi-conversation decision. |
| `PAI_OPERATOR_*`, `ROUTER_LLM_ENABLED`, browser/web provider config | shared | Gateway operator role; retained generic workflow/event engine; fetch/browser/web search. | Keep. |
| `PAI_OS_SERVICE_TOKEN` | shared | Escalation auth in current branch and origin/pai-os; contract test rejects invalid token. | Keep. |
| `.env` and `.env.*` | shared | Not opened, edited or copied. Key evidence above comes from code/Compose, not secret files. | No proposed file changes. Example-file edits need an explicit scoped list if later required. |
| OS workflow/task templates, agents | shared-split-later | No isolated source template/agent package proven deletable; workflows/agents are common registered services and stored models. | Do not delete generic engine, registry entries or stored rows by name. |
| `docs/counselor/CLEANUP_AUDIT.md`, current workflow/policy/SPINE, shared auth/Vault/capability docs | shared | Historical audit plus current source-of-truth/contract references. | Keep. This new audit supplements, not rewrites, their history. |

## Dynamic-loading checks

1. FastAPI include_router registrations and Application Workspace subrouters.
2. In-process ASGI transport importing main; not treated as a disconnected router graph.
3. Capability plugin discovery, declared uses_capabilities, owner task types and status hooks.
4. System capability registrations: opening, sessions, analysis, Mirror/research, memory, documents, research refresh/resume, roadmaps.mark_stale and operator.run.
5. Tool registry audiences/permissions, ctx.api HTTP calls and generic Operator's capability/tool selection.
6. Event factory/WorkspaceMod message handling and workflow/task hooks.
7. Worker CLI, named sweeps, Docker/Compose entry points and migration metadata registration.
8. Prompt allowlist/dynamic instruction names, playbook glob loading, JSON policy/coverage/lane data and qualification pack globs.
9. Next filesystem routes, shared view-mode mounts, TS alias/relative imports and public URL assets.

## Approval boundary and open questions

Counts below are grouped inventory rows, not individual files. The four OS-only frontend rows contain **nine files**. The OS-only config row covers **two UI flag names**. The four OS-only storage rows cover **six tables**, all retained for later migration review.

| Section | C-only | shared | shared-split-later | OS-only |
| --- | ---: | ---: | ---: | ---: |
| Backend modules/routes | 2 | 18 | 13 | 0 |
| Frontend | 1 | 4 | 12 | 4 |
| Storage | 2 | 8 | 4 | 4 |
| Config/templates/docs | 0 | 4 | 2 | 1 |
| Total (79 rows) | 5 | 34 | 31 | 9 |

1. Approve the isolated Applications, Deadlines, Workflows and Tasks UI candidates and their explicit mounts/navigation entries before any removal. Shared wrapper/API/context files themselves stay; no such edit has been performed.
2. The literal transitive keep rule currently prevents full backend OS removal. May a later scoped change detach Application Workspace/deadline routers and their main scheduler blocks while preserving the ASGI transport? This requires approving behavior removal, not just deleting unimported files. Until then those modules stay shared-split-later.
3. Does the OS developer want to retain C's generic tasks.list/tasks.create and workflow advancement contract? They are live/registered today; removal would be a contract change. No tool/plugin deletion is proposed.
4. Should browser UI remain for auth-required recovery, and should integration channels remain usable? Backend browser/relay functionality is currently shared. No answer is assumed.
5. Approve primary-thread/monitor/routine UI separation before deleting the mixed chat controls. An OS-only product label does not prove a component is unused by C's shell.
6. All six OS-only application/deadline tables above need data/retention/FK and OS-owner review later. This audit does not authorize a database drop or delete records.
7. Board section 12 calls the generic loop agent.run; the actual registered durable job is operator.run and its policy selects workflow or generic execution. No duplicate capability was introduced to match conceptual naming.

No code on dev or pai-os was changed. The existing pre-os-removal tag is preserved. No live model, embedding or research call was made. No student records or secret values were inspected.

## Checks relevant to this audit

- All 268 app modules imported under an offline, dotenv-disabled bootstrap; zero unresolved dynamic imports. The script reports no OS-eligible modules among its application/deadline/workflow candidate set.
- Nine architecture-boundary tests and two C–OS contract tests passed (11 total). They cover gateway ownership, Task Runtime registration, research delegation, Memory Service ownership, Messenger, Orchestrator, exact contract table names, rejected service tokens and valid escalation handling.
- Three production-only security cases passed separately (four subtests); these are the cases skipped in the development-mode full suites.
- Frontend: 32 tests across 11 files passed with one Vitest worker; production build passed. The initial unrestricted worker run had five worker-startup timeouts and only 18 executed tests; it was not counted as a passing suite. No source workaround was made.
- Full backend: 1240 passed, 3 production-only skips and 8 subtests in **each** policy mode, against the 1196-pass guided baseline. Details and the Phase 0 change record are in `SPINE.md`. No removal tests are claimed because no removal was performed.
