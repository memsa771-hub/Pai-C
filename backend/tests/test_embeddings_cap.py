# -*- coding: utf-8 -*-
"""Vault items in the embeddings index, recall without vectors, and the monthly cap.

No live API calls: the embedding client is a fake and the index is the null one.
"""
import asyncio
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.config import config
from app.inference import gateway, usage
from app.memory.candidates import MemoryCandidateService
from app.memory.handlers import _records_for
from app.memory.reconciler import MemoryReconciler
from app.models import BackgroundJob, PaiUsageMonth
from app.pai_c.memory import MemoryService
from scripts.counselor_eval_support import StudentSession

BACKEND = Path(__file__).resolve().parents[1]


def _accept_item(db, ws, item_type, value):
    candidate = MemoryCandidateService(db).propose(ws, "vault_item", key=item_type, proposed_value=value,
        confidence=0.95, source_type="conversation", evidence={"quote": "Said in chat"})
    result = MemoryReconciler(db).reconcile(candidate)
    assert result.accepted, result.reason
    db.flush()
    return result.result_id


def test_items_are_embedded_on_accept():
    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "PAI_SEMANTIC_RECALL_ENABLED", True):
        ws = student.workspace_id
        item_id = _accept_item(db, ws, "interest", {"text": "Robotics"})
        jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "memory.embed")).all()
        assert [job.payload for job in jobs] == [{"item_ids": [item_id]}]
        records = _records_for(db, ws, [], [], item_ids=[item_id])
        assert [(row.kind, row.id) for row in records] == [("vault_item", item_id)]
        assert "Robotics" in records[0].text and "Interest" in records[0].text and "stated" in records[0].text
        assert _records_for(db, "another-workspace", [], [], item_ids=[item_id]) == []


def test_recall_off_is_empty_not_error():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _accept_item(db, ws, "interest", {"text": "Robotics"})
        db.commit()
        memory = MemoryService(db)
        with patch.object(config, "PAI_SEMANTIC_RECALL_ENABLED", False):
            assert asyncio.run(memory.recall(ws, "robotics")) == []
        # On, but no vectors (no key or over the cap): lexical answers, nothing raises.
        with patch.object(config, "PAI_SEMANTIC_RECALL_ENABLED", True), \
                patch("app.memory.embeddings.embed", AsyncMock(return_value=[])):
            found = asyncio.run(memory.recall(ws, "robotics"))
    assert any(row["kind"] == "vault_item" and "Robotics" in row["text"] for row in found)


def _client():
    response = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])], usage=None)
    return SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=response)), close=AsyncMock())


def test_embed_cap_stops_calls(caplog):
    client = _client()
    text = "x" * 4000  # about 1,000 tokens
    with StudentSession() as student, \
            patch.object(config, "PAI_SEMANTIC_RECALL_ENABLED", True), \
            patch.object(config, "MEMORY_EMBEDDING_MODEL", "text-embedding-3-small"), \
            patch.object(config, "PAI_EMBEDDING_MONTHLY_CAP_USD", 0.00001), \
            patch.object(usage, "_cap_logged", ""), \
            patch.object(gateway.transport, "create_embedding_client", return_value=client), \
            caplog.at_level(logging.WARNING, logger="app.inference.usage"):
        first = asyncio.run(gateway.embed("embeddings", [text], api_key="fake", base_url=None))
        with student.factory() as db:
            row = db.scalar(select(PaiUsageMonth))
            assert (row.scope, row.month, row.calls) == ("embeddings", datetime_month(), 1)
            assert abs(float(row.est_usd) - 1000 * 0.02 / 1_000_000) < 1e-9
        second = asyncio.run(gateway.embed("embeddings", [text], api_key="fake", base_url=None))
        third = asyncio.run(gateway.embed("embeddings", [text], api_key="fake", base_url=None))
    assert first == [[0.1, 0.2]] and second == [] and third == []
    assert client.embeddings.create.await_count == 1
    assert len([r for r in caplog.records if "cap" in r.getMessage()]) == 1


def datetime_month():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


def test_usage_months_migration_and_rates():
    spec = importlib.util.spec_from_file_location("migration120", BACKEND / "alembic/versions/120_usage_months.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert (migration.revision, migration.down_revision) == ("120", "119")
    table = PaiUsageMonth.__table__
    assert table.name == "pai_usage_months"
    assert {"id", "scope", "month", "calls", "est_usd", "updated_at"} <= set(table.columns.keys())
    assert usage.rate_per_million("text-embedding-3-small") == 0.02
    assert usage.rate_per_million("some-new-model") == usage.embedding_costs()["usd_per_million_tokens"]["default"]


def test_estimate_prefers_provider_tokens():
    assert usage.estimate_usd("text-embedding-3-small", ["x" * 4000], 500) == 500 * 0.02 / 1_000_000
    assert usage.estimate_usd("text-embedding-3-small", ["x" * 4000]) == 1000 * 0.02 / 1_000_000
