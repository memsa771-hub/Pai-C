"""Slice 4 Task 5: tables os_0006 and programme requests researched once (spec S4-D8, S4-D11, §3, Q1)."""

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, inspect, select

from app.os import models
from app.os.db import OS_SCHEMA
from app.os.knowledge.port import Fact
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.requests import RequestLimit, request_programme, requested_without_facts, visible_programmes
from app.os.knowledge.store import SqlKnowledge

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
URL = "https://www.uni-x.example/master/data-science"


def ask(engine, student="stu-1", url=URL, name="Data Science", university="Uni X", now=NOW, sent=None):
    sent = sent if sent is not None else []
    return request_programme(engine, "pai", student, "germany_master", university, name, url, now=now,
                             enqueue=sent.append), sent


def add_fact(engine, ref, year=2027):
    SqlKnowledge(engine, "pai").upsert("programme", ref, "language_of_instruction", Fact(
        value="english", quote="", url=URL, checked_at=NOW, intake_year=year, status="unconfirmed"), "research")


def test_migration_up_down(os_db):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0005"], os_db)
    eng = create_engine(os_db)
    try:
        tables = set(inspect(eng).get_table_names(schema=OS_SCHEMA))
        assert not tables & {"os_programme_requests", "os_eligibility_seen", "os_eligibility_notes"}
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_request_creates_and_enqueues_once(engine, clean):
    (ref, created), sent = ask(engine)
    assert created and ref.startswith("req-") and sent == [ref]
    p = ProgrammeStore(engine, "pai").get(ref)
    assert (p.status, p.route_key, p.university, p.name) == ("requested", "germany_master", "Uni X", "Data Science")
    assert p.official_domains == ("uni-x.example",) and p.start_urls == (URL,)
    assert p.notes == "requested by a student"


def test_same_url_returns_existing(engine, clean):
    (ref, _), _ = ask(engine)
    (again, created), sent = ask(engine, student="stu-2", url=URL.upper().replace("HTTPS", "https") + "/")
    assert (again, created, sent) == (ref, False, [])


def test_same_university_and_name_returns_existing(engine, clean):
    (ref, _), _ = ask(engine)
    (again, created), _ = ask(engine, student="stu-2", url="https://uni-x.example/ds", name=" data science ",
                              university="UNI X")
    assert (again, created) == (ref, False)


def test_existing_active_programme_returned(engine, clean):
    ProgrammeStore(engine, "pai").upsert(Programme(ref="uni-x-ds", route_key="germany_master", university="Uni X",
                                                   name="Data Science", aliases=(), start_urls=(URL,),
                                                   official_domains=("uni-x.example",)))
    (ref, created), sent = ask(engine)
    assert (ref, created, sent) == ("uni-x-ds", False, [])


def test_concurrent_requests_one_programme(engine, clean):
    sent, results, barrier = [], [], threading.Barrier(4)

    def go(i):
        barrier.wait()
        results.append(ask(engine, student=f"stu-{i}", sent=sent)[0])

    threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({ref for ref, _ in results}) == 1 and sum(c for _, c in results) == 1 and len(sent) == 1
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.programmes)).scalar() == 1


def test_daily_cap(engine, clean):
    for i in range(3):
        ask(engine, url=f"https://uni-{i}.example/p", name=f"P{i}", university=f"U{i}")
    with pytest.raises(RequestLimit):
        ask(engine, url="https://uni-9.example/p", name="P9", university="U9", now=NOW + timedelta(hours=23))
    ask(engine, url="https://uni-9.example/p", name="P9", university="U9", now=NOW + timedelta(hours=25))


def test_http_url_refused(engine, clean):
    with pytest.raises(ValueError, match="https"):
        ask(engine, url="http://uni-x.example/p")
    with pytest.raises(ValueError, match="https"):
        ask(engine, url="https://")


def test_requested_hidden_until_facts(engine, clean):
    (ref, _), _ = ask(engine)
    assert ref not in {p.ref for p in visible_programmes(engine, "pai", "germany_master", 2027)}
    add_fact(engine, ref)
    assert ref in {p.ref for p in visible_programmes(engine, "pai", "germany_master", 2027)}
    assert ref not in {p.ref for p in visible_programmes(engine, "pai", "germany_master", 2028)}


def test_second_student_sees_it_without_research(engine, clean):
    (ref, _), sent = ask(engine)
    add_fact(engine, ref)
    (again, created), sent2 = ask(engine, student="stu-2")
    assert (again, created, sent2) == (ref, False, [])
    assert ref in {p.ref for p in visible_programmes(engine, "pai", "germany_master", 2027)}


def test_admin_open_facts_lists_unresearched_request(engine, clean):
    (ref, _), _ = ask(engine)
    assert [p.ref for p in requested_without_facts(engine, "pai")] == [ref]
    add_fact(engine, ref)
    assert requested_without_facts(engine, "pai") == []


def test_tenants_apart(engine, clean):
    (ref, _), _ = ask(engine)
    assert visible_programmes(engine, "other", "germany_master", 2027) == []
    assert requested_without_facts(engine, "other") == []
