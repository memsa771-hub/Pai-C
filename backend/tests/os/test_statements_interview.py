"""Slice 5 Task 7: the interview, follow-ups and pasted rules (spec S5-D2, S5-D3). Fictional answers only."""

import pytest
from sqlalchemy import insert, select

from app.os import models
from app.os.statements.interview import (MAX_ANSWER_CHARS, answer_follow_up, interview, missing_required,
                                         save_answer, save_pasted_rules)
from app.os.statements.rules import pasted
from tests.os.test_statements_run import CONFIGS, OK, ROUTE, STUDENT, TENANT, YEAR, make_statements, stop

CFG = CONFIGS[ROUTE]
REQUIRED = [q.id for q in CFG.questions if q.required]


def answer_all(engine, student=STUDENT):
    for q in CFG.questions:
        if q.required:
            save_answer(engine, TENANT, student, CFG, q.id, f"My fictional answer to {q.id}.")


def test_answers_saved_and_listed(engine, clean):
    save_answer(engine, TENANT, STUDENT, CFG, "field_why", "  Traffic data got me hooked.  ")
    save_answer(engine, TENANT, STUDENT, CFG, "field_why", "Traffic data got me hooked, then maps.")
    items = interview(engine, TENANT, STUDENT, CFG)
    assert [i["id"] for i in items] == [q.id for q in CFG.questions]
    [why] = [i for i in items if i["id"] == "field_why"]
    assert why["answer"] == "Traffic data got me hooked, then maps." and why["follow_up"] is False
    assert interview(engine, TENANT, "student-2", CFG)[0]["answer"] == ""  # another student sees nothing


def test_unknown_question_refused(engine, clean):
    for qid in ("no_such_question", "followup:1"):  # no follow-up was asked yet
        with pytest.raises(ValueError, match="unknown question"):
            save_answer(engine, TENANT, STUDENT, CFG, qid, "x")


def test_missing_required_named(engine, clean):
    assert missing_required(engine, TENANT, STUDENT, CFG) == REQUIRED
    answer_all(engine)
    save_answer(engine, TENANT, STUDENT, CFG, REQUIRED[0], "   ")  # blank counts as missing
    assert missing_required(engine, TENANT, STUDENT, CFG) == [REQUIRED[0]]
    with engine.begin() as conn:
        conn.execute(insert(models.statement_answers).values(
            tenant_id=TENANT, student_ref=STUDENT, question_id="followup:1", question="Which tools?", answer=""))
    assert missing_required(engine, TENANT, STUDENT, CFG) == [REQUIRED[0], "followup:1"]
    assert interview(engine, TENANT, STUDENT, CFG)[0] == {
        "id": "followup:1", "prompt": "Which tools?", "hint": "", "required": True, "answer": "", "follow_up": True}


def test_long_answer_refused(engine, clean):
    with pytest.raises(ValueError, match="at most"):
        save_answer(engine, TENANT, STUDENT, CFG, "field_why", "x" * (MAX_ANSWER_CHARS + 1))
    save_answer(engine, TENANT, STUDENT, CFG, "field_why", "x" * MAX_ANSWER_CHARS)


def test_answering_follow_ups_resumes_draft(os_db, engine, clean):
    ctx = make_statements(engine, os_db)
    try:
        answer_all(engine)
        ctx.critic = [OK | {"ok": False, "follow_ups": ["Which tools?", "Who led the team?"]}, OK]
        art = ctx.sop()
        assert ctx.draft(art) == {"status": "needs_answers"}
        assert answer_follow_up(engine, ctx.client, TENANT, STUDENT, CFG, "followup:1", "Python.", YEAR, None) == []
        [wid] = answer_follow_up(engine, ctx.client, TENANT, STUDENT, CFG, "followup:2", "I did.", YEAR, None)
        assert ctx.client.retrieve_workflow(wid).get_result()["status"] == "draft"
        assert ctx.store.get(art).status == "draft" and "Who led the team?" in ctx.prompts["writer"][-1]
        with pytest.raises(ValueError):
            answer_follow_up(engine, ctx.client, TENANT, STUDENT, CFG, "field_why", "x", YEAR, None)
    finally:
        stop(ctx)


def test_pasted_rules_saved(engine, clean):
    save_pasted_rules(engine, TENANT, STUDENT, "prog-1", "  Why this programme?  ", 800, None)
    save_pasted_rules(engine, TENANT, STUDENT, "prog-1", "Why this programme, and why now?", None, 4000)
    row = pasted(engine, TENANT, STUDENT, "prog-1")
    assert (row.prompt, row.limit_words, row.limit_chars) == ("Why this programme, and why now?", None, 4000)
    assert pasted(engine, TENANT, "student-2", "prog-1") is None
    with pytest.raises(ValueError):
        save_pasted_rules(engine, TENANT, STUDENT, "prog-1", None, 0, None)
    with engine.connect() as conn:
        assert len(conn.execute(select(models.statement_rules)).all()) == 1
