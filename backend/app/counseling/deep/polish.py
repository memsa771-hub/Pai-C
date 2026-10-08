"""Generic punctuation, layout and configured Unicode script checks."""

import re
import unicodedata
from functools import lru_cache

import regex as unicode_regex


_LIST = re.compile(r"(?m)^\s*(?:[-*\u2022]|\d+[.)])\s+")


def _question_positions(reply: str) -> list[int]:
    return [index for index, char in enumerate(reply)
            if "QUESTION MARK" in unicodedata.name(char, "")]


def question_count(reply: str) -> int:
    return len(_question_positions(reply))


def has_list(reply: str) -> bool:
    return bool(_LIST.search(reply))


@lru_cache(maxsize=64)
def _script_pattern(name: str):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_ ]*", name):
        raise ValueError("invalid blocked Unicode script name")
    try:
        return unicode_regex.compile(rf"\p{{Script={name}}}")
    except unicode_regex.error as exc:
        raise ValueError("unknown blocked Unicode script name") from exc


def contains_blocked_script(reply: str, blocked_scripts: str) -> bool:
    return any(_script_pattern(name).search(reply) is not None
               for raw in blocked_scripts.split(",") if (name := raw.strip()))


def keep_first_question(reply: str) -> str:
    """Drop later questions and their trailing text without rewriting prose."""
    marks = _question_positions(reply)
    return reply[:marks[0] + 1].rstrip() if len(marks) > 1 else reply


def polish_reply(reply: str) -> str:
    return keep_first_question(reply.strip())
