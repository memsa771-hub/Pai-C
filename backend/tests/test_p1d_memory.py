"""Offline P1d memory checks."""
import ast
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

from app.pai_c.memory import MemoryService
from app.pai_c.deep.context import build_context
from app.pai_c.deep.turn_input import CounselorTurnInput
from scripts.counselor_eval_support import StudentSession


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_pai_c_memory_imports_have_one_owner():
    for path in (APP / "pai_c").rglob("*.py"):
        if path.name == "memory.py":
            continue
        assert not any(name == "app.memory" or name.startswith("app.memory.")
                       for name in imports(path)), str(path)


def test_shared_memory_does_not_import_pai_c():
    for path in (APP / "memory").rglob("*.py"):
        assert not any(name == "app.pai_c" or name.startswith("app.pai_c.")
                       for name in imports(path)), str(path)


def test_truth_map_writes_have_only_authorized_callers():
    allowed = {"pai_c/deep/analysis.py", "pai_c/deep/sensitive.py"}
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "apply_truth_map":
                    assert relative in allowed, relative
                if (node.func.attr == "apply" and isinstance(node.func.value, ast.Call)
                        and isinstance(node.func.value.func, ast.Name)
                        and node.func.value.func.id == "NotebookService"):
                    assert relative == "pai_c/memory.py", relative
        if relative not in {"pai_c/deep/notebook.py", "pai_c/memory.py", "routers/workspaces.py",
                            "research/gateway.py", "research/jobs.py"}:
            assert "NotebookService" not in path.read_text(encoding="utf-8-sig"), relative


@pytest.mark.asyncio
async def test_context_reads_profile_once_without_foreground():
    with StudentSession() as student, student.factory() as db:
        turn = CounselorTurnInput("channel/pai", student.workspace_id, "A question", (),
                                  None, "", None, f"human:{student.user_id}")
        original = MemoryService.profile
        with patch.object(MemoryService, "profile", autospec=True, side_effect=original) as read:
            context = await build_context(db, student.workspace_id, turn)
        read.assert_called_once()
        assert '"foreground"' not in context.text
        assert '"latest_episode_summary"' in context.text
        assert '"open_threads"' in context.text




def test_resume_job_enqueue_rolls_back_with_reconciliation():
    from sqlalchemy import select
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    from app.models import BackgroundJob, VaultFact
    with StudentSession() as student, student.factory() as db:
        candidate = MemoryCandidateService(db).propose(
            student.workspace_id, "vault_fact", key="preferences.study_mode",
            proposed_value="online", confidence=0.95, source_type="conversation",
            evidence={"quote": "My name"})
        assert MemoryReconciler(db).reconcile(candidate).accepted
        db.flush()
        assert db.scalar(select(BackgroundJob.id).where(
            BackgroundJob.job_type == "memory.resume_research"))
        db.rollback()
        assert not db.scalars(select(BackgroundJob)).all()
        assert not db.scalars(select(VaultFact)).all()
