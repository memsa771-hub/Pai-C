"""The statement interview (Slice 5 spec S5-D3): the route's fixed questions, the Critic's follow-ups, and the
prompt and limit a student pasted from a programme's page (the fallback rules, S5-D2).

Answers are the student's own words, stored as typed. Answering the last open follow-up starts the waiting draft
again: its inputs changed, so it gets a new workflow ID (invariant 8).
"""

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models
from app.os.artifacts.store import STATEMENT_KINDS, ArtifactStore
from app.os.statements.config import StatementConfig
from app.os.statements.run import enqueue_statement, inputs_for, inputs_sha, statement_workflow_id

MAX_ANSWER_CHARS = 4000
FOLLOW_UP = "followup:"
ANS = models.statement_answers
R = models.statement_rules


def _answers(engine: Engine, tenant: str, student: str) -> list:
    with engine.connect() as conn:
        return conn.execute(select(ANS.c.question_id, ANS.c.question, ANS.c.answer).where(
            ANS.c.tenant_id == tenant, ANS.c.student_ref == student).order_by(ANS.c.id)).all()


def _open_follow_ups(rows) -> list:
    return [r for r in rows if r.question_id.startswith(FOLLOW_UP) and not (r.answer or "").strip()]


def save_answer(engine: Engine, tenant: str, student: str, cfg: StatementConfig, question_id: str, text: str) -> None:
    """Saves one answer. A route question or a follow-up the Critic asked this student; anything else is refused."""
    if cfg.question(question_id) is None and not (
            question_id.startswith(FOLLOW_UP) and any(r.question_id == question_id
                                                      for r in _answers(engine, tenant, student))):
        raise ValueError(f"unknown question {question_id!r}")
    text = (text or "").strip()
    if len(text) > MAX_ANSWER_CHARS:
        raise ValueError(f"an answer is at most {MAX_ANSWER_CHARS} characters")
    with engine.begin() as conn:
        conn.execute(pg_insert(ANS).values(tenant_id=tenant, student_ref=student, question_id=question_id, answer=text)
                     .on_conflict_do_update(constraint="uq_os_statement_answers", set_={"answer": text}))


def interview(engine: Engine, tenant: str, student: str, cfg: StatementConfig) -> list[dict]:
    """Open follow-ups first, then the route's questions with this student's answers."""
    rows = _answers(engine, tenant, student)
    given = {r.question_id: r.answer for r in rows}
    out = [{"id": r.question_id, "prompt": r.question, "hint": "", "required": True, "answer": "", "follow_up": True}
           for r in _open_follow_ups(rows)]
    return out + [{"id": q.id, "prompt": q.prompt, "hint": q.hint, "required": q.required,
                   "answer": given.get(q.id, ""), "follow_up": False} for q in cfg.questions]


def missing_required(engine: Engine, tenant: str, student: str, cfg: StatementConfig) -> list[str]:
    rows = _answers(engine, tenant, student)
    given = {r.question_id for r in rows if (r.answer or "").strip()}
    return [q.id for q in cfg.questions if q.required and q.id not in given] + [
        r.question_id for r in _open_follow_ups(rows)]


def start_draft(engine: Engine, client, tenant: str, cfg: StatementConfig, artifact_id: int, year: int,
                knowledge) -> str | None:
    """Enqueues os.statement for this artifact with its current inputs. Returns the workflow ID, or None when there
    is nothing to do: these inputs were already drafted (invariant 8), or a draft is being written. After a `failed`
    or `budget` run the same inputs get a new attempt. The artifact shows `drafting` from here, so the page polls."""
    store = ArtifactStore(engine, tenant)
    art = store.get(artifact_id)
    if art.status == "drafting":
        return None
    sha = inputs_sha(inputs_for(engine, tenant, cfg, art.student_ref, art.kind, art.programme_ref, knowledge, year))
    prefix = statement_workflow_id(tenant, artifact_id, sha, 0)[:-1]  # "...:<sha16>:"
    done = len(client.list_workflows(workflow_id_prefix=prefix, load_input=False, load_output=False))
    if done and art.status not in ("failed", "budget"):
        return None
    store.set_status(artifact_id, "drafting")
    return enqueue_statement(client, tenant, artifact_id, cfg.route_key, year, sha, attempt=done + 1)


def answer_follow_up(engine: Engine, client, tenant: str, student: str, cfg: StatementConfig, question_id: str,
                     text: str, year: int, knowledge) -> list[str]:
    """Saves a follow-up answer. When none is left open, every artifact waiting on answers is drafted again."""
    if not question_id.startswith(FOLLOW_UP):
        raise ValueError(f"{question_id!r} is not a follow-up question")
    save_answer(engine, tenant, student, cfg, question_id, text)
    if _open_follow_ups(_answers(engine, tenant, student)):
        return []
    store = ArtifactStore(engine, tenant)
    started = [start_draft(engine, client, tenant, cfg, a.id, year, knowledge)
               for a in store.list_for(student, STATEMENT_KINDS) if a.status == "needs_answers"]
    return [w for w in started if w]


def save_pasted_rules(engine: Engine, tenant: str, student: str, programme_ref: str, prompt: str | None,
                      limit_words: int | None, limit_chars: int | None) -> None:
    prompt = (prompt or "").strip() or None
    if prompt is not None and len(prompt) > MAX_ANSWER_CHARS:
        raise ValueError(f"a pasted prompt is at most {MAX_ANSWER_CHARS} characters")
    for n in (limit_words, limit_chars):
        if n is not None and not 0 < n <= 100_000:
            raise ValueError("a limit is a positive number")
    row = {"prompt": prompt, "limit_words": limit_words, "limit_chars": limit_chars}
    with engine.begin() as conn:
        conn.execute(pg_insert(R).values(tenant_id=tenant, student_ref=student, programme_ref=programme_ref, **row)
                     .on_conflict_do_update(constraint="uq_os_statement_rules", set_=row))
