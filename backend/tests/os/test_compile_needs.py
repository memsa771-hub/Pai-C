"""P1-T8 Task 2: a step's `needs` become provide, result expected and which is right steps (R-17, R-18, R-20, R-21).
Pure: no database. Fictional routes and students only."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.os.compiler import compile_plan
from app.os.contracts.route_contract import RouteContract
from app.os.knowledge import Fact
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.requests import keys
from app.os.requests.state import QuestionRef, StudentState, scale_pairs

HERE = Path(__file__).parent
BOOKS = {**load_playbook_dir(HERE / "playbooks"), **load_playbook_dir(HERE / "playbooks" / "needs")}
INTER1, INTER2 = BOOKS[("pakistan_inter", 1)], BOOKS[("pakistan_inter", 2)]
BS2 = BOOKS[("pakistan_bs", 2)]
TODAY = date(2027, 3, 1)
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
OBTAINED, TOTAL = "education.matric.marks_obtained", "education.matric.marks_total"
PROVIDE_OBTAINED = f"provide@fact:{OBTAINED}"
RESULT = f"result_expected@fact:{OBTAINED}"

pytestmark = pytest.mark.req("R-17")


def contract(refs=("p1",), level="bachelor") -> RouteContract:  # the compiler reads only the programmes
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "ext-1", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "PK", "level": level,
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)],
    })


def fact(value, status="confirmed") -> Fact:
    return Fact(value=value, quote="q", url="https://calendar.example/x", checked_at=CHECKED, intake_year=2027,
                status=status)


def merit(refs=("p1",)) -> dict:
    return {(r, "merit_list_date"): fact({"date": "2027-08-15"}) for r in refs}


CALENDAR = {"matric_result_date": fact({"date": "2027-04-30", "tz": "Asia/Karachi"})}


def build(state, book=INTER2, refs=("p1",), route_facts=None, today=TODAY, level="bachelor", **kw):
    return compile_plan(contract(refs, level), book, route_facts or {}, merit(refs), today, student=state, **kw)


def task(draft, key):
    return next(t for t in draft.tasks if t.instance_key == key)


def keys_of(draft) -> set[str]:
    return {t.instance_key for t in draft.tasks}


NOTHING = StudentState()


def test_missing_fact_adds_one_provide_step_dated_from_the_needing_step():
    d = build(NOTHING)
    provide, form = task(d, f"{PROVIDE_OBTAINED}:stated"), task(d, "admission_form")
    assert (provide.task_type, provide.kind, provide.inbox_kind) == ("student.provide", "student", "provide")
    assert provide.template_key == "provide" and provide.title == "Tell us your matric marks"
    assert provide.latest_finish == form.latest_start  # R-17: dated backwards from the step that needs it
    assert form.blocked_reason == f"awaiting_fact:{OBTAINED}"
    assert (provide.instance_key, True) in form.depends_on
    assert not [k for k in d.answered if k.startswith("provide@")]  # nothing was given yet


@pytest.mark.req("R-19")
def test_two_steps_needing_one_fact_share_one_provide_step():
    d = build(NOTHING, refs=("p1", "p2"))
    asking = [k for k in keys_of(d) if k.startswith(PROVIDE_OBTAINED)]
    assert asking == [f"{PROVIDE_OBTAINED}:stated"]
    for step in ("admission_form", "merit_list@p1", "merit_list@p2"):
        assert (asking[0], True) in task(d, step).depends_on
        assert task(d, step).blocked_reason == f"awaiting_fact:{OBTAINED}"


@pytest.mark.req("R-18")
def test_stated_met_moves_the_ask_to_shown():
    state = StudentState(facts={OBTAINED: "stated", TOTAL: "stated"})
    d = build(state)
    assert f"{PROVIDE_OBTAINED}:stated" in d.answered
    assert f"{PROVIDE_OBTAINED}:stated" not in keys_of(d) and f"{PROVIDE_OBTAINED}:shown" in keys_of(d)
    assert task(d, "admission_form").blocked_reason is None  # typing the marks was all it needed
    merit_list = task(d, "merit_list@p1")  # but it needs the mark sheet
    assert merit_list.blocked_reason == f"awaiting_fact:{OBTAINED}"
    assert (f"{PROVIDE_OBTAINED}:shown", True) in merit_list.depends_on
    assert not [k for k in keys_of(d) if k.startswith(f"provide@fact:{TOTAL}")]


@pytest.mark.req("R-18")
def test_shown_meets_a_stated_need_and_a_shown_need():
    d = build(StudentState(facts={OBTAINED: "shown", TOTAL: "confirmed"}))
    assert not [k for k in keys_of(d) if k.startswith("provide@")]
    assert {t.blocked_reason for t in d.tasks} == {None}
    assert {f"{PROVIDE_OBTAINED}:stated", f"{PROVIDE_OBTAINED}:shown"} <= set(d.answered)


@pytest.mark.req("R-18")
def test_inferred_counts_as_missing():
    d = build(StudentState(facts={OBTAINED: "unknown", TOTAL: "unknown"}))
    assert f"{PROVIDE_OBTAINED}:stated" in keys_of(d) and f"provide@fact:{TOTAL}:stated" in keys_of(d)
    assert not [k for k in d.answered if k.startswith("provide@")]


def test_document_need_met_only_by_a_confirmed_document():
    uploaded = build(StudentState(facts={"education.intermediate.marks_obtained": "stated"},
                                  documents={"hssc_certificate": "uploaded"}), BS2, level="bachelor")
    provide = task(uploaded, "provide@document:hssc_certificate:shown")
    assert provide.title == "Upload your intermediate certificate"
    assert task(uploaded, "merit_list@p1").blocked_reason == "awaiting_fact:hssc_certificate"
    assert "provide@document:hssc_certificate:shown" not in uploaded.answered
    confirmed = build(StudentState(facts={"education.intermediate.marks_obtained": "stated"},
                                   documents={"hssc_certificate": "confirmed"}), BS2, level="bachelor")
    assert "provide@document:hssc_certificate:shown" not in keys_of(confirmed)
    assert "provide@document:hssc_certificate:shown" in confirmed.answered
    assert task(confirmed, "merit_list@p1").blocked_reason is None


@pytest.mark.req("R-20")
def test_result_expected_before_provide_when_calendar_date_is_ahead():
    d = build(NOTHING, route_facts=CALENDAR)
    waits, provide = task(d, RESULT), task(d, f"{PROVIDE_OBTAINED}:stated")
    assert (waits.task_type, waits.kind, waits.template_key) == ("system.milestone", "work", "result_expected")
    assert waits.title == "Matric result expected"
    assert waits.blocked_reason == f"result_expected:{OBTAINED}"
    assert waits.latest_finish == datetime(2027, 4, 30, 23, 59, 59, tzinfo=ZoneInfo("Asia/Karachi"))
    assert {c["url"] for c in waits.citations} == {"https://calendar.example/x"}
    assert (RESULT, True) in provide.depends_on
    # the provide step's date does not pull the calendar date earlier
    assert waits.latest_finish == datetime(2027, 4, 30, 23, 59, 59, tzinfo=ZoneInfo("Asia/Karachi"))
    assert waits.fact_refs == (("route", "pakistan_inter", "matric_result_date"),)
    # after the date the step is gone and the provide step stays
    later = build(NOTHING, route_facts=CALENDAR, today=date(2027, 5, 1))
    assert RESULT not in keys_of(later) and f"{PROVIDE_OBTAINED}:stated" in keys_of(later)
    assert (RESULT, True) not in task(later, f"{PROVIDE_OBTAINED}:stated").depends_on
    # on the day itself the result is out
    assert RESULT not in keys_of(build(NOTHING, route_facts=CALENDAR, today=date(2027, 4, 30)))
    # with the fact given, both are gone
    given = build(StudentState(facts={OBTAINED: "shown", TOTAL: "stated"}), route_facts=CALENDAR)
    assert RESULT not in keys_of(given) and not [k for k in keys_of(given) if k.startswith("provide@")]


@pytest.mark.req("R-20")
def test_no_result_expected_without_a_calendar_fact_or_an_ask_for_it():
    assert RESULT not in keys_of(build(NOTHING))
    assert not [k for k in keys_of(build(NOTHING, route_facts=CALENDAR)) if k.startswith(f"result_expected@fact:{TOTAL}")]
    bad = {"matric_result_date": fact({"date": "not a date"})}
    assert RESULT not in keys_of(build(NOTHING, route_facts=bad))


@pytest.mark.req("R-21")
def test_fact_in_question_gets_which_is_right_not_provide():
    state = StudentState(facts={OBTAINED: "stated", TOTAL: "stated"},
                         questions={f"fact:{OBTAINED}": QuestionRef("vault", "profile_issue:7")})
    d = build(state)
    ask = task(d, f"which_is_right@fact:{OBTAINED}:shown")  # the highest level any step needs
    assert (ask.task_type, ask.kind, ask.inbox_kind, ask.template_key) == (
        "student.choose", "student", "choose", "which_is_right")
    assert ask.title == "Which matric marks are right?"
    assert not [k for k in keys_of(d) if k.startswith(PROVIDE_OBTAINED)]
    for step in ("admission_form", "merit_list@p1"):
        assert task(d, step).blocked_reason == f"which_is_right:{OBTAINED}"
        assert (ask.instance_key, True) in task(d, step).depends_on
    assert ask.latest_finish == task(d, "admission_form").latest_start


@pytest.mark.req("R-21")
def test_impossible_value_is_a_question():
    state = StudentState(facts={OBTAINED: "stated", TOTAL: "stated"},
                         questions={f"fact:{OBTAINED}": QuestionRef("impossible", f"{OBTAINED}:{TOTAL}")})
    d = build(state)
    assert f"which_is_right@fact:{OBTAINED}:shown" in keys_of(d)
    assert f"which_is_right@fact:{TOTAL}:stated" not in keys_of(d)


def test_scale_pairs_come_from_document_types_and_limits():
    from app.os.documents.types import load_document_types

    pairs = scale_pairs(load_document_types())
    assert (OBTAINED, TOTAL) in pairs
    assert ("education.intermediate.part1.marks_obtained", "education.intermediate.part1.marks_total") in pairs


@pytest.mark.req("R-21")
def test_document_conflict_gets_a_which_is_right_step_that_blocks_the_needing_steps():
    state = StudentState(facts={"education.intermediate.marks_obtained": "stated"},
                         documents={"hssc_certificate": "confirmed"},
                         questions={"document:hssc_certificate": QuestionRef("documents", "finding:3")})
    d = build(state, BS2, level="bachelor")
    ask, merit_list = task(d, "which_is_right@document:hssc_certificate:shown"), task(d, "merit_list@p1")
    assert (ask.instance_key, True) in merit_list.depends_on
    assert merit_list.blocked_reason == "which_is_right:hssc_certificate"
    assert ask.latest_finish == merit_list.latest_start  # dated backwards from the step it blocks
    # answered: the conflict goes, the step and the block go, and the question counts as answered
    done = build(StudentState(facts=state.facts, documents=state.documents), BS2, level="bachelor")
    assert "which_is_right@document:hssc_certificate:shown" in done.answered
    assert "which_is_right@document:hssc_certificate:shown" not in keys_of(done)
    assert task(done, "merit_list@p1").blocked_reason != "which_is_right:hssc_certificate"


@pytest.mark.req("R-21")
def test_mismatch_finding_blocks_steps_needing_those_documents():
    state = StudentState(facts={"education.intermediate.marks_obtained": "stated"},
                         documents={"hssc_certificate": "confirmed"},
                         questions={"document:hssc_certificate": QuestionRef("documents", "finding:3")})
    d = build(state, BS2, level="bachelor")
    assert task(d, "merit_list@p1").blocked_reason == "which_is_right:hssc_certificate"
    assert task(d, "entry_test").blocked_reason is None  # it needs a fact, not that document
    # D-w5 (controller ruling, fix round 1): a document in question gets its which_is_right step too, as a fact does
    ask = task(d, "which_is_right@document:hssc_certificate:shown")
    assert (ask.task_type, ask.kind, ask.inbox_kind) == ("student.choose", "student", "choose")
    assert ask.title  # from the ask, or the ask's own title for the level when the book gives no which_is_right
    assert not [k for k in keys_of(d) if k.startswith("provide@document:hssc_certificate")]  # none while in question
    assert not [k for k in d.answered if k.startswith("which_is_right@document:hssc_certificate")]


def test_a_step_with_its_own_block_keeps_it():
    # no merit-list date: the anchor blocks merit_list; the missing marks do not replace that
    d = compile_plan(contract(), INTER2, {}, {}, TODAY, student=NOTHING)
    assert task(d, "merit_list@p1").blocked_reason == "fact_missing:merit_list_date"
    assert (f"{PROVIDE_OBTAINED}:stated", True) in task(d, "merit_list@p1").depends_on


def test_same_state_same_draft():
    state = StudentState(facts={OBTAINED: "stated"}, documents={"hssc_certificate": "uploaded"})
    assert build(state, route_facts=CALENDAR) == build(state, route_facts=CALENDAR)
    assert build(state, refs=("p2", "p1")) == build(state, refs=("p1", "p2"))


def test_needs_ignored_without_student_state():
    plain = compile_plan(contract(), INTER1, {}, merit(), TODAY)
    ignored = compile_plan(contract(), INTER2, {}, merit(), TODAY)
    assert ignored.tasks == plain.tasks and ignored.answered == ()
    assert (ignored.playbook_version, plain.playbook_version) == (2, 1)
    assert compile_plan(contract(), INTER2, {}, merit(), TODAY, student=None) == ignored


def test_germany_v2_needs_ignored_without_student_state_equals_v1_without_school_certificates():
    v1, v2 = (load_playbook_dir(PLAYBOOK_DIR)[("germany_master", n)] for n in (1, 2))
    gone = {"school_certificates"}
    data = v1.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"] = [{**t, "depends_on": [d for d in t.get("depends_on", []) if d["key"] not in gone]}
                     for t in data["tasks"] if t["template_key"] not in gone]
    trimmed = type(v1).model_validate(data)
    germany = RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "g", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "DE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": "tu-x", "rank": 1}]})
    a = compile_plan(germany, trimmed, {}, {}, TODAY)
    b = compile_plan(germany, v2, {}, {}, TODAY)
    assert {t.instance_key for t in a.tasks} == {t.instance_key for t in b.tasks}
    assert a.tasks == b.tasks and b.answered == ()


def test_student_none_omitted_and_empty_state_compile_the_same_for_books_without_needs():
    """Only what it says: for a book without needs, omitting `student`, passing None and passing an empty state give
    one draft with `answered == ()`. It does not prove the draft equals the one the compiler gave before T8; that
    proof is `test_compiler.py`, `test_golden.py` and `test_kernel.py`, which pass unchanged."""
    germany = load_playbook_dir(PLAYBOOK_DIR)[("germany_master", 1)]
    c = RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "g", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "DE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": "tu-x", "rank": 1}, {"programme_ref": "uni-y", "rank": 2}]})
    omitted = compile_plan(c, germany, {}, {}, TODAY)
    for book, contract_ in ((germany, c), (INTER1, contract()), (BOOKS[("ireland_master", 1)], contract(level="master"))):
        base = compile_plan(contract_, book, {}, {}, TODAY)
        assert compile_plan(contract_, book, {}, {}, TODAY, student=None) == base
        assert compile_plan(contract_, book, {}, {}, TODAY, student=NOTHING) == base
        assert base.answered == ()
    assert omitted.answered == ()


def test_keys_make_and_parse():
    k = keys.make("provide", "fact", OBTAINED, "stated")
    assert keys.parse(k) == keys.RequestKey("provide", "fact", OBTAINED, "stated")
    assert keys.parse(keys.make("result_expected", "fact", OBTAINED)).level is None
    assert keys.parse(f"{k}#c3") is None and keys.parse("admission_form") is None
    assert keys.parse("provide@thing:x:stated") is None and keys.parse("provide@fact:x:odd") is None


def test_the_request_steps_have_the_asks_citations_when_a_route_requires_them():
    germany = load_playbook_dir(PLAYBOOK_DIR)[("germany_master", 2)]
    assert germany.require_citations
    c = RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "g", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "DE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": "tu-x", "rank": 1}]})
    d = compile_plan(c, germany, {}, {}, TODAY, student=NOTHING)
    asked = [t for t in d.tasks if t.template_key == "provide"]
    assert {t.instance_key for t in asked} == {"provide@document:ssc_certificate:shown",
                                               "provide@document:hssc_certificate:shown"}
    assert all(t.citations for t in asked)
    uncited = {t.instance_key for t in d.tasks if t.kind == "student" and not t.citations}
    assert not uncited & {t.instance_key for t in asked}


@pytest.mark.req("R-21")
def test_a_document_which_is_right_step_has_the_asks_citations():
    germany = load_playbook_dir(PLAYBOOK_DIR)[("germany_master", 2)]
    c = RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "g", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "DE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": "tu-x", "rank": 1}]})
    state = StudentState(documents={"ssc_certificate": "confirmed", "hssc_certificate": "confirmed"},
                         questions={"document:ssc_certificate": QuestionRef("documents", "finding:1")})
    d = compile_plan(c, germany, {}, {}, TODAY, student=state)
    ask = task(d, "which_is_right@document:ssc_certificate:shown")
    given = [c.model_dump(mode="json") for c in germany.asks["ssc_certificate"].citations]
    assert list(ask.citations) == given and given
    assert ask.title
