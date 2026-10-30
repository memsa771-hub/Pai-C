"""Slice 5 Task 6: the os.statement workflow (spec S5-D3, S5-D6, S5-D10).

DBOS runs in this process (as in test_document_run). The Writer and the Critic are one FunctionModel that answers by
system prompt, from queues each test sets; every answer and profile value is fictional.
"""

from datetime import datetime, timezone

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import insert, select, text

from app.os import models
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.artifacts.store import ArtifactStore
from app.os.documents.store import ProfileStore
from app.os.settings import load_settings
from app.os.statements.agents import build_agents
from app.os.statements.config import load_statement_configs
from app.os.statements.interview import start_draft
from app.os.statements.run import enqueue_statement, inputs_for, inputs_sha, register_statements, \
    statement_workflow_id
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema

TENANT = "pai"
STUDENT = "student-1"
YEAR = 2027
NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
WSPEC = load_agent_spec(AGENT_DIR / "writer.v1.yaml")
CSPEC = load_agent_spec(AGENT_DIR / "critic.v1.yaml")
CONFIGS = load_statement_configs()
[ROUTE] = CONFIGS
ANS = models.statement_answers

# Fictional material only.
ANSWERS = {"field_why": "A traffic project at Example University got me into data science.",
           "key_project": "I built a bus delay predictor with three classmates."}
CLEAN = "A traffic project at Example University got me into data science."
OK = {"scores": {"Motivation": 4}, "fixes": [], "follow_ups": [], "ok": True}
NOT_OK = {"scores": {"Motivation": 2}, "fixes": ["Say more about the project"], "follow_ups": [], "ok": False}


class Ctx:
    def __init__(self, engine, client):
        self.engine, self.client = engine, client
        self.writer: list[dict] = [{"text": CLEAN}]  # answers in order; the last one repeats
        self.critic: list[dict] = [OK]
        self.prompts: dict[str, list[str]] = {"writer": [], "critic": []}
        self.store = ArtifactStore(engine, TENANT)

    def answer(self, student: str = STUDENT, answers: dict = ANSWERS) -> None:
        with self.engine.begin() as conn:
            for qid, a in answers.items():
                conn.execute(insert(ANS).values(tenant_id=TENANT, student_ref=student, question_id=qid, answer=a))

    def sha(self, artifact_id: int) -> str:
        art = self.store.get(artifact_id)
        return inputs_sha(inputs_for(self.engine, TENANT, CONFIGS[ROUTE], art.student_ref, art.kind,
                                     art.programme_ref, None, YEAR))

    def draft(self, artifact_id: int) -> dict:
        wid = enqueue_statement(self.client, TENANT, artifact_id, ROUTE, YEAR, self.sha(artifact_id))
        return self.client.retrieve_workflow(wid).get_result()

    def sop(self, student: str = STUDENT) -> int:
        return self.store.get_or_create(student, "sop", None).id


def _prompt(messages) -> str:
    return " ".join(str(p.content) for m in messages for p in m.parts if isinstance(p, UserPromptPart))


def make_statements(engine, os_db, clock=lambda: NOW) -> Ctx:
    from dbos import DBOS, DBOSClient

    from app.os.kernel import Kernel
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    holder: dict = {}

    def fn(messages, info: AgentInfo) -> ModelResponse:
        ctx: Ctx = holder["ctx"]
        system = " ".join(p.content for m in messages for p in m.parts if p.part_kind == "system-prompt")
        who = "writer" if "You co-write" in system else "critic"
        queue = ctx.writer if who == "writer" else ctx.critic
        ctx.prompts[who].append(_prompt(messages))
        args = queue[0] if len(queue) == 1 else queue.pop(0)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    writer, critic = build_agents(FunctionModel(fn), WSPEC, CSPEC)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, TENANT))
    register_statements(engine, settings, writer, critic, WSPEC, CSPEC, CONFIGS, None, clock=clock)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    ctx = Ctx(engine, client)
    holder["ctx"] = ctx
    return ctx


def stop(ctx: Ctx) -> None:
    from dbos import DBOS

    ctx.client.destroy()
    DBOS.destroy(destroy_registry=True)


@pytest.fixture
def statements(os_db, engine, clean):
    ctx = make_statements(engine, os_db)
    try:
        yield ctx
    finally:
        stop(ctx)


def agent_rows(engine):
    with engine.connect() as conn:
        return conn.execute(select(models.agent_runs).order_by(models.agent_runs.c.id)).all()


def test_draft_stored_with_critic_report(statements):
    statements.answer()
    art = statements.sop()
    assert statements.draft(art) == {"status": "draft", "version": 1, "flags": 0}
    v = statements.store.version(art, 1)
    assert v.text == CLEAN and v.author == "writer" and v.flags == [] and v.limit_words == 1000
    assert v.critic["ok"] is True and v.critic["scores"] == {"Motivation": 4}
    assert statements.store.get(art).status == "draft"
    rows = agent_rows(statements.engine)
    assert [r.agent for r in rows] == ["writer", "critic"] and {r.artifact_id for r in rows} == {art}


def test_two_revisions_then_stops(statements):
    statements.answer()
    statements.critic = [NOT_OK]
    art = statements.sop()
    assert statements.draft(art)["status"] == "draft"
    assert len(statements.prompts["writer"]) == 3 and len(statements.prompts["critic"]) == 3  # 1 + 2 revisions
    assert "Say more about the project" in statements.prompts["writer"][1]
    assert [v.number for v in statements.store.versions(art)] == [1]  # one stored version per run


def test_flags_sent_back_to_writer(statements):
    statements.answer()
    statements.writer = [{"text": CLEAN + " I won the National Robotics Olympiad in 2019."}, {"text": CLEAN}]
    art = statements.sop()
    assert statements.draft(art) == {"status": "draft", "version": 1, "flags": 0}
    second = statements.prompts["writer"][1]
    assert "remove them" in second and "2019" in second and "National Robotics Olympiad" in second
    assert "2019" in statements.prompts["critic"][0]  # the Critic sees the flags too
    assert statements.store.version(art, 1).flags == []


def test_flags_kept_when_writer_does_not_remove_them(statements):
    statements.answer()
    statements.writer = [{"text": CLEAN + " I scored 98 in 2019."}]
    art = statements.sop()
    result = statements.draft(art)
    assert result["status"] == "draft" and result["flags"] == 2
    assert set(statements.store.version(art, 1).flags) == {"98", "2019"}


def test_follow_ups_wait_for_answers(statements):
    statements.answer()
    statements.critic = [OK | {"ok": False, "follow_ups": ["Which tools did you use?"]}]
    art = statements.sop()
    assert statements.draft(art) == {"status": "needs_answers"}
    assert statements.store.get(art).status == "needs_answers"
    with statements.engine.connect() as conn:
        rows = conn.execute(select(ANS.c.question_id, ANS.c.question, ANS.c.answer)
                            .where(ANS.c.question_id.like("followup:%"))).all()
    assert [tuple(r) for r in rows] == [("followup:1", "Which tools did you use?", "")]
    assert [v.number for v in statements.store.versions(art)] == [1]  # the draft so far is kept
    with statements.engine.begin() as conn:  # the student answers: new inputs, a new draft
        conn.execute(ANS.update().where(ANS.c.question_id == "followup:1").values(answer="Python and pandas."))
    statements.critic = [OK]
    assert statements.draft(art)["status"] == "draft"
    assert "Python and pandas." in statements.prompts["writer"][-1]


def test_same_inputs_not_drafted_twice(statements):
    statements.answer()
    art = statements.sop()
    first = statements.draft(art)
    assert statements.draft(art) == first
    assert len(statements.prompts["writer"]) == 1 and len(statements.store.versions(art)) == 1


def test_inputs_are_one_students_only(statements):
    statements.answer()
    statements.answer("student-2", {"field_why": "Another student's secret story."})
    profile = ProfileStore(statements.engine, TENANT)
    profile.set(STUDENT, "transcript.cgpa", 3.4, None)
    profile.set(STUDENT, "passport.number", "ZZ0000000", None)  # not a key the SOP may use
    profile.set("student-2", "transcript.cgpa", 2.1, None)
    inputs = inputs_for(statements.engine, TENANT, CONFIGS[ROUTE], STUDENT, "sop", None, None, YEAR)
    assert inputs.profile == {"transcript.cgpa": 3.4}
    assert set(inputs.answers.values()) == set(ANSWERS.values())
    statements.draft(statements.sop())
    sent = " ".join(statements.prompts["writer"] + statements.prompts["critic"])
    assert "secret story" not in sent and "ZZ0000000" not in sent and "2.1" not in sent and "3.4" in sent


def test_budget_exceeded_waits(os_db, engine, clean):
    """Over the month's cap nothing is drafted and the student sees `budget`; next month Write again drafts."""
    now = {"t": NOW}
    ctx = make_statements(engine, os_db, clock=lambda: now["t"])
    try:
        ctx.answer()
        art = ctx.sop()
        with engine.begin() as conn:  # this month's statements budget is spent
            conn.execute(insert(models.agent_runs).values(
                tenant_id=TENANT, artifact_id=art, reading="earlier", agent="writer", agent_version=1, model="m",
                cost_usd=10.0, at=datetime(2026, 10, 5, tzinfo=timezone.utc)))
        assert ctx.draft(art) == {"status": "budget"}
        with engine.connect() as conn:
            [event] = conn.execute(select(models.events.c.payload)
                                   .where(models.events.c.type == "budget_exceeded")).scalars().all()
        assert event["artifact_id"] == art and event["cap_usd"] == 10.0 and event["spent_usd"] == 10.0
        assert ctx.prompts == {"writer": [], "critic": []} and ctx.store.get(art).status == "budget"
        now["t"] = datetime(2026, 11, 2, tzinfo=timezone.utc)  # a new month: the same inputs get a new attempt
        wid = start_draft(engine, ctx.client, TENANT, CONFIGS[ROUTE], art, YEAR, None)
        assert wid.endswith(":2") and ctx.client.retrieve_workflow(wid).get_result()["status"] == "draft"
    finally:
        stop(ctx)


def test_write_again_after_failure_runs_again(statements):
    """Final review: the same inputs after a failed run must draft again, not return the finished workflow."""
    statements.answer()
    statements.writer = [{"no_text": 1}]
    art = statements.sop()
    cfg = CONFIGS[ROUTE]
    first = start_draft(statements.engine, statements.client, TENANT, cfg, art, YEAR, None)
    assert statements.store.get(art).status == "drafting"  # at once, before the worker starts: the page polls
    assert statements.client.retrieve_workflow(first).get_result() == {"status": "failed"}
    statements.writer = [{"text": CLEAN}]
    again = start_draft(statements.engine, statements.client, TENANT, cfg, art, YEAR, None)
    assert again != first and statements.client.retrieve_workflow(again).get_result()["status"] == "draft"
    assert start_draft(statements.engine, statements.client, TENANT, cfg, art, YEAR, None) is None  # drafted
    assert statements.store.get(art).status == "draft"


def test_model_requests_are_dbos_steps(statements):
    statements.answer()
    art = statements.sop()
    statements.draft(art)
    wid = statement_workflow_id(TENANT, art, statements.sha(art))
    with statements.engine.connect() as conn:
        names = conn.execute(text(
            f"SELECT function_name FROM {TEST_DBOS_SCHEMA}.operation_outputs WHERE workflow_uuid = :w "
            "ORDER BY function_id"), {"w": wid}).scalars().all()
    assert sum("model.request" in n for n in names) == 2
    assert [n for n in names if n.startswith("os.statement.")] == [
        "os.statement.start", "os.statement.load", "os.statement.record", "os.statement.record",
        "os.statement.store"]


def test_failed_run_marks_failed(statements):
    statements.answer()
    statements.writer = [{"no_text": 1}]  # never valid: 1 + 2 repairs, then the Writer gives up
    art = statements.sop()
    assert statements.draft(art) == {"status": "failed"}
    assert statements.store.get(art).status == "failed" and statements.store.versions(art) == []
    [row] = agent_rows(statements.engine)
    assert row.agent == "writer" and row.error and "no_text" not in row.error  # the error kind only
