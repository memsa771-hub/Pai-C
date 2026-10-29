"""The Path engine runs from the Vault (FOUR_FEATURES_SPEC 3): a path-relevant
Vault write queues it, its key is the relevance version plus the student's own
paths, semantic recall is extra evidence the model can cite, a why must cite
the Vault, and stored evidence carries the badge the Paths page shows. Fake
models and fake recall only; the embedding API is never called."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.journey import JourneyService
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.memory.student_records import StudentRecordService
from app.models import BackgroundJob, PaiPossibility
from app.pai_c.paths.analyzer import (JOB_ANALYZE_PATHS, PathAnalysis, enqueue_path_analysis,
                                      path_analysis_job, policy, sanitize)
from app.pai_c.possibilities import PossibilityService
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import client_for, fake_post
from tests.test_path_analyzer import (CANDIDATES, CITED, HEADERS, VAULT, VAULT_ITEM, add_education, analysis,
                                      path, seed, title)

MODEL = "app.pai_c.paths.analyzer.chat_completion"
POST = "app.pai_c.paths.analyzer.send_to_student"
RECALL = "app.pai_c.memory.MemoryService.recall"
QUOTE = "VERBATIM-QUOTE-XYZ"


def accept(db, ws, kind, key, value):
    candidate = MemoryCandidateService(db).propose(workspace_id=ws, candidate_type=kind, key=key,
        proposed_value=value, confidence=0.9, source_type="user_explicit",
        evidence={"quote": QUOTE}, allow_user_explicit=True)
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()


def jobs(db, ws):
    return db.scalars(select(BackgroundJob).where(BackgroundJob.workspace_id == ws,
                                                  BackgroundJob.job_type == JOB_ANALYZE_PATHS)
                      .order_by(BackgroundJob.created_at)).all()


def finish_all(db, ws):
    for job in jobs(db, ws):
        job.status = "succeeded" if job.status == "pending" else job.status
    db.commit()


async def run_job(student, db, reply, *, recall=None):
    """Queue and run one analysis with a fake model (and, when given, fake
    recall); returns the result, the prompt the model saw and the recall mock."""
    job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
    db.commit()
    sent = []

    async def model(**kwargs):
        sent.append(kwargs["messages"][0]["content"])
        return json.dumps(reply)

    recalled = AsyncMock(return_value=recall or [])
    with patch(MODEL, AsyncMock(side_effect=model)), patch(RECALL, recalled), \
         patch(POST, AsyncMock(side_effect=fake_post(student))):
        result = await path_analysis_job(db.get(BackgroundJob, job_id), db)
    db.expire_all()
    return result, sent[0] if sent else "", recalled


# ---- trigger and idempotency ---------------------------------------------------------

def test_vault_write_enqueues_analysis():
    """Moved from test_research_relevance (Task 3) and extended: a finished
    run does not swallow the next relevant write, and an education record
    through the reconciler triggers like an item."""
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        JourneyService(db).ensure_counselor(ws)
        db.commit()
        accept(db, ws, "vault_fact", "location.current_city", "Lahore")
        assert jobs(db, ws) == []  # not path-relevant
        accept(db, ws, "vault_item", "interest", {"text": "Robotics"})
        queued = jobs(db, ws)
        assert len(queued) == 1 and queued[0].payload["reason"] == "vault"
        accept(db, ws, "vault_item", "interest", {"text": "Circuits"})
        assert len(jobs(db, ws)) == 1  # a pending run reads everything when it starts
        finish_all(db, ws)
        accept(db, ws, "student_record", "education",
               {"qualification_name": "fsc", "field_of_study": "pre_engineering", "academic_status": "current"})
        queued = jobs(db, ws)
        assert len(queued) == 2 and queued[-1].status == "pending" and queued[-1].payload["reason"] == "vault"


def test_idempotent_on_relevance_version():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        seed(student, db)
        add_education(student, db)
        first = enqueue_path_analysis(db, ws, source_event_id=None, channel=None, reason="vault")
        db.commit()
        finish_all(db, ws)
        assert enqueue_path_analysis(db, ws, source_event_id=None, channel=None, reason="vault") == first
        accept(db, ws, "vault_fact", "location.current_city", "Lahore")  # outside vault_trigger_types
        assert enqueue_path_analysis(db, ws, source_event_id=None, channel=None, reason="vault") == first
        accept(db, ws, "vault_item", "strength", {"text": "Maths"})  # path-relevant: a new run
        second = jobs(db, ws)[-1]
        assert second.id != first and second.status == "pending"
        assert enqueue_path_analysis(db, ws, source_event_id=None, channel=None, reason="planner") == second.id
        assert db.get(BackgroundJob, first).idempotency_key != second.idempotency_key


# ---- semantic recall -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_block_in_prompt_and_citable():
    hits = [{"id": VAULT_ITEM.removeprefix("item:"), "kind": "vault_item", "text": "interest: Repairing phones"},
            {"id": "ep-1", "kind": "episode", "text": "We talked about building circuits."},
            {"id": "not-a-card", "kind": "vault_fact", "text": "a sensitive fact the cards leave out"}]
    reply = analysis(path("electrical_engineering", ids=["c1", VAULT_ITEM]),
                     path("electronic_engineering", ids=["c1", "ep-1"]))
    with StudentSession() as student, student.factory() as db:
        seed(student, db)
        add_education(student, db)
        accept(db, student.workspace_id, "student_record", "goal", {"goal_type": "career", "title": "Build robots"})
        result, prompt, recalled = await run_job(student, db, reply, recall=hits)
        saved = {row.title for row in PossibilityService(db).list(student.workspace_id)}
    query = recalled.await_args.args[1]
    assert recalled.await_args.kwargs["top_k"] == policy()["recall_top_k"]
    assert title("electrical_engineering") in query and "Build robots" in query and "Repairing phones" in query
    block = json.loads(prompt.split("<semantic_recall>")[1].split("</semantic_recall>")[0])
    assert block == [{"id": VAULT_ITEM, "kind": "vault_item", "text": "interest: Repairing phones"},
                     {"id": None, "kind": "episode", "text": "We talked about building circuits."}]
    # The Vault hit is cited; a path resting on an episode alone has no Vault entry behind its why.
    assert result["status"] == "stored"
    assert title("electrical_engineering") in saved and title("electronic_engineering") not in saved


@pytest.mark.asyncio
async def test_analyzer_runs_without_recall():
    reply = analysis(path("electrical_engineering"))
    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "PAI_SEMANTIC_RECALL_ENABLED", False):
        seed(student, db)
        add_education(student, db)
        job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        db.commit()
        sent = []

        async def model(**kwargs):
            sent.append(kwargs["messages"][0]["content"])
            return json.dumps(reply)

        with patch(MODEL, AsyncMock(side_effect=model)), patch(POST, AsyncMock(side_effect=fake_post(student))), \
             patch("app.memory.retriever.MemoryRetriever.retrieve", AsyncMock(side_effect=AssertionError)):
            result = await path_analysis_job(db.get(BackgroundJob, job_id), db)
        rows = PossibilityService(db).list(student.workspace_id)
    assert "<semantic_recall>" not in sent[0]
    assert result["status"] == "stored" and result["paths"] == [rows[0].id]
    assert set(rows[0].evidence[0]) == {"text", "item_id", "evidence_level", "source_label"}


# ---- the why cites the Vault -----------------------------------------------------------

def test_why_without_vault_citation_dropped():
    raw = analysis(path("electrical_engineering", ids=["c1", "c3"]),     # notebook only
                   path("electronic_engineering", ids=[]),               # nothing
                   path("mechanical_engineering", ids=["made-up-item"]),  # not a Vault entry
                   path("civil_engineering", ids=["c1", VAULT_ITEM]))
    result = sanitize(PathAnalysis.model_validate(raw), CITED, set(), CANDIDATES, vault=VAULT)
    assert [row["title"] for row in result] == [title("civil_engineering")]


@pytest.mark.asyncio
async def test_evidence_has_level_and_source():
    with StudentSession() as student, student.factory() as db:
        seed(student, db)
        add_education(student, db)  # typed in Details (user_explicit)
        education_id = StudentRecordService(db).list(student.workspace_id, "education")[0].id
        reply = analysis(path("electrical_engineering", ids=["c1", VAULT_ITEM, education_id]))
        await run_job(student, db, reply)
        row = db.scalar(select(PaiPossibility).where(PaiPossibility.workspace_id == student.workspace_id))
        evidence = {item["item_id"]: item for item in row.evidence}
        assert (evidence[VAULT_ITEM]["evidence_level"], evidence[VAULT_ITEM]["source_label"]) == ("stated", "Chat")
        assert evidence[education_id]["source_label"] == "Details"
        assert evidence[education_id]["evidence_level"] in {"stated", "confirmed"}
        assert (evidence["c1"]["evidence_level"], evidence["c1"]["source_label"]) == (None, None)  # notebook
        client = client_for(student)
        try:
            listed = client.get(f"/v1/counselor/possibilities?network={student.workspace_id}", headers=HEADERS)
        finally:
            client.app.dependency_overrides.clear()
    served = {item["item_id"]: item for item in listed.json()["data"]["possibilities"][0]["evidence"]}
    assert served[VAULT_ITEM]["source_label"] == "Chat" and served[VAULT_ITEM]["evidence_level"] == "stated"


@pytest.mark.asyncio
async def test_agent_stated_fact_shows_as_pai_guess_on_the_path():
    """One ladder (review Important 1): a fact an agent wrote is "PAI's guess"
    on the Vault page, so the path citing it says the same, not "stated"."""
    from app.memory.vault import VaultService
    from app.memory.vault_view import VaultView
    with StudentSession() as student, student.factory() as db:
        seed(student, db)
        add_education(student, db)
        VaultService(db).apply_fact(student.workspace_id, "location.current_city", "Lahore", source_type="agent",
                                    evidence={"quote": "Probably Lahore"})
        db.commit()
        fact_id = next(row.entry["id"] for row in VaultView(db).rows(student.workspace_id)
                       if row.entry["kind"] == "fact" and row.entry["type"] == "location.current_city")
        assert next(row.entry["level"] for row in VaultView(db).rows(student.workspace_id)
                    if row.entry["id"] == fact_id) == "inferred"
        reply = analysis(path("electrical_engineering", ids=["c1", VAULT_ITEM, fact_id]))
        _, prompt, _ = await run_job(student, db, reply,
                                     recall=[{"id": fact_id, "kind": "vault_fact", "text": "City: Lahore"}])
        row = db.scalar(select(PaiPossibility).where(PaiPossibility.workspace_id == student.workspace_id))
        evidence = {item["item_id"]: item for item in row.evidence}
    # A fact hit maps to its card id (the VaultFact id) and is citable.
    assert f'"id":"{fact_id}"' in prompt.split("<semantic_recall>")[1]
    assert evidence[fact_id]["evidence_level"] == "inferred"
    assert evidence[VAULT_ITEM]["evidence_level"] == "stated"


@pytest.mark.asyncio
async def test_a_failing_recall_never_fails_the_run():
    with StudentSession() as student, student.factory() as db:
        seed(student, db)
        add_education(student, db)
        job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="vault")
        db.commit()
        with patch(MODEL, AsyncMock(return_value=json.dumps(analysis(path("electrical_engineering"))))) as model,              patch(RECALL, AsyncMock(side_effect=RuntimeError("index down"))):
            result = await path_analysis_job(db.get(BackgroundJob, job_id), db)
    assert result["status"] == "stored" and len(result["paths"]) == 1
    assert "<semantic_recall>" not in model.await_args.kwargs["messages"][0]["content"]
