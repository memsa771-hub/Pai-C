"""P1-T10 Task B1 (R-04): every P1 row of master section 6 has a scripted test, and no test claims a row P1 does not
test. A test says which rows it proves with `@pytest.mark.connect_row("6.1", ...)`. The marks are read from the source
(no import, no database), so this runs in every job.

P1 rows: 6.1-6.9, 6.11-6.19, 6.21, 6.22. Not P1: 6.10 (Knowledge changes), 6.20 (the result-expected step is only
exercised as a mechanism inside the T8 flow), 6.23-6.25 (later phases). The marks sit on the scripted flows
of T3-T9 and on `test_connect_p1_rows.py`."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("R-04")

ROOT = Path(__file__).parent
P1_ROWS = {f"6.{n}" for n in (*range(1, 10), *range(11, 20), 21, 22)}
NOT_P1 = {"6.10", "6.20", "6.23", "6.24", "6.25"}



def _marks(node) -> set[str]:
    """The rows named by `connect_row(...)` in a decorator list or a `pytestmark` value."""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and getattr(sub.func, "attr", None) == "connect_row":
            found |= {a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return found


def marked() -> dict[str, list[str]]:
    """Row -> the `file::test` nodes that carry the mark, across tests/os and tests."""
    rows: dict[str, list[str]] = {}
    for path in sorted([*ROOT.glob("test_*.py"), *ROOT.parent.glob("test_*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        module = set()
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in stmt.targets):
                module = _marks(stmt.value)
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name.startswith("test"):
                for row in module | {r for d in fn.decorator_list for r in _marks(d)}:
                    rows.setdefault(row, []).append(f"{path.name}::{fn.name}")
    return rows


def node_exists(node: str) -> bool:
    """A `file::test` node of a marked test, in tests/os or in tests (the same two places `marked` reads)."""
    name, _, test = node.partition("::")
    path = next((d / name for d in (ROOT, ROOT.parent) if (d / name).exists()), None)
    if path is None:
        return False
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return any(isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == test for f in ast.walk(tree))


def test_every_p1_row_of_master_section_6_has_a_test():
    have = marked()
    missing = sorted(r for r in P1_ROWS if not have.get(r))
    assert missing == [], f"rows without a test: {missing}"


def test_no_test_claims_a_row_p1_does_not_test():
    assert sorted(set(marked()) - P1_ROWS) == []
    assert not NOT_P1 & set(marked())


def test_every_marked_node_resolves_to_a_test():
    gone = [n for nodes in marked().values() for n in nodes if not node_exists(n)]
    assert gone == [], f"marked tests that cannot be found: {gone}"


def test_the_new_row_tests_are_the_ones_the_index_counts():
    have = marked()
    for row in ("6.1", "6.2", "6.3", "6.4", "6.11"):
        assert any(n.startswith("test_connect_p1_rows.py::") for n in have[row])
    assert any(n.startswith("test_connect_p1_rows.py::") for n in have["6.18"])
    assert len([n for n in have["6.9"] if n.startswith("test_connect_p1_rows.py::")]) >= 4
