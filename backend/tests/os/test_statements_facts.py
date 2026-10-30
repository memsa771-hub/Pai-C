"""Slice 5 Task 2: the rule-based invented-facts check (spec S5-D5). Fictional values only."""

from app.os.statements.facts_check import claims, normalise, unsupported

ANSWERS = [
    "I studied Computer Science at the University of Exampleton and finished with a CGPA of 3.40 out of 4.0.",
    "My final project was a traffic prediction app built with Python; it won second prize at Techfest 2023.",
    "I worked at Sample Systems Ltd from June 2022 to August 2023 as a junior developer.",
]
PROFILE = ["transcript.completion_date: 2023-07-15", "ielts_trf.overall: 7.5"]
SOURCES = ANSWERS + PROFILE


def kinds(text):
    return sorted((c.kind, c.norm) for c in claims(text))


def test_supported_claim_passes():
    draft = ("At the University of Exampleton I earned a CGPA of 3.4/4.0, and at Sample Systems Ltd I learned to "
             "ship software. My IELTS band of 7.5 reflects my English.")
    assert unsupported(draft, SOURCES) == []


def test_invented_number_flagged():
    [c] = unsupported("I graduated with a CGPA of 3.9.", SOURCES)
    assert (c.kind, c.text) == ("number", "3.9")


def test_invented_institution_flagged():
    flagged = unsupported("I also took a summer course at the Institute of Advanced Robotics.", SOURCES)
    assert [c.text for c in flagged] == ["Institute of Advanced Robotics"]


def test_invented_award_and_year_flagged():
    flagged = {c.text for c in unsupported("In 2021 I won the National Coding Olympiad.", SOURCES)}
    assert flagged == {"2021", "National Coding Olympiad"}


def test_number_and_date_formats_match():
    assert normalise("number", "3.40") == normalise("number", "3.4") == "3.4"
    assert normalise("number", "1,000") == "1000"
    assert normalise("date", "15 July 2023") == normalise("date", "2023-07-15") == "2023-07-15"
    assert normalise("date", "July 2023") == "2023-07"
    draft = "I finished my degree on 15 July 2023 with a 3.4 CGPA."
    assert unsupported(draft, SOURCES) == []


def test_year_supported_by_full_date():
    assert unsupported("I graduated in 2023.", SOURCES) == []
    assert unsupported("I started work in June 2022.", SOURCES) == []


def test_sentence_start_capital_not_a_name():
    text = "During my studies I learned to code. After that I wanted more. My Bachelor taught me patience."
    assert [c for c in claims(text) if c.kind == "name"] == []


def test_common_acronyms_not_claims():
    assert claims("This CV and my SOP are attached. I hope to hear from you.") == []


def test_empty_draft_no_claims():
    assert claims("") == [] and unsupported("", SOURCES) == []


def test_single_word_invented_name_flagged():
    """Final review: one capitalised word inside a sentence is a name too (an employer, a university)."""
    assert [c.text for c in unsupported("I interned at Siemens.", SOURCES)] == ["Siemens"]
    assert {c.text for c in unsupported("I studied at Oxford and then joined Google.", SOURCES)} == {"Oxford", "Google"}
    assert unsupported("Then I moved on. Python is my main tool.", SOURCES) == []  # supported, and a sentence start


def test_headings_and_salutations_not_flagged():
    draft = ("Dear Admissions Committee,\nStatement of Purpose\nWORK EXPERIENCE\nTechnical Skills\n"
             "I hold a Bachelor of Science in Computer Science. During COVID I studied online.")
    assert unsupported(draft, SOURCES) == []


def test_line_break_ends_a_run():
    found = [c.text for c in claims("EDUCATION\nUniversity of Exampleton\nSKILLS\nPython")]
    assert found == ["University of Exampleton"]  # one claim per line, never one across the lines


def test_institution_checked_without_its_generic_words():
    assert unsupported("I studied at the University of Exampleton.", SOURCES) == []
    [c] = unsupported("I studied at the University of Nowhere.", SOURCES)
    assert c.text == "University of Nowhere"
