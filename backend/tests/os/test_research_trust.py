"""Trust rules and evidence validators (Slice 2 spec §4.4, plan Task 4). No AI, no database."""

import gzip
import json
from pathlib import Path

import pytest
import yaml

from app.os.knowledge.profile import load_profile_dir, reading_model
from app.os.knowledge.programmes import PROGRAMME_SEED, Programme
from app.os.knowledge.research.pages import Page
from app.os.knowledge.research.text import normalise
from app.os.knowledge.research.trust import (
    is_link_label,
    judge,
    list_complete,
    quote_on_page,
    scope_ok,
    value_in_quote,
)

FIXTURES = Path(__file__).parent / "fixtures" / "research"
PROFILE = load_profile_dir()["germany_master"]
Reading = reading_model(PROFILE)
UNI = "https://www.uni-x.de"
PROG = Programme(ref="uni-x-data", route_key="germany_master", university="Uni X", name="Data Science",
                 aliases=("Data Science", "MSc Data Science"), start_urls=(UNI + "/data-science",),
                 official_domains=("uni-x.de",))


def spec(name):
    return PROFILE.field(name)


def page(url, text, links=()):
    return Page(url=url, final_url=url, http_status=200, text=text, links=tuple(links))


def found(field, value, quote, url, cycle=None, scope_quote=None):
    """A reading's fact, built through the profile's reading model (so the shapes are the real ones)."""
    data = {field: {"value": value, "quote": quote, "url": url, "cycle": cycle, "scope_quote": scope_quote}}
    return getattr(Reading.model_validate(data), field)


def value_of(field, value):
    return getattr(Reading.model_validate({field: {"value": value, "quote": "q", "url": UNI}}), field).value


# --- 2. quote on the page ---------------------------------------------------------------------------------


def test_quote_on_page_whole_and_in_pieces():
    text = normalise("Deadline\nWinter semester: 15 July\nSummer semester: 15 January")
    assert quote_on_page("Winter semester: 15 July", text)
    assert quote_on_page("Deadline\nWinter semester: 15 July", text)  # table pieces, in order, close together
    assert not quote_on_page("Winter semester: 31 July", text)
    far = normalise("Deadline" + " filler" * 100 + " 15 July")
    assert not quote_on_page("Deadline ... 15 July", far)  # pieces more than 400 characters apart


# --- 3. not a link label ----------------------------------------------------------------------------------


def test_link_label_rejected():
    p = page(UNI + "/apply", "Find your path here:\nApplication via uni-assist\nApplication via Uni X",
             links=[(UNI + "/a", "Application via uni-assist"), (UNI + "/b", "Application via Uni X")])
    assert is_link_label("Application via Uni X", p)
    assert is_link_label("Find your path here:\nApplication via uni-assist\nApplication via Uni X", p)
    assert not is_link_label("International applicants apply via uni-assist.", p)


# --- 4. the value is in the quote, by generic type ----------------------------------------------------------


@pytest.mark.parametrize("field, value, quote, ok", [
    # month_day: the day and the month, by number or a profile month name (English and German)
    ("deadline_close", "07-15", "Application deadline: 15 July 2026", True),
    ("deadline_close", "07-15", "Bewerbungsschluss: 15. Juli 2026", True),
    ("deadline_close", "07-15", "15.03. - 15.07. (winter)", True),
    ("deadline_close", "07-15", "Application deadline: 15 June 2026", False),
    ("deadline_open", "03-01", "March 1, 2027 to July 15, 2027", True),
    # amount: both number formats; 0 needs a "not required" phrase
    ("semester_contribution_eur", 1234.56, "Semester fee: 1.234,56 €", True),
    ("semester_contribution_eur", 1234.56, "Semester fee: 1,234.56 EUR", True),
    ("semester_contribution_eur", 322.8, "Sem Contribution €322.80 (incl. semester ticket)", True),
    ("semester_contribution_eur", 1234.56, "Semester fee: 1,500 EUR", False),
    ("tuition_fee_non_eu_eur", 0.0, "There are no tuition fees for this programme.", True),
    ("tuition_fee_non_eu_eur", 0.0, "The program, including teaching and exams, is in Englisch.", False),  # D5
    # level: the level token; none needs a none_phrase
    ("german_requirement", {"level": "A1"}, "a German language proof at minimum level A1", True),
    ("german_requirement", {"level": "none"}, "a German language proof at minimum level A1", False),  # D5
    ("german_requirement", {"level": "none"}, "No German language skills required.", True),
    ("german_requirement", {"level": "B1"}, "a German language proof at minimum level A1", False),
    # level_scores: every score given, and every yes/no flag given
    ("english_requirement", {"cefr": "B2", "ielts": 6.5, "toefl_ibt": 85}, "IELTS Academic: 6.5, TOEFL iBT: 85", True),
    ("english_requirement", {"cefr": "C1", "ielts": 7.0}, "C1 required: IELTS Academic: 7", True),
    ("english_requirement", {"cefr": "B2", "ielts": 7.0}, "B2: IELTS Academic: 6.5", False),
    ("english_requirement", {"cefr": "B2"}, "English at least at level B2 of the CEFR", True),
    ("english_requirement", {"cefr": "B2"}, "Proof of English language skills is required", False),
    ("english_requirement", {"cefr": "B2", "moi_accepted": True}, "English at level B2 of the CEFR", False),  # D2
    ("english_requirement", {"cefr": "B2", "moi_accepted": False},
     "level B2; medium of instruction certificates are not accepted", True),
    # a flag that only withholds something (False) need not be stated; one that grants it (True) must be
    ("english_requirement", {"cefr": "C1", "ielts": 6.5, "moi_accepted": False}, "C1: IELTS Academic: 6.5", True),
    ("english_requirement", {"cefr": "C1", "ielts": 6.5, "moi_accepted": True}, "C1: IELTS Academic: 6.5", False),
    # grade: the number
    ("grade_requirement", {"german_max": 2.5}, "a final grade of 2,5 or better", True),
    ("grade_requirement", {"german_max": 2.5}, "a final grade of 2.0 or better", False),
    # enum: one of the value's aliases
    ("application_route", "uni_assist", "International applicants apply via uni-assist.", True),
    ("application_route", "direct", "International applicants apply via uni-assist.", False),
    # name_set: every name; an empty list needs a none_phrase
    ("admission_test", {"any_of": ["GRE", "GATE"]}, "a GRE or GATE score is required", True),
    ("admission_test", {"any_of": ["GRE", "GATE"]}, "a GRE score is required", False),
    ("admission_test", {"any_of": []}, "There is no admission test.", True),
    ("admission_test", {"any_of": []}, "Applicants send a CV.", False),
    # season_set: every season
    ("intakes", ["winter", "summer"], "Start: winter and summer semester", True),
    ("intakes", ["winter", "summer"], "Start: winter semester", False),
])
def test_value_in_quote(field, value, quote, ok):
    assert value_in_quote(spec(field), value_of(field, value), quote, PROFILE) is ok


# --- 5. complete lists ------------------------------------------------------------------------------------


@pytest.mark.parametrize("field, value, quote, ok", [
    ("intakes", ["winter"], "Intake winter semester 2026", False),  # D1
    ("intakes", ["winter"], "Admission is for the winter semester only.", True),
    ("intakes", ["winter", "summer"], "winter and summer semester", True),
    ("admission_test", {"any_of": ["GRE"]}, "a GRE score is required", False),
    ("admission_test", {"any_of": ["GRE"]}, "only the GRE is accepted", True),
    ("deadline_close", "07-15", "15 July", True),  # not a list
])
def test_list_complete(field, value, quote, ok):
    assert list_complete(spec(field), value_of(field, value), quote, PROFILE) is ok


# --- 6. scope ---------------------------------------------------------------------------------------------

GENERAL_URL = UNI + "/admission/master"
GENERAL_TEXT = ("Master's admission | Uni X\nRules for all applicants.\nGerman at A1 is needed at the time of "
                "application.\nThis rule applies to: Data Science, Physics.")


def test_scope_specific_page_needs_no_scope_quote():
    p = page(UNI + "/data-science/apply", "MSc Data Science | Uni X\nGerman at A1 is needed.")
    assert scope_ok(p, PROG, "German at A1 is needed.", None, PROFILE)


def test_scope_specific_page_by_title_ampersand_or_url_alias():
    prog = Programme(ref="uni-x-ece", route_key="germany_master", university="Uni X",
                     name="Electrical and Computer Engineering", aliases=("ECE-MSc",), start_urls=(),
                     official_domains=("uni-x.de",))
    assert scope_ok(page(UNI + "/studies/x/info.html", "Electrical & Computer Engineering | Uni X\nTaught in English."),
                    prog, "Taught in English.", None, PROFILE)
    assert scope_ok(page(UNI + "/en/ece-msc/faq", "FAQ - Uni X\nTaught in English."),
                    prog, "Taught in English.", None, PROFILE)
    assert not scope_ok(page(UNI + "/en/faq", "FAQ - Uni X\nTaught in English."),
                        prog, "Taught in English.", None, PROFILE)


def test_scope_general_page_needs_scope_quote_near_and_naming():
    p = page(GENERAL_URL, GENERAL_TEXT)
    quote = "German at A1 is needed at the time of application."
    assert not scope_ok(p, PROG, quote, None, PROFILE)  # D3
    assert scope_ok(p, PROG, quote, "This rule applies to: Data Science, Physics.", PROFILE)
    assert not scope_ok(p, PROG, quote, "Rules for all applicants. German", PROFILE)  # names nothing
    assert not scope_ok(p, PROG, quote, "Data Science is great", PROFILE)  # not on the page
    far = page(GENERAL_URL, "Master's admission\n" + quote + "\n" + "x " * 1500 + "\nApplies to Data Science.")
    assert not scope_ok(far, PROG, quote, "Applies to Data Science.", PROFILE)  # beyond 2,000 characters


def test_scope_quote_for_all_programmes():
    p = page(GENERAL_URL, "Language proof\nThe following certificates are accepted for studies in international "
                          "bachelor or master study programmes:\nIELTS 6.0")
    assert scope_ok(p, PROG, "IELTS 6.0",
                    "The following certificates are accepted for studies in international bachelor or master "
                    "study programmes:", PROFILE)


# --- judge -----------------------------------------------------------------------------------------------

SPECIFIC = UNI + "/data-science"
SPECIFIC_TEXT = ("MSc Data Science | Uni X\nThe programme is taught in English.\n"
                 "Winter semester 2027/28: application deadline 15 July 2027.\n"
                 "Winter semester 2026/27: application deadline 15 June 2026.")


def run(field, readings, pages=None, min_cycle=2027):
    return judge(spec(field), readings, pages or [page(SPECIFIC, SPECIFIC_TEXT)], PROG, PROFILE, min_cycle)


def test_two_valid_agreeing_readings_confirm():
    q = "The programme is taught in English."
    v = run("language_of_instruction", {"A": found("language_of_instruction", "english", q, SPECIFIC),
                                        "B": found("language_of_instruction", "english", q, SPECIFIC)})
    assert v.status == "confirmed" and v.value == "english" and v.url == SPECIFIC and v.reasons == []
    assert [e["reading"] for e in v.evidence] == ["A", "B"] and all(e["reasons"] == [] for e in v.evidence)


def test_one_valid_reading_is_unconfirmed():
    q = "The programme is taught in English."
    v = run("language_of_instruction", {"A": found("language_of_instruction", "english", q, SPECIFIC),
                                        "B": found("language_of_instruction", "english", "Not on the page.", SPECIFIC)})
    assert v.status == "unconfirmed" and "single_reading" in v.reasons and "B:quote_not_on_page" in v.reasons


def test_disagreement_is_unconfirmed_with_conflict_note():
    q1, q2 = "Winter semester 2027/28: application deadline 15 July 2027.", \
        "Winter semester 2026/27: application deadline 15 June 2026."
    v = run("deadline_close", {"A": found("deadline_close", "07-15", q1, SPECIFIC),
                               "B": found("deadline_close", "06-15", q2, SPECIFIC)}, min_cycle=2026)
    assert v.status == "unconfirmed" and "readings_disagree" in v.reasons
    assert "07-15" in v.conflict_note and "06-15" in v.conflict_note


def test_third_reading_cannot_outvote():
    q = "The programme is taught in English."
    v = run("language_of_instruction", {"A": found("language_of_instruction", "english", q, SPECIFIC),
                                        "B": found("language_of_instruction", "english", q, SPECIFIC),
                                        "C": found("language_of_instruction", "english_or_german", q, SPECIFIC)})
    # C's value is not in its quote, so C is invalid and A and B still confirm ...
    assert v.status == "confirmed" and "C:value_not_in_quote" in v.reasons
    # ... but when C is valid and disagrees, it is not outvoted: the readings disagree
    q2 = "Taught in English or German."
    p = page(SPECIFIC, SPECIFIC_TEXT + "\n" + q2)
    v = run("language_of_instruction", {"A": found("language_of_instruction", "english", q, SPECIFIC),
                                        "B": found("language_of_instruction", "english", q, SPECIFIC),
                                        "C": found("language_of_instruction", "english_or_german", q2, SPECIFIC)},
            pages=[p])
    assert v.status == "unconfirmed" and "readings_disagree" in v.reasons


def test_no_reading_is_not_found():
    assert run("deadline_close", {"A": None, "B": None}).status == "not_found"


def test_not_official_and_unread_urls_rejected():
    q = "The programme is taught in English."
    v = run("language_of_instruction", {"A": found("language_of_instruction", "english", q, "https://blog.example.com/x"),
                                        "B": found("language_of_instruction", "english", q, UNI + "/never-read")})
    assert v.status == "unconfirmed"
    assert "A:not_official" in v.reasons and "B:url_not_read" in v.reasons


def test_cycle_rule_old_cycle_is_unconfirmed_with_note():
    q = "Winter semester 2026/27: application deadline 15 June 2026."
    readings = {"A": found("deadline_close", "06-15", q, SPECIFIC, cycle="Winter semester 2026/27"),
                "B": found("deadline_close", "06-15", q, SPECIFIC, cycle="Winter semester 2026/27")}
    v = run("deadline_close", readings, min_cycle=2027)
    assert v.status == "unconfirmed" and "cycle_old:2026" in v.reasons
    assert "page shows" in v.conflict_note and "2026/27" in v.conflict_note
    assert run("deadline_close", readings, min_cycle=2026).status == "confirmed"


def test_cycle_unknown_is_unconfirmed():
    p = page(SPECIFIC, "MSc Data Science | Uni X\nApplication deadline: 15 July.")
    q = "Application deadline: 15 July."
    v = run("deadline_close", {"A": found("deadline_close", "07-15", q, SPECIFIC),
                               "B": found("deadline_close", "07-15", q, SPECIFIC)}, pages=[p])
    assert v.status == "unconfirmed" and "cycle_unknown" in v.reasons


def test_cefr_alone_not_confirmed_when_a_page_lists_scores():
    p1 = page(SPECIFIC, "MSc Data Science | Uni X\nEnglish at least at level B2 of the CEFR.")
    handout = page(UNI + "/handout.pdf", "Language certificates\nTOEFL iBT IELTS Academic\n79 6.0")
    q = "English at least at level B2 of the CEFR."
    readings = {"A": found("english_requirement", {"cefr": "B2"}, q, SPECIFIC),
                "B": found("english_requirement", {"cefr": "B2"}, q, SPECIFIC)}
    assert run("english_requirement", readings, pages=[p1]).status == "confirmed"
    v = run("english_requirement", readings, pages=[p1, handout])
    assert v.status == "unconfirmed" and "A:scores_on_other_page" in v.reasons  # D2


def test_evidence_records_every_reading():
    q = "The programme is taught in English."
    v = run("language_of_instruction", {"A": found("language_of_instruction", "english", q, SPECIFIC),
                                        "B": None,
                                        "C": found("language_of_instruction", "german", q, SPECIFIC)})
    by = {e["reading"]: e for e in v.evidence}
    assert set(by) == {"A", "C"}
    assert by["A"]["value"] == "english" and by["A"]["quote"] == q and by["A"]["url"] == SPECIFIC
    assert "value_not_in_quote" in by["C"]["reasons"] and "scope_quote" in by["A"]


# --- Spike 1 regressions (D1-D5) ---------------------------------------------------------------------------


def _fixture_pages():
    data = json.loads(gzip.open(FIXTURES / "spike1-pages-2026-10-19.json.gz").read())
    pages = {}
    for url, p in data["pages"].items():
        pages[url] = Page(url=url, final_url=p.get("final_url"), http_status=p.get("status"),
                          text=p.get("text") or "", links=tuple(tuple(x) for x in p.get("links") or ()),
                          blocked=p.get("blocked"))
    return pages


def _seed_programme(ref):
    seed = yaml.safe_load(PROGRAMME_SEED.read_text(encoding="utf-8"))
    p = seed["programmes"][ref]
    return Programme(ref=ref, route_key=seed["route_key"], university=p["university"], name=p["name"],
                     aliases=tuple(p.get("aliases", ())), start_urls=tuple(p["start_urls"]),
                     official_domains=tuple(p["official_domains"]))


CASES = yaml.safe_load((FIXTURES / "regressions.yaml").read_text(encoding="utf-8"))["cases"]


def test_regression_set_covers_d1_to_d5():
    assert {c["defect"] for c in CASES} == {"D1", "D2", "D3", "D4", "D5"}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_spike1_regressions(case):
    pages = _fixture_pages()
    field = case["field"]
    readings = {n: getattr(Reading.model_validate({field: r}), field) for n, r in case["readings"].items()}
    v = judge(spec(field), readings, [pages[u] for u in case["pages"]], _seed_programme(case["programme"]),
              PROFILE, 2026)
    wrong = value_of(field, case["wrong_value"])
    dumped = wrong.model_dump() if hasattr(wrong, "model_dump") else wrong
    assert not (v.status == "confirmed" and v.value == dumped), v.reasons
