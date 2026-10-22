"""Slice 5 Task 8: the statements API and plan task completion (spec §4, S5-D8). The drafting itself is the
os.statement workflow's (test_statements_run); here a fake DBOS client records what would be enqueued, and drafts are
written through the store as the workflow would. Fictional answers only."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.artifacts.store import ArtifactStore
from app.os.documents.store import ProfileStore
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings
from app.os.statements.approval import delete_statements
from app.os.statements.config import load_statement_configs
from tests.os.test_api_knowledge import FakeClient

FAKE = Path(__file__).parent / "playbooks"
CONFIGS = load_statement_configs(Path(__file__).parent / "statements")
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
TENANT = "pai"
P = "/v1/os"
CFG = CONFIGS["ireland_master"]


def me(student="stu-1") -> dict:
    return {"X-Test-Student": student}


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})
    fake = FakeClient()
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2027, 3, 1),
                        dbos_client=lambda: fake, statement_configs=CONFIGS)
    store, kb = ProgrammeStore(engine, TENANT), SqlKnowledge(engine, TENANT)
    for ref in ("p1", "p2"):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="Uni X", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://uni.example/{ref}",),
                               official_domains=("uni.example",)))
        kb.upsert("programme", ref, "deadline_close", Fact({"date": "2027-07-15"}, "q", "https://uni.example/r",
                                                           CHECKED, 2027, "confirmed"), "manual")
    # p1 asks for its own statement (researched); p2 does not say
    kb.upsert("programme", "p1", "statement_requirement",
              Fact({"limit_words": 500, "limit_chars": None}, "q", "https://uni.example/r", CHECKED, 2027,
                   "confirmed"), "manual")
    ProfileStore(engine, TENANT).set("stu-1", "transcript.institution", "Example University", None)
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.fake, c.engine = fake, engine
    return c


def start(api, student="stu-1", refs=("p1", "p2")):
    r = api.post(f"{P}/plans/self", headers=me(student), json={
        "route": "ireland_master", "intake": {"term": "winter", "year": 2027},
        "choices": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})
    assert r.status_code == 201, r.text
    return r.json()["plan_id"]


def answer_all(api, student="stu-1"):
    for q in CFG.questions:
        if q.required:
            r = api.put(f"{P}/statements/answers/{q.id}", headers=me(student),
                        json={"answer": f"At Example University I worked on {q.id}."})
            assert r.status_code == 200, r.text


def written(api, kind="sop", programme_ref=None, text="At Example University I worked on motivation.",
            student="stu-1") -> int:
    """A draft as the os.statement workflow would store it."""
    store = ArtifactStore(api.engine, TENANT)
    art = store.get_or_create(student, kind, programme_ref)
    store.add_version(art.id, text, "writer", critic={"ok": True}, flags=[], limit_words=800)
    return art.id


def apply_tasks(api, plan_id):
    """The apply tasks, made ready for the student (as the kernel does when their turn comes)."""
    T = models.tasks
    with api.engine.begin() as conn:
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.template_key == "apply")
                     .values(state="waiting_student"))
        return {r.programme_ref: r.id for r in conn.execute(
            select(T.c.id, T.c.programme_ref).where(T.c.plan_id == plan_id, T.c.template_key == "apply"))}


def task_state(api, task_id):
    with api.engine.connect() as conn:
        return conn.execute(select(models.tasks.c.state, models.tasks.c.result)
                            .where(models.tasks.c.id == task_id)).one()


def test_interview_get_and_put(api):
    assert api.get(f"{P}/statements/interview", headers=me()).status_code == 404  # no plan yet
    start(api)
    body = api.get(f"{P}/statements/interview", headers=me()).json()
    assert body["route"] == "ireland_master" and [q["id"] for q in body["questions"]] == [q.id for q in CFG.questions]
    assert body["missing"] == [q.id for q in CFG.questions if q.required]
    assert api.put(f"{P}/statements/answers/motivation", headers=me(), json={"answer": "Data."}).json() == {
        "saved": True, "drafting": 0}
    body = api.get(f"{P}/statements/interview", headers=me()).json()
    assert next(q for q in body["questions"] if q["id"] == "motivation")["answer"] == "Data."
    assert "motivation" not in body["missing"]
    assert api.put(f"{P}/statements/answers/nope", headers=me(), json={"answer": "x"}).status_code == 404
    assert api.put(f"{P}/statements/answers/motivation", headers=me(), json={"answer": "x" * 4001}).status_code == 422


def test_draft_409_names_missing(api):
    start(api)
    api.put(f"{P}/statements/answers/background", headers=me(), json={"answer": "BSc."})
    r = api.post(f"{P}/statements/sop/draft", headers=me())
    assert r.status_code == 409
    assert r.json()["detail"]["missing"] == [q.id for q in CFG.questions if q.required and q.id != "background"]
    assert api.fake.calls == []


def test_draft_202_enqueued(api):
    start(api)
    answer_all(api)
    r = api.post(f"{P}/statements/sop/draft", headers=me())
    assert r.status_code == 202 and r.json()["kind"] == "sop" and r.json()["programme_ref"] is None
    [(options, args)] = api.fake.calls
    assert options["workflow_name"] == "os.statement" and args == (r.json()["id"], "ireland_master", 2027)
    assert api.post(f"{P}/statements/sop/draft", headers=me(), json={"programme_ref": "p9"}).status_code == 422
    assert api.post(f"{P}/statements/cv/draft", headers=me(), json={"programme_ref": "p1"}).status_code == 422
    assert api.post(f"{P}/statements/poem/draft", headers=me()).status_code == 404
    r = api.post(f"{P}/statements/sop/draft", headers=me(), json={"programme_ref": "p1"})
    assert r.status_code == 202 and r.json()["programme_ref"] == "p1"


def test_edit_runs_facts_check(api):
    start(api)
    answer_all(api)
    art = written(api)
    r = api.put(f"{P}/statements/{art}/text", headers=me(),
                json={"text": "At Example University I worked on motivation. I won the Gold Medal in 2019."})
    v = r.json()["version"]
    assert r.status_code == 200 and v["number"] == 2 and v["author"] == "student"
    assert set(v["flags"]) == {"Gold Medal", "2019"}
    assert v["limit_words"] == 800  # the route default for a base SOP


def test_approve_returns_sha256(api):
    import hashlib

    start(api)
    art = written(api)
    r = api.post(f"{P}/statements/{art}/approve", headers=me(), json={"version": 1})
    text = "At Example University I worked on motivation."
    assert r.status_code == 200 and r.json()["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    listed = api.get(f"{P}/statements", headers=me()).json()["statements"]
    assert listed[0]["status"] == "approved" and listed[0]["approval"]["version"] == 1
    assert api.post(f"{P}/statements/{art}/approve", headers=me(), json={"version": 7}).status_code == 404


def test_approve_flagged_version_keeps_flags(api):
    """Approving a version with flags is the student's call; the flags stay on it, visible."""
    start(api)
    answer_all(api)
    art = written(api)
    api.put(f"{P}/statements/{art}/text", headers=me(), json={"text": "I won the Gold Medal in 2019."})
    assert api.post(f"{P}/statements/{art}/approve", headers=me(), json={"version": 2}).status_code == 200
    [s] = api.get(f"{P}/statements", headers=me()).json()["statements"]
    assert s["approval"]["version"] == 2 and set(s["version"]["flags"]) == {"Gold Medal", "2019"}


def test_task_completes_when_all_approved(api):
    plan = start(api)
    tasks = apply_tasks(api, plan)
    sop, cv = written(api), written(api, "cv", text="Example University, BSc.")
    assert api.post(f"{P}/statements/{sop}/approve", headers=me(), json={"version": 1}).json()["completed_tasks"] == []
    r = api.post(f"{P}/statements/{cv}/approve", headers=me(), json={"version": 1}).json()
    assert r["completed_tasks"] == [tasks["p2"]]  # p1 asks for its own SOP too
    state, result = task_state(api, tasks["p2"])
    assert state == "done" and set(result["artifacts"]) == {"sop", "cv"}
    assert result["artifacts"]["cv"] == r["sha256"]


def test_task_waits_for_programme_sop_when_needed(api):
    plan = start(api)
    tasks = apply_tasks(api, plan)
    for art in (written(api), written(api, "cv", text="Example University, BSc.")):
        api.post(f"{P}/statements/{art}/approve", headers=me(), json={"version": 1})
    assert task_state(api, tasks["p1"]).state == "waiting_student"
    own = written(api, "sop", "p1", "Why p1: Example University.")
    r = api.post(f"{P}/statements/{own}/approve", headers=me(), json={"version": 1}).json()
    assert r["completed_tasks"] == [tasks["p1"]]
    assert task_state(api, tasks["p1"]).result["artifacts"]["programme_sop"] == r["sha256"]


def test_student_sees_only_own(api):
    start(api)
    start(api, "stu-2")
    art = written(api)
    assert api.get(f"{P}/statements", headers=me("stu-2")).json() == {"statements": []}
    for call in (lambda: api.put(f"{P}/statements/{art}/text", headers=me("stu-2"), json={"text": "Mine now."}),
                 lambda: api.post(f"{P}/statements/{art}/approve", headers=me("stu-2"), json={"version": 1})):
        assert call().status_code == 404
    assert api.get(f"{P}/statements", headers=me("stu-3")).json() == {"statements": []}
    assert api.get(f"{P}/statements/interview", headers=me("stu-3")).status_code == 404


def test_pasted_rules_put(api):
    start(api)
    r = api.put(f"{P}/statements/rules/p2", headers=me(), json={"prompt": "Why p2?", "limit_words": 600})
    assert r.status_code == 204
    assert api.put(f"{P}/statements/rules/p9", headers=me(), json={"limit_words": 600}).status_code == 404
    assert api.put(f"{P}/statements/rules/p2", headers=me(), json={"limit_words": 0}).status_code == 422
    with api.engine.connect() as conn:
        row = conn.execute(select(models.statement_rules)).one()
    assert (row.student_ref, row.programme_ref, row.prompt, row.limit_words) == ("stu-1", "p2", "Why p2?", 600)


def test_deleting_a_student_deletes_statements(api):
    start(api)
    answer_all(api)
    written(api)
    api.put(f"{P}/statements/rules/p2", headers=me(), json={"limit_words": 600})
    delete_statements(api.engine, TENANT, "stu-1")
    with api.engine.connect() as conn:
        for table in (models.artifacts, models.artifact_versions, models.statement_answers, models.statement_rules):
            assert conn.execute(select(table)).all() == []
