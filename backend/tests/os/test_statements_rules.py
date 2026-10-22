"""Slice 5 Task 4: statement rules, researched, pasted or default (spec S5-D2)."""

from datetime import datetime, timezone

from sqlalchemy import insert

from app.os import models
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.profile import load_profile_dir, reading_model
from app.os.statements.config import load_statement_configs
from app.os.statements.rules import resolve_rules

CFG = load_statement_configs()["germany_master"]
NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def rules(engine, kind="sop", ref="p1"):
    return resolve_rules(engine, "pai", SqlKnowledge(engine, "pai"), "stu-1", ref, 2027, CFG, kind)


def paste(engine, prompt="Why this programme?", words=500):
    with engine.begin() as conn:
        conn.execute(insert(models.statement_rules).values(tenant_id="pai", student_ref="stu-1", programme_ref="p1",
                                                           prompt=prompt, limit_words=words))


def test_researched_rule_wins(engine, clean):
    SqlKnowledge(engine, "pai").upsert("programme", "p1", "statement_requirement", Fact(
        {"limit_words": 800, "limit_chars": None}, "", "https://uni.example/a", NOW, 2027, "unconfirmed"), "research")
    paste(engine)
    r = rules(engine)
    assert (r.needed, r.limit_words, r.source, r.status, r.prompt) == (True, 800, "research", "unconfirmed",
                                                                      "Why this programme?")


def test_student_paste_when_not_researched(engine, clean):
    paste(engine)
    r = rules(engine)
    assert (r.needed, r.limit_words, r.prompt, r.source) == (True, 500, "Why this programme?", "student")


def test_default_labelled(engine, clean):
    r = rules(engine)
    assert (r.needed, r.limit_words, r.source) == (False, 1000, "default")
    base = rules(engine, ref=None)
    assert (base.needed, base.limit_words, base.source) == (True, 1000, "default")


def test_cv_uses_default(engine, clean):
    paste(engine)
    r = rules(engine, kind="cv")
    assert (r.limit_words, r.source) == (700, "default")


def test_profile_field_loads_and_reading_model_accepts_it():
    profile = load_profile_dir()["germany_master"]
    spec = next(f for f in profile.fields if f.name == "statement_requirement")
    assert (spec.type, spec.parts) == ("numbers", ["limit_words", "limit_chars"])
    model = reading_model(profile)
    found = model.model_validate({"statement_requirement": {
        "value": {"limit_words": 1000, "limit_chars": None}, "quote": "at most 1,000 words",
        "url": "https://uni.example/a"}})
    assert found.statement_requirement.value.limit_words == 1000
