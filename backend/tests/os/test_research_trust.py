"""Trust rules and evidence validators (Slice 2 spec §4.4, plan Task 4). No AI, no database."""

import gzip
import json
from pathlib import Path

import pytest
import yaml

from app.os.knowledge.profile import load_profile_dir, reading_model
from app.os.knowledge.programmes import PROGRAMME_SEED, Programme, with_own_pages
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
    progs = [Programme(ref=r, route_key=seed["route_key"], university=p["university"], name=p["name"],
                       aliases=tuple(p.get("aliases", ())), start_urls=tuple(p["start_urls"]),
                       official_domains=tuple(p["official_domains"])) for r, p in seed["programmes"].items()]
    return next(p for p in with_own_pages(progs) if p.ref == ref)


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


def test_scope_programme_own_pages_are_specific():
    """A start page only this programme uses, and the pages under it, are about this programme even when
    the title does not repeat the name (the gate's largest scope_unclear group). A start page that several
    programmes share stays general, so D3 still holds."""
    own = "https://www.uni-x.de/studies/ds-msc/info.html"
    prog = Programme(ref="uni-x-ds", route_key="germany_master", university="Uni X", name="Data Science",
                     aliases=(), start_urls=(own, UNI + "/apply/all"), official_domains=("uni-x.de",),
                     own_pages=(own,))
    q = "Taught in English."
    assert scope_ok(page(own, "Info - Uni X\nTaught in English."), prog, q, None, PROFILE)
    assert scope_ok(page(UNI + "/studies/ds-msc/faq", "FAQ - Uni X\nTaught in English."), prog, q, None, PROFILE)
    assert not scope_ok(page(UNI + "/studies/other/faq", "FAQ - Uni X\nTaught in English."), prog, q, None, PROFILE)
    assert not scope_ok(page(UNI + "/apply/all", "Apply - Uni X\nTaught in English."), prog, q, None, PROFILE)
    shallow = Programme(ref="uni-x-ds", route_key="germany_master", university="Uni X", name="Data Science",
                        aliases=(), start_urls=(UNI + "/en/ds",), official_domains=("uni-x.de",),
                        own_pages=(UNI + "/en/ds",))
    assert not scope_ok(page(UNI + "/en/faq", "FAQ - Uni X\nTaught in English."), shallow, q, None, PROFILE)


def test_seed_own_pages_leave_out_shared_start_pages():
    chemnitz = _seed_programme("tu-chemnitz-web-engineering")
    shared = "https://www.tu-chemnitz.de/studierendenservice/studserv/bewerbung/bew_bamala.php.en"
    assert shared in chemnitz.start_urls and shared not in chemnitz.own_pages


# --- university-wide fields (Slice 9b entry condition 2: semester_start on the academic calendar) ------------
# A synthetic academic calendar: one page on the university's own domain that gives the semester dates for every
# programme, and names none of them. The profile marks semester_start `university_wide`; no other field is.

CALENDAR_URL = UNI + "/studium/academic-calendar.html"
CALENDAR_TEXT = ("Academic Calendar | Uni X\nWinter semester 2027/28 - October 01, 2027 - March 31, 2028\n"
                 "Classes: October 11, 2027 - January 28, 2028\nApplication deadline: July 15, 2027")
CLASSES = "Classes: October 11, 2027 - January 28, 2028"


def test_only_semester_start_is_university_wide():
    assert [f.name for f in PROFILE.fields if f.university_wide] == ["semester_start"]
    assert PROFILE.university_wide_titles  # what a calendar page's title names


def test_scope_calendar_page_counts_for_a_university_wide_field_only():
    p = page(CALENDAR_URL, CALENDAR_TEXT)
    assert scope_ok(p, PROG, CLASSES, None, PROFILE, spec("semester_start"))
    assert not scope_ok(p, PROG, "Application deadline: July 15, 2027", None, PROFILE, spec("deadline_close"))
    assert not scope_ok(p, PROG, CLASSES, None, PROFILE)  # no field given: the general rule, unchanged


def test_scope_calendar_page_title_may_follow_a_byte_order_mark():
    p = page(CALENDAR_URL, "﻿\n" + CALENDAR_TEXT)
    assert scope_ok(p, PROG, CLASSES, None, PROFILE, spec("semester_start"))


def test_scope_university_wide_needs_own_domain_and_calendar_title():
    start = spec("semester_start")
    # a shared source (DAAD) is official, but it is not the programme's university
    assert not scope_ok(page("https://www2.daad.de/academic-calendar", CALENDAR_TEXT), PROG, CLASSES, None,
                        PROFILE, start)
    # another university's calendar
    assert not scope_ok(page("https://www.uni-y.de/academic-calendar", CALENDAR_TEXT), PROG, CLASSES, None,
                        PROFILE, start)
    # redirected off the programme's domain
    moved = Page(url=CALENDAR_URL, final_url="https://www.uni-y.de/cal", http_status=200, text=CALENDAR_TEXT)
    assert not scope_ok(moved, PROG, CLASSES, None, PROFILE, start)
    # the university's own domain, but not its calendar: another programme's page
    other = page(UNI + "/studies/physics/info.html", "Physics | Uni X\n" + CLASSES)
    assert not scope_ok(other, PROG, CLASSES, None, PROFILE, start)


def test_judge_confirms_semester_start_from_the_calendar_and_not_other_fields():
    pages = [page(CALENDAR_URL, CALENDAR_TEXT)]
    v = run("semester_start", {"A": found("semester_start", "10-11", CLASSES, CALENDAR_URL, cycle="2027/28"),
                               "B": found("semester_start", "10-11", CLASSES, CALENDAR_URL)}, pages=pages)
    assert v.status == "confirmed" and v.value == "10-11" and v.cycle_year == 2027, v.reasons
    q = "Application deadline: July 15, 2027"
    v = run("deadline_close", {"A": found("deadline_close", "07-15", q, CALENDAR_URL),
                               "B": found("deadline_close", "07-15", q, CALENDAR_URL)}, pages=pages)
    assert v.status == "unconfirmed" and "A:scope_unclear" in v.reasons and "B:scope_unclear" in v.reasons


def test_judge_calendar_with_last_years_dates_is_cycle_old():
    """The calendar has not published the intake's winter semester yet: never confirmed for it."""
    text = "Academic Calendar | Uni X\nWinter semester 2026/27\nClasses: October 12, 2026 - January 29, 2027"
    q = "Classes: October 12, 2026 - January 29, 2027"
    v = run("semester_start", {"A": found("semester_start", "10-12", q, CALENDAR_URL, cycle="2026/27"),
                               "B": found("semester_start", "10-12", q, CALENDAR_URL)},
            pages=[page(CALENDAR_URL, text)])
    assert v.status == "unconfirmed" and "cycle_old:2026" in v.reasons


def test_judge_academic_year_written_in_full_is_its_first_year():
    """'winter term 2026/2027' is the 2026 intake, not 2027; and a lecture start's own year decides, not the
    end of the lecture period that follows it."""
    text = ("Academic Calendar | Uni X\nSemester dates in general winter term 2026/2027\nBegin of lectures\n"
            "12.10.2026\nEnd of lectures\n05.02.2027")
    q = "Begin of lectures\n12.10.2026\nEnd of lectures\n05.02.2027"
    v = run("semester_start", {"A": found("semester_start", "10-12", q, CALENDAR_URL, cycle="winter term 2026/2027"),
                               "B": found("semester_start", "10-12", q, CALENDAR_URL,
                                          cycle="winter term 2026/2027")},
            pages=[page(CALENDAR_URL, text)])
    assert v.status == "unconfirmed" and "cycle_old:2026" in v.reasons


# The universities' real academic calendars (Slice 9b): the URL and the page's real title (first line) only;
# the dates below are synthetic.
CALENDARS = {
    "ovgu-": ("https://www.ovgu.de/unimagdeburg/en/academiccalendar-p-49226.html", "OVGU - Academic Calendar"),
    "tu-chemnitz-": ("https://www.tu-chemnitz.de/studierendenservice/termine.php.en",
                     "﻿\nAcademic Calendar | Student Service and Central Course Guidance Service | TU Chemnitz"),
    "btu-": ("https://www-docs.b-tu.de/studierende/public/termine-fristen/Termine_WiSe_2027_28.pdf",
             "Terminplan Wintersemester 2027/28 / Dates for the Winter Semester 2027/28"),
}


def test_seed_every_programme_of_the_three_universities_reads_its_calendar():
    seed = yaml.safe_load(PROGRAMME_SEED.read_text(encoding="utf-8"))
    refs = [r for r in seed["programmes"] if r.startswith(tuple(CALENDARS))]
    assert len(refs) == 12
    for ref in refs:
        url, title = next(v for k, v in CALENDARS.items() if ref.startswith(k))
        prog = _seed_programme(ref)
        assert url in prog.start_urls and url not in prog.own_pages, ref  # shared, so never "specific"
        p = page(url, title + "\nLecture period: 11.10.2027 - 28.01.2028")
        assert scope_ok(p, prog, "Lecture period: 11.10.2027 - 28.01.2028", None, PROFILE, spec("semester_start"))
        assert not scope_ok(p, prog, "Lecture period: 11.10.2027 - 28.01.2028", None, PROFILE,
                            spec("deadline_close")), ref


def test_an_application_window_opening_the_year_before_stays_the_intakes():
    """Only a field whose date falls in the intake's own year (`value_year_is_cycle`, the lecture start) takes its
    cycle from the date's year: an application window for WS 2027/28 may open in December 2026."""
    assert [f.name for f in PROFILE.fields if f.value_year_is_cycle] == ["semester_start"]
    text = "MSc Data Science | Uni X\nWinter semester 2027/28: application period 01.12.2026 - 15.07.2027"
    q = "Winter semester 2027/28: application period 01.12.2026 - 15.07.2027"
    v = run("deadline_open", {"A": found("deadline_open", "12-01", q, SPECIFIC, cycle="2027/28"),
                              "B": found("deadline_open", "12-01", q, SPECIFIC)}, pages=[page(SPECIFIC, text)])
    assert v.status == "confirmed" and v.cycle_year == 2027, v.reasons
