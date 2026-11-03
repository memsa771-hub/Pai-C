"""Freeze check for Counsellor prompts, policy and model settings (R-43, master spec section 10)."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("R-43")

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_freeze.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_freeze", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cf = _load()


def test_frozen_paths_are_caught():
    paths = [
        "backend/app/pai_c/deep/analysis.py",
        "backend/app/pai_c/deep/prompts/path_analyzer.md",
        "backend/app/pai_c/policy/academic_calendar.json",
        "backend/app/pai_c/playbooks/x.json",
        "backend/app/pai_c/policy/actions/a.json",
        "backend/app/pai_c/voice/prompts/v.md",
        "backend/app/pai_c/roadmap/notes.md",
        "docs/counselor/COUNSELOR_V3_PROMPTS.md",
    ]
    assert cf.frozen_files(paths) == sorted(paths)


def test_unfrozen_paths_pass():
    assert cf.frozen_files([
        "backend/app/os/playbooks/route.yaml",
        "backend/app/pai_c/possibilities.py",
        "backend/app/pai_c/policy/sub/x.json",
        "backend/app/pai_os_bridge.py",
    ]) == []


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _rename_repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    src = tmp_path / "backend/app/pai_c/deep/a.py"
    src.parent.mkdir(parents=True)
    src.write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "one")
    _git(tmp_path, "mv", "backend/app/pai_c/deep/a.py", "backend/app/pai_c/a.py")
    _git(tmp_path, "commit", "-qm", "two")


def test_rename_out_of_frozen_dir_is_caught(tmp_path, monkeypatch):
    _rename_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PR_LABELS", raising=False)
    monkeypatch.delenv("PR_TEXT", raising=False)
    assert cf.main(["--base", "HEAD~1"]) == 1


def test_rename_with_exception_passes(tmp_path, monkeypatch):
    _rename_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PR_LABELS", "freeze-exception")
    monkeypatch.setenv("PR_TEXT", "R-47 fix")
    assert cf.main(["--base", "HEAD~1"]) == 0


OLD = 'class Config:\n    PAI_COUNSELOR_MODEL: str = "a"\n    OS_ENABLED = True\n    MEMORY_EMBEDDING_MODEL = "e"\n'


def test_counsellor_model_default_change_is_caught():
    new = OLD.replace('"a"', '"b"')
    assert cf.changed_model_settings(OLD, new) == ["PAI_COUNSELOR_MODEL"]


def test_other_setting_change_passes():
    new = OLD.replace("True", "False").replace('"e"', '"f"')
    assert cf.changed_model_settings(OLD, new) == []


def test_reorder_is_not_a_change():
    new = 'class Config:\n    MEMORY_EMBEDDING_MODEL = "e"\n    PAI_COUNSELOR_MODEL: str = "a"\n    OS_ENABLED = True\n'
    assert cf.changed_model_settings(OLD, new) == []


def test_added_and_removed_settings_are_caught():
    assert cf.changed_model_settings("class C:\n    A = 1\n", "class C:\n    PAI_MODEL = 'x'\n") == ["PAI_MODEL"]
    assert cf.changed_model_settings("class C:\n    PAI_MODEL = 'x'\n", "") == ["PAI_MODEL"]


def test_label_without_rid_fails():
    assert cf.exception_allowed(["freeze-exception"], "fix C1") is False


def test_label_with_rid_passes():
    assert cf.exception_allowed(["freeze-exception"], "R-47: fix C1") is True
    assert cf.exception_allowed([], "R-47") is False
