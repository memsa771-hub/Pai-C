"""Fitness checks for invariants 1 (kernel is the sole writer), 11 (no provider SDK outside Pydantic AI) and 12
(nothing country-specific in code)."""

import ast
import re
from pathlib import Path

import pytest

APP_OS = Path(__file__).resolve().parents[2] / "app" / "os"
PLAN_TABLES = ("plans", "tasks", "task_edges", "plan_revisions")
_CORE = re.compile(r"\b(insert|update|delete)\(\s*(?:models\.)?(" + "|".join(PLAN_TABLES) + r")\b")
_SQL = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:os\.)?os_(" + "|".join(PLAN_TABLES) + r")\b", re.I)

COUNTRY_TERMS = re.compile(
    r"\b(Germany|German|Pakistan|Pakistani|Ireland|Irish|DAAD|HEC|IBCC|uni[-_]assist|EUR|PKR|Berlin|Karachi|"
    r"Islamabad|PK|DE|IE|Punjab|Sindh|Khyber|Pakhtunkhwa|Balochistan|Kashmir|Gilgit|Baltistan|MDCAT|ECAT|PMDC|UHS|"
    r"Lahore|Peshawar|Quetta|Rawalpindi)\b"
)


def kernel_write_violations(root: Path) -> list[str]:
    found = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("kernel/") or rel == "models.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _CORE.search(line) or _SQL.search(line):
                found.append(f"{rel}:{n}: {line.strip()}")
    return found


def test_only_kernel_writes_plan_tables():
    assert kernel_write_violations(APP_OS) == []


def test_write_check_catches_a_violation(tmp_path):
    (tmp_path / "workers").mkdir()
    (tmp_path / "workers" / "bad.py").write_text("conn.execute(update(models.tasks).values(state='done'))\n")
    (tmp_path / "kernel").mkdir()
    (tmp_path / "kernel" / "ok.py").write_text("conn.execute(update(models.tasks).values(state='done'))\n")
    assert [v.split(":")[0] for v in kernel_write_violations(tmp_path)] == ["workers/bad.py"]


def provider_sdk_imports(root: Path) -> list[str]:
    """Imports of a model provider's SDK (the Counsellor's legacy guard, test_model_gateway.py, bans them outside
    app/inference). The OS reaches models only through Pydantic AI (invariant 11)."""
    found = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + (["openai"] if any(a.name == "AsyncOpenAI" for a in node.names) else [])
            if any(n == "openai" or n.startswith("openai.") or n.startswith("app.inference") for n in names):
                found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    return found


def test_no_provider_sdk_imports():
    assert provider_sdk_imports(APP_OS) == []


def test_provider_sdk_check_catches_a_violation(tmp_path):
    (tmp_path / "a.py").write_text("from openai import AsyncOpenAI\n")
    (tmp_path / "b.py").write_text("from pydantic_ai.providers.openai import OpenAIProvider\n")
    assert provider_sdk_imports(tmp_path) == ["a.py:1"]


@pytest.mark.req("R-58")
def test_no_country_terms_in_python():
    hits = []
    for path in APP_OS.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if COUNTRY_TERMS.search(line):
                hits.append(f"{path.relative_to(APP_OS).as_posix()}:{n}: {line.strip()}")
    assert hits == []


@pytest.mark.req("R-58")
def test_country_terms_cover_pakistani_names():
    for term in ("Pakistan", "Punjab", "Sindh", "Khyber", "Pakhtunkhwa", "Balochistan", "Kashmir", "Gilgit", "Baltistan",
                 "MDCAT", "ECAT", "PMDC", "UHS", "Lahore", "Peshawar", "Quetta", "Rawalpindi"):
        assert COUNTRY_TERMS.search(term), term
    for inside in ("xPunjab_", "MDCATS"):
        assert not COUNTRY_TERMS.search(inside), inside


_CLOCK_CALL = re.compile(r"\b(datetime\.now|datetime\.utcnow|date\.today)\b")


def direct_clock_calls(root: Path) -> list[str]:
    """Reads of the wall clock outside app/os/clock.py, with or without brackets (rehearsal mode moves one shared
    clock, so a module that reads real time itself would not move with it)."""
    found = []
    for path in root.rglob("*.py"):
        if path.relative_to(root).as_posix() == "clock.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _CLOCK_CALL.search(line):
                found.append(f"{path.relative_to(root).as_posix()}:{number}")
    return found


def test_no_direct_clock_calls():
    assert direct_clock_calls(APP_OS) == []


def test_clock_check_catches_a_violation(tmp_path):
    (tmp_path / "workers").mkdir()
    (tmp_path / "workers" / "bad.py").write_text("x = datetime.now(timezone.utc)\ny = date.today()\nz = datetime.now\n")
    (tmp_path / "clock.py").write_text("x = datetime.now(timezone.utc)\n")
    assert direct_clock_calls(tmp_path) == ["workers/bad.py:1", "workers/bad.py:2", "workers/bad.py:3"]


@pytest.mark.req("R-58")
def test_fake_routes_stay_in_tests():
    """The fake Ireland master's and Pakistan BS routes are test fixtures only: they exist where the tests load them
    and nowhere under app/os (invariant 12: real routes are data, fakes never ship)."""
    packs = Path(__file__).parent / "fixtures" / "packs"
    for route in ("ireland_master", "pakistan_bs"):
        text = (packs / f"{route}.yaml").read_text(encoding="utf-8")
        assert re.search(rf"^route_key: {route}$", text, re.M), route
        assert "Fake" in text.splitlines()[0], route
        assert not list(APP_OS.rglob(f"{route}*")), route
