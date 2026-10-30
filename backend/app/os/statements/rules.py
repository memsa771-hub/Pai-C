"""A statement's rules: needed or not, its limit and prompt (Slice 5 spec S5-D2).

The first that exists wins: the programme's researched `statement_requirement` fact (shown with its status), then the
prompt and limit the student pasted from the programme's page, then the route default (labelled as a default). A CV
always uses its route default.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine, select

from app.os import models
from app.os.statements.config import StatementConfig

FIELD = "statement_requirement"
R = models.statement_rules


@dataclass(frozen=True)
class Rules:
    needed: bool
    limit_words: int | None
    limit_chars: int | None
    prompt: str | None
    source: Literal["research", "student", "default"]
    status: str | None = None  # the researched fact's status (confirmed / unconfirmed / stale)


def pasted(engine: Engine, tenant_id: str, student_ref: str, programme_ref: str):
    with engine.connect() as conn:
        return conn.execute(select(R).where(R.c.tenant_id == tenant_id, R.c.student_ref == student_ref,
                                            R.c.programme_ref == programme_ref)).first()


def resolve_rules(engine: Engine, tenant_id: str, knowledge, student_ref: str, programme_ref: str | None, year: int,
                  cfg: StatementConfig, kind: str) -> Rules:
    default = cfg.kinds[kind].default_words
    if kind == "cv" or programme_ref is None:
        return Rules(True, default, None, None, "default")
    paste = pasted(engine, tenant_id, student_ref, programme_ref)
    fact = knowledge.programme_facts([programme_ref], [FIELD], year).get((programme_ref, FIELD))
    value = fact.value if fact is not None and isinstance(fact.value, dict) else {}
    words, chars = value.get("limit_words"), value.get("limit_chars")
    if value.get("needed") is True:  # researched: this programme asks for its own statement (a limit alone does not)
        words = words if words is not None or chars is not None else default
        return Rules(True, int(words) if words is not None else None, int(chars) if chars is not None else None,
                     paste.prompt if paste is not None else None, "research", fact.status)
    if paste is not None and (paste.limit_words or paste.limit_chars or paste.prompt):
        return Rules(True, paste.limit_words or (None if paste.limit_chars else default), paste.limit_chars,
                     paste.prompt, "student")
    return Rules(False, default, None, None, "default")  # nothing known: the base statement serves
