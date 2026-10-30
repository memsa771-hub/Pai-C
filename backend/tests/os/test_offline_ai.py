"""Slice 9a Task 4: offline AI for rehearsals (spec §2.3).

Canned, repeatable, zero-cost answers from the files in tests/os/rehearsal/answers/. The answers are test data
(invariant 12); app/os only reads the folder OS_OFFLINE_ANSWERS_DIR names. Output validation still runs (invariant 7).
"""

import io
import logging
from datetime import date
from pathlib import Path

import pytest
import yaml
from PIL import Image
from pydantic_ai.usage import RunUsage
from sqlalchemy import select

from app.os import models
from app.os.agents.offline import offline_model
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.documents.intake import PagePart, check_upload, prepare
from app.os.documents.reader import build_readers, read_document
from app.os.documents.types import load_document_types, reading_model
from app.os.knowledge.research.readings import cost
from app.os.settings import load_settings

ANSWERS = Path(__file__).resolve().parent / "rehearsal" / "answers"
SAMPLES = Path(__file__).resolve().parent / "fixtures" / "documents" / "samples"
BASE = {"OS_DATABASE_URL": "postgresql://unused/x"}
OFFLINE = {**BASE, "OS_MODEL_MODE": "offline", "OS_REHEARSAL": "on", "OS_OFFLINE_ANSWERS_DIR": str(ANSWERS)}
TYPES = load_document_types()
DOC_SPEC = load_agent_spec(AGENT_DIR / "documents.v1.yaml")


# --- settings ------------------------------------------------------------------------------------------------


def test_offline_refused_without_rehearsal():
    with pytest.raises(ValueError, match="OS_REHEARSAL"):
        load_settings({**OFFLINE, "OS_REHEARSAL": ""})


def test_unknown_mode_refused():
    with pytest.raises(ValueError, match="OS_MODEL_MODE"):
        load_settings({**BASE, "OS_MODEL_MODE": "anthropic"})


def test_offline_needs_answers_dir():
    with pytest.raises(ValueError, match="OS_OFFLINE_ANSWERS_DIR"):
        load_settings({**OFFLINE, "OS_OFFLINE_ANSWERS_DIR": ""})


def test_mode_defaults_and_offline_accepted():
    assert load_settings(BASE).model_mode == "openai" and load_settings(BASE).offline_answers_dir is None
    s = load_settings(OFFLINE)
    assert (s.model_mode, s.offline_answers_dir, s.rehearsal) == ("offline", str(ANSWERS), True)


# --- documents -----------------------------------------------------------------------------------------------


def _sample_key() -> dict:
    return yaml.safe_load((SAMPLES / "samples_key.yaml").read_text(encoding="utf-8"))["documents"]


def test_documents_answers_current():
    """The committed documents.yaml matches what make_answers computes on this machine's Pillow."""
    from tests.os.rehearsal.make_answers import answers

    committed = yaml.safe_load((ANSWERS / "documents.yaml").read_text(encoding="utf-8"))
    fresh = answers()
    stale = sorted({e["file"] for e in committed.values()} ^ {e["file"] for e in fresh.values()}
                   | {e["file"] for k, e in fresh.items() if committed.get(k) != e})
    assert committed == fresh, (
        f"documents.yaml is stale for this Pillow (differs for {stale}); "
        "run `python -m tests.os.rehearsal.make_answers` from backend/ and commit the result")


def test_document_answer_by_hash():
    model = offline_model("documents", ANSWERS)
    assert model.model_name == "offline"
    readers = build_readers(model, TYPES, DOC_SPEC)
    for name, doc in _sample_key().items():  # every sample, as the pipeline prepares and tiles it
        data = (SAMPLES / name).read_bytes()
        t = TYPES[doc["type"]]
        r = read_document(readers[doc["type"]], DOC_SPEC, t, prepare(data, check_upload(name, data)))
        assert r.error is None, (name, r.error)
        assert r.detected_type == doc["type"], name
        want = reading_model(t).model_validate({f.name: doc["fields"].get(f.name) for f in t.fields}).model_dump()
        want.pop("detected_type")
        assert r.values == want, name  # the key's values, as the reading model holds them


def _blank_jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1000, 1200), (250, 250, 250)).save(out, "JPEG")
    return out.getvalue()


def test_missing_answer_fails_validation(caplog):
    import hashlib

    from app.os.documents.intake import tiles

    readers = build_readers(offline_model("documents", ANSWERS), TYPES, DOC_SPEC)
    image = _blank_jpeg()
    missing = hashlib.sha256(tiles(image)[0]).hexdigest()  # the first tile is what reaches the model first
    with caplog.at_level(logging.WARNING, logger="app.os.agents.offline"):
        r = read_document(readers["ielts_trf"], DOC_SPEC, TYPES["ielts_trf"], [PagePart(1, None, image, "image/jpeg")])
    # the normal invalid-output path: output validation fails, 1 + 2 repairs, then the reading is an error
    assert r.values is None and r.error and r.usage.requests == 1 + DOC_SPEC.retries.output
    assert any(missing in rec.getMessage() for rec in caplog.records)  # a driver can name the missing key


# --- research ------------------------------------------------------------------------------------------------


def test_research_offline_makes_no_fetch(os_db, engine, clean, monkeypatch):
    from dbos import DBOS, DBOSClient

    from app.os.kernel import Kernel
    from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
    from app.os.knowledge.programmes import Programme, ProgrammeStore
    from app.os.knowledge.research import pages
    from app.os.playbooks import load_playbook_dir
    from app.os.runner import (
        APP_NAME,
        dbos_config,
        default_registry,
        launch,
        register_workflow,
        worker,
    )
    from app.os.service import PlanService
    from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
    from tests.os.test_research_run import (
        PAGES,
        confirm_tasks,
        research_today,
        start_and_wait,
    )

    fetched: list[str] = []
    monkeypatch.setattr(pages.PageGateway, "fetch", lambda self, url, *a: fetched.append(url))
    reset_dbos_schema(os_db)
    settings = load_settings({**OFFLINE, "OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    assert settings.openai_api_key is None
    kernel = Kernel(engine, "pai")
    service = PlanService(engine, settings, kernel, SqlKnowledge(engine, "pai"), load_playbook_dir(),
                          today=lambda: date(2027, 2, 1))
    store = ProgrammeStore(engine, "pai")
    for ref, (url, domain, title) in PAGES.items():
        store.upsert(Programme(ref=ref, route_key="germany_master", university=ref.split("-")[0], name=ref,
                               aliases=(), start_urls=(url,), official_domains=(domain,)))
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), kernel)
    assert worker.register_research_if_configured(settings, engine, kernel) is True  # offline counts as configured
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)

    class Ctx:
        pass

    ctx = Ctx()
    ctx.engine, ctx.client, ctx.kernel, ctx.service = engine, client, kernel, service
    F = models.knowledge_facts
    try:
        load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
        plan_id = start_and_wait(ctx)
        with engine.connect() as conn:
            before = conn.execute(select(F).order_by(F.c.id)).all()
        assert research_today(ctx) > 0
        with engine.connect() as conn:
            after = conn.execute(select(F).order_by(F.c.id)).all()
            runs = conn.execute(select(models.research_runs.c.status, models.research_runs.c.cost_usd)).all()
            agent_runs = conn.execute(select(models.agent_runs.c.model, models.agent_runs.c.cost_usd)).all()
            stored_pages = conn.execute(select(models.pages.c.url)).all()
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)
    assert fetched == [] and stored_pages == []  # no page fetch, nothing cached
    assert after == before  # facts unchanged
    assert runs and all(r.status == "done" and float(r.cost_usd) == 0 for r in runs)
    assert agent_runs and all(r.model == "offline" and float(r.cost_usd) == 0 for r in agent_runs)
    waiting = {t["result"].get("waiting_for") for k, t in confirm_tasks(engine, plan_id).items()
               if t["state"] == "waiting_review" and ":deadline_close" in k}
    assert waiting == {"research"}  # unconfirmed stays as the student would see it


# --- writer, critic, supervisor ------------------------------------------------------------------------------


def _inputs(limit_words=None, limit_chars=None, kind="sop"):
    from app.os.statements.agents import Inputs
    from app.os.statements.rules import Rules

    answers = {f"Question {i}?": " ".join(["I built a small robot arm with my friends"] * 6) for i in range(6)}
    profile = {"degree_title": "Bachelor of Science in Computer Science", "cgpa": 3.4}
    rules = Rules(needed=True, limit_words=limit_words, limit_chars=limit_chars, prompt=None, source="default")
    return Inputs(kind=kind, answers=answers, profile=profile, rules=rules, rubric=["clarity", "fit", "evidence"])


def _statement_agents():
    from app.os.statements.agents import build_agents

    wspec, cspec = load_agent_spec(AGENT_DIR / "writer.v1.yaml"), load_agent_spec(AGENT_DIR / "critic.v1.yaml")
    writer, critic = build_agents(offline_model("writer", ANSWERS), wspec, cspec,
                                  critic_model=offline_model("critic", ANSWERS))
    return writer, critic, wspec, cspec


def test_writer_draft_within_word_limit():
    from app.os.statements.agents import review, write
    from app.os.statements.facts_check import unsupported

    writer, critic, wspec, cspec = _statement_agents()
    for limit in (40, 120):
        inputs = _inputs(limit_words=limit)
        r = write(writer, wspec, inputs)
        assert r.error is None and 0 < len(r.output.text.split()) <= limit
        assert "robot arm" in r.output.text
    r = write(writer, wspec, _inputs(limit_chars=300, kind="cv"))
    assert r.error is None and 0 < len(r.output.text) <= 300
    full = write(writer, wspec, _inputs(limit_words=2000)).output.text
    assert "Bachelor of Science in Computer Science" in full and "3.4" in full  # the confirmed profile is used
    from app.os.statements.run import sources as fact_sources

    assert unsupported(full, fact_sources(_inputs(limit_words=2000))) == []  # nothing invented
    rev = review(critic, cspec, _inputs(limit_words=120), full)
    assert rev.error is None and rev.output.ok and not rev.output.fixes and not rev.output.follow_ups
    assert set(rev.output.scores) == {"clarity", "fit", "evidence"}


def test_supervisor_answers_by_event_type(caplog):
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from app.os.replan.events import EVENT_TYPES
    from app.os.replan.ops import Escalate
    from app.os.replan.supervisor import build_supervisor

    spec = load_agent_spec(AGENT_DIR / "supervisor.v1.yaml")
    agent = build_supervisor(offline_model("supervisor", ANSWERS), spec)
    canned = yaml.safe_load((ANSWERS / "supervisor.yaml").read_text(encoding="utf-8"))
    assert set(canned) == set(EVENT_TYPES)
    import json

    from app.os.knowledge.research.readings import run_in_reading_loop

    def ask(event: dict):
        body = {"events": [event], "tasks": [], "steps": [], "programmes": [], "refused": [], "suggestions": {}}
        prompt = "Propose the operations for this plan.\n<<<PLAN>>>\n" + json.dumps(body) + "\n<<<END>>>"
        return run_in_reading_loop(lambda: agent.run(prompt))

    out = ask({"type": "deadline_at_risk", "instance_key": "apply@x"}).output
    assert out.ops and out.summary
    assert isinstance(ask({"type": "escalate"}).output.ops[0], Escalate)
    with caplog.at_level(logging.WARNING, logger="app.os.agents.offline"), pytest.raises(UnexpectedModelBehavior):
        ask({"type": "not_an_event"})
    assert any("not_an_event" in rec.getMessage() for rec in caplog.records)


# --- cost and worker wiring ----------------------------------------------------------------------------------


def test_offline_cost_zero():
    settings = load_settings(OFFLINE)
    usage = RunUsage(input_tokens=10_000, output_tokens=2_000)
    assert cost(usage, settings, "strong", model="offline") == 0
    assert cost(usage, settings, "strong", model="gpt-5.4") > 0
    assert cost(usage, settings, "strong") > 0


def test_worker_registers_every_agent_offline_without_key(monkeypatch):
    from app.os.documents import run as documents_run
    from app.os.runner import worker
    from app.os.statements import run as statements_run

    for hook in ("OS_TEST_DOCUMENT_MODEL", "OS_TEST_STATEMENT_MODEL", "OS_TEST_REPLAN_MODEL", "OS_TEST_RESEARCH_MODEL"):
        monkeypatch.delenv(hook, raising=False)
    seen: dict = {}
    monkeypatch.setattr(documents_run, "register_documents", lambda e, s, readers, *a: seen.update(docs=readers))
    monkeypatch.setattr(statements_run, "register_statements",
                        lambda e, s, writer, critic, *a: seen.update(writer=writer, critic=critic))
    settings = load_settings(OFFLINE)
    assert worker.register_documents_if_configured(settings, engine=None) is True
    assert worker.register_statements_if_configured(settings, engine=None) is True
    assert {a.model.model_name for a in seen["docs"].values()} == {"offline"}
    assert seen["writer"].model.model_name == seen["critic"].model.model_name == "offline"
    assert seen["writer"].model is not seen["critic"].model  # each agent answers from its own file
    online = load_settings(BASE)
    assert worker.register_documents_if_configured(online, engine=None) is False  # no key, not offline: still off


def test_api_refuses_to_start_offline_without_rehearsal():
    """Spec §7: the API refuses to start with the reason (it does not quietly switch the OS off)."""
    from fastapi import FastAPI

    from app.os.api.mount import mount_os

    env = {**OFFLINE, "OS_ENABLED": "true", "OS_REHEARSAL": ""}
    with pytest.raises(ValueError, match="OS_REHEARSAL"):
        mount_os(FastAPI(), env=env, student_dependency=lambda: "s")
    assert mount_os(FastAPI(), env={**env, "OS_ENABLED": ""}) is False  # OS off: nothing to refuse
