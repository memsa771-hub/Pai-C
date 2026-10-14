"""Old-OS inventory: which old modules exist, who imports them, and whether the
Counsellor depends on them (directly or transitively).

Usage, from backend/:
    python scripts/os_inventory.py > ../docs/os/old-os-inventory.md
"""
import ast
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

try:
    from scripts.import_graph import graph
except ModuleNotFoundError as exc:  # run as a plain script: scripts/ is on sys.path
    if exc.name not in ("scripts", "scripts.import_graph"):
        raise
    from import_graph import graph

COUNSELLOR_ROOT_PREFIXES = ("app.pai_c",)
COUNSELLOR_ROUTER_PREFIX = "app.routers.counselor"

WATCHED_EXACT = (
    "app.services.operator",
    "app.routers.operator",
    "app.routers.escalations",
    "app.routers.deadlines",
    "app.tools.builtin.operator",
    "app.tools.builtin.capabilities",
    # Owner-approved scope additions (agent tools, task runtime, application workspace).
    "app.runtime.task_runtime",
    "app.routers.tasks",
    "app.tools.builtin.tasks",
    "app.routers.workflows",
    "app.services.workflow",
    "app.routers.timers",
    "app.routers.todos",
    "app.routers.browser",
    "app.tools.builtin.browser",
    "app.routers.application_workspace",
    "app.routers.routines",
)
WATCHED_PREFIXES = (
    "app.capabilities",
    "app.plugins",
    "app.jobs",
    "app.research",
    "app.documents",
    "app.deadlines",
    "app.browser",
    "app.application_workspace",
)

# app.main is the composition root and imports every router; following it would make everything "reachable".
REACHABILITY_STOPS = ("app.main",)

FATE_VALUES = ("keep", "read-only", "retire")

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
FRONTEND_SUFFIXES = (".ts", ".tsx")
FRONTEND_SKIP_DIRS = {"node_modules", ".next"}


@dataclass(frozen=True)
class Fate:
    fate: str
    replaced_by: str
    reason: str


KEPT_S2 = (
    " Kept: Slice 2 researches a fixed programme list into OS Knowledge and does not replace the "
    "Counsellor's per-student research; revisit when the Slice 8 spec decides whether the Counsellor reads OS Knowledge."
)
KEPT_S3 = " Kept: Slice 3 only partly replaces this for the Counsellor; revisit with the Slice 3 spec's Documents port."
SLICE1_DEADLINES = "Slice 1 (deadline engine + inbox reminders)"
SLICES_1_6 = "Slices 1 and 6 (deadlines/inbox, application pack)"
SLICES_1_6_TASKS = "Slices 1 and 6 (plan tasks + inbox, application pack)"
DEADLINES_REASON = (
    "A live Deadlines screen with in-app reminders that students use today; it stays running, frozen, "
    "until Slice 1 ships its replacement, then it is retired."
)
WORKSPACE_REASON = (
    "The live application tracker and its review routines; frozen until Slices 1 and 6 replace them, then retired."
)


def _entries(fate: str, replaced_by: str, items: dict[str, str], suffix: str = "") -> dict[str, Fate]:
    return {module: Fate(fate, replaced_by, reason + suffix) for module, reason in items.items()}


# Decided by the project owner and the controller (Task 4 step C). module name -> Fate.
FATES: dict[str, Fate] = {
    # --- keep: the Counsellor's durable job queue and capability registry ---
    **_entries("keep", "—", {
        "app.capabilities": "Its registry validates and dispatches every Counsellor background job, and no slice moves those jobs.",
        "app.capabilities.contract": "It is the record type for every Counsellor background job, so the queue cannot run without it.",
        "app.capabilities.manifest": "It checks every Counsellor job payload when the job is queued.",
        "app.capabilities.registry": "It is the lookup table that finds the handler for each Counsellor background job.",
        "app.capabilities.system": "It registers the Counsellor's background jobs (sessions, analysis, Mirror, memory and documents); its Operator and research entries go only if those modules are ever retired.",
        "app.jobs": "It is the Counsellor's durable background-job queue package, and no slice moves those jobs.",
        "app.jobs.service": "Every Counsellor background job is stored and claimed here; Slices 0 and 1 use a separate queue for the OS only.",
        "app.jobs.worker": "It is the production worker process that runs all Counsellor background jobs.",
        "app.runtime.task_runtime": "It enqueues and dispatches every Counsellor background job.",
    }),
    # --- keep: documents read/store path ---
    **_entries("keep", "—", {
        "app.documents": "Chat attachments enter the Counsellor's document pipeline through its upload type check, and no slice rebuilds that for the Counsellor.",
        "app.documents.attachments": "The Counsellor's turn uses it to normalise chat attachments.",
        "app.documents.content": "The Counsellor's memory recall rebuilds document passages with it, and Slice 3 does not cover Counsellor recall.",
        "app.documents.progress": "It gives the reading / understanding / done status shown in the Counsellor chat, which no slice builds.",
        "app.documents.reader": "It serves the document status and parsed-text endpoints used by the Counsellor chat.",
        "app.documents.retrieval": "The Counsellor's memory search over documents depends on it.",
        "app.documents.service": "It stores the parsed document artifacts that Counsellor recall reads and registers uploads.",
        "app.documents.types": "It detects upload types, and the kept document service depends on it.",
    }),
    # --- keep: documents ingest (controller ruling) ---
    **_entries("keep", "—", {
        "app.documents.classify": "It classifies uploaded documents for the Counsellor's profile and feeds the memory vault intake.",
        "app.documents.extractor": "It turns uploads into facts the Counsellor learns, feeding the profile and memory candidates.",
        "app.documents.handlers": "It runs the parse, extract, index and notify jobs behind Counsellor document understanding, including recall indexing and the \"I read your file\" chat notice.",
        "app.documents.ocr": "It reads scanned pages of Counsellor uploads so their content reaches the profile and memory.",
        "app.documents.parsers": "It extracts text from PDF and DOCX uploads before the Counsellor can learn from them.",
        "app.documents.untrusted": "It fences untrusted document text inside the extraction prompt, so it goes with the extractor.",
    }, KEPT_S3),
    # --- keep: Counsellor per-student roadmap research chain (owner decision) ---
    **_entries("keep", "—", {
        "app.capabilities.context": "It carries the student's scope into the Counsellor's per-student roadmap research.",
        "app.capabilities.execution_policy": "It sends the Counsellor's roadmap research runs down the fixed workflow path instead of the open-ended Operator loop.",
        "app.capabilities.loader": "It loads the research plugins that the Counsellor's per-student roadmap research needs.",
        "app.capabilities.permissions": "It grants the research plugins their permissions during the Counsellor's per-student roadmap research.",
        "app.capabilities.router": "It runs the roadmap plugin and its nested programme lookups for the Counsellor's per-student roadmap research.",
        "app.capabilities.tool_broker": "It is the only path from the research plugins to web search and fetch in the Counsellor's per-student roadmap research.",
        "app.plugins": "It is the home of the research plugins that the Counsellor's per-student roadmap research loads.",
        "app.plugins._shared": "Its children are used directly by the Counsellor's per-student roadmap research and by Counsellor code.",
        "app.plugins._shared.budget": "It enforces the per-student research spending limit during the Counsellor's roadmap research.",
        "app.plugins._shared.institution_registry": "It confirms official university domains for the Counsellor's per-student roadmap research.",
        "app.plugins._shared.sources": "It checks source URLs in the Counsellor's per-student roadmap research, and Counsellor code calls it directly.",
        "app.plugins._shared.verification": "It decides which facts count as verified on the Counsellor's per-student roadmaps.",
        "app.plugins.program_discovery": "It finds candidate programme pages for each lane of the Counsellor's per-student roadmap.",
        "app.plugins.program_research": "It extracts cited admission, fee and deadline facts for the Counsellor's per-student roadmaps.",
        "app.plugins.roadmap_builder": "It is the Counsellor's per-student roadmap-research workflow, publishing roadmap cards and moving the student's stage.",
        "app.research": "Its modules run the Counsellor's per-student roadmap research.",
        "app.research.gateway": "It is the single entry point for the Counsellor's per-student roadmap research and its is-the-Mirror-current check.",
        "app.research.jobs": "It resumes the Counsellor's per-student roadmap research after each accepted fact and advances the discovery stage.",
        "app.research.light": "It collects the cited facts behind each lane of the Counsellor's per-student roadmap.",
        "app.research.requirements": "It stores the cited facts that the Counsellor's per-student roadmaps display.",
        "app.research.scheduler": "It marks the Counsellor's per-student roadmap facts stale when evidence ages out, and the OS freshness sweeper (Slice 1) covers only OS Knowledge.",
        "app.routers.operator": "It feeds the \"PAI is researching\" status on Counsellor screens while per-student roadmap research runs.",
        "app.services.operator": "It runs, resumes and reports every Counsellor per-student roadmap research run.",
        "app.tools.builtin.capabilities": "It is the tool that starts the roadmap plugin for each Counsellor per-student research run.",
        "app.tools.builtin.operator": "It is the hand-off tool that the Counsellor's research gateway uses to start a per-student research run.",
    }, KEPT_S2),
    # --- read-only: live screens until Slice 1 / 6 ship ---
    **_entries("read-only", SLICE1_DEADLINES, {
        "app.deadlines": DEADLINES_REASON,
        "app.deadlines.service": DEADLINES_REASON,
        "app.routers.deadlines": DEADLINES_REASON,
    }),
    **_entries("read-only", SLICES_1_6, {
        "app.application_workspace": WORKSPACE_REASON,
        "app.application_workspace.access": WORKSPACE_REASON,
        "app.application_workspace.calendar": WORKSPACE_REASON,
        "app.application_workspace.catalog": WORKSPACE_REASON,
        "app.application_workspace.context": WORKSPACE_REASON,
        "app.application_workspace.operations": WORKSPACE_REASON,
        "app.application_workspace.plans": WORKSPACE_REASON,
        "app.application_workspace.queries": WORKSPACE_REASON,
        "app.application_workspace.schemas": WORKSPACE_REASON,
        "app.application_workspace.serializers": WORKSPACE_REASON,
        "app.routers.application_workspace": WORKSPACE_REASON,
        "app.routers.routines": WORKSPACE_REASON,
    }),
    # --- retire: old-OS only, with notes on what to salvage first ---
    "app.plugins._shared.costs": Fate("retire", "—", "A test-only fee helper that nothing in the running app calls."),
    "app.plugins.scholarship_discovery": Fate("retire", "—", "No v1 slice builds scholarship listing and nothing calls it."),
    "app.routers.escalations": Fate("retire", "Slice 8 EscalationSink (outside slices 0–7)", "Nothing calls it today; it is a tested intake the Slice 8 adapter may reuse from git history, and it is retired only after the pilot."),
    "app.plugins.qualification_recognition": Fate("retire", "Slice 1 playbook (data only)", "Registered but never called; its sourced packs (DAAD, uni-assist, HEC attestation, APS, with official URLs) must be copied into the Slice 1 Germany playbook/Knowledge before deletion."),
    "app.plugins.gap_assessment": Fate("retire", "—", "Registered but never called; its meets / does-not-meet / unknown logic is a reference for the Slice 1 eligibility checks."),
    # --- read-only: workflow and task features driven by the live application workspace ---
    **_entries("read-only", SLICES_1_6_TASKS, {
        "app.routers.tasks": "The live application workspace links requirements to these tasks (`application_workspace/operations.py`, `calendar.py`, `serializers.py`) and the deadlines service reads them, so it is frozen until those features are replaced, then retired with them.",
        "app.routers.workflows": "The application workspace and workflow-bound threads drive workflows, and `advance_workflow` runs after every event, including Counsellor replies, as a no-op without an active run, so it is frozen until Slices 1 and 6 replace the application workspace, then retired.",
        "app.services.workflow": "The application workspace and workflow-bound threads drive workflows, and `advance_workflow` runs after every event, including Counsellor replies, as a no-op without an active run, so it is frozen until Slices 1 and 6 replace the application workspace, then retired.",
    }),
    # --- keep: browser rendering behind POST /v1/fetch, used by the kept Counsellor research (checked by hand) ---
    **_entries("keep", "—", {
        "app.browser": "The package for the kept browser manager that renders pages for the Counsellor's research fetches.",
        "app.browser.manager": "It renders JavaScript-heavy pages for `POST /v1/fetch` (`routers/fetch.py:36`), which is how the kept Counsellor research (`program_research` via tool `web.fetch`) reads university pages; this use goes over HTTP, so the import graph cannot see it.",
        "app.browser.egress": "It is the network egress filter inside the kept browser manager that renders pages for `POST /v1/fetch`, which the Counsellor's research uses to read university pages.",
        "app.browser.credentials": "Its `redact` helper is used by the kept browser manager that renders pages for `POST /v1/fetch`, which the Counsellor's research uses; the stored-credential flows are not needed for research.",
        "app.browser.maintenance": "It sweeps leaked browser sessions and tabs for the kept browser manager (`main.py` browser sweep).",
        "app.routers.browser": "`/v1/fetch` imports its `_resolve_bf_key` (`routers/fetch.py:45`), so it stays for the Counsellor's research fetches; only that helper and the ephemeral render path are needed, so the interactive tab endpoints and credential flows are candidates to split out and switch off.",
    }),
    # --- retire: agent tools with no Counsellor function ---
    "app.tools.builtin.browser": Fate("retire", "—", "Operator-only interactive tab control; research uses `web.fetch`, not `browser.*`, and the spec forbids agent login/credential tools (invariant 6, §10)."),
    "app.tools.builtin.tasks": Fate("retire", "—", "An agent tool for the Operator's general loop; it is listed in `PAI_ALLOWED_TOOLS`, but the deep Counsellor never calls tools (`services/pai.py:52-54`) and every Counsellor caller narrows the allowed tools to `operator.delegate`."),
    "app.routers.timers": Fate("retire", "—", "Agent planning endpoints that nothing in the backend creates and the Counsellor never does; Counsellor screens only poll the always-empty list, and no slice builds agent timers because the Slice 1 scheduler covers timed work."),
    "app.routers.todos": Fate("retire", "—", "Agent planning endpoints that nothing in the backend creates and the Counsellor never does; Counsellor screens only poll the always-empty list, and no slice builds agent to-dos because the Slice 1 scheduler covers timed work."),
}


# Retire fates that touch Counsellor code or screens. Signed off 2026-10-14 (see render_markdown).
# module -> how it touches the Counsellor.
COUNSELLOR_TOUCHING_RETIRES: dict[str, str] = {
    "app.tools.builtin.tasks": "`tasks.list` is in the Counsellor's allowed-tool list and the tool is in the shared registry",
    "app.routers.timers": "polled by the Counsellor chat status bar",
    "app.routers.todos": "polled and cancelled by the Counsellor chat status bar",
}


@dataclass
class InventoryRow:
    module: str
    imported_by: list[str]
    used_by_counsellor: bool
    fate: str = ""
    reachable_from_counsellor: bool = False
    counsellor_path: list[str] = field(default_factory=list)
    frontend_calls: list[str] = field(default_factory=list)
    replaced_by: str = ""
    reason: str = ""


def _has_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def is_watched(module: str) -> bool:
    return module in WATCHED_EXACT or any(_has_prefix(module, p) for p in WATCHED_PREFIXES)


def is_counsellor_root(module: str) -> bool:
    return any(_has_prefix(module, p) for p in COUNSELLOR_ROOT_PREFIXES) or module.startswith(
        COUNSELLOR_ROUTER_PREFIX
    )


def _is_watched_router(module: str) -> bool:
    return module.startswith("app.routers.") and is_watched(module)


def _counsellor_paths(edges: dict[str, set[str]], roots: list[str]) -> dict[str, list[str]]:
    """Shortest import chain from any root to each reachable module (BFS)."""
    parent: dict[str, str | None] = {r: None for r in roots}
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in REACHABILITY_STOPS:
            continue  # reachable itself, but its imports are not followed
        for nxt in sorted(edges.get(current, ())):
            if nxt not in parent:
                parent[nxt] = current
                queue.append(nxt)
    paths: dict[str, list[str]] = {}
    for module in parent:
        chain = [module]
        while parent[chain[-1]] is not None:
            chain.append(parent[chain[-1]])
        paths[module] = chain[::-1]
    return paths


def _static_path(full: str) -> str:
    """Static part before the first `{`, without leading or trailing `/`."""
    return full.split("{", 1)[0].rstrip("/").lstrip("/")


def _router_paths(file: Path, modules: dict[str, Path] | None = None, name: str = "", follow: bool = True) -> list[str]:
    """Static API paths (no leading slash) served by the routers in `file`.

    If the file defines no APIRouter but imports `router` from another app module, that module is read
    instead (one level only).
    """
    tree = ast.parse(file.read_text(encoding="utf-8-sig"))
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", getattr(node.value.func, "attr", None)) == "APIRouter"
        ):
            prefix = ""
            for kw in node.value.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    prefix = kw.value.value
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix
    found: set[str] = set()
    if not prefixes and follow and modules is not None:
        package = name.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == "router" for a in node.names):
                target = node.module or ""
                if node.level:
                    parts = package.split(".")
                    target = ".".join(parts[: len(parts) - node.level + 1] + ([target] if target else []))
                if target in modules and modules[target] != file:
                    found.update(_router_paths(modules[target], modules, target, follow=False))
    for prefix in prefixes.values():
        static = _static_path(prefix)
        if static and static != "v1":
            found.add(static)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in HTTP_METHODS
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id in prefixes
            ):
                continue
            path = None
            if dec.args and isinstance(dec.args[0], ast.Constant):
                path = dec.args[0].value
            else:
                for kw in dec.keywords:
                    if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                        path = kw.value.value
            if not isinstance(path, str):
                continue
            static = _static_path(prefixes[dec.func.value.id] + path)
            if static and static != "v1":
                found.add(static)
    return sorted(found)


def _frontend_files(frontend: Path) -> dict[str, str]:
    """repo-relative posix path -> text, for .ts/.tsx files outside node_modules/.next."""
    files: dict[str, str] = {}
    repo = frontend.parent
    for dirpath, dirnames, filenames in os.walk(frontend):
        dirnames[:] = sorted(d for d in dirnames if d not in FRONTEND_SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(FRONTEND_SUFFIXES):
                path = Path(dirpath) / name
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                files[path.relative_to(repo).as_posix()] = text
    return files


def build_inventory(app_root: Path) -> list[InventoryRow]:
    app_root = app_root.resolve()
    modules, edges, _ = graph(app_root)
    importers: dict[str, set[str]] = {name: set() for name in modules}
    for source, targets in edges.items():
        for target in targets:
            if target != source:  # package __init__ gets a self-edge from its parent link
                importers[target].add(source)

    roots = sorted(m for m in modules if is_counsellor_root(m))
    paths = _counsellor_paths(edges, roots)

    frontend = app_root.parent.parent / "frontend"
    frontend_files: dict[str, str] | None = None

    rows: list[InventoryRow] = []
    for name in sorted(m for m in modules if is_watched(m)):
        imported_by = sorted(importers[name])
        row = InventoryRow(
            module=name,
            imported_by=imported_by,
            used_by_counsellor=any(is_counsellor_root(i) for i in imported_by),
            reachable_from_counsellor=name in paths,
            counsellor_path=paths.get(name, []),
        )
        if _is_watched_router(name) and frontend.is_dir():
            if frontend_files is None:
                frontend_files = _frontend_files(frontend)
            api_paths = _router_paths(modules[name], modules, name)
            row.frontend_calls = sorted(
                rel for rel, text in frontend_files.items() if any(p in text for p in api_paths)
            )
        fate = FATES.get(name)
        if fate is not None:
            row.fate, row.replaced_by, row.reason = fate.fate, fate.replaced_by, fate.reason
        rows.append(row)
    return rows


INTRO = """\
Generated by `backend/scripts/os_inventory.py`. Do not edit by hand: regenerate with
`python scripts/os_inventory.py > ../docs/os/old-os-inventory.md` from `backend/`.
Fates live in `FATES` in that script.

## How fates are decided

> Keep a module only if it is important for PAI. If a module is used by the Counsellor (directly or indirectly): if a PAI OS slice 0–7 builds the same thing, it is read-only until that slice ships, then retired; if no slice builds it and it is necessary, keep it. Modules used only by the old OS are retired, unless they are really important (the owner decides those).

Retire means switched off and deleted later, after the pilot, each removal in its own PR. Nothing is deleted by this inventory.
A Counsellor-used module cannot be retired without the Counsellor lead's sign-off in the PR. Sign-offs already given are recorded under "Retires that touch Counsellor code or screens" below the table.

Limits: reachability follows imports only, and stops at `app.main`. In-process HTTP calls (e.g. `app.services.pai` calling routes through the ASGI app) and frontend calls outside the watched routers are not traced, so those are checked by reading the code when fates are decided. Tool-mediated HTTP use (agent tools calling backend routes) is not traced by imports either; for the kept research path this was checked by hand on 2026-10-14: it only invokes `web.fetch`, `web.search` and `web.institution_registry`, and `web.fetch` → `/v1/fetch` → `app.browser.manager` is why the browser modules are kept. Frontend matching is also blind to `include_router(prefix=...)`, `api_route` / `add_api_route` and annotated `router: APIRouter = ...` assignments (not traced); the Frontend calls column names the file holding the URL (usually `frontend/lib/api.ts`), not the screens that call it; and a match can come from a comment.

Only watched modules get a row (the `WATCHED_*` constants in the script). "Imported by" and reachability are computed over the whole import graph.

"Used by Counsellor" means a direct importer is a Counsellor root (a module under `app.pai_c` or a router named `app.routers.counselor*`). "Reachable from Counsellor" is transitive; "Counsellor path" is one shortest import chain from a root.
"""

PRESERVE_NOTES = (
    "`application_workspace/plans.py:111,171,191` (old OS, read-only) imports `deadlines.service.expire_deadline_notices` (read-only): retire the two together, or move that helper first.",
    "`main.py:110-111` runs the hourly deadlines sweep (`sweep_due_notices`): switch it off only when Slice 1 reminders are live.",
    "`deadlines.service` and `application_workspace` read the `KanbanTask` model: do not drop it when the tasks router and tool are retired.",
    "`PAI_ALLOWED_TOOLS` in `services/pai.py:59` lists `tasks.list` and is guarded by `TestToolBoundary` in `tests/test_pai.py`: remove the entry and update the test together with `tools/builtin/tasks.py`.",
    "`pai_c/posting.py:224-237` calls `advance_workflow` from `app.services.workflow` after every reply; it is a no-op without an active workflow run (known incidental hook). Remove the call before retiring `app.services.workflow`; `services/integrations.py:237`, `routers/events.py:392`, `routers/workspaces.py:625` (`get_active_run`, `start_run`) and `routers/tasks.py:256,473,505,717` also use the workflow service.",
    "`main.py:114-373` `_fire_due` fires timers and routines and imports `routers.routines` (line 127): change it before retiring the timers router or moving routines.",
    "`tools/builtin/__init__.py:3,36,51,53-61` imports and registers the `tasks.*` and `browser.*` tools: remove the registrations with the tool modules (`tools/builtin/tasks.py` and `browser.py`).",
    "Counsellor chat renders `ThreadStatusBar` for every session (`frontend/components/chat/chat-view.tsx:983,1000`); it polls `/v1/timers` every 15 seconds (`thread-status-bar.tsx:34-46`) and calls `cancelChannelTodos` on `/v1/todos` (`thread-status-bar.tsx:106`): remove that polling and cancelling before the timers and todos routers go.",
    "`frontend/lib/workspace-context.tsx:797-804` and `:1245-1250` fetch tasks, workflows, routines, todos and browser tabs on every screen: remove the todos fetch before the todos router goes, and the tasks, workflows and routines fetches only when the application workspace group retires.",
    "Split candidate: the interactive shared-tab endpoints and credential flows in `routers/browser.py` and `app.browser.credentials` are not needed by `/v1/fetch`, so they can be switched off in a dedicated PR once `_resolve_bf_key` and the render path are isolated.",
    "A \"Browser\" nav item exists (`frontend/components/layout/workspace-navigation.tsx:52-54`): check student use before switching off the interactive browser endpoints.",
    "`frontend/components/applications/application-operations.tsx:30,36` (read-only application workspace) calls `/v1/tasks` and `/v1/workflows`: the tasks and workflows routers and the workflow service are read-only and retire together with the application workspace group, not before.",
    "`plugins/roadmap_builder/__init__.py:5-8` `DEPENDENCIES` names `qualification.recognize`, `scholarship.discover` and `gap.assess`: remove those names before deleting the three plugins.",
    "`app.plugins.qualification_recognition` packs (`packs/de.json`, `pk.json`, `uk.json`: DAAD, uni-assist, HEC attestation, APS, with official URLs) must be copied into the Slice 1 Germany playbook/Knowledge before the plugin is deleted.",
    "`app.plugins.gap_assessment` meets / does-not-meet / unknown logic is a reference for the Slice 1 eligibility checks: read it before deleting.",
    "`routers/escalations.py:109-116` needs `PAI_OS_SERVICE_TOKEN`: the Slice 8 EscalationSink adapter may reuse this tested intake (`tests/test_counselor_escalations.py`) from git history.",
)

HEADER = (
    "| Module | Imported by | Used by Counsellor | Fate (keep / read-only / retire) "
    "| Reachable from Counsellor | Counsellor path | Frontend calls | Replaced by slice | Reason |"
)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ") or "—"


def _join(items: list[str], sep: str = ", ") -> str:
    return _cell(sep.join(items)) if items else "—"


def _yn(value: bool) -> str:
    return "yes" if value else "no"


def render_markdown(rows: list[InventoryRow]) -> str:
    counts = {f: sum(1 for r in rows if r.fate == f) for f in FATE_VALUES}
    undecided = sum(1 for r in rows if r.fate not in FATE_VALUES)
    summary = ", ".join(f"{f}: {n}" for f, n in counts.items()) + f", undecided: {undecided}"
    lines = [
        "# Old OS inventory",
        "",
        INTRO,
        f"Summary ({len(rows)} modules): {summary}.",
        "",
        HEADER,
        "|" + "---|" * 9,
    ]
    for r in rows:
        cells = [
            f"`{r.module}`",
            _join(r.imported_by),
            _yn(r.used_by_counsellor),
            _cell(r.fate),
            _yn(r.reachable_from_counsellor),
            _join(r.counsellor_path, " → "),
            _join(r.frontend_calls),
            _cell(r.replaced_by),
            _cell(r.reason),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Retires that touch Counsellor code or screens", ""]
    lines += [
        "Signed off 2026-10-14: the Counsellor lead delegated sign-off to the project owner, who delegated these decisions to Claude; each row's reason gives the rationale.",
        "",
    ]
    lines += [f"- `{module}`: {why}." for module, why in COUNSELLOR_TOUCHING_RETIRES.items()]
    lines += ["", "## Before retiring anything", ""]
    lines += [f"- {note}" for note in PRESERVE_NOTES]
    return "\n".join(lines) + "\n"


def main() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    print(render_markdown(build_inventory(app_root)), end="")


if __name__ == "__main__":
    main()
