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
except ModuleNotFoundError:  # run as a plain script: scripts/ is on sys.path
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
)
WATCHED_PREFIXES = (
    "app.capabilities",
    "app.plugins",
    "app.jobs",
    "app.research",
    "app.documents",
    "app.deadlines",
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


# Decided later by the project owner. module name -> Fate.
FATES: dict[str, Fate] = {}


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


def _router_paths(file: Path) -> list[str]:
    """Static API paths (no leading slash) served by the routers in `file`."""
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
            full = prefixes[dec.func.value.id] + path
            static = full.split("{", 1)[0].rstrip("/").lstrip("/")
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
            api_paths = _router_paths(modules[name])
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
A Counsellor-used module cannot be retired without the Counsellor lead's sign-off in the PR.

Limits: reachability follows imports only, and stops at `app.main`. In-process HTTP calls (e.g. `app.services.pai` calling routes through the ASGI app) and frontend calls outside the watched routers are not traced, so those are checked by reading the code when fates are decided.

Only watched modules get a row: the PAI-relevant old-OS modules (operator, escalations, deadlines routers and services, capabilities, plugins, jobs, research, documents, deadlines). "Imported by" and reachability are computed over the whole import graph.

"Used by Counsellor" means a direct importer is a Counsellor root (a module under `app.pai_c` or a router named `app.routers.counselor*`). "Reachable from Counsellor" is transitive; "Counsellor path" is one shortest import chain from a root.
"""

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
    return "\n".join(lines) + "\n"


def main() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    print(render_markdown(build_inventory(app_root)), end="")


if __name__ == "__main__":
    main()
