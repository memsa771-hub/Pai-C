"""The 360-degree path analyzer: code-level honesty, one job, its triggers and
the student's own paths. Fake models only."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import BackgroundJob, EventRecord, PaiPossibility, VaultItem
from app.pai_c.deep.notebook import NotebookService
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.paths.analyzer import (JOB_ANALYZE_PATHS, PathAnalysis, enqueue_path_analysis,
                                      path_analysis_job, policy, sanitize)
from app.pai_c.paths.fields import candidate_fields, study_fields
from app.pai_c.possibilities import PossibilityService
from app.pai_c.possibility_titles import normalized_title
from scripts.counselor_eval_support import StudentSession
from tests.test_adaptive_counseling import reply, signals
from tests.counselor_fixtures import client_for, fake_post, prepare
from tests.truth_map_fixtures import item

ROOT = Path(__file__).parents[1]
HEADERS = {"X-Workspace-Token": "synthetic-test-only"}
EVIDENCE = {"c1": "I fix phones for neighbours.", "c2": "Money at home is tight.",
            "c3": "My father wants me to be an engineer."}
# One Vault item every seeded student has, so a path's why can cite the Vault
# (FOUR_FEATURES_SPEC 3); unit tests treat it as a stated chat entry.
VAULT_ITEM = "item:v-repair"
CITED = {**EVIDENCE, VAULT_ITEM: "Repairing phones"}
VAULT = {VAULT_ITEM: {"evidence_level": "stated", "source_label": "Chat"}}


def fit(label, status, ids=(), note=""):
    return {"label": label, "status": status, "note": note, "evidence_item_ids": list(ids)}


FSC_ENGINEERING = {"qualification_name": "fsc", "field_of_study": "pre_engineering", "academic_status": "current"}
CANDIDATES = candidate_fields(FSC_ENGINEERING)
STRONG = (fit("Hands-on skill", "have", ["c1"]), fit("Interest", "partial", ["c3"]))


def path(field_key, *, why="It follows what you said.", ids=("c1", VAULT_ITEM), fits=STRONG, title=""):
    return {"field_key": field_key, "title": title, "why": why, "evidence_item_ids": list(ids), "fit": list(fits)}


def title(key):
    return study_fields()[key].title


def add_education(student, db, values=FSC_ENGINEERING):
    from app.memory.student_records import StudentRecordService
    StudentRecordService(db).apply(student.workspace_id, "education", values, source_type="user_explicit",
                                   claim_origin="student", capture_method="explicit_correction")
    db.commit()


def analysis(*paths, message="I have put together a few paths from what you shared."):
    return {"message": message, "paths": list(paths)}


def seed(student, db):
    """Three things the student said, enough for the analyzer to start."""
    turn, journey, snapshot = prepare(student, db)
    data = snapshot.notebook.model_dump(mode="json")
    data["said"] = [item(text, key=f"claim_{key}", id=key, evidence=text) for key, text in EVIDENCE.items()]
    snapshot, _ = NotebookService(db).apply(student.workspace_id, data, turn.source_event_id,
                                           expected_version=snapshot.version)
    if db.get(VaultItem, VAULT_ITEM.removeprefix("item:")) is None:
        db.add(VaultItem(id=VAULT_ITEM.removeprefix("item:"), workspace_id=student.workspace_id,
                         item_type="interest", value={"text": "Repairing phones"}, level="stated",
                         source_type="conversation", evidence={"quote": EVIDENCE["c1"]}))
    db.commit()
    return turn, journey, snapshot


def test_policy_prompt_and_document_agree():
    rules = policy()
    assert rules["statuses"] == ["have", "partial", "blocker", "unknown"]
    assert set(rules["evidenced_statuses"]) < set(rules["statuses"])
    prompt = load_prompt("path_analyzer")
    for status in rules["statuses"]:
        assert f"- {status}:" in prompt
    doc = (ROOT.parent / "docs/counselor/COUNSELOR_V3_PROMPTS.md").read_text(encoding="utf-8")
    assert prompt.strip() in doc


def test_sanitize_makes_uncited_verdicts_unknown_and_keeps_student_words():
    result = sanitize(PathAnalysis.model_validate(analysis(path("electronic_engineering", fits=[
        fit("Hands-on skill", "have", ["c1"]),
        fit("Interest", "partial", ["c3"]),
        fit("Afford fees", "blocker", ["made-up"]),
        fit("Maths level", "partial"),
        fit("Family support", "unknown", ["c3"]),
    ]))), CITED, set(), CANDIDATES, vault=VAULT)
    assert [(row["label"], row["status"], row["evidence"]) for row in result[0]["fit"]] == [
        ("Hands-on skill", "have", [EVIDENCE["c1"]]),
        ("Interest", "partial", [EVIDENCE["c3"]]),
        ("Afford fees", "unknown", []),
        ("Maths level", "unknown", []),
        ("Family support", "unknown", []),
    ]
    assert result[0]["evidence"] == [
        {"text": EVIDENCE["c1"], "item_id": "c1", "evidence_level": None, "source_label": None},
        {"text": CITED[VAULT_ITEM], "item_id": VAULT_ITEM, "evidence_level": "stated", "source_label": "Chat"}]


def test_sanitize_drops_world_numbers_dismissed_duplicates_and_caps():
    rules = policy()
    many = [path(key) for key in ("civil_engineering", "chemical_engineering", "physics", "mathematics",
                                  "statistics", "bba", "economics")]
    raw = analysis(
        path("electrical_engineering", why="Merit closed at 85% last year."),
        path("education"),
        path("education"),
        path("mechanical_engineering", fits=[*STRONG, *[fit(f"Need {n}", "unknown") for n in range(10)]]),
        *many)
    result = sanitize(PathAnalysis.model_validate(raw), CITED, {normalized_title(title("education"))}, CANDIDATES, vault=VAULT)
    titles = [row["title"] for row in result]
    assert title("electrical_engineering") not in titles and title("education") not in titles
    assert len(result) == rules["max_paths"]
    assert len(next(row for row in result if row["title"] == title("mechanical_engineering"))["fit"]) == rules["max_fit_items"]


def test_sanitize_keeps_only_fields_of_study():
    raw = analysis(path("electrical_engineering"), path("", title="Phone Repair Shop"),
                   path("9999", title="Online Resale"))
    assert [row["title"] for row in sanitize(PathAnalysis.model_validate(raw), CITED, set(), CANDIDATES, vault=VAULT)] == [
        title("electrical_engineering")]


def test_profile_evidence_is_the_stored_value_not_the_raw_quote():
    from app.pai_c.paths.analyzer import _card_text
    assert _card_text("Family cannot pay high fees") == "Family cannot pay high fees"
    assert _card_text({"qualification_name": "FSc Pre-Engineering", "marks_obtained": 780, "notes": ""}) == "FSc Pre-Engineering, 780"


def test_sanitize_clears_a_note_that_carries_a_world_number():
    result = sanitize(PathAnalysis.model_validate(analysis(path("electronic_engineering", fits=[
        fit("Fees", "unknown", note="Usually $500 per semester."), *STRONG,
    ]))), CITED, set(), CANDIDATES, vault=VAULT)
    assert result[0]["fit"][0]["note"] == ""


@pytest.mark.asyncio
async def test_job_stores_paths_updates_fit_posts_once_and_never_revives_dismissed():
    with StudentSession() as student, student.factory() as db:
        turn, journey, _ = seed(student, db)
        service = PossibilityService(db)
        own = service.add(student.workspace_id, journey.id, title="Mobile repair", why="Mine",
                          kind="student_added", source="student", status="saved")
        gone = service.add(student.workspace_id, journey.id, title=title("civil_engineering"), why="Earlier",
                           kind="discovered", source="planner", status="dismissed")
        add_education(student, db)
        job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                       channel=turn.channel, reason="asked")
        db.commit()
        reply_json = json.dumps(analysis(
            path("", title="Mobile repair", fits=[fit("Hands-on skill", "have", ["c1"])]),
            path("electrical_engineering", ids=["c3", VAULT_ITEM], fits=[*STRONG, fit("Afford fees", "blocker", ["c2"])]),
            path("civil_engineering")))

        async def model(**kwargs):
            assert not db.in_transaction()
            assert kwargs["role"] == "analyst"
            sent = kwargs["messages"][0]["content"]
            assert "<dismissed_paths>" in sent and title("civil_engineering") in sent and "Mobile repair" in sent
            assert '"key":"electrical_engineering"' in sent and "<workspace_language>" in sent
            return reply_json

        job = db.get(BackgroundJob, job_id)
        with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(side_effect=model)) as call, \
             patch("app.pai_c.paths.analyzer.send_to_student", AsyncMock(side_effect=fake_post(student))) as post:
            first = await path_analysis_job(job, db)
            again = await path_analysis_job(job, db)
        assert first["status"] == again["status"] == "posted"
        assert call.await_count == post.await_count == 1
        db.expire_all()
        rows = {row.title: row for row in service.list(student.workspace_id)}
        assert rows["Mobile repair"].id == own.id and rows["Mobile repair"].source == "student"
        assert rows["Mobile repair"].fit[0]["status"] == "have"
        added = rows[title("electrical_engineering")]
        assert (added.source, added.kind, added.status) == ("analyzer", "discovered", "suggested")
        assert added.fit[-1] == {"label": "Afford fees", "status": "blocker", "note": "",
                                 "evidence": [EVIDENCE["c2"]]}
        assert added.study_field["key"] == "electrical_engineering"
        assert db.get(PaiPossibility, gone.id).status == "dismissed"
        event = db.scalar(select(EventRecord).where(EventRecord.source == "openagents:pai"))
        assert event.metadata_["paths_job_id"] == job.id
        assert event.metadata_["paths_found"] == first["paths"] == [own.id, added.id]


@pytest.mark.asyncio
async def test_job_waits_for_enough_known_and_gives_up_after_two_invalid_replies():
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = prepare(student, db)
        add_education(student, db)  # placed: only the notebook is short
        job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None,
                                       channel=turn.channel, reason="student")
        db.commit()
        with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock()) as call:
            assert (await path_analysis_job(db.get(BackgroundJob, job_id), db))["status"] == "not_enough_known"
        call.assert_not_awaited()
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)
        add_education(student, db)
        job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=None,
                                       channel=turn.channel, reason="student")
        db.commit()
        with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(return_value="not JSON")) as call, \
             patch("app.pai_c.paths.analyzer.send_to_student", AsyncMock()) as post:
            assert (await path_analysis_job(db.get(BackgroundJob, job_id), db))["status"] == "invalid"
        assert call.await_count == 2
        assert "Return one complete JSON object" in call.await_args.kwargs["system_prompt"]
        post.assert_not_awaited()
        assert PossibilityService(db).list(student.workspace_id) == []


def test_enqueue_reuses_a_pending_job():
    with StudentSession() as student, student.factory() as db:
        seed(student, db)
        first = enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None, reason="student")
        db.commit()
        assert enqueue_path_analysis(db, student.workspace_id, source_event_id=None, channel=None,
                                     reason="asked") == first
        assert len(db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_ANALYZE_PATHS)).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,queued", [("decision_help", True), ("information", False)])
async def test_asking_for_paths_queues_the_analyzer_in_the_background(monkeypatch, kind, queued):
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-fake")
    sig = signals(intent="deciding" if kind == "decision_help" else "asking_info",
                  request={"text": "Which paths do I have?", "kind": kind,
                           "needs_research": False, "needs_context": False})
    with StudentSession() as student:
        with patch("app.pai_c.policy.classifier.complete", AsyncMock(return_value=sig.model_dump_json())), \
             patch("app.pai_c.deep.turn.chat_completion", AsyncMock(return_value=reply("Let us look at that together."))):
            await student.turn("Mere paas kaun kaun se raste hain?")
        with student.factory() as db:
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.job_type == JOB_ANALYZE_PATHS))
            assert (job is not None) is queued
            if queued:
                assert job.payload["reason"] == "asked" and job.payload["channel"]


def test_student_adds_own_path_and_asks_for_analysis():
    from app.main import app
    with StudentSession() as student, student.factory() as db:
        turn, journey, _ = seed(student, db)
        gone = PossibilityService(db).add(student.workspace_id, journey.id, title="Graphic design",
            why="Earlier", kind="discovered", source="analyzer", status="dismissed")
        db.commit()
        client = client_for(student)
        base = f"/v1/counselor/possibilities?network={student.workspace_id}"
        try:
            assert client.post(base, json={"title": "Mobile repair"}).status_code == 401
            assert client.post(base, json={"title": "   "}, headers=HEADERS).status_code == 422
            assert client.post(base, json={"title": "x", "extra": 1}, headers=HEADERS).status_code == 422
            made = client.post(base, json={"title": "  Mobile   repair ", "why": "I like it"}, headers=HEADERS)
            assert made.status_code == 200, made.text
            row = made.json()["data"]
            assert (row["title"], row["why"], row["kind"], row["source"], row["status"]) == (
                "Mobile repair", "I like it", "student_added", "student", "saved")
            assert row["fit"] == []
            back = client.post(base, json={"title": "graphic design"}, headers=HEADERS).json()["data"]
            assert back["id"] == gone.id and back["status"] == "saved"
            jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_ANALYZE_PATHS)).all()
            assert len(jobs) == 1 and "channel" not in jobs[0].payload
            db.get(BackgroundJob, jobs[0].id).status = "completed"
            db.commit()
            # No button route: paths run only on their own triggers.
            assert client.post(f"/v1/counselor/possibilities/analyze?network={student.workspace_id}",
                               headers=HEADERS).status_code in {404, 405}
            client.post(base, json={"title": "Solar installation"}, headers=HEADERS)
            db.expire_all()
            job = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_ANALYZE_PATHS,
                                                         BackgroundJob.status == "pending")).one()
            assert job.id != jobs[0].id
            db.get(BackgroundJob, job.id).status = "completed"
            db.commit()
        finally:
            app.dependency_overrides.clear()


def test_migration_112_adds_fit_and_analyzer_source_and_downgrades():
    spec = importlib.util.spec_from_file_location("migration112", ROOT / "alembic/versions/112_possibility_fit.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "112" and migration.down_revision == "111"
    with patch.object(migration, "op", Mock()) as op:
        migration.upgrade()
        column = op.add_column.call_args.args[1]
        assert (column.name, column.nullable) == ("fit", False)
        assert "'analyzer'" in op.create_check_constraint.call_args.args[2]
        migration.downgrade()
        assert "'analyzer'" not in op.create_check_constraint.call_args.args[2]
        op.drop_column.assert_called_once_with("pai_possibilities", "fit")
    with StudentSession() as student, student.factory() as db:
        _, journey, _ = prepare(student, db)
        row = PossibilityService(db).add(student.workspace_id, journey.id, title="Practical route",
            why="Evidence", kind="discovered", source="analyzer", status="suggested")
        db.commit()
        db.expire_all()
        assert db.get(PaiPossibility, row.id).fit == []
