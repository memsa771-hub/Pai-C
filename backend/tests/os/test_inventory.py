from pathlib import Path

from scripts import os_inventory
from scripts.os_inventory import (
    FATE_VALUES,
    FATES,
    Fate,
    COUNSELLOR_TOUCHING_RETIRES,
    InventoryRow,
    build_inventory,
    render_markdown,
)

APP = Path(__file__).resolve().parents[2] / "app"


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _synthetic_app(tmp_path: Path) -> Path:
    app = tmp_path / "backend" / "app"
    _write(app / "__init__.py")
    return app


def test_inventory_lists_operator_service_with_importers():
    rows = {r.module: r for r in build_inventory(APP)}
    assert "app.routers.operator" in rows["app.services.operator"].imported_by
    md = render_markdown(list(rows.values()))
    assert "Module | Imported by | Used by Counsellor | Fate (keep / read-only / retire)" in md


def test_fate_values_fixed():
    assert FATE_VALUES == ("keep", "read-only", "retire")


def test_rows_sorted_and_defaults():
    rows = build_inventory(APP)
    names = [r.module for r in rows]
    assert names == sorted(names)
    assert all(r.imported_by == sorted(r.imported_by) for r in rows)
    row = InventoryRow(module="m", imported_by=[], used_by_counsellor=False)
    assert row.fate == "" and row.reachable_from_counsellor is False
    assert row.counsellor_path == [] and row.frontend_calls == []
    assert row.replaced_by == "" and row.reason == ""


def test_counsellor_reachability_is_transitive(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(app / "pai_c" / "__init__.py", "from app.memory import x\n")
    _write(app / "memory" / "__init__.py")
    _write(app / "memory" / "x.py", "from app.documents import y\n")
    _write(app / "documents" / "__init__.py")
    _write(app / "documents" / "y.py")
    _write(app / "documents" / "orphan.py")
    rows = {r.module: r for r in build_inventory(app)}
    y = rows["app.documents.y"]
    assert y.used_by_counsellor is False
    assert y.reachable_from_counsellor is True
    assert y.counsellor_path[0].startswith("app.pai_c")
    assert y.counsellor_path[-1] == "app.documents.y"
    orphan = rows["app.documents.orphan"]
    assert orphan.reachable_from_counsellor is False
    assert orphan.counsellor_path == []
    assert orphan.used_by_counsellor is False


def test_only_watched_modules_get_rows(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(app / "pai_c" / "__init__.py", "from app.memory import x\n")
    _write(app / "memory" / "__init__.py")
    _write(app / "memory" / "x.py", "from app.documents import y\n")
    _write(app / "documents" / "__init__.py")
    _write(app / "documents" / "y.py")
    _write(app / "deadlines_x.py")
    rows = {r.module: r for r in build_inventory(app)}
    assert "app.documents.y" in rows
    assert "app.memory.x" not in rows and "app.pai_c" not in rows
    assert "app.deadlines_x" not in rows and "app" not in rows
    # imported_by still comes from the whole graph, including unwatched importers
    assert rows["app.documents.y"].imported_by == ["app.memory.x"]


def test_reachability_stops_at_app_main(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(app / "pai_c" / "__init__.py", "from app import main\n")
    _write(app / "main.py", "from app.documents import z\n")
    _write(app / "documents" / "__init__.py")
    _write(app / "documents" / "z.py")
    rows = {r.module: r for r in build_inventory(app)}
    assert rows["app.documents.z"].used_by_counsellor is False
    assert rows["app.documents.z"].reachable_from_counsellor is False
    assert rows["app.documents.z"].counsellor_path == []
    assert "app.main" in os_inventory.REACHABILITY_STOPS


def test_counselor_router_is_a_root(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(app / "routers" / "__init__.py")
    _write(app / "routers" / "counselor_chat.py", "from app.documents import helper\n")
    _write(app / "documents" / "__init__.py")
    _write(app / "documents" / "helper.py")
    rows = {r.module: r for r in build_inventory(app)}
    assert rows["app.documents.helper"].used_by_counsellor is True


def test_frontend_calls_for_watched_router(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(app / "routers" / "__init__.py")
    _write(
        app / "routers" / "deadlines.py",
        "from fastapi import APIRouter\n"
        'router = APIRouter(prefix="/v1/deadlines")\n\n'
        '@router.get("/{deadline_id}")\n'
        "def get_one(deadline_id): ...\n",
    )
    _write(app / "routers" / "other.py", "from fastapi import APIRouter\nrouter = APIRouter(prefix='/v1/other')\n")
    _write(tmp_path / "frontend" / "lib" / "api.ts", "fetch(`${API}/v1/deadlines/${id}`)\n")
    _write(tmp_path / "frontend" / "node_modules" / "x" / "skip.ts", "v1/deadlines")
    rows = {r.module: r for r in build_inventory(app)}
    assert rows["app.routers.deadlines"].frontend_calls == ["frontend/lib/api.ts"]
    assert "app.routers.other" not in rows


def test_frontend_missing_and_bare_v1(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(app / "routers" / "__init__.py")
    _write(
        app / "routers" / "operator.py",
        "from fastapi import APIRouter\n"
        'router = APIRouter(prefix="/v1")\n\n'
        '@router.get("")\n'
        "def root(): ...\n",
    )
    rows = {r.module: r for r in build_inventory(app)}
    assert rows["app.routers.operator"].frontend_calls == []
    _write(tmp_path / "frontend" / "a.ts", "const u = `${API}/v1/anything`\n")
    rows = {r.module: r for r in build_inventory(app)}
    assert rows["app.routers.operator"].frontend_calls == []


def test_prefix_group_does_not_match_lookalike():
    assert os_inventory.is_watched("app.deadlines")
    assert os_inventory.is_watched("app.deadlines.sub")
    assert not os_inventory.is_watched("app.deadlines_x")
    assert os_inventory.is_watched("app.routers.deadlines")
    assert not os_inventory.is_watched("app.routers.files")


def test_fates_are_copied(tmp_path, monkeypatch):
    app = _synthetic_app(tmp_path)
    _write(app / "documents" / "thing.py")
    monkeypatch.setitem(os_inventory.FATES, "app.documents.thing", Fate("retire", "slice 3", "old only"))
    rows = {r.module: r for r in build_inventory(app)}
    assert (rows["app.documents.thing"].fate, rows["app.documents.thing"].replaced_by, rows["app.documents.thing"].reason) == (
        "retire",
        "slice 3",
        "old only",
    )


def test_render_formats_cells():
    rows = [
        InventoryRow(
            module="app.a",
            imported_by=["app.b", "app.c"],
            used_by_counsellor=True,
            reachable_from_counsellor=True,
            counsellor_path=["app.pai_c", "app.a"],
            reason="a | b",
        ),
        InventoryRow(module="app.z", imported_by=[], used_by_counsellor=False, fate="retire"),
    ]
    md = render_markdown(rows)
    assert md.startswith("# Old OS inventory")
    assert "| Module | Imported by | Used by Counsellor | Fate (keep / read-only / retire) | Reachable from Counsellor | Counsellor path | Frontend calls | Replaced by slice | Reason |" in md
    assert "app.b, app.c" in md
    assert "app.pai_c → app.a" in md
    assert "a \\| b" in md
    assert "yes" in md and "no" in md and "—" in md
    assert "Keep a module only if it is important for PAI." in md
    assert "retire: 1" in md and "undecided: 1" in md


def test_every_row_has_a_fate_and_reason():
    """Slice 0 gate: fate for every row."""
    rows = build_inventory(APP)
    missing = [r.module for r in rows if r.fate not in FATE_VALUES or not r.reason.strip()]
    assert missing == []


def test_counsellor_used_retires_are_listed_as_signed_off():
    """Plan rule: retiring a Counsellor-used module needs the Counsellor lead's sign-off in the PR."""
    rows = {r.module: r for r in build_inventory(APP)}
    used_retires = {m for m, r in rows.items() if r.used_by_counsellor and r.fate == "retire"}
    assert used_retires <= set(COUNSELLOR_TOUCHING_RETIRES)


def test_touching_retires_members_are_retire_rows():
    rows = {r.module: r for r in build_inventory(APP)}
    for module in COUNSELLOR_TOUCHING_RETIRES:
        assert rows[module].fate == "retire", module


def test_every_fates_key_is_a_real_row():
    modules = {r.module for r in build_inventory(APP)}
    assert sorted(set(FATES) - modules) == []


def test_render_includes_preserve_notes_after_table():
    md = render_markdown(build_inventory(APP))
    assert md.index("## Before retiring anything") > md.index("| `app.services.operator` |")
    assert "advance_workflow" in md


def test_signoff_section_precedes_preserve_notes():
    md = render_markdown(build_inventory(APP))
    heading = "## Retires that touch Counsellor code or screens"
    assert md.index(heading) < md.index("## Before retiring anything")
    assert "Signed off 2026-10-14" in md.split(heading)[1]
    assert "app.routers.timers" in md.split(heading)[1]


def test_frontend_calls_follow_one_level_reexport(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(app / "routers" / "__init__.py")
    _write(app / "routers" / "application_workspace.py", "from app.application_workspace import router\n")
    _write(
        app / "application_workspace" / "__init__.py",
        "from fastapi import APIRouter\n"
        'router = APIRouter(prefix="/v1/application-workspace")\n\n'
        '@router.get("/plans/{plan_id}")\n'
        "def get_plan(plan_id): ...\n",
    )
    _write(tmp_path / "frontend" / "lib" / "api.ts", "fetch(`${API}/v1/application-workspace/plans/${id}`)\n")
    rows = {r.module: r for r in build_inventory(app)}
    assert rows["app.routers.application_workspace"].frontend_calls == ["frontend/lib/api.ts"]


def test_router_prefix_alone_is_searchable(tmp_path):
    app = _synthetic_app(tmp_path)
    _write(
        app / "routers" / "escalations.py",
        "from fastapi import APIRouter\n"
        'router = APIRouter(prefix="/v1/escalations")\n',
    )
    _write(tmp_path / "frontend" / "x.ts", "get('/v1/escalations')\n")
    rows = {r.module: r for r in build_inventory(app)}
    assert rows["app.routers.escalations"].frontend_calls == ["frontend/x.ts"]


def test_committed_inventory_matches_generator():
    committed = (APP.parent.parent / "docs" / "os" / "old-os-inventory.md").read_text(encoding="utf-8")
    assert render_markdown(build_inventory(APP)) == committed, (
        "docs/os/old-os-inventory.md is stale: regenerate with "
        "`python scripts/os_inventory.py > ../docs/os/old-os-inventory.md` from backend/"
    )
