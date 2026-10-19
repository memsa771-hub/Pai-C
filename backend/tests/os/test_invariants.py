"""Fitness checks for invariants 1 (kernel is the sole writer) and 12 (nothing country-specific in code)."""

import re
from pathlib import Path

APP_OS = Path(__file__).resolve().parents[2] / "app" / "os"
PLAN_TABLES = ("plans", "tasks", "task_edges", "plan_revisions")
_CORE = re.compile(r"\b(insert|update|delete)\(\s*(?:models\.)?(" + "|".join(PLAN_TABLES) + r")\b")
_SQL = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:os\.)?os_(" + "|".join(PLAN_TABLES) + r")\b", re.I)

COUNTRY_TERMS = re.compile(
    r"\b(Germany|German|Pakistan|Pakistani|Ireland|Irish|DAAD|HEC|IBCC|uni[-_]assist|EUR|PKR|Berlin|Karachi|"
    r"Islamabad|PK|DE|IE)\b"
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


def test_no_country_terms_in_python():
    hits = []
    for path in APP_OS.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if COUNTRY_TERMS.search(line):
                hits.append(f"{path.relative_to(APP_OS).as_posix()}:{n}: {line.strip()}")
    assert hits == []
