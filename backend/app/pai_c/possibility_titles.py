"""Structural title checks only; entity claims are not inferred from titles."""
import re
from app.pai_c.policy.controller import load_data


def valid_title(value):
    if not isinstance(value, str):
        return False
    policy = load_data("possibilities.json")
    return (policy["title_min_words"] <= len(value.split()) <= policy["title_max_words"]
            and not any(character.isdigit() for character in value)
            # One field per title: "A/B" or "A (B)" is two paths or a note.
            and not re.search(r"[/()\[\]{}]", value)
            and not re.search(r"(?:\w+://|www\.|\S+\.[^\W\d_]{2,}(?:/|\b))", value, re.I))


def normalized_title(value):
    return " ".join(value.split()).casefold()
