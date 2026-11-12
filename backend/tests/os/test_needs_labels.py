"""P1-T8 Task 1 (R-55, D-w16): the words a student sees in a needs (v2) playbook follow the label rule too. Every
needs book's task titles and ask titles (stated, shown, confirmed, which_is_right, expected) are checked against the
word lists: no other route's word, and no "abroad" or "visa" on a route that stays in one country. Pure: no database."""

from pathlib import Path

import pytest

from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from tests.os.route_labels import abroad_words, foreign_words, load_words

pytestmark = [pytest.mark.req("R-55")]

NEEDS_DIR = Path(__file__).parent / "playbooks" / "needs"


def needs_books() -> list:
    books = list(load_playbook_dir(PLAYBOOK_DIR).values()) + list(load_playbook_dir(NEEDS_DIR).values())
    return sorted((b for b in books if b.declares_needs), key=lambda b: (b.key, b.version))


def student_text(book) -> str:
    """The titles a student reads: every task and every ask a need uses."""
    parts = [t.title for t in book.tasks]
    for ask in book.asks.values():
        parts += [ask.stated, ask.shown, ask.confirmed, ask.which_is_right]
        if ask.expected is not None:
            parts.append(ask.expected.title)
    return "\n".join(p for p in parts if p)


def test_there_are_needs_books_to_check():
    assert {(b.key, b.version) for b in needs_books()} == {
        ("germany_master", 2), ("ireland_master", 2), ("pakistan_bs", 2), ("pakistan_inter", 2)}


@pytest.mark.parametrize("book", needs_books(), ids=lambda b: f"{b.key}.v{b.version}")
def test_needs_book_words_stay_on_their_route(book):
    text = student_text(book)
    assert text
    assert foreign_words(book.key, text) == []
    if book.route.origin == book.route.destination:
        assert abroad_words(text) == []


def test_a_planted_foreign_word_is_seen():
    """The check can fail: another route's word in an ask title is found."""
    words = load_words()
    inter = next(b for b in needs_books() if b.key == "pakistan_inter")
    assert foreign_words(inter.key, student_text(inter) + "\nUpload your blocked account letter", words) == [
        "blocked account"]
    assert abroad_words(student_text(inter) + "\nYour visa abroad") == ["abroad", "visa"]
