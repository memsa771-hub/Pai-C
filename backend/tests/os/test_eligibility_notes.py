"""Slice 4 Task 7: change notes from the fact-change and confirm hooks (spec S4-D7). Synthetic values only."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.contracts.route_contract import RouteContract
from app.os.documents.store import ProfileStore
from app.os.eligibility.notes import cards_for, on_fact_change, on_profile_change
from app.os.eligibility.rules import EligibilityRules
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.changes import after_fact_change
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import load_playbook_dir
from app.os.settings import load_settings

FAKE = Path(__file__).parent / "playbooks"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
URL = "https://uni.example/req"


def contract(student, refs=("p1",)) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"self:{student}", "student_ref": student,
        "origin_country": "PK", "destination_country": "IE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


@pytest.fixture
def svc(engine, clean, os_db):
    return _services(engine, os_db, load_playbook_dir(FAKE))


def _services(engine, os_db, books):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})
    s = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1))
    store, kb = ProgrammeStore(engine, "pai"), SqlKnowledge(engine, "pai")
    for ref, ielts in (("p1", 6.5), ("p2", 6.0), ("p3", 7.5)):
        store.upsert(Programme(ref=ref, route_key="ireland_master", university="Uni X", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://uni.example/{ref}",),
                               official_domains=("uni.example",)))
        set_fact(kb, ref, "grade_requirement", {"percent_min": 60})
        set_fact(kb, ref, "english_requirement", {"ielts": ielts})
    return s


def set_fact(kb, ref, field, value, status="confirmed") -> int:
    return kb.upsert("programme", ref, field, Fact(value, "q" if status == "confirmed" else "", URL, CHECKED, 2027,
                                                    status), "manual")


def profile(engine, student, **values):
    store = ProfileStore(engine, "pai")
    for key, v in values.items():
        store.set(student, key.replace("__", "."), v, None)


def notes(engine, student=None) -> list:
    N = models.eligibility_notes
    q = select(N).order_by(N.c.id)
    with engine.connect() as conn:
        return conn.execute(q.where(N.c.student_ref == student) if student else q).all()


def start(svc, student, refs=("p1",)) -> int:
    return svc.plans.start_plan(contract(student, refs)).plan_id


def test_first_evaluation_no_note(svc, engine):
    start(svc, "stu-1")
    profile(engine, "stu-1", transcript__percentage=70, ielts_trf__overall=7.0)
    assert on_profile_change(svc.plans, "stu-1") == 0 and notes(engine) == []
    with engine.connect() as conn:
        seen = conn.execute(select(models.eligibility_seen)).all()
    assert [(r.student_ref, r.programme_ref, r.verdict) for r in seen] == [("stu-1", "p1", "likely_meets")]


def test_confirm_changing_verdict_writes_one_note(svc, engine):
    plan_id = start(svc, "stu-1")
    profile(engine, "stu-1", transcript__percentage=70, ielts_trf__overall=7.0)
    on_profile_change(svc.plans, "stu-1")
    profile(engine, "stu-1", ielts_trf__overall=6.0)
    assert on_profile_change(svc.plans, "stu-1") == 1
    [n] = notes(engine, "stu-1")
    assert (n.programme_ref, n.verdict, n.payload["previous"]) == ("p1", "likely_below", "likely_meets")
    assert n.payload["plan_id"] == plan_id
    english = next(ln for ln in n.payload["lines"] if ln["check"] == "language:english")
    assert (english["status"], english["have"], english["need"]) == ("likely_below", 6.0, 6.5)


def test_replay_writes_none(svc, engine):
    start(svc, "stu-1")
    profile(engine, "stu-1", transcript__percentage=70, ielts_trf__overall=7.0)
    on_profile_change(svc.plans, "stu-1")
    profile(engine, "stu-1", ielts_trf__overall=6.0)
    on_profile_change(svc.plans, "stu-1")
    assert on_profile_change(svc.plans, "stu-1") == 0 and len(notes(engine)) == 1


def test_back_and_forth_notes_each_change(svc, engine):
    start(svc, "stu-1")
    profile(engine, "stu-1", transcript__percentage=70, ielts_trf__overall=7.0)
    on_profile_change(svc.plans, "stu-1")
    for ielts in (6.0, 7.0, 6.0):
        profile(engine, "stu-1", ielts_trf__overall=ielts)
        on_profile_change(svc.plans, "stu-1")
    assert [n.verdict for n in notes(engine)] == ["likely_below", "likely_meets", "likely_below"]


def test_fact_change_notifies_every_affected_student(svc, engine):
    for s in ("stu-1", "stu-2"):
        start(svc, s)
        profile(engine, s, transcript__percentage=70, ielts_trf__overall=7.0)
        on_profile_change(svc.plans, s)
    start(svc, "stu-3", refs=("p3",))  # another programme: not affected
    profile(engine, "stu-3", transcript__percentage=70, ielts_trf__overall=7.0)
    on_profile_change(svc.plans, "stu-3")
    fact_id = set_fact(svc.knowledge, "p1", "english_requirement", {"ielts": 7.5})
    after_fact_change(svc.plans, svc.kernel, "programme", "p1", "english_requirement", fact_id, "confirmed", 2027)
    assert sorted(n.student_ref for n in notes(engine)) == ["stu-1", "stu-2"]
    assert on_fact_change(svc.plans, "p1", 2027) == 0  # replay


def test_note_carries_suggestions(svc, engine):
    start(svc, "stu-1", refs=("p1", "p3"))
    profile(engine, "stu-1", transcript__percentage=70, ielts_trf__overall=6.5)
    on_profile_change(svc.plans, "stu-1")
    profile(engine, "stu-1", ielts_trf__overall=6.0)
    on_profile_change(svc.plans, "stu-1")
    [n] = notes(engine)  # p3 (needs 7.5) was already below at 6.5: no change, no note
    assert n.programme_ref == "p1" and n.payload["suggestions"] == ["p2"]  # p2 needs 6.0; p3 is chosen anyway


def test_uses_pinned_playbook_rules(engine, clean, os_db):
    v1 = load_playbook_dir(FAKE)
    old = v1[("ireland_master", 1)]
    v2 = old.model_copy(update={"version": 2, "eligibility": EligibilityRules(
        grade=old.eligibility.grade, grade_scales=old.eligibility.grade_scales)})  # no English check in v2
    svc = _services(engine, os_db, v1)
    plan_id = start(svc, "stu-1")
    svc2 = _services(engine, os_db, v1 | {("ireland_master", 2): v2})
    profile(engine, "stu-1", transcript__percentage=70, ielts_trf__overall=7.0)
    [card] = cards_for(svc2.plans, "stu-1", plan_id).values()
    assert [ln.check for ln in card.lines] == ["grade", "language:english"]  # v1, the plan's pinned rules


def test_route_without_rules_writes_nothing(engine, clean, os_db):
    books = load_playbook_dir(FAKE)
    bare = books[("ireland_master", 1)].model_copy(update={"eligibility": None})
    svc = _services(engine, os_db, books | {("ireland_master", 1): bare})
    plan_id = start(svc, "stu-1")
    assert cards_for(svc.plans, "stu-1", plan_id) == {} and on_profile_change(svc.plans, "stu-1") == 0


def test_inbox_lists_unread_notes_and_read_hides_it(svc, engine):
    start(svc, "stu-1")
    profile(engine, "stu-1", transcript__percentage=70, ielts_trf__overall=7.0)
    on_profile_change(svc.plans, "stu-1")
    profile(engine, "stu-1", ielts_trf__overall=6.0)
    on_profile_change(svc.plans, "stu-1")
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    [note] = c.get("/v1/os/inbox", headers={"X-Test-Student": "stu-1"}).json()["notes"]
    assert (note["programme_ref"], note["verdict"]) == ("p1", "likely_below") and note["payload"]["lines"]
    assert c.get("/v1/os/inbox", headers={"X-Test-Student": "stu-2"}).json()["notes"] == []
    assert c.post(f"/v1/os/inbox/notes/{note['id']}/read", headers={"X-Test-Student": "stu-2"}).status_code == 404
    assert c.post(f"/v1/os/inbox/notes/{note['id']}/read", headers={"X-Test-Student": "stu-1"}).status_code == 204
    assert c.get("/v1/os/inbox", headers={"X-Test-Student": "stu-1"}).json()["notes"] == []
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.eligibility_notes)).scalar() == 1  # kept, read
