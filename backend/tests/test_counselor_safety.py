"""Offline safety contracts and pre-post routing, with fake providers only."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from app.config import config
from app.inference import gateway
from app.pai_c import runtime
from app.pai_c.safety import gate
from app.models import CounselorTurnDecision
from scripts.counselor_eval_support import StudentSession


def answer(reply):
    return SimpleNamespace(reply=reply, action={"type":"none"},
        context=SimpleNamespace(build_ms=1, notebook=SimpleNamespace(mirror_ready=False)),
        model_ms=1, polish_ms=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("text,level,category", [
    ("I have a plan to hurt myself tonight.", "urgent", "self_harm"),
    ("main aaj khud ko nuqsan pohanchane ka irada rakhta hoon", "urgent", "self_harm"),
    ("Someone at home keeps hurting me and I feel unsafe.", "concern", "abuse"),
    ("ghar mein koi mujhe marta hai aur main unsafe feel karta hoon", "concern", "abuse"),
    ("I have felt hopeless for weeks and cannot cope.", "concern", "acute_distress"),
    ("kai hafton se hope nahi aur cope nahi kar pa raha", "concern", "acute_distress"),
    ("I am worried about my exam.", "none", None),
    ("My family wants a different degree.", "none", None),
    ("I'm confused about my career.", "none", None),
])
async def test_safety_routes_fixtures_before_post(text, level, category):
    model = AsyncMock(return_value=json.dumps({"level":level,"category":category}))
    voice = AsyncMock(side_effect=lambda *a, **kw: answer(
        "That sounds difficult. Please reach out to someone you trust." if kw.get("instructions") else "Which degree interests you?"))
    with StudentSession() as student, patch.object(config,"PAI_API_KEY","fake-only"), \
            patch.object(gate,"complete",model), patch("app.pai_c.deep.turn.run_deep_turn",voice):
        await student.turn(text)
        replies = [r for r in student.transcript if r["role"]=="assistant"]
        assert len(replies)==1
        assert voice.await_count == (1 if level=="none" else 2)
        assert replies[0]["content"] == ("Which degree interests you?" if level=="none" else
            "That sounds difficult. Please reach out to someone you trust.")
        with student.factory() as db:
            row = db.scalar(select(CounselorTurnDecision))
            assert row.safety_level == level and row.safety_category == category
            assert row.move == ("none" if level=="none" else "wellbeing")
            assert "safety_reason" not in row.__table__.columns
    assert model.await_args.kwargs["role"] == "safety"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ['{}','{"level":"invalid","category":null}',
    '{"level":"urgent","category":null,"reason":"private"}', 'not json'])
async def test_invalid_safety_json_fails_open_without_text_logs(response, caplog):
    with StudentSession() as student, patch.object(config,"PAI_API_KEY","fake-only"), \
            patch.object(gate,"complete",AsyncMock(return_value=response)), \
            patch("app.pai_c.deep.turn.run_deep_turn",AsyncMock(return_value=answer("Normal reply?"))):
        await student.turn("private student content")
        assert student.transcript[-1]["content"] == "Normal reply?"
    assert "safety_gate_error" in caplog.text
    assert "private student content" not in caplog.text
    assert "reason" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["error", "timeout"])
async def test_safety_error_and_timeout_fail_open(mode, caplog):
    async def fake(**kwargs):
        if mode=="error":raise RuntimeError("private student content")
        await asyncio.sleep(1)
    with StudentSession() as student, patch.object(config,"PAI_API_KEY","fake-only"), \
            patch.object(config,"PAI_SAFETY_TIMEOUT_MS",5), patch.object(gate,"complete",fake), \
            patch("app.pai_c.deep.turn.run_deep_turn",AsyncMock(return_value=answer("Normal reply?"))):
        await student.turn("private student content")
        assert student.transcript[-1]["content"] == "Normal reply?"
    assert "safety_gate_error" in caplog.text and "private student content" not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_normal_completion_is_not_posted_before_gate_finishes():
    normal_finished=asyncio.Event()
    with StudentSession() as student, patch.object(config,"PAI_API_KEY","fake-only"):
        async def safety(**kwargs):
            await asyncio.wait_for(normal_finished.wait(),1)
            assert not any(r["role"]=="assistant" for r in student.transcript)
            return '{"level":"urgent","category":"self_harm"}'
        async def voice(*args,**kwargs):
            if not kwargs.get("instructions"):
                normal_finished.set()
                return answer("Discard this normal reply?")
            return answer("Please reach out to someone you trust.")
        with patch.object(gate,"complete",safety), patch("app.pai_c.deep.turn.run_deep_turn",voice):
            await student.turn("fixture")
        assert student.transcript[-1]["content"] == "Please reach out to someone you trust."


@pytest.mark.asyncio
async def test_wellbeing_failure_uses_configured_fallback_and_resources(caplog):
    with StudentSession() as student, patch.object(config,"PAI_API_KEY","fake-only"), \
            patch.object(config,"PAI_WELLBEING_FALLBACK_REPLY","Please speak to someone you trust."), \
            patch.object(config,"PAI_WELLBEING_RESOURCES","Configured resource"), \
            patch.object(gate,"complete",AsyncMock(return_value='{"level":"urgent","category":"self_harm"}')), \
            patch("app.pai_c.deep.turn.run_deep_turn",AsyncMock(side_effect=[answer("Discard?"),RuntimeError("private text")])):
        await student.turn("private text")
        assert student.transcript[-1]["content"] == "Please speak to someone you trust.\n\nConfigured resource"
        assert "private text" not in caplog.text


@pytest.mark.asyncio
async def test_safety_input_is_text_only_and_last_four_messages():
    model=AsyncMock(return_value='{"level":"none","category":null}')
    turns=[{"role":"user","content":str(i),"event_id":"private-id"} for i in range(10)]
    with patch.object(gate,"complete",model):await gate.check_message("current",turns)
    data=json.loads(model.await_args.kwargs["messages"][0]["content"])
    assert data=={"recent_turns":[{"role":"user","text":str(i)} for i in range(6,10)],"student_message":"current"}


@pytest.mark.parametrize("safety,analyst,expected", [("s","a","s"),("","a","a"),("","","p")])
def test_safety_model_chain(safety,analyst,expected):
    with patch.object(config,"PAI_SAFETY_MODEL",safety), patch.object(config,"PAI_ANALYST_MODEL",analyst), \
            patch.object(config,"PAI_MODEL","p"):
        assert gateway.resolve_model("safety")==expected
        assert gateway.reasoning_effort("safety")==config.PAI_SAFETY_REASONING_EFFORT


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["concern", "urgent"])
async def test_wellbeing_turn_uses_shared_language_policy_and_urgent_resources(level):
    from unittest.mock import Mock
    from app.pai_c.deep import turn as turn_module
    from app.pai_c.deep.turn_input import CounselorTurnInput
    current = CounselorTurnInput("chat", "workspace", "fixture", (), None, "event", None, "human:student")
    model = AsyncMock(return_value='{"reply":"Please reach out to someone you trust.","action":{"type":"wellbeing"}}')
    context = SimpleNamespace(text="<language_policy>configured policy</language_policy>", build_ms=0)
    db = SimpleNamespace(rollback=Mock())
    with patch.object(turn_module,"build_context",AsyncMock(return_value=context)), \
            patch.object(turn_module,"chat_completion",model), \
            patch.object(config,"PAI_WELLBEING_RESOURCES","Configured resource"):
        result = await turn_module.run_deep_turn(db,current,history=[],instructions="wellbeing",safety_level=level)
    prompt = model.await_args.kwargs["system_prompt"]
    assert "configured policy" in prompt
    assert "Do not ask a career question" in prompt
    assert ("<wellbeing_resources>Configured resource</wellbeing_resources>" in prompt) == (level=="urgent")
    assert result.action == {"type":"wellbeing"}
    db.rollback.assert_called_once()


def test_safety_migration_upgrade_and_downgrade():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "alembic/versions/104_safety_and_turn_plans.py"
    spec = importlib.util.spec_from_file_location("safety_migration",path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE pai_counselor_turn_decisions (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO pai_counselor_turn_decisions (id) VALUES ('old')"))
        with patch.object(migration,"op",Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            columns = {c["name"]:c for c in sa.inspect(connection).get_columns("pai_counselor_turn_decisions")}
            assert columns["safety_level"]["nullable"] and columns["safety_category"]["nullable"]
            assert connection.execute(sa.text("SELECT safety_level, safety_category FROM pai_counselor_turn_decisions")).one() == (None,None)
            migration.downgrade()
        assert [c["name"] for c in sa.inspect(connection).get_columns("pai_counselor_turn_decisions")] == ["id"]
        assert connection.execute(sa.text("SELECT id FROM pai_counselor_turn_decisions")).scalar_one() == "old"
    engine.dispose()
