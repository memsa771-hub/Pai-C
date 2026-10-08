"""Deterministic, channel-independent reply checks for the future deep turn."""

import re


_PRAISE_OPENER = re.compile(r"^(?:great|nice|good|absolutely|solid|strong base)\b[!,.\s-]*", re.I)
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
