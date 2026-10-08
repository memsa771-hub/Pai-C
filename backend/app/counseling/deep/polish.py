"""Deterministic, channel-independent reply checks for the future deep turn."""

import re


_PRAISE_OPENER = re.compile(
    r"^(?:great|nice|good|absolutely|solid|strong base|zabardast|"
    r"bohat acha|bahut acha|kya baat hai|shabash|wah|"
    r"بہت اچھا|زبردست|شاباش)\b[!,.،\s-]*", re.I,
)
_LIST = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")
_QUESTION_FORMS = re.compile(
    r"\b(?:kya|kyun|kab|kaise|kaun|kis|kitna|kitni)\b"
    r"|(?:کیا|کیوں|کب|کیسے|کون|کس|کتنا|کتنی)", re.I,
)
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")


def strip_praise_opener(reply: str) -> str:
    return _PRAISE_OPENER.sub("", reply.strip(), count=1).lstrip()


def question_count(reply: str) -> int:
    punctuation = reply.count("?") + reply.count("؟")
    return punctuation if punctuation else int(bool(_QUESTION_FORMS.search(reply)))


def has_list(reply: str) -> bool:
    return bool(_LIST.search(reply))


def contains_devanagari(reply: str) -> bool:
    return bool(_DEVANAGARI.search(reply))


def keep_first_question(reply: str) -> str:
    """Drop later questions and their trailing text without rewriting prose."""
    marks = [match.start() for match in re.finditer(r"[?؟]", reply)]
    return reply[:marks[0] + 1].rstrip() if len(marks) > 1 else reply


def polish_reply(reply: str) -> str:
    return keep_first_question(strip_praise_opener(reply))
