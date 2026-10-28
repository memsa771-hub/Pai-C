"""Slice 9a Task 9: the rehearsal driver's own rules (spec §2.4, §2.5, S9-D12; plan Review Focus 5).

The first four tests need no database. The last one runs a short real rehearsal (a worker subprocess, offline AI)
with one student's document answer removed. Fictional data only."""

from datetime import date, timedelta
from pathlib import Path

import yaml
from sqlalchemy import select

from app.os import models
from app.os.knowledge.programmes import PROGRAMME_SEED
from app.os.knowledge.seed import SEED_DIR
from tests.os.rehearsal.driver import END, SAMPLES, StuckWatch, load_students, should_stop, student_ref, Rehearsal
from tests.os.rehearsal.failures import Failure, FailureLog

EVENTS = {"S3": "rejected", "S5": "missing_document", "S7": "late", "S9": "approved_changed", "S11": "ignore_big"}


def _seeded_programmes() -> set[str]:
    """The seeded Germany programmes that have the facts an application step needs (route and deadline)."""
    facts = yaml.safe_load((SEED_DIR / "germany_ws2027.yaml").read_text(encoding="utf-8"))["programmes"]
    registry = yaml.safe_load(PROGRAMME_SEED.read_text(encoding="utf-8"))["programmes"]
    return {ref for ref, f in facts.items() if ref in registry and {"deadline_close", "application_route"} <= set(f)}


def test_students_file_valid():
    students = load_students()
    assert list(students) == [f"S{n}" for n in range(1, 13)]
    key = yaml.safe_load((SAMPLES / "samples_key.yaml").read_text(encoding="utf-8"))
    planted = {int(b[1:]) for b, v in key["bundles"].items() if v["expect"]}
    seeded = _seeded_programmes()
    for sid, s in students.items():
        assert s.event == EVENTS.get(sid, "none"), sid
        assert 2 <= len(s.programmes) <= 4 and set(s.programmes) <= seeded, sid
        assert set(s.admission) == set(s.programmes), sid
        assert set(s.admission.values()) <= {"admitted", "rejected"} and "admitted" in s.admission.values(), sid
        assert s.admission[s.visa_programme] == "admitted", sid
        assert 1 <= s.bundle <= 5, sid
        for doc_type, name in s.files().items():  # only the fictional sample bundles, each file listed in the key
            assert (SAMPLES / name).is_file() and key["documents"][name]["type"] == doc_type, (sid, name)
        assert (s.bundle in planted) == (sid in ("S2", "S4")), sid  # exactly two students have planted mistakes
    assert {sid for sid, s in students.items() if "rejected" in s.admission.values()} == {"S3", "S11"}
    assert all(students[s].resolve for s in ("S2", "S4"))


def test_failure_log_roundtrip(tmp_path):
    path = tmp_path / "run" / "failures.yaml"
    log = FailureLog(path)
    first = Failure("stuck:S1", "S1", None, "a change within 30 rehearsal days", "no change", "blocks")
    second = Failure("missed:S3:rejected", "S3", "admission_result", "programme removed", "still open", "workaround")
    assert log.add(first) and log.add(second)
    assert not log.add(first)  # one entry per id
    again = FailureLog(path)
    assert again.entries() == [first, second]
    assert again.counts() == {"blocks": 1, "workaround": 1}
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["failures"][1]["severity"] == "workaround"


def test_stuck_after_30_days():
    watch, start = StuckWatch(), date(2027, 1, 4)
    for day in range(30):  # 29 days without a change and nothing waiting: not yet
        assert watch.see("S1", start + timedelta(days=day), ("active", 3), waiting=False) is None
    got = watch.see("S1", start + timedelta(days=30), ("active", 3), waiting=False)
    assert isinstance(got, Failure) and got.severity == "blocks" and got.student == "S1" and "stuck" in got.got
    assert watch.see("S1", start + timedelta(days=31), ("active", 3), waiting=False) is None  # reported once

    for day in range(0, 60, 2):  # something waits on the student: never stuck
        assert watch.see("S2", start + timedelta(days=day), ("active", 1), waiting=True) is None
    for day in range(0, 60, 2):  # the plan keeps changing: never stuck
        assert watch.see("S3", start + timedelta(days=day), ("active", day), waiting=False) is None


def test_stop_at_30_sep_2027():
    assert END == date(2027, 9, 30)
    assert not should_stop(date(2027, 9, 30), {"S1": "running", "S2": "visa_ready"})
    assert should_stop(date(2027, 10, 1), {"S1": "running"})
    assert should_stop(date(2026, 12, 20), {"S1": "visa_ready", "S2": "stuck"})  # every plan is over
    assert not should_stop(date(2026, 12, 20), {"S1": "visa_ready", "S2": "running"})
    assert should_stop(date(2026, 12, 5), {"S1": "running"}, end=date(2026, 12, 4))


def test_missing_offline_answer_logged_run_continues(os_db, tmp_path):
    """Review Focus 5: S1's transcript has no offline answer. Its reading fails through the normal invalid-output
    path; the driver logs one failure naming the missing key and file; S1's other documents and S6 (no scripted event)
    carry on: S6 reaches both end points with no failure of its own."""
    students = load_students()
    transcript = students["S1"].files()["transcript"]
    assert students["S6"].bundle != students["S1"].bundle and students["S6"].event == "none"
    removed = {}

    def drop_transcript(answers_dir: Path) -> None:
        path = answers_dir / "documents.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        [sha] = [k for k, v in data.items() if v["file"] == transcript]
        removed["sha"] = sha
        del data[sha]
        path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    out = tmp_path / "run"
    report = Rehearsal(["S1", "S6"], out, end=date(2026, 12, 6), answers_edit=drop_transcript).run()

    entries = FailureLog(out / "failures.yaml").entries()
    missing = [f for f in entries if "missing offline answer" in f.got]
    assert len(missing) == 1, entries
    assert missing[0].student == "S1"
    assert f"documents:{removed['sha']}" in missing[0].got and transcript in missing[0].got
    assert not [f for f in entries if f.student == "S6"], entries
    assert report.students["S6"].reached == ["ready_to_submit", "visa_ready"], report.students["S6"]
    from sqlalchemy import create_engine

    engine = create_engine(os_db)
    try:
        with engine.connect() as conn:
            D = models.documents
            rows = conn.execute(select(D.c.student_ref, D.c.doc_type, D.c.status)).all()
    finally:
        engine.dispose()
    s1 = {r.doc_type: r.status for r in rows if r.student_ref == student_ref("S1")}
    s6 = {r.doc_type: r.status for r in rows if r.student_ref == student_ref("S6")}
    assert s1.pop("transcript") == "failed" and set(s1.values()) == {"confirmed"}
    assert s6 and set(s6.values()) == {"confirmed"}
