"""Offline semantic writers/readers and the embeddings kill switch."""
import asyncio
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from app.config import config
from app.models import BackgroundJob, PaiEpisode, VaultFact
from app.pai_c.memory import MemoryService
from scripts.counselor_eval_support import StudentSession
from tests.test_p2b_sessions import message


def test_extractor_only_proposes_objective_candidates():
    from app.memory.extractor import CANDIDATE_TYPES, SYSTEM_PROMPT
    assert set(CANDIDATE_TYPES) == {"vault_fact", "student_record"}
    assert "semantic_memory with" not in SYSTEM_PROMPT
    assert "episode with" not in SYSTEM_PROMPT


def test_index_records_only_supported_sources_and_workspace():
    from app.memory.episodic import EpisodicMemoryService
    from app.memory.semantic import MemoryService as LegacyMemory
    from app.memory.handlers import _records_for
    with StudentSession() as student, student.factory() as db:
        episode = EpisodicMemoryService(db).record(student.workspace_id, "legacy", "Old episode")
        summary = EpisodicMemoryService(db).record(student.workspace_id, "session_summary", "Session summary")
        fact = VaultFact(workspace_id=student.workspace_id, field_key="objective",
                         value={"value": "Fact"}, source_type="conversation")
        db.add(fact); db.flush()
        from app.memory.candidates import MemoryCandidateService
        from app.memory.reconciler import MemoryReconciler
        candidate = MemoryCandidateService(db).propose(student.workspace_id, "student_record",
            key="education", proposed_value={"qualification_name": "Completed qualification"},
            confidence=0.95, source_type="conversation", evidence={"quote": "My qualification"})
        result = MemoryReconciler(db).reconcile(candidate)
        refs = [{"kind": "education", "id": result.result_id}]
        records = _records_for(db, student.workspace_id, ["legacy-memory"], [episode.id, summary.id],
            fact_ids=[fact.id], record_refs=refs)
        assert [(row.kind, row.id) for row in records] == [("vault_fact", fact.id),
            ("student_record:education", result.result_id), ("episode", summary.id)]
        assert "Completed qualification" in records[1].text
        assert not _records_for(db, "another-workspace", [], [], record_refs=refs)
        assert _records_for(db, "another-workspace", [], [summary.id], fact_ids=[fact.id]) == []
        fact.status = "superseded"; db.flush()
        assert _records_for(db, student.workspace_id, [], [], fact_ids=[fact.id]) == []


def test_accepted_fact_enqueues_one_index_job_and_disabled_enqueues_none():
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    with StudentSession() as student, student.factory() as db:
        candidate = MemoryCandidateService(db).propose(student.workspace_id, "vault_fact",
            key="preferences.study_mode", proposed_value="online", confidence=0.95,
            source_type="conversation", evidence={"quote": "I want online study"})
        MemoryReconciler(db).reconcile(candidate)
        MemoryReconciler(db).reconcile(candidate)
        db.flush()
        assert len(db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "memory.embed")).all()) == 1
    with StudentSession() as student, student.factory() as db, patch.object(config, "PAI_SEMANTIC_RECALL_ENABLED", False):
        candidate = MemoryCandidateService(db).propose(student.workspace_id, "vault_fact",
            key="preferences.study_mode", proposed_value="online", confidence=0.95,
            source_type="conversation", evidence={"quote": "I want online study"})
        MemoryReconciler(db).reconcile(candidate)
        db.flush()
        assert not db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "memory.embed")).all()


def test_disabled_makes_zero_embedding_calls_and_no_recall():
    from app.inference import gateway
    from app.documents.content import Segment
    from app.documents.retrieval import index_document_chunks
    from app.memory.handlers import embed_memory, reindex_workspace
    model = AsyncMock(side_effect=AssertionError("No provider call allowed"))
    with StudentSession() as student, student.factory() as db, patch.object(config, "PAI_SEMANTIC_RECALL_ENABLED", False), patch.object(gateway.transport, "create_embedding_client", model):
        assert asyncio.run(gateway.embed("embeddings", ["text"])) == []
        assert asyncio.run(MemoryService(db).recall(student.workspace_id, "question")) == []
        assert asyncio.run(index_document_chunks(student.workspace_id, "file", "doc", [Segment("p1", "text")])) == 0
        job = SimpleNamespace(workspace_id=student.workspace_id, payload={}, id="test")
        assert asyncio.run(embed_memory(job, db))["indexed"] == 0
        assert asyncio.run(reindex_workspace(job, db))["indexed"] == 0
    assert model.call_count == 0


def test_recall_hybrid_validates_canonical_facts():
    from app.memory.index import SearchHit
    from app.memory.retriever import MemoryRetriever
    with StudentSession() as student, student.factory() as db:
        fact = VaultFact(workspace_id=student.workspace_id, field_key="objective", value={"value": "training"}, source_type="conversation")
        db.add(fact); db.flush()
        index = SimpleNamespace(search=AsyncMock(return_value=[SearchHit(fact.id, "vault_fact", 1), SearchHit("missing", "vault_fact", 2)]))
        result = asyncio.run(MemoryRetriever(db, index=index).retrieve(student.workspace_id, "training", kinds=("vault_fact",)))
        assert [row.id for row in result.ordered] == [fact.id]
        assert result.dropped_stale == 1
        assert "training" in result.ordered[0].text
        result = asyncio.run(MemoryRetriever(db, index=index).retrieve("another-workspace", "training", kinds=("vault_fact",)))
        assert not result.ordered


def test_recall_only_called_by_analyst():
    app = Path(__file__).resolve().parents[1] / "app/pai_c"
    callers = []
    for path in app.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "recall" for node in ast.walk(tree)):
            callers.append(path.relative_to(app).as_posix())
    assert callers == ["deep/analysis.py"]


def test_summarizer_role_fallback_and_reasoning():
    from app.inference.gateway import resolve_model, reasoning_effort
    with patch.object(config, "PAI_SUMMARIZER_MODEL", ""), patch.object(config, "PAI_ANALYST_MODEL", "fake-model"), patch.object(config, "PAI_ANALYST_REASONING_EFFORT", "medium"):
        assert resolve_model("summarizer") == "fake-model"
        assert reasoning_effort("summarizer") == "medium"


def test_analyst_recalls_latest_student_message_and_clears_transaction():
    from app.pai_c.deep.analysis import analyze_job
    from tests.test_counselor_deep_pr4 import _turn_job, _model_notebook
    with StudentSession() as student, student.factory() as db:
        job, event_id = _turn_job(student, db, "My latest question")
        recall = AsyncMock(return_value=[{"id": "past", "kind": "episode", "text": "Previous session"}])
        async def model(**kwargs):
            assert not db.in_transaction()
            assert "<semantic_recall>" in kwargs["messages"][0]["content"]
            assert "Previous session" in kwargs["messages"][0]["content"]
            return _model_notebook()
        with patch.object(MemoryService, "recall", recall), patch("app.pai_c.deep.analysis.chat_completion", model):
            asyncio.run(analyze_job(job, db))
        recall.assert_awaited_once_with(student.workspace_id, "My latest question")


def test_retriever_document_hits_require_active_canonical_file():
    from app.models import FileRecord, DocumentArtifact
    from app.memory.index import SearchHit
    from app.memory.retriever import MemoryRetriever
    with StudentSession() as student, student.factory() as db:
        file = FileRecord(workspace_id=student.workspace_id, filename="file.pdf",
            content_type="application/pdf", size=10, storage_key="synthetic", uploaded_by="human:test")
        db.add(file); db.flush()
        db.add(DocumentArtifact(workspace_id=student.workspace_id, file_id=file.id,
            status="ready", document_type="pdf", content={"segments": [{"locator": "p1", "text": "Canonical document"}]}))
        db.flush()
        hit = SearchHit(file.id + ":p1:0", "document_chunk", 1, "Stale index text")
        index = SimpleNamespace(search=AsyncMock(return_value=[hit]))
        reader = MemoryRetriever(db, index=index)
        result = asyncio.run(reader.retrieve(student.workspace_id, "document", kinds=("document_chunk",)))
        assert result.ordered[0].text == "Canonical document"
        file.status = "deleted"; db.flush()
        assert not asyncio.run(reader.retrieve(student.workspace_id, "document", kinds=("document_chunk",))).ordered


def test_recall_obeys_existing_latency_budget():
    from app.memory.retriever import MemoryRetriever, RetrievalResult
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
        raise AssertionError("must be cancelled")
    with StudentSession() as student, student.factory() as db, patch.object(config, "PAI_MEMORY_CONTEXT_TIMEOUT_MS", 50), patch.object(MemoryRetriever, "retrieve", slow), patch.object(MemoryRetriever, "_fallback", return_value=RetrievalResult()) as fallback:
        assert asyncio.run(MemoryService(db).recall(student.workspace_id, "query")) == []
        fallback.assert_called_once()
