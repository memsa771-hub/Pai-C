"""Question repetition and repeat-greeting checks based only on Unicode punctuation and tokens."""
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

import regex

from app.config import config
from app.pai_c.deep.polish import _question_positions


def question_sentences(text):
    """Return sentence offsets, including the Unicode question terminator."""
    positions = set(_question_positions(text))
    start = 0
    for index, char in enumerate(text):
        if index in positions:
            yield start, index + 1, text[start:index + 1].strip()
            start = index + 1
        elif regex.fullmatch(r"\p{Sentence_Terminal}", char):
            start = index + 1


def _tokens(text):
    return set("".join(char for char in text.casefold()
                       if not unicodedata.category(char).startswith("P")).split())


def similarity(first, second):
    left, right = _tokens(first), _tokens(second)
    union = left | right
    return len(left & right) / len(union) if union else 0


def repeated_questions(reply, history, avoid_questions=()):
    previous = [question for row in history if row.get("role") == "assistant"
                for _, _, question in question_sentences(row.get("content", ""))]
    references = previous[-config.PAI_REPEAT_QUESTION_WINDOW:] + list(avoid_questions)
    return [(start, end, question) for start, end, question in question_sentences(reply)
            if any(similarity(question, old) >= config.PAI_REPEAT_QUESTION_SIMILARITY
                   for old in references)]


def remove_repeated(reply, matches):
    for start, end, _ in reversed(matches):
        reply = reply[:start] + reply[end:]
    return reply.strip()


def repeats_previous_reply(reply, history):
    """True when the draft restates the previous counselor reply (token Jaccard)."""
    previous = next((row.get("content", "") for row in reversed(history) if row.get("role") == "assistant"), "")
    return bool(previous.strip()) and similarity(reply, previous) >= config.PAI_REPEAT_REPLY_SIMILARITY


_GREETING_END = "!.?\u061f\n"


@lru_cache(maxsize=1)
def _greetings():
    data = json.loads((Path(__file__).parent / "greetings.json").read_text(encoding="utf-8"))
    return [phrase.casefold().split() for phrase in data["phrases"]], int(data["max_extra_words"])


def _word_tokens(text):
    return "".join(char if not unicodedata.category(char).startswith("P") else " "
                   for char in text.casefold()).split()


def _leading_greeting(text, limit_extra):
    end = next((index + 1 for index, char in enumerate(text) if char in _GREETING_END), len(text))
    tokens = _word_tokens(text[:end])
    phrases, max_extra = _greetings()
    for phrase in phrases:
        if tokens[:len(phrase)] == phrase and (not limit_extra or len(tokens) - len(phrase) <= max_extra):
            return end
    return 0


def leading_greeting(text: str) -> int:
    """End offset of a leading greeting sentence (terminator included), or 0 when none."""
    return _leading_greeting(text, True)


def drop_repeat_greeting(reply: str, history: list[dict], student_text: str = "") -> str:
    """Drop the reply's opening greeting when an earlier assistant reply already greeted.

    Any earlier assistant reply that opens with a greeting phrase counts, however long that
    sentence is. A greeting sentence that ends in a question is real content and is kept.
    When the student's own message opens with a greeting, PAI returns it and the reply is kept.
    """
    if _leading_greeting(student_text, False) > 0:
        return reply
    if not any(row.get("role") == "assistant" and _leading_greeting(row.get("content", ""), False) > 0
               for row in history):
        return reply
    end = leading_greeting(reply)
    if not end or reply[end - 1] in "?\u061f":
        return reply
    rest = reply[end:].lstrip()
    if not rest:
        return reply
    return rest[0].upper() + rest[1:]
