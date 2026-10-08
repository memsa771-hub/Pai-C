"""Generic punctuation, layout and script checks for Counselor replies."""

import re


_LIST = re.compile(r"(?m)^\s*(?:[-*\u2022]|\d+[.)])\s+")
_QUESTION_MARK = re.compile(r"[?\u061f]")
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")


def question_count(reply: str) -> int:
    return len(_QUESTION_MARK.findall(reply))


def has_list(reply: str) -> bool:
    return bool(_LIST.search(reply))


def contains_devanagari(reply: str) -> bool:
    return bool(_DEVANAGARI.search(reply))


def keep_first_question(reply: str) -> str:
    """Drop later questions and their trailing text without rewriting prose."""
    marks = list(_QUESTION_MARK.finditer(reply))
    return reply[:marks[0].end()].rstrip() if len(marks) > 1 else reply


def polish_reply(reply: str) -> str:
    return keep_first_question(reply.strip())
