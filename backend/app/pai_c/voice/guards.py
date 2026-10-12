"""Question repetition checks based only on Unicode punctuation and tokens."""
import unicodedata

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
