"""CI workflow shape: every required job exists and the standalone marker selects the gate tests (R-59)."""
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.req("R-59")

BACKEND = Path(__file__).resolve().parents[1]
WORKFLOWS = BACKEND.parent / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(data):
    # YAML 1.1 reads the key `on` as the boolean True.
    return data.get("on", data.get(True))


def _run_lines(job):
    return [s["run"] for s in job["steps"] if "run" in s]


def _run_text(job):
    return "\n".join(_run_lines(job))


def test_ci_has_every_required_job():
    assert {"os", "legacy", "frontend", "standalone", "traceability"} <= set(_load("ci.yml")["jobs"])


def test_frontend_job_runs_tsc_tests_and_build():
    job = _load("ci.yml")["jobs"]["frontend"]
    runs = [r.strip() for r in _run_lines(job)]
    for cmd in ("npm ci", "npx tsc --noEmit", "npm test", "npx next build --webpack"):
        assert cmd in runs
    assert job["defaults"]["run"]["working-directory"] == "frontend"
    dockerfile = (Path(__file__).resolve().parents[2] / "frontend" / "Dockerfile").read_text()
    major = re.search(r"^FROM node:(\d+)", dockerfile, re.M).group(1)
    node_steps = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/setup-node")]
    assert str(node_steps[0]["with"]["node-version"]) == major


def test_os_job_keeps_tach_and_alembic_checks():
    text = _run_text(_load("ci.yml")["jobs"]["os"])
    assert "tach check" in text
    assert "scripts/check_alembic_heads.py" in text


def test_standalone_job_uses_marker_and_postgres():
    job = _load("ci.yml")["jobs"]["standalone"]
    assert "-m standalone" in _run_text(job)
    assert "postgres" in job["services"]
    assert "OS_TEST_DATABASE_URL" in job["env"]


def test_push_runs_on_integration_branches():
    assert {"dev", "main", "pai-merge", "pai-connect"} <= set(_triggers(_load("ci.yml"))["push"]["branches"])


def test_freeze_workflow_reacts_to_labels():
    data = _load("freeze.yml")
    assert {"labeled", "unlabeled", "edited", "synchronize"} <= set(_triggers(data)["pull_request"]["types"])
    assert _triggers(data)["pull_request"]["branches"] == ["pai-connect"]
    assert data["concurrency"]["cancel-in-progress"] is True
    assert "check_freeze.py" in "\n".join(_run_text(j) for j in data["jobs"].values())


def test_standalone_marker_selects_gate_tests():
    env = {k: v for k, v in __import__("os").environ.items() if k != "PAI_API_KEY"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-p", "no:tach",
         "-m", "standalone", "tests/os"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300,
    )
    lines = [ln for ln in proc.stdout.splitlines() if "::" in ln]
    assert len(lines) >= 12, proc.stdout[-2000:] + proc.stderr[-1000:]
    assert any("test_slice7_gate.py" in ln for ln in lines)
    assert any("test_slice8_gate.py::test_standalone_suite_module_off" in ln for ln in lines)


def test_standalone_suite_covers_every_p1_port():
    """P1-T10 Task D1 (R-59, R-09): the `-m standalone` job runs the module-off tests of every P1 port, not only the
    slice gates."""
    env = {k: v for k, v in __import__("os").environ.items() if k != "PAI_API_KEY"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-p", "no:tach",
         "-m", "standalone", "tests/os"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300,
    )
    lines = [ln for ln in proc.stdout.splitlines() if "::" in ln]
    for module in ("test_student_facts_port", "test_document_files_port", "test_choice_sink", "test_my_plan_off",
                   "test_os_events", "test_escalation_port", "test_slice8_gate", "test_standalone_guard"):
        assert any(f"{module}.py::" in ln for ln in lines), f"no standalone test from {module}\n" + proc.stdout[-1500:]
