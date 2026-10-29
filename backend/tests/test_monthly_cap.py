"""One monthly cap for every model call: cost per role, stages, the roles each
stage stops, and the founder's usage view (offline; own SQLite database)."""
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.inference import gateway, usage
from app.memory.extractor import extract_candidates
from app.models import PaiUsageMonth
from app.pai_c.deep.turn import run_deep_turn
from app.pai_c.mirror.text_job import mirror_text_job
from app.pai_c.paths.analyzer import path_analysis_job
from app.research.gateway import request_research
from app.routers import admin_usage
from scripts.counselor_eval_support import StudentSession
from tests.test_counselor_deep_pr3 import _turn

pytestmark = pytest.mark.model_usage


def _spend(student, **scopes):
    with student.factory() as db:
        for scope, usd in scopes.items():
            db.add(PaiUsageMonth(id=str(uuid.uuid4()), scope=scope.replace("__", ":"),
                                 month=usage._month(), calls=1, est_usd=usd))
        db.commit()


@pytest.mark.asyncio
async def test_cost_recorded_per_role():
    anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        usage=SimpleNamespace(input_tokens=70, output_tokens=20, cache_read_input_tokens=30,
                              cache_creation_input_tokens=0)))), close=AsyncMock())
    openai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100, prompt_tokens_details=None),
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])))), close=AsyncMock())
    with StudentSession() as student, \
            patch.object(config, "ANTHROPIC_API_KEY", "anthropic-key"), \
            patch.object(config, "PAI_COUNSELOR_PROVIDER", "anthropic"), \
            patch.object(config, "PAI_COUNSELOR_MODEL", "claude-sonnet-5-5"), \
            patch("app.inference.anthropic_client.AsyncAnthropic", return_value=anthropic), \
            patch.object(gateway.transport, "create_client", return_value=openai):
        await gateway.complete("counselor", [{"role": "user", "content": "hi"}])
        await gateway.complete("counselor", [{"role": "user", "content": "hi"}])
        await gateway.complete("analyst", [], model="gpt-5", api_key="fake")
        with student.factory() as db:
            rows = {row.scope: row for row in db.scalars(select(PaiUsageMonth))}
    assert set(rows) == {"models:counselor", "models:analyst"}
    assert rows["models:counselor"].calls == 2
    assert float(rows["models:counselor"].est_usd) == pytest.approx(2 * (70 * 3 + 30 * 0.3 + 20 * 15) / 1e6)
    assert float(rows["models:analyst"].est_usd) == pytest.approx((1000 * 1.25 + 100 * 10) / 1e6)
    # An unpriced model uses the data's default rate.
    unknown = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0, prompt_tokens_details=None)
    assert usage.estimate_model_usd("some-new-model", unknown) == usage.model_costs()["usd_per_million_tokens"]["default"]["input"]


def test_cap_stages_count_every_scope():
    with StudentSession() as student, patch.object(config, "PAI_MONTHLY_CAP_USD", 100.0):
        assert usage.cap_state()["stage"] == "ok"
        _spend(student, models__counselor=50.0, embeddings=4.0)
        state = usage.cap_state()
        assert (state["spent"], state["cap"], state["stage"]) == (54.0, 100.0, "ok")
        _spend(student, models__analyst=26.0)
        assert usage.cap_state()["stage"] == "research_paused"
        _spend(student, models__mirror=20.0)
        assert usage.cap_state()["stage"] == "paused"
        # Rows of another month and unrelated scopes do not count.
        with student.factory() as db:
            db.add(PaiUsageMonth(id=str(uuid.uuid4()), scope="models:counselor", month="1999-01", calls=1, est_usd=500))
            db.commit()
        assert usage.cap_state()["spent"] == 100.0


@pytest.mark.asyncio
async def test_research_paused_skips_quietly_with_one_daily_log(caplog):
    with StudentSession() as student, patch.object(config, "PAI_MONTHLY_CAP_USD", 100.0), \
            patch.object(usage, "_gate_logged", {}), \
            patch("app.pai_c.mirror.text_job.chat_completion", AsyncMock()) as mirror_model, \
            patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock()) as analyst_model, \
            caplog.at_level(logging.WARNING, logger="app.inference.usage"):
        _spend(student, models__researcher=85.0)
        assert not usage.role_allowed("researcher") and not usage.role_allowed("researcher")
        assert usage.role_allowed("counselor") and usage.role_allowed("extractor")
        job = SimpleNamespace(id="job", workspace_id=student.workspace_id, payload={})
        assert (await mirror_text_job(job, Mock()))["status"] == "cap_paused"
        assert (await path_analysis_job(job, Mock()))["status"] == "cap_paused"
        with student.factory() as db:
            result = await request_research("path_explain", student.workspace_id, db=db, journey=None,
                                            tool_context=None, possibility_id="p")
        assert result == {"ok": False, "error": {"code": "research_paused"}}
    mirror_model.assert_not_awaited()
    analyst_model.assert_not_awaited()
    stopped = [r.getMessage() for r in caplog.records if "stopped at cap stage" in r.getMessage()]
    assert len([m for m in stopped if m.startswith("models: researcher ")]) == 1
    assert {m.split()[1] for m in stopped} == {"researcher", "mirror", "analyst"}


@pytest.mark.asyncio
async def test_paused_counselor_replies_fixed_and_extraction_stops():
    with StudentSession() as student, patch.object(config, "PAI_MONTHLY_CAP_USD", 100.0), \
            patch.object(usage, "_gate_logged", {}), \
            patch("app.pai_c.deep.turn.chat_completion", AsyncMock()) as counselor_model, \
            patch("app.memory.extractor.chat_completion", AsyncMock()) as extractor_model:
        _spend(student, models__counselor=100.0)
        with student.factory() as db:
            result = await run_deep_turn(db, _turn(student), history=[])
        assert result.reply == config.PAI_COUNSELOR_FALLBACK_REPLY + "\n\n" + usage.paused_line()
        assert usage.paused_line() == gateway.model_roles()["copy"]["paused_line"]
        assert result.guard_violations == ["cap_paused"]
        turn = SimpleNamespace(is_empty=lambda: False)
        output = await extract_candidates(turn, {"interest"})
        assert (output.candidates, output.drops) == ([], [])
    counselor_model.assert_not_awaited()
    extractor_model.assert_not_awaited()


def test_admin_usage_auth_and_shape():
    with StudentSession() as student, student.factory() as db, \
            patch.object(config, "PAI_MONTHLY_CAP_USD", 100.0), \
            patch.object(config, "PAI_FOUNDER_EMAILS", "Founder@example.com, other@example.com"):
        _spend(student, models__counselor=12.5, models__extractor=0.5, embeddings=0.25)
        with patch.object(admin_usage, "resolve_current_user", return_value=None):
            assert admin_usage.admin_usage(db=db, authorization=None).status_code == 401
        with patch.object(admin_usage, "resolve_current_user", return_value=SimpleNamespace(email="student@example.com")):
            assert admin_usage.admin_usage(db=db, authorization="Bearer x").status_code == 403
        with patch.object(admin_usage, "resolve_current_user", return_value=SimpleNamespace(email="founder@example.com")):
            body = admin_usage.admin_usage(db=db, authorization="Bearer x")
    data = body["data"]
    assert (data["month"], data["cap"], data["spent"], data["stage"]) == (usage._month(), 100.0, 13.25, "ok")
    assert data["by_role"] == [{"role": "counselor", "calls": 1, "est_usd": 12.5},
                               {"role": "extractor", "calls": 1, "est_usd": 0.5},
                               {"role": "embeddings", "calls": 1, "est_usd": 0.25}]
    from app.main import app
    assert any(getattr(route, "path", "") == "/v1/admin/usage" for route in app.routes)
