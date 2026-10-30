"""Slice 4 final review: one test per Critical / Important finding, each written to fail first. Synthetic values only."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.os import models
from app.os.api import make_services
from app.os.contracts.route_contract import IntakeRef, RouteContract
from app.os.documents.store import ProfileStore
from app.os.eligibility import notes as notes_module
from app.os.eligibility.evaluate import evaluate
from app.os.eligibility.notes import on_profile_change
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.changes import after_fact_change
from app.os.knowledge.profile import load_profile_dir
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.requests import request_programme
from app.os.knowledge.research.run import store_research
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.routes import builder
from app.os.routes.builder import PlanExists, start, swap
from app.os.settings import load_settings
from tests.os.test_route_builder import choices

FAKE = Path(__file__).parent / "playbooks"
BOOKS = load_playbook_dir(FAKE) | load_playbook_dir(PLAYBOOK_DIR)
DE = BOOKS[("germany_master", 1)].eligibility
PK = BOOKS[("pakistan_bs", 1)].eligibility
NOW = datetime(2026, 10, 22, 9, tzinfo=timezone.utc)
WINTER = IntakeRef(term="winter", year=2027)


def fact(value, status="confirmed") -> Fact:
    return Fact(value, "q" if status == "confirmed" else "", "https://uni.example/r", NOW, 2027, status)


DE_FACTS = {"grade_requirement": fact({"german_max": 2.5}), "english_requirement": fact({"ielts": 6.5}),
            "german_requirement": fact({"level": "none"}), "admission_test": fact(None)}


def line(card, check):
    return next(ln for ln in card.lines if ln.check == check)


@pytest.fixture
def svc(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})
    s = make_services(settings, engine=engine, playbooks=BOOKS, today=lambda: date(2027, 3, 1))
    store, kb = ProgrammeStore(engine, "pai"), SqlKnowledge(engine, "pai")
    for ref in ("p1", "p2", "p3", "p4"):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="Uni X", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
        for field, value in (("grade_requirement", {"percent_min": 60}), ("english_requirement", {"ielts": 6.5}),
                             ("deadline_close", {"date": "2027-07-15"})):
            kb.upsert("programme", ref, field, fact(value), "manual")
    return s


# --- 1 (Critical): an impossible scale never crashes a confirm, a card or fact storage -------------------------


def test_zero_span_letter_needs_input_not_crash():
    letter = {"transcript.cgpa": 3.2, "min_passing_grade_letter.scale_best": 4.0, "min_passing_grade_letter.min_pass": 4.0}
    g = line(evaluate(DE, "p", DE_FACTS, letter), "grade")
    assert (g.status, g.reason) == ("needs_input", "invalid_value")


def test_zero_total_needs_input_not_crash():
    values = {"hssc_certificate.marks_obtained": 0, "hssc_certificate.marks_total": 0, "entry_test.score": 80}
    facts = {"merit_closing": fact({"aggregate": 80}), "entry_test_required": fact({"any_of": []})}
    g = line(evaluate(PK, "p", facts, values), "grade")
    assert (g.status, g.reason) == ("needs_input", "invalid_value")


def test_note_failure_never_breaks_fact_change(svc, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("note failed")

    monkeypatch.setattr(notes_module, "on_fact_change", boom)
    fact_id = SqlKnowledge(svc.engine, "pai").upsert("programme", "p1", "english_requirement", fact({"ielts": 7.0}),
                                                     "manual")
    after_fact_change(svc.plans, svc.kernel, "programme", "p1", "english_requirement", fact_id, "confirmed", 2027)


def test_note_failure_never_breaks_a_confirm(monkeypatch):
    import app.os.api.router as router_module

    assert hasattr(router_module, "_notify"), "the router calls notes through a guard that logs and carries on"
    called = []

    def boom(*a, **k):
        called.append(1)
        raise RuntimeError("note failed")

    monkeypatch.setattr(router_module, "on_profile_change", boom)
    router_module._notify(object(), "stu-1")  # must not raise
    assert called == [1]


# --- 2 (Important): concurrent swaps never lose a change -------------------------------------------------------


def test_concurrent_swaps_keep_both(svc, monkeypatch):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
    stale = svc.plans._contract(plan)[0]  # what the first tab read, before the second swap landed
    swap(svc.plans, "stu-1", plan, "p2", "p4")
    real_own = builder._own
    monkeypatch.setattr(builder, "_own", lambda plans, student, pid: (real_own(plans, student, pid), stale)[1])
    swap(svc.plans, "stu-1", plan, "p1", "p3")
    contract = svc.plans._contract(plan)[0]
    assert sorted((p.programme_ref, p.rank) for p in contract.programmes) == [("p3", 1), ("p4", 2)]


# --- 3 (Important): starting again cannot rewrite a plan -------------------------------------------------------


def test_start_again_with_other_choices_refused(svc):
    first = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2"))
    with pytest.raises(PlanExists, match="swap"):
        start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p3", "p4"))
    again = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2"))
    assert (again.plan_id, again.created) == (first.plan_id, False)
    assert [p.programme_ref for p in svc.plans._contract(first.plan_id)[0].programmes] == ["p1", "p2"]


# --- 4 (Important): a test score the rules cannot check is never "meets" ---------------------------------------


def test_toefl_only_requirement_needs_proof():
    e = line(evaluate(DE, "p", DE_FACTS | {"english_requirement": fact({"toefl_ibt": 72, "moi_accepted": False})},
                      {"ielts_trf.overall": 8.0}), "language:english")
    assert (e.status, e.reason) == ("needs_input", "no_proof_type") and "toefl ibt 72" in str(e.need)


def test_requirement_stating_nothing_is_unknown():
    e = line(evaluate(DE, "p", DE_FACTS | {"english_requirement": fact({"cefr": None, "ielts": None})}, {}),
             "language:english")
    assert e.status == "unknown"


# --- 5 (Important): a CGPA on another scale is never read as out of 4 ------------------------------------------


def test_cgpa_on_other_scale_not_read_as_4():
    g = line(evaluate(DE, "p", DE_FACTS, {"transcript.cgpa": 3.0, "transcript.cgpa_scale": 5.0}), "grade")
    assert (g.status, g.reason) == ("needs_input", "other_scale")
    g = line(evaluate(DE, "p", DE_FACTS, {"transcript.cgpa": 3.0, "transcript.cgpa_scale": 4.0}), "grade")
    assert g.status == "likely_meets"
    g = line(evaluate(DE, "p", DE_FACTS, {"transcript.cgpa": 3.0}), "grade")  # scale not printed: the scale's own
    assert g.status == "likely_meets"


# --- 6 (Important): the same programme in two plans never writes false notes -----------------------------------


def test_same_programme_two_plans_no_spurious_notes(svc):
    for year in (2027, 2028):  # facts exist for 2027 only: the 2028 card is "being researched"
        svc.plans.start_plan(RouteContract.model_validate({
            "contract_version": "1", "source": "self_serve", "external_ref": f"self:stu-1:{year}", "student_ref": "stu-1",
            "origin_country": "PK", "destination_country": "IE", "level": "master",
            "target_intake": {"term": "winter", "year": year}, "programmes": [{"programme_ref": "p1", "rank": 1}]}))
    ProfileStore(svc.engine, "pai").set("stu-1", "transcript.percentage", 70, None)
    on_profile_change(svc.plans, "stu-1")
    assert [on_profile_change(svc.plans, "stu-1") for _ in range(3)] == [0, 0, 0]
    with svc.engine.connect() as conn:
        assert conn.execute(select(models.eligibility_notes)).all() == []


# --- 7 (Important): a request for another intake year gets that year researched --------------------------------


def test_request_other_year_enqueues_research(svc):
    sent = []

    def ask(student, year):
        return request_programme(svc.engine, "pai", student, "ireland_master", "Uni New", "New", "https://new.example/x",
                                 now=NOW, intake_year=year, enqueue=lambda ref: sent.append((ref, year)))

    ref, created = ask("stu-1", 2027)
    assert created and sent == [(ref, 2027)]
    assert ask("stu-2", 2028) == (ref, False) and sent[-1] == (ref, 2028)  # a new year: research for it
    SqlKnowledge(svc.engine, "pai").upsert("programme", ref, "english_requirement", fact({"ielts": 6.0}), "research")
    ask("stu-3", 2027)
    assert len(sent) == 2  # 2027 has facts now: no new research


# --- Ruling (graded Important): a student-supplied page cannot make facts "checked" -----------------------------


def test_requested_programme_facts_capped_unconfirmed(svc):
    ProgrammeStore(svc.engine, "pai").upsert(Programme(
        ref="req-abc", route_key="germany_master", university="Uni R", name="R", aliases=(),
        start_urls=("https://r.example/p",), official_domains=("r.example",), status="requested"))
    verdict = {"status": "confirmed", "value": "english", "quote": "Taught in English.", "url": "https://r.example/p",
               "conflict_note": None, "evidence": []}
    store_research(svc.engine, svc.plans, svc.kernel, None, "req-abc", 2027, load_profile_dir()["germany_master"],
                   {"language_of_instruction": verdict}, NOW)
    [(_, stored)] = SqlKnowledge(svc.engine, "pai").programme_facts(["req-abc"], ["language_of_instruction"], 2027).items()
    assert stored.status == "unconfirmed"
