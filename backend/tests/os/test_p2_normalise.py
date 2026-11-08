"""P2-T4: Urdu text folding from data and language detection (P2-D14, R-29). Fictional sentences."""

import re

import pytest

from app.os.knowledge.research.text import detect_language, normalise
from app.os.knowledge.research.trust import quote_on_page

pytestmark = pytest.mark.req("R-29", "R-76")
DEADLINE = "داخلے کی آخری تاریخ ۱ اگست ۲۰۲۷ ہے۔"  # "the last date for admission is 1 August 2027"


def _old_normalise(text: str) -> str:
    text = text.replace("\x00a0", " ").replace("\x00a0", " ").replace(" ", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


@pytest.mark.parametrize("text", [
    "Applications close on 1 August 2027.", "  Fee:\t1000 units – per “semester”  ", "Ünïcode ÄÖÜ ß straße",
    "Deadline 15.07.2027 at 12:00", "",
])
def test_latin_text_normalises_exactly_as_before(text):
    assert normalise(text) == _old_normalise(text)


def test_digits_fold_to_ascii():
    assert "1 اگست 2027" in normalise(DEADLINE)
    assert normalise("٢٠٢٧") == normalise("۲۰۲۷") == "2027"


def test_arabic_letter_forms_match_urdu_forms():
    assert normalise("كتاب") == normalise("کتاب")
    assert normalise("علي") == normalise("علی") and normalise("هو") == normalise("ہو")


def test_diacritics_tatweel_and_joiners_are_removed():
    assert normalise("كَتَبَ") == normalise("کتب")
    assert normalise("تـاريخ") == normalise("تاریخ")
    assert normalise("می‌خواهم") == normalise("میخواہم")


def test_different_words_are_not_merged():
    assert normalise("ہے") != normalise("ہی")  # bari yeh and choti yeh make different words
    assert normalise("ھ") != normalise("ہ")


def test_a_quote_typed_in_another_form_still_matches_the_page():
    page = normalise("اعلان\n" + DEADLINE + "\nمزید معلومات")
    assert quote_on_page("آخري تاريخ ١ اگست ٢٠٢٧", page)  # Arabic yeh and digits
    assert not quote_on_page("آخری تاریخ ۲ اگست ۲۰۲۷", page)


def test_language_needs_urdu_letter_evidence_else_a_script_tag():
    assert detect_language(DEADLINE) == "ur"  # ے ہ ں ... are Urdu-only forms
    assert detect_language("Notice: " + DEADLINE) == "ur"  # most letters decide, not the first
    assert detect_language("فیس ۱۰۰۰ یونٹ") == "arab"  # Arabic script, but fewer than 3 Urdu-only letters: no language guessed
    assert detect_language("كتاب جديد في المكتبة") == "arab"  # Arabic text is never tagged Urdu
    assert detect_language("کتاب نو در کتابخانه") == "arab"  # Persian likewise
    assert detect_language("Applications close on 1 August 2027.") is None  # Latin keeps today's behaviour
    assert detect_language("12345 ...") is None
    assert detect_language("") is None


def test_direction_marks_around_ocr_digits_are_ignored():
    assert normalise("تاریخ \u200e١\u200f اگست") == normalise("تاریخ 1 اگست")


def test_composed_and_decomposed_letters_match_and_hamza_marks_survive():
    assert normalise("آخری") == normalise("ا\u0653خری")  # alef + maddah above composes to alef with madda
    assert normalise("آخری") != normalise("اخری")  # the maddah is NOT stripped (0653-0655 are letter parts)
    assert normalise("أحمد") != normalise("احمد") and normalise("إسلام") != normalise("اسلام")
    assert normalise("cafe\u0301") == normalise("café")  # NFC applies to every script


def test_joiners_are_removed_only_next_to_arabic_letters():
    assert normalise("می\u200cخواہم") == normalise("میخواہم")
    assert normalise("ب\u200dا") == normalise("با")
    assert normalise("a\u200db") == "a\u200db" and normalise("a\u200cb") == "a\u200cb"  # elsewhere they stay
    assert normalise("\U0001F468\u200d\U0001F469") == "\U0001F468\u200d\U0001F469"
