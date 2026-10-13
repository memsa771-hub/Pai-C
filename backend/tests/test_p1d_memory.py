"""Offline P1d memory checks."""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

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




@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_type,key,value", [
    ("vault_fact", "preferences.study_mode", "online"),
    ("student_record", "education", {"qualification_name": "Completed qualification"}),
])
async def test_accepted_candidate_queues_one_stale_job_and_preserves_notification(
        candidate_type, key, value):
    from sqlalchemy import select
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    from app.models import BackgroundJob, NotificationRecord, Roadmap
    from app.pai_c.roadmaps.service import RoadmapService
    from app.runtime.task_runtime import run
    from tests.test_roadmaps import _journey, _card

    with StudentSession() as student, student.factory() as db:
        journey = _journey(db, student.workspace_id)
        card = _card(db, student.workspace_id, journey.id, "Existing route")
        RoadmapService(db).set_flag(student.workspace_id, card.id, "favorite", True)
        candidate = MemoryCandidateService(db).propose(
            student.workspace_id, candidate_type, key=key, proposed_value=value,
            confidence=0.95, source_type="conversation",
            evidence={"quote": "My student statement"})
        reconciler = MemoryReconciler(db)
        assert reconciler.reconcile(candidate).accepted
        assert not reconciler.reconcile(candidate).accepted
        db.flush()
        jobs = db.scalars(select(BackgroundJob).where(
            BackgroundJob.job_type == "roadmaps.mark_stale")).all()
        assert len(jobs) == 1
        job = jobs[0]
        reason = f"Student profile changed: {key}"
        assert job.workspace_id == student.workspace_id
        assert job.idempotency_key == f"roadmap-stale:{candidate.id}"
        assert job.payload == {"workspace_id": student.workspace_id, "reason": reason}
        assert db.get(Roadmap, card.id).generation_status == "ready"
        assert not db.scalars(select(NotificationRecord)).all()
        db.commit()
        assert await run(job, db) == {"marked_stale": 1}
        db.flush()
        result = RoadmapService(db).get(student.workspace_id, card.id)
        assert result["generation_status"] == "stale"
        assert result["stale_reason"] == reason
        assert result["favorite"] is True
        notification = db.scalars(select(NotificationRecord)).one()
        assert notification.workspace_id == student.workspace_id
        assert notification.dedupe_key == f"roadmap-stale:{card.id}:{card.version}"
        assert notification.created_by == "system:roadmaps"
        assert notification.title == "Roadmap needs a fresh check"
        assert notification.message == card.title
        assert notification.link_url == "/roadmaps"
        assert await run(job, db) == {"marked_stale": 0}
        db.flush()
        assert len(db.scalars(select(NotificationRecord)).all()) == 1


@pytest.mark.asyncio
async def test_stale_job_rejects_another_workspace():
    from types import SimpleNamespace
    from app.runtime.task_runtime import run
    job = SimpleNamespace(job_type="roadmaps.mark_stale", workspace_id="first",
                          payload={"workspace_id": "second", "reason": "Profile changed"})
    with pytest.raises(ValueError, match="own workspace"):
        await run(job, None)


def test_stale_capability_is_internal_and_requires_typed_input():
    from app.capabilities import CapabilityRouter, get_capability_registry
    from app.capabilities.router import CapabilityNotFound
    from app.runtime.task_runtime import enqueue
    registry = get_capability_registry()
    contract = registry.get("roadmaps.mark_stale")
    assert contract.kind == "system"
    assert contract.input_schema["required"] == ["workspace_id", "reason"]
    with pytest.raises(CapabilityNotFound):
        CapabilityRouter(registry).resolve("roadmaps.mark_stale")
    with pytest.raises(ValueError):
        enqueue(None, "roadmaps.mark_stale", {"workspace_id": "workspace"})


def test_stale_job_enqueue_rolls_back_with_reconciliation():
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
            BackgroundJob.job_type == "roadmaps.mark_stale"))
        db.rollback()
        assert not db.scalars(select(BackgroundJob)).all()
        assert not db.scalars(select(VaultFact)).all()
